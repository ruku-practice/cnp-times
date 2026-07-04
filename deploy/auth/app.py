"""
CNP TIMES: Discord OAuth2認証 + NinjaDAOサーバーのロール確認バックエンド

設計書（設計_Discord認証.md）に基づく実装。v2で「日次分析コメントの簡易ブログCMS」に拡張。
- /login              … 署名付きstateを発行し、Discordの認可画面へリダイレクト
- /callback           … stateを検証しcodeをトークン交換、メンバー情報からロールを確認してJWTを発行
- /api/me             … JWTを検証し、ログイン状態・ロール情報を返す
- /api/entries        … (owner/editor) 記事一覧
- /api/entries/<date> … (owner/editor で閲覧、editor で作成・更新・削除) 記事本体
- /api/images         … (editor) 画像アップロード
- /api/images/<name>  … (owner/editor) 画像バイナリ配信
- /healthz            … ヘルスチェック
"""

import hmac
import io
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import jwt
import requests
from flask import Flask, jsonify, redirect, request, send_file

app = Flask(__name__)

# --- 環境変数 -------------------------------------------------------------

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
GUILD_ID = os.environ.get("GUILD_ID", "1000922162741379086")  # NinjaDAO
REQUIRED_ROLE_ID = os.environ.get("REQUIRED_ROLE_ID", "")  # 「CNP Owner❤️」のロールID
FRONTEND_URL = os.environ.get(
    "FRONTEND_URL", "https://ruku-practice.github.io/cnp-times/advanced.html"
)
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://ruku-practice.github.io")
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "")  # 未設定ならリクエストURLから導出

# v2: 日次分析コメントCMS用
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
CONTENT_DIR = os.environ.get("CONTENT_DIR", os.path.join(os.path.dirname(__file__), "content"))
EDITOR_USER_IDS = {
    uid.strip() for uid in os.environ.get("EDITOR_USER_IDS", "").split(",") if uid.strip()
}


def _parse_editor_api_keys(raw):
    """`キー:DiscordユーザーID:表示名` のカンマ区切りをパースして {キー: (ユーザーID, 表示名)} を返す。

    書式が壊れたエントリ（コロン不足など）は無視する。
    """
    result = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        if len(parts) != 3:
            continue
        key, user_id, name = (p.strip() for p in parts)
        if not key or not user_id:
            continue
        result[key] = (user_id, name)
    return result


# 長期APIキー認証（Chrome拡張からの投稿用）: "キー:DiscordユーザーID:表示名" のカンマ区切り。
# 実値はSecret Manager経由で注入する。JWTと違い失効期限が無いため、無効化はこの環境変数から
# 該当キーを削除して再デプロイすることで行う。
EDITOR_API_KEYS = _parse_editor_api_keys(os.environ.get("EDITOR_API_KEYS", ""))

DISCORD_API_BASE = "https://discord.com/api/v10"
STATE_TTL_SECONDS = 10 * 60  # state の有効期限（10分）
JWT_TTL_SECONDS = 7 * 24 * 60 * 60  # セッションJWTの有効期限（7日）

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IMAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|jpeg|gif|webp)$")
ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB

IMAGE_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


# --- ストレージ層 -----------------------------------------------------------
# GCS_BUCKET が設定されていれば Google Cloud Storage、なければ CONTENT_DIR
# 配下のローカルディレクトリを使う薄い抽象化。google-cloud-storage は
# GCS使用時のみ遅延importする（ローカルテストでimportエラーにならないように）。


