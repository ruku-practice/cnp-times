# cnp-auth（Discord OAuth2認証 + NinjaDAOロール確認 + 日次分析コメントCMS）

CNP TIMES（高機能版 advanced.html）の「🔒 CNP Owner限定 日次分析コメント」用バックエンド。
Discord OAuth2でログインしたユーザー本人のNinjaDAOサーバーでのロール（「CNP Owner❤️」）を
確認し、条件を満たす場合のみ日次分析コメント（簡易ブログCMS）を閲覧できる。加えて、
`EDITOR_USER_IDS` に登録された分析者は記事の作成・編集・削除ができる。詳細は
`../../設計_Discord認証.md` を参照。

常駐サービスとして **Cloud Run サービス**（Job ではない）にデプロイする。scale to zero
のため実質無料枠内で運用できる想定。

## エンドポイント

| メソッド/パス | 権限 | 内容 |
|---|---|---|
| `GET /login` | - | state発行 → Discord認可URLへ302 |
| `GET /callback` | - | state検証 → code交換 → ロール判定 → JWT発行 → フロントへ302 |
| `GET /api/me` | JWT必須 | `{authorized, id, owner, editor, name, roles}` を返す |
| `GET /api/entries` | owner or editor | 記事一覧（日付降順）`[{date, title, updated_at}]` |
| `GET /api/entries/<YYYY-MM-DD>` | owner or editor | 記事本体 `{date, title, body_md, author_id, author_name, updated_at}` |
| `PUT /api/entries/<YYYY-MM-DD>` | editor | 作成・更新（body: `{title, body_md}`） |
| `DELETE /api/entries/<YYYY-MM-DD>` | editor | 削除 |
| `POST /api/images` | editor | multipart画像アップロード（png/jpg/jpeg/gif/webp、5MBまで）→ `{url: "/api/images/<name>"}` |
| `GET /api/images/<name>` | owner or editor | 画像バイナリ配信 |
| `GET /healthz` | - | 200 |

`/api/exclusive`（v1の静的限定コンテンツAPI）は廃止し、`/api/entries` 系に置き換えた。
editorはownerロールが無くても記事の閲覧・書き込みができる（editorはowner相当の閲覧権限を包含する）。

CORSは `ALLOWED_ORIGIN` のみ許可。許可メソッドは `GET, PUT, POST, DELETE, OPTIONS`。

## 環境変数

| 変数 | 内容 | 置き場所 |
|---|---|---|
| `DISCORD_CLIENT_ID` | Discord Developer Portalで取得 | env |
| `DISCORD_CLIENT_SECRET` | 同上 | Secret Manager |
| `JWT_SECRET` | ランダム生成の署名鍵 | Secret Manager |
| `GUILD_ID` | `1000922162741379086`（NinjaDAO、デフォルト値あり） | env |
| `REQUIRED_ROLE_ID` | 「CNP Owner❤️」のロールID（要調査） | env |
| `FRONTEND_URL` | `https://ruku-practice.github.io/cnp-times/advanced.html` | env |
| `ALLOWED_ORIGIN` | `https://ruku-practice.github.io`（デフォルト値あり） | env |
| `OAUTH_REDIRECT_URI` | 任意。未設定ならリクエストURLから `/callback` を導出 | env |
| `GCS_BUCKET` | 記事・画像の保存先GCSバケット名（例: `cnp-times-exclusive`）。**未設定ならローカルディレクトリ（`CONTENT_DIR`）にフォールバック** | env |
| `CONTENT_DIR` | `GCS_BUCKET` 未設定時のローカル保存先ディレクトリ（デフォルト: `./content`） | env（ローカル開発用） |
| `EDITOR_USER_IDS` | 記事の書き込み権限を持つDiscordユーザーIDのカンマ区切りリスト（例: `123456789012345678,234567890123456789`） | env |

`GCS_BUCKET` を設定すると `google-cloud-storage` を使った永続ストレージになる。ローカル
テスト・開発では `GCS_BUCKET` を空にしておけば `google-cloud-storage` のインストールは
不要（`app.py` はGCS使用時のみ遅延importする設計）。

## ストレージレイアウト（GCS / ローカル共通）

```
entries/YYYY-MM-DD.json   … {date, title, body_md, author_id, author_name, updated_at}
images/<uuid32hex>.<ext>  … 添付画像（png/jpg/jpeg/gif/webp、5MBまで）
```

## デプロイ手順

想定プロジェクト: `writeinfo2spreadsheet` / リージョン: `asia-northeast1`（既存Cloud Run Jobと同じ）。

### 0. GCSバケットの作成とサービスアカウントへの権限付与

