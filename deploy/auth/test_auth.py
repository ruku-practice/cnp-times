"""
deploy/auth/app.py のローカルテスト（pytest不要・素のPythonで実行可能）

Discord APIへのHTTP呼び出しを unittest.mock でモックし、以下を確認する:
  1. ロールありユーザーのcallback → owner=true のJWTが発行される
  2. ロールなしユーザーのcallback → owner=false
  3. 非メンバー（memberエンドポイントが404）→ cnp_status=not_member
  4. editorユーザーのcallback → editor=true のJWTが発行される
  5. stateを改ざんすると/callbackが拒否される（エラー扱いになる）
  6. /api/entries 系（v2 日次分析コメントCMS）のアクセス制御・CRUD
  7. /api/images 系のアップロード・配信・パストラバーサル防止

CONTENT_DIR に一時ディレクトリを使うため、GCS（google-cloud-storage）は不要。

実行方法:
  cd deploy/auth
  python test_auth.py
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

# --- app.py が参照する環境変数をimport前にセットする -----------------------

_TEST_CONTENT_DIR = tempfile.mkdtemp(prefix="cnp_auth_test_content_")

os.environ["DISCORD_CLIENT_ID"] = "test-client-id"
os.environ["DISCORD_CLIENT_SECRET"] = "test-client-secret"
os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["GUILD_ID"] = "1000922162741379086"
os.environ["REQUIRED_ROLE_ID"] = "999999999999999999"  # 「CNP Owner❤️」相当（テスト用）
os.environ["FRONTEND_URL"] = "https://example.github.io/cnp-times/advanced.html"
os.environ["ALLOWED_ORIGIN"] = "https://example.github.io"
os.environ["CONTENT_DIR"] = _TEST_CONTENT_DIR
os.environ["EDITOR_USER_IDS"] = "editor-1,editor-2"
# GCS_BUCKET は意図的に未設定のままにする（ローカルストレージを使わせる）

sys.path.insert(0, os.path.dirname(__file__))
import app as app_module  # noqa: E402

REQUIRED_ROLE_ID = os.environ["REQUIRED_ROLE_ID"]
OTHER_ROLE_ID = "111111111111111111"


def _cleanup_content_dir():
    if os.path.isdir(_TEST_CONTENT_DIR):
        shutil.rmtree(_TEST_CONTENT_DIR)
    os.makedirs(_TEST_CONTENT_DIR, exist_ok=True)


class FakeResponse:
    """requests.Response の最小モック。"""

    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def fake_requests_post_token_ok(url, **kwargs):
    assert url == f"{app_module.DISCORD_API_BASE}/oauth2/token"
    return FakeResponse(200, {"access_token": "fake-access-token"})


def make_fake_get(user_roles, member_status=200, user_id="123456789", name="テストユーザー"):
    """/users/@me と /users/@me/guilds/{id}/member をモックするGET関数を作る。"""

    def fake_get(url, **kwargs):
        if url == f"{app_module.DISCORD_API_BASE}/users/@me":
            return FakeResponse(200, {"id": user_id, "global_name": name})
        if url == f"{app_module.DISCORD_API_BASE}/users/@me/guilds/{app_module.GUILD_ID}/member":
            if member_status == 404:
                return FakeResponse(404, {})
            return FakeResponse(200, {"roles": user_roles})
        raise AssertionError(f"unexpected GET url: {url}")

    return fake_get


class DiscordAuthCallbackTests(unittest.TestCase):
    """/login → /callback のフロー。"""

    def setUp(self):
        app_module.app.testing = True
        self.client = app_module.app.test_client()

    def _get_valid_state(self):
        """/login にアクセスしてDiscordへのリダイレクトURLからstateを取り出す。"""
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 302)
        location = resp.headers["Location"]
        qs = parse_qs(urlparse(location).query)
        self.assertIn("state", qs)
        # scopeがidentify guilds.members.readであることも確認しておく
        self.assertEqual(qs["scope"][0], "identify guilds.members.read")
        return qs["state"][0]

    def _decode_jwt_from_redirect(self, location):
        frag = urlparse(location).fragment
        parts = dict(p.split("=", 1) for p in frag.split("&") if "=" in p)
        return parts

    # 1. ロールありユーザー → owner=trueのJWT発行
    @patch("app.requests.get")
    @patch("app.requests.post", side_effect=fake_requests_post_token_ok)
    def test_callback_with_role_issues_owner_jwt(self, mock_post, mock_get):
        state = self._get_valid_state()
        mock_get.side_effect = make_fake_get(user_roles=[REQUIRED_ROLE_ID, OTHER_ROLE_ID])

        resp = self.client.get(f"/callback?code=dummy-code&state={state}")
        self.assertEqual(resp.status_code, 302)

        frag = self._decode_jwt_from_redirect(resp.headers["Location"])
        self.assertEqual(frag.get("cnp_status"), "ok")
        self.assertIn("cnp_auth", frag)

        payload = app_module._verify_session_jwt(frag["cnp_auth"])
        self.assertTrue(payload["owner"])
        self.assertFalse(payload["editor"])
        self.assertEqual(payload["sub"], "123456789")
        self.assertEqual(payload["name"], "テストユーザー")
        self.assertIn(REQUIRED_ROLE_ID, payload["roles"])

    # 2. ロールなしユーザー → owner=false
    @patch("app.requests.get")
    @patch("app.requests.post", side_effect=fake_requests_post_token_ok)
    def test_callback_without_role_issues_non_owner_jwt(self, mock_post, mock_get):
        state = self._get_valid_state()
        mock_get.side_effect = make_fake_get(user_roles=[OTHER_ROLE_ID])

        resp = self.client.get(f"/callback?code=dummy-code&state={state}")
        self.assertEqual(resp.status_code, 302)

        frag = self._decode_jwt_from_redirect(resp.headers["Location"])
        self.assertEqual(frag.get("cnp_status"), "no_role")
        # ownerでなくてもJWTは発行される（/api/meでロールID確認できるようにするため）
        self.assertIn("cnp_auth", frag)

        payload = app_module._verify_session_jwt(frag["cnp_auth"])
        self.assertFalse(payload["owner"])

    # 3. 非メンバー（member取得が404）→ not_member
    @patch("app.requests.get")
    @patch("app.requests.post", side_effect=fake_requests_post_token_ok)
    def test_callback_not_member(self, mock_post, mock_get):
        state = self._get_valid_state()
        mock_get.side_effect = make_fake_get(user_roles=[], member_status=404)

        resp = self.client.get(f"/callback?code=dummy-code&state={state}")
        self.assertEqual(resp.status_code, 302)

        location = resp.headers["Location"]
        # not_memberの場合はcnp_authなしでcnp_statusのみ
        self.assertIn("cnp_status=not_member", location)
        self.assertNotIn("cnp_auth", location)

    # 4. editorユーザー（EDITOR_USER_IDSに含まれる）→ editor=trueのJWT発行
    @patch("app.requests.get")
    @patch("app.requests.post", side_effect=fake_requests_post_token_ok)
    def test_callback_editor_user_issues_editor_jwt(self, mock_post, mock_get):
        state = self._get_valid_state()
        # editor-1 は EDITOR_USER_IDS に含まれるが、CNP Ownerロールは持たない想定
        mock_get.side_effect = make_fake_get(
            user_roles=[OTHER_ROLE_ID], user_id="editor-1", name="分析者"
        )

        resp = self.client.get(f"/callback?code=dummy-code&state={state}")
        self.assertEqual(resp.status_code, 302)

        frag = self._decode_jwt_from_redirect(resp.headers["Location"])
        # editorはownerロールが無くてもstatus=okになる
        self.assertEqual(frag.get("cnp_status"), "ok")

        payload = app_module._verify_session_jwt(frag["cnp_auth"])
        self.assertTrue(payload["editor"])
        self.assertFalse(payload["owner"])
        self.assertEqual(payload["sub"], "editor-1")

    # 5. stateを改ざんすると拒否される
    @patch("app.requests.get")
    @patch("app.requests.post", side_effect=fake_requests_post_token_ok)
    def test_callback_rejects_tampered_state(self, mock_post, mock_get):
        state = self._get_valid_state()
        tampered_state = state + "tampered"
        mock_get.side_effect = make_fake_get(user_roles=[REQUIRED_ROLE_ID])

        resp = self.client.get(f"/callback?code=dummy-code&state={tampered_state}")
        self.assertEqual(resp.status_code, 302)

        location = resp.headers["Location"]
        self.assertIn("cnp_status=error", location)
        self.assertNotIn("cnp_auth", location)
        # Discordへの実通信は発生していないはず（state検証で弾かれるため）
        mock_post.assert_not_called()
        mock_get.assert_not_called()

    # stateが全く別のsecretで署名されている場合も拒否される
    def test_callback_rejects_forged_state(self):
        import jwt as pyjwt

        forged_state = pyjwt.encode({"nonce": "x"}, "wrong-secret", algorithm="HS256")
        resp = self.client.get(f"/callback?code=dummy-code&state={forged_state}")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("cnp_status=error", resp.headers["Location"])


class ApiMeTests(unittest.TestCase):
    """/api/me の基本動作。"""

    def setUp(self):
        app_module.app.testing = True
        self.client = app_module.app.test_client()

    def test_me_returns_profile_for_valid_token(self):
        token = app_module._issue_session_jwt(
            "789", "ロール確認くん", False, [OTHER_ROLE_ID, REQUIRED_ROLE_ID]
        )
        resp = self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["authorized"])
        self.assertEqual(data["id"], "789")
        self.assertFalse(data["owner"])
        self.assertFalse(data["editor"])
        self.assertEqual(data["name"], "ロール確認くん")
        self.assertIn(REQUIRED_ROLE_ID, data["roles"])

    def test_me_returns_editor_true_for_editor_token(self):
        token = app_module._issue_session_jwt("editor-1", "分析者", False, [], editor=True)
        resp = self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["editor"])

    def test_me_without_token_returns_401(self):
        resp = self.client.get("/api/me")
        self.assertEqual(resp.status_code, 401)

    def test_healthz_ok(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)


class ApiEntriesTests(unittest.TestCase):
    """/api/entries 系（v2 日次分析コメントCMS）のアクセス制御・CRUD。"""

    def setUp(self):
        app_module.app.testing = True
        self.client = app_module.app.test_client()
        app_module.reset_storage_cache()
        _cleanup_content_dir()

    def tearDown(self):
        app_module.reset_storage_cache()
        _cleanup_content_dir()

    def _owner_token(self):
        return app_module._issue_session_jwt("owner-1", "オーナー太郎", True, [REQUIRED_ROLE_ID])

    def _editor_token(self):
        return app_module._issue_session_jwt("editor-1", "分析者", False, [], editor=True)

    def _non_owner_token(self):
        return app_module._issue_session_jwt("456", "非オーナー", False, [OTHER_ROLE_ID])

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    # editorがPUTした記事をGETで取得でき、内容が一致する
    def test_editor_put_then_get_returns_same_content(self):
        editor_token = self._editor_token()
        resp = self.client.put(
            "/api/entries/2026-07-01",
            json={"title": "テスト記事", "body_md": "本文です"},
            headers=self._auth(editor_token),
        )
        self.assertEqual(resp.status_code, 200)
        put_data = resp.get_json()
        self.assertEqual(put_data["title"], "テスト記事")
        self.assertEqual(put_data["body_md"], "本文です")
        self.assertEqual(put_data["author_id"], "editor-1")
        self.assertEqual(put_data["author_name"], "分析者")
        self.assertIn("updated_at", put_data)

        get_resp = self.client.get(
            "/api/entries/2026-07-01", headers=self._auth(editor_token)
        )
        self.assertEqual(get_resp.status_code, 200)
        get_data = get_resp.get_json()
        self.assertEqual(get_data["title"], "テスト記事")
        self.assertEqual(get_data["body_md"], "本文です")

    # PUTした記事が一覧に反映される（日付降順）
    def test_entries_list_reflects_put_and_sorted_desc(self):
        editor_token = self._editor_token()
        self.client.put(
            "/api/entries/2026-07-01",
            json={"title": "7/1の記事", "body_md": "本文1"},
            headers=self._auth(editor_token),
        )
        self.client.put(
            "/api/entries/2026-07-02",
            json={"title": "7/2の記事", "body_md": "本文2"},
            headers=self._auth(editor_token),
        )

        resp = self.client.get("/api/entries", headers=self._auth(editor_token))
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()
        dates = [item["date"] for item in items]
        self.assertEqual(dates, ["2026-07-02", "2026-07-01"])
        self.assertEqual(items[0]["title"], "7/2の記事")
        self.assertIn("updated_at", items[0])

    # DELETEで記事が消える
    def test_editor_delete_removes_entry(self):
        editor_token = self._editor_token()
        self.client.put(
            "/api/entries/2026-07-01",
            json={"title": "消す記事", "body_md": "本文"},
            headers=self._auth(editor_token),
        )
        del_resp = self.client.delete(
            "/api/entries/2026-07-01", headers=self._auth(editor_token)
        )
        self.assertEqual(del_resp.status_code, 200)

        get_resp = self.client.get(
            "/api/entries/2026-07-01", headers=self._auth(editor_token)
        )
        self.assertEqual(get_resp.status_code, 404)

        list_resp = self.client.get("/api/entries", headers=self._auth(editor_token))
        self.assertEqual(list_resp.get_json(), [])

    # ownerはGETできるがPUT/DELETEは403
    def test_owner_can_get_but_not_put_or_delete(self):
        editor_token = self._editor_token()
        owner_token = self._owner_token()
        self.client.put(
            "/api/entries/2026-07-01",
            json={"title": "記事", "body_md": "本文"},
            headers=self._auth(editor_token),
        )

        get_resp = self.client.get(
            "/api/entries/2026-07-01", headers=self._auth(owner_token)
        )
        self.assertEqual(get_resp.status_code, 200)

        list_resp = self.client.get("/api/entries", headers=self._auth(owner_token))
        self.assertEqual(list_resp.status_code, 200)

        put_resp = self.client.put(
            "/api/entries/2026-07-01",
            json={"title": "上書き", "body_md": "上書き本文"},
            headers=self._auth(owner_token),
        )
        self.assertEqual(put_resp.status_code, 403)

        del_resp = self.client.delete(
            "/api/entries/2026-07-01", headers=self._auth(owner_token)
        )
        self.assertEqual(del_resp.status_code, 403)

    # 非owner非editorはentries GETも403
    def test_non_owner_non_editor_forbidden_on_entries(self):
        token = self._non_owner_token()
        list_resp = self.client.get("/api/entries", headers=self._auth(token))
        self.assertEqual(list_resp.status_code, 403)

        get_resp = self.client.get("/api/entries/2026-07-01", headers=self._auth(token))
        self.assertEqual(get_resp.status_code, 403)

        put_resp = self.client.put(
            "/api/entries/2026-07-01",
            json={"title": "x", "body_md": "y"},
            headers=self._auth(token),
        )
        self.assertEqual(put_resp.status_code, 403)

    # 無トークンは401
    def test_entries_without_token_returns_401(self):
        resp = self.client.get("/api/entries")
        self.assertEqual(resp.status_code, 401)

    # 不正な日付形式は400（パストラバーサルを狙う値はFlaskのルーティング段階で
    # 別ルートに解決され405になることがあるが、いずれにせよ200で漏洩しないことを確認する）
    def test_invalid_date_format_returns_400(self):
        editor_token = self._editor_token()
        for bad_date in ["2026-7-1", "20260701", "not-a-date"]:
            resp = self.client.get(
                f"/api/entries/{bad_date}", headers=self._auth(editor_token)
            )
            self.assertEqual(resp.status_code, 400, f"date={bad_date}")

            put_resp = self.client.put(
                f"/api/entries/{bad_date}",
                json={"title": "x", "body_md": "y"},
                headers=self._auth(editor_token),
            )
            self.assertEqual(put_resp.status_code, 400, f"date={bad_date}")

        for traversal_date in ["2026-07-01/../secret", "../../etc/passwd"]:
            resp = self.client.get(
                f"/api/entries/{traversal_date}", headers=self._auth(editor_token)
            )
            self.assertIn(resp.status_code, (400, 404, 405), f"date={traversal_date}")
            self.assertNotEqual(resp.status_code, 200, f"date={traversal_date}")

    # 存在しない記事のGETは404
    def test_get_nonexistent_entry_returns_404(self):
        editor_token = self._editor_token()
        resp = self.client.get(
            "/api/entries/2099-01-01", headers=self._auth(editor_token)
        )
        self.assertEqual(resp.status_code, 404)

    # 空一覧の場合は空配列
    def test_empty_entries_list(self):
        editor_token = self._editor_token()
        resp = self.client.get("/api/entries", headers=self._auth(editor_token))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])

    # title/body_mdが欠けている場合は400
    def test_put_missing_fields_returns_400(self):
        editor_token = self._editor_token()
        resp = self.client.put(
            "/api/entries/2026-07-01",
            json={"title": "タイトルだけ"},
            headers=self._auth(editor_token),
        )
        self.assertEqual(resp.status_code, 400)


class ApiImagesTests(unittest.TestCase):
    """/api/images 系のアップロード・配信・パストラバーサル防止。"""

    def setUp(self):
        app_module.app.testing = True
        self.client = app_module.app.test_client()
        app_module.reset_storage_cache()
        _cleanup_content_dir()

    def tearDown(self):
        app_module.reset_storage_cache()
        _cleanup_content_dir()

    def _editor_token(self):
        return app_module._issue_session_jwt("editor-1", "分析者", False, [], editor=True)

    def _owner_token(self):
        return app_module._issue_session_jwt("owner-1", "オーナー太郎", True, [REQUIRED_ROLE_ID])

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    # editorは画像をアップロードでき、GETで取得できる
    def test_editor_upload_then_get_image(self):
        editor_token = self._editor_token()
        data = {"file": (io.BytesIO(b"\x89PNG\r\n\x1a\nfakepngdata"), "photo.png")}
        resp = self.client.post(
            "/api/images",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(editor_token),
        )
        self.assertEqual(resp.status_code, 200)
        url = resp.get_json()["url"]
        self.assertTrue(url.startswith("/api/images/"))
        self.assertTrue(url.endswith(".png"))

        name = url.rsplit("/", 1)[-1]
        get_resp = self.client.get(f"/api/images/{name}", headers=self._auth(editor_token))
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.data, b"\x89PNG\r\n\x1a\nfakepngdata")
        self.assertEqual(get_resp.headers["Content-Type"], "image/png")

    # 拡張子違反は400
    def test_upload_rejects_unsupported_extension(self):
        editor_token = self._editor_token()
        data = {"file": (io.BytesIO(b"not an image"), "malware.exe")}
        resp = self.client.post(
            "/api/images",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(editor_token),
        )
        self.assertEqual(resp.status_code, 400)

    # 5MB超は400
    def test_upload_rejects_oversized_file(self):
        editor_token = self._editor_token()
        big_data = b"0" * (5 * 1024 * 1024 + 1)
        data = {"file": (io.BytesIO(big_data), "big.png")}
        resp = self.client.post(
            "/api/images",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(editor_token),
        )
        self.assertEqual(resp.status_code, 400)

    # 非editor（owner含む）は403
    def test_upload_forbidden_for_non_editor(self):
        owner_token = self._owner_token()
        data = {"file": (io.BytesIO(b"fakepng"), "photo.png")}
        resp = self.client.post(
            "/api/images",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(owner_token),
        )
        self.assertEqual(resp.status_code, 403)

    # GET /api/images/ のパストラバーサル拒否
    # （../ を含むものはFlaskのルーティング段階で別ルートに解決され405になることがあるが、
    #   いずれにせよ200で画像データが漏洩しないことを確認する）
    def test_get_image_rejects_path_traversal(self):
        editor_token = self._editor_token()
        for bad_name in [
            "../../etc/passwd",
            "..%2f..%2fetc%2fpasswd",
            "foo/../../secret.png",
            "notauuid.png",
            "12345.png",
        ]:
            resp = self.client.get(
                f"/api/images/{bad_name}", headers=self._auth(editor_token)
            )
            self.assertIn(resp.status_code, (400, 404, 405), f"name={bad_name}")
            # 少なくとも200で漏洩しないこと
            self.assertNotEqual(resp.status_code, 200, f"name={bad_name}")

    # 存在しない画像は404
    def test_get_nonexistent_image_returns_404(self):
        editor_token = self._editor_token()
        fake_uuid = "0" * 32
        resp = self.client.get(
            f"/api/images/{fake_uuid}.png", headers=self._auth(editor_token)
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