class LocalStorage:
    """CONTENT_DIR をルートにしたローカルファイルストレージ。"""

    def __init__(self, base_dir):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, key):
        # key は "entries/2026-07-01.json" のようなスラッシュ区切りを想定
        path = os.path.join(self.base_dir, *key.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def get_bytes(self, key):
        path = self._path(key)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def put_bytes(self, key, data, content_type=None):
        path = self._path(key)
        with open(path, "wb") as f:
            f.write(data)

    def delete(self, key):
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def list(self, prefix):
        prefix_dir = self._path(prefix if prefix.endswith("/") else prefix + "/")
        prefix_dir = os.path.dirname(prefix_dir) if not prefix.endswith("/") else prefix_dir
        if not os.path.isdir(prefix_dir):
            return []
        names = []
        for fname in os.listdir(prefix_dir):
            full = os.path.join(prefix_dir, fname)
            if os.path.isfile(full):
                names.append(prefix.rstrip("/") + "/" + fname)
        return names


class GCSStorage:
    """Google Cloud Storage バケットを使うストレージ。google-cloud-storageはここでのみimport。"""

    def __init__(self, bucket_name):
        from google.cloud import storage  # 遅延import（GCS使用時のみ必要）

        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    def get_bytes(self, key):
        blob = self._bucket.blob(key)
        if not blob.exists():
            return None
        return blob.download_as_bytes()

    def put_bytes(self, key, data, content_type=None):
        blob = self._bucket.blob(key)
        blob.upload_from_string(data, content_type=content_type)

    def delete(self, key):
        blob = self._bucket.blob(key)
        if not blob.exists():
            return False
        blob.delete()
        return True

    def list(self, prefix):
        return [blob.name for blob in self._bucket.list_blobs(prefix=prefix)]


_storage = None


def get_storage():
    """ストレージインスタンスを遅延生成して返す（テスト時にモジュール差し替えできるようキャッシュしない）。"""
    global _storage
    if _storage is not None:
        return _storage
    if GCS_BUCKET:
        _storage = GCSStorage(GCS_BUCKET)
    else:
        _storage = LocalStorage(CONTENT_DIR)
    return _storage


def reset_storage_cache():
    """テスト用: ストレージインスタンスのキャッシュをクリアする。"""
    global _storage
    _storage = None


# --- ユーティリティ ---------------------------------------------------------


def _redirect_uri():
    """OAuth2のredirect_uriを決定する。環境変数優先、なければリクエストURLから導出。"""
    if OAUTH_REDIRECT_URI:
        return OAUTH_REDIRECT_URI
    return request.url_root.rstrip("/") + "/callback"


def _issue_state():
    """CSRF対策用の署名付きstateトークンを発行する（10分期限）。"""
    payload = {
        "typ": "state",  # セッションJWTをstateとして流用されないよう用途を明示
        "nonce": uuid.uuid4().hex,
        "exp": int(time.time()) + STATE_TTL_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _verify_state(state):
    """stateトークンを検証する。不正・期限切れ・用途違いならNoneを返す。"""
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=["HS256"])
        return True if payload.get("typ") == "state" else None
    except jwt.PyJWTError:
        return None


def _issue_session_jwt(user_id, name, owner, roles, editor=False):
    """ログインセッション用のJWTを発行する（HS256, 7日）。"""
    payload = {
        "sub": user_id,
        "name": name,
        "owner": owner,
        "editor": editor,
        "roles": roles,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_TTL_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _verify_session_jwt(token):
    """セッションJWTを検証する。不正・期限切れなら例外を投げる。"""
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])


