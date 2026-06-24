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

`.github/workflows/daily.yml` が毎日 0:00(JST) に実行され、スクレイプ → スプレッドシート更新 → JSON生成 → 自動コミットして GitHub Pages に反映する。

## ローカル実行

```bash
pip install -r requirements.txt
playwright install chromium
python get_CNP_stats_integrated_json.py            # フル実行（スクレイプ含む）
python get_CNP_stats_integrated_json.py --build-only  # 派生データ生成のみ（スクレイプなし）
```

認証は環境変数 `SPREADSHEET_ID` / `GOOGLE_CREDENTIALS_PATH`（無ければローカル `.env`）で解決する。
