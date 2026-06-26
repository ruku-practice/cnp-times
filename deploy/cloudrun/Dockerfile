# 勝手にCNP TIMES 日次更新ジョブ（Cloud Run Job）
# 起動時にリポジトリを clone → Playwrightで NFTT/OpenSea をスクレイプ →
# Googleスプレッドシート更新 → Web用JSON生成 → main へ push（Pagesはmainルート配信）。
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# get_CNP_stats_integrated_json.py の依存
RUN pip install --no-cache-dir playwright python-dotenv yfinance gspread google-auth
# Chromium 本体＋OS依存（GitHub Actions と同じ手順）
RUN playwright install --with-deps chromium

ENV TZ=Asia/Tokyo \
    PYTHONUNBUFFERED=1

COPY run.sh /run.sh
RUN chmod +x /run.sh

ENTRYPOINT ["/run.sh"]