```bash
# プライベートバケットを作成（リージョンは既存Jobに合わせる）
gsutil mb -p writeinfo2spreadsheet -l asia-northeast1 gs://cnp-times-exclusive

# 誤って公開しないよう Public Access Prevention を有効化
gsutil pap set enforced gs://cnp-times-exclusive

# Cloud Run サービスアカウントにオブジェクトの読み書き権限を付与
# （SERVICE_ACCOUNT は Cloud Run サービスが使うSAのメールアドレスに置き換える。
#   未指定でデプロイした場合はデフォルトの compute サービスアカウントになる）
gsutil iam ch serviceAccount:SERVICE_ACCOUNT:roles/storage.objectAdmin gs://cnp-times-exclusive
```

### 1. Secret Managerにシークレットを登録

```bash
echo -n "xxxxxxxx" | gcloud secrets create cnp-discord-client-secret \
  --data-file=- --project writeinfo2spreadsheet
echo -n "$(openssl rand -hex 32)" | gcloud secrets create cnp-jwt-secret \
  --data-file=- --project writeinfo2spreadsheet
```

### 2. イメージのビルド & デプロイ

```bash
gcloud builds submit --tag asia-northeast1-docker.pkg.dev/writeinfo2spreadsheet/REPO/cnp-auth:latest \
  deploy/auth --project writeinfo2spreadsheet

gcloud run deploy cnp-auth \
  --image asia-northeast1-docker.pkg.dev/writeinfo2spreadsheet/REPO/cnp-auth:latest \
  --project writeinfo2spreadsheet \
  --region asia-northeast1 --allow-unauthenticated \
  --set-env-vars GUILD_ID=1000922162741379086,REQUIRED_ROLE_ID=1086131792081322025,DISCORD_CLIENT_ID=1522153021579067462,FRONTEND_URL=https://ruku-practice.github.io/cnp-times/advanced.html,ALLOWED_ORIGIN=https://ruku-practice.github.io,GCS_BUCKET=cnp-times-exclusive,EDITOR_USER_IDS=<分析者のID>,<るくさんのID> \
  --set-secrets DISCORD_CLIENT_SECRET=cnp-discord-client-secret:latest,JWT_SECRET=cnp-jwt-secret:latest
```

`EDITOR_USER_IDS` のDiscordユーザーIDが分からない場合は、当該ユーザーに一度ログインして
もらい `/api/me` のレスポンスの `id` から特定できる（デプロイ済みでロール未許可でもJWTは
発行されるため確認可能）。

デプロイ後:

1. デプロイされたURL（例: `https://cnp-auth-xxxxx.a.run.app`）を確認
2. Discord Developer Portal の OAuth2 → Redirects に `https://<cnp-authのURL>/callback` を登録
3. リポジトリルートの `member.js` の `AUTH_BASE_URL` にデプロイ先URLを設定してpush

## ローカル実行

GCS不要（`GCS_BUCKET` を設定しなければローカルディレクトリにフォールバックする）。

```bash
cd deploy/auth
pip install -r requirements.txt   # ローカルのみなら google-cloud-storage は無くても動く
export DISCORD_CLIENT_ID=xxx DISCORD_CLIENT_SECRET=xxx JWT_SECRET=devsecret \
       REQUIRED_ROLE_ID=xxx FRONTEND_URL=http://localhost:8000/advanced.html \
       ALLOWED_ORIGIN=http://localhost:8000 EDITOR_USER_IDS=your-discord-user-id
python app.py
```

## テスト

Discord APIをモックし、`CONTENT_DIR` に一時ディレクトリを使ってGCS無しで実行するテストを
同梱（pytest不要、素のPythonで実行可能）。

```bash
cd deploy/auth
python test_auth.py
```

## 過去記事の一括インポート

`scripts/import_entries.py` は、ローカルの `YYYY-MM-DD.md`（1行目 `# タイトル`、空行を
挟んで本文がMarkdownで続く）を読み込み、editor権限のJWTを使って各日付を
`PUT /api/entries/<date>` で一括投入する。フォーマットのサンプルは
`scripts/past_entries/2026-07-01.md` を参照（このファイル自体は変更しない）。

```bash
cd deploy/auth
pip install requests   # requirements.txtに含まれる

# editorのJWTを用意する（本番なら実際にDiscordログインして/api/meで確認したトークン、
# ローカル検証ならapp.py の _issue_session_jwt で発行したテスト用トークンでも可）
python scripts/import_entries.py \
  --base-url https://cnp-auth-xxxxx.a.run.app \
  --token "<editorのJWT>" \
  --dir scripts/past_entries
```

成功・失敗件数がサマリ表示される。既に存在する日付は上書き（PUTなので冪等）。