def _get_bearer_token():
    """Authorizationヘッダーから Bearer トークンを取り出す。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header[len("Bearer "):]


def _lookup_api_key_payload(api_key):
    """X-Api-Keyヘッダーの値を検証し、一致すればJWTと同等のpayloadを返す。

    hmac.compare_digestでタイミング攻撃を避けるため、辞書検索ではなく全キーと
    定数時間で比較する（キー数は少数のため性能上の問題は無い）。
    """
    for candidate, (user_id, name) in EDITOR_API_KEYS.items():
        if hmac.compare_digest(candidate, api_key):
            return {"sub": user_id, "name": name, "owner": True, "editor": True, "roles": []}
    return None


def _require_payload():
    """認証情報を検証してpayloadを返す。不正なら (None, エラーレスポンス) を返す。

    X-Api-Key ヘッダーがあれば長期APIキー認証を優先し、無ければ従来のBearer JWT検証を行う
    （既存のJWTフローは無変更）。
    """
    api_key = request.headers.get("X-Api-Key", "")
    if api_key:
        payload = _lookup_api_key_payload(api_key)
        if payload is None:
            return None, (jsonify({"error": "unauthorized"}), 401)
        return payload, None

    token = _get_bearer_token()
    if not token:
        return None, (jsonify({"error": "unauthorized"}), 401)
    try:
        payload = _verify_session_jwt(token)
    except jwt.PyJWTError:
        return None, (jsonify({"error": "unauthorized"}), 401)
    return payload, None


def _require_viewer():
    """owner または editor であることを要求する。閲覧系エンドポイント用。"""
    payload, err = _require_payload()
    if err:
        return None, err
    if not (payload.get("owner") or payload.get("editor")):
        return None, (jsonify({"error": "forbidden"}), 403)
    return payload, None


def _require_editor():
    """editor であることを要求する。書き込み系エンドポイント用。"""
    payload, err = _require_payload()
    if err:
        return None, err
    if not payload.get("editor"):
        return None, (jsonify({"error": "forbidden"}), 403)
    return payload, None


def _cors_headers(resp):
    """/api/* 用にALLOWED_ORIGINのみ許可するCORSヘッダーを付与する。"""
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, PUT, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Api-Key"
    resp.headers["Access-Control-Max-Age"] = "3600"
    return resp


@app.after_request
def add_cors_headers(resp):
    """/api/* へのレスポンスにのみCORSヘッダーを付与する。"""
    if request.path.startswith("/api/"):
        return _cors_headers(resp)
    return resp


@app.route("/api/<path:_subpath>", methods=["OPTIONS"])
def api_preflight(_subpath):
    """/api/* のCORSプリフライトに応答する。"""
    return _cors_headers(app.make_default_options_response())


# --- エンドポイント ---------------------------------------------------------


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/login")
def login():
    """署名付きstateを発行し、Discordの認可画面へ302リダイレクトする。"""
    state = _issue_state()
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "identify guilds.members.read",
        "state": state,
        "prompt": "consent",
    }
    return redirect(f"{DISCORD_API_BASE}/oauth2/authorize?{urlencode(params)}")


def _finish_with_status(status):
    return redirect(f"{FRONTEND_URL}#cnp_status={status}")


@app.route("/callback")
def callback():
    """Discordからのコールバックを処理し、ロール確認後にJWTを発行してフロントへ戻す。"""
    code = request.args.get("code")
    state = request.args.get("state")

    if not state or not _verify_state(state):
        return _finish_with_status("error")

    if not code:
        return _finish_with_status("error")

    try:
        # 1. code をアクセストークンに交換する
        token_resp = requests.post(
            f"{DISCORD_API_BASE}/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        if token_resp.status_code != 200:
            return _finish_with_status("error")

        access_token = token_resp.json().get("access_token")
        if not access_token:
            return _finish_with_status("error")

        # 2. ユーザー情報を取得する（表示名・ID用）
        user_resp = requests.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if user_resp.status_code != 200:
            return _finish_with_status("error")
        user = user_resp.json()
        user_id = user.get("id")
        name = user.get("global_name") or user.get("username") or "unknown"

        # 3. NinjaDAOサーバーでのメンバー情報（ロールID一覧）を取得する
        member_resp = requests.get(
            f"{DISCORD_API_BASE}/users/@me/guilds/{GUILD_ID}/member",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if member_resp.status_code == 404:
            return _finish_with_status("not_member")
        if member_resp.status_code != 200:
            return _finish_with_status("error")

        roles = member_resp.json().get("roles", [])
        owner = REQUIRED_ROLE_ID in roles
        editor = user_id in EDITOR_USER_IDS

        # ownerでなくてもJWTは発行する（/api/meでロールID確認できるようにするため）
        session_jwt = _issue_session_jwt(user_id, name, owner, roles, editor=editor)
        status = "ok" if (owner or editor) else "no_role"
        return redirect(f"{FRONTEND_URL}#cnp_auth={session_jwt}&cnp_status={status}")

    except requests.RequestException:
        return _finish_with_status("error")


@app.route("/api/me")
def api_me():
    """JWTを検証し、ログイン状態・ロール情報を返す。"""
    token = _get_bearer_token()
    if not token:
        return jsonify({"authorized": False}), 401
    try:
        payload = _verify_session_jwt(token)
    except jwt.PyJWTError:
        return jsonify({"authorized": False}), 401

    return jsonify(
        {
            "authorized": True,
            "id": payload.get("sub"),
            "owner": bool(payload.get("owner")),
            "editor": bool(payload.get("editor")),
            "name": payload.get("name"),
            "roles": payload.get("roles", []),
        }
    )


# --- 日次分析コメントCMS（v2） -----------------------------------------------


ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def _valid_posted_at(value):
    """簡易ISO日時バリデーション。文字列でなければ、または形式が不正ならFalse。"""
    return isinstance(value, str) and bool(ISO_DATETIME_RE.match(value.strip()))


def _entry_key(date):
    return f"entries/{date}.json"


def _load_entry(date):
    data = get_storage().get_bytes(_entry_key(date))
    if data is None:
        return None
    return json.loads(data.decode("utf-8"))


@app.route("/api/entries", methods=["GET"])
def api_entries_list():
    """owner または editor: entries/ 配下を列挙し日付降順で返す。"""
    _, err = _require_viewer()
    if err:
        return err

    keys = get_storage().list("entries")
    items = []
    for key in keys:
        fname = key.rsplit("/", 1)[-1]
        if not fname.endswith(".json"):
            continue
        date = fname[: -len(".json")]
        if not DATE_RE.match(date):
            continue
        entry = _load_entry(date)
        if entry is None:
            continue
        items.append(
            {
                "date": entry.get("date", date),
                "title": entry.get("title", ""),
                "updated_at": entry.get("updated_at", ""),
            }
        )

    items.sort(key=lambda e: e["date"], reverse=True)
    return jsonify(items)


@app.route("/api/entries/<date>", methods=["GET"])
def api_entries_get(date):
    """owner または editor: 記事本体を返す。"""
    _, err = _require_viewer()
    if err:
        return err

    if not DATE_RE.match(date):
        return jsonify({"error": "invalid date"}), 400

    entry = _load_entry(date)
    if entry is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(entry)


@app.route("/api/entries/<date>", methods=["PUT"])
def api_entries_put(date):
    """editor: 記事を作成・更新する。"""
    payload, err = _require_editor()
    if err:
        return err

    if not DATE_RE.match(date):
        return jsonify({"error": "invalid date"}), 400

    body = request.get_json(silent=True) or {}
    title = body.get("title")
    body_md = body.get("body_md")
    if not isinstance(title, str) or not title.strip():
        return jsonify({"error": "title is required"}), 400
    if not isinstance(body_md, str) or not body_md.strip():
        return jsonify({"error": "body_md is required"}), 400

    entry = {
        "date": date,
        "title": title,
        "body_md": body_md,
        "author_id": payload.get("sub"),
        "author_name": payload.get("name"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Discordでの発言日時はWebエディタからの更新では失わないよう既存値を引き継ぐ
    existing = _load_entry(date)
    if existing and existing.get("posted_at"):
        entry["posted_at"] = existing["posted_at"]
    else:
        # 既存記事にposted_atが無い場合のみ、リクエストbodyの値を新規採用する
        # （Chrome拡張が新規投稿時に付与する投稿日時。改ざん防止のため既存値は上書きさせない）
        posted_at = body.get("posted_at")
        if _valid_posted_at(posted_at):
            entry["posted_at"] = posted_at.strip()
    get_storage().put_bytes(
        _entry_key(date), json.dumps(entry, ensure_ascii=False).encode("utf-8"), "application/json"
    )
    return jsonify(entry)


@app.route("/api/entries/<date>", methods=["DELETE"])
def api_entries_delete(date):
    """editor: 記事を削除する。"""
    _, err = _require_editor()
    if err:
        return err

    if not DATE_RE.match(date):
        return jsonify({"error": "invalid date"}), 400

    deleted = get_storage().delete(_entry_key(date))
    if not deleted:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/images", methods=["POST"])
def api_images_upload():
    """editor: multipart画像アップロード。png/jpg/jpeg/gif/webp、5MBまで。"""
    _, err = _require_editor()
    if err:
        return err

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "file is required"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": "unsupported file type"}), 400

    data = file.read()
    if len(data) > MAX_IMAGE_BYTES:
        return jsonify({"error": "file too large"}), 400

    name = f"{uuid.uuid4().hex}.{ext}"
    get_storage().put_bytes(f"images/{name}", data, IMAGE_CONTENT_TYPES.get(ext, "application/octet-stream"))
    return jsonify({"url": f"/api/images/{name}"})


@app.route("/api/images/<name>", methods=["GET"])
def api_images_get(name):
    """owner または editor: 画像バイナリを配信する。"""
    _, err = _require_viewer()
    if err:
        return err

    if not IMAGE_NAME_RE.match(name):
        return jsonify({"error": "invalid name"}), 400

    data = get_storage().get_bytes(f"images/{name}")
    if data is None:
        return jsonify({"error": "not found"}), 404

    ext = name.rsplit(".", 1)[-1].lower()
    content_type = IMAGE_CONTENT_TYPES.get(ext, "application/octet-stream")
    return send_file(io.BytesIO(data), mimetype=content_type)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
