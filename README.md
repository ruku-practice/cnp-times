# 勝手にCNP TIMES

CryptoNinja Partners (CNP) のフロア価格・出品数などの統計を表示するダッシュボードサイト。

- **クラシック版（新聞風）**: [`index.html`](./index.html) — 本日のサマリ＋直近の推移グラフ
- **高機能版**: [`advanced.html`](./advanced.html) — モダンUI（ダーク対応）／日付を遡って当時の表を見る／長期推移グラフ

公開URL: https://ruku-practice.github.io/cnp-times/

## データの流れ

```
get_CNP_stats_integrated_json.py
  ├─ OpenSea / NFTT をスクレイプ（Playwright）＋ ETH/USD価格（yfinance）
  ├─ Googleスプレッドシートへ書き込み
  ├─ html2_data.json（本日サマリ） / floorprice_full.json（全履歴・gitignore）を出力
  └─ build_site_data():
        ├─ data/history.json        … キャラ別フロア/出品数の長期時系列（1日1点）
        ├─ floorprice_data.json     … クラシック版グラフ用に直近200列へトリム
        └─ snapshots/YYYY-MM-DD.json … その日のフル表スナップショット（過去日再現用）
```

## 自動更新

- `.github/workflows/daily.yml` は日次本体の更新用。
- listings 更新は Cloud Run Job へ移行する前提で、`.github/workflows/listings.yml` は手動実行専用。

### listings を Cloud Run で動かす

`deploy/listings/` は `get_nftt_listings_for_list_sheet.py` を Cloud Run Job から起動するための最小構成。

想定フロー:

1. `deploy/listings/Dockerfile` で Job イメージを build
2. `deploy/listings/run.sh` が起動時に `main` を clone
3. `GOOGLE_CREDENTIALS_JSON` を `/tmp/sa.json` に展開
4. `python3 get_nftt_listings_for_list_sheet.py` を実行
5. 重複ガードは script 側で判定

例:

```bash
gcloud builds submit --tag REGION-docker.pkg.dev/PROJECT/REPO/cnp-listings-job:latest deploy/listings

gcloud run jobs create cnp-listings-update \
  --image REGION-docker.pkg.dev/PROJECT/REPO/cnp-listings-job:latest \
  --region REGION \
  --max-retries 0 \
  --task-timeout 1800s \
  --set-secrets GH_TOKEN=GH_TOKEN:latest,GOOGLE_CREDENTIALS_JSON=GOOGLE_CREDENTIALS_JSON:latest

gcloud scheduler jobs create http cnp-listings-update-0510 \
  --location REGION \
  --schedule "0 5 * * *" \
  --time-zone "Asia/Tokyo" \
  --uri "https://REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT/jobs/cnp-listings-update:run" \
  --http-method POST \
  --oauth-service-account-email SCHEDULER_INVOKER_SA@PROJECT.iam.gserviceaccount.com
```

## ローカル実行

```bash
pip install -r requirements.txt
playwright install chromium
python get_CNP_stats_integrated_json.py            # フル実行（スクレイプ含む）
python get_CNP_stats_integrated_json.py --build-only  # 派生データ生成のみ（スクレイプなし）
```

認証は環境変数 `SPREADSHEET_ID` / `GOOGLE_CREDENTIALS_PATH`（無ければローカル `.env`）で解決する。
