# CNP listings 更新ジョブ（Cloud Run Job）
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright python-dotenv yfinance gspread google-auth
RUN playwright install --with-deps chromium

ENV TZ=Asia/Tokyo \
    PYTHONUNBUFFERED=1

COPY run.sh /run.sh
RUN chmod +x /run.sh

ENTRYPOINT ["/run.sh"]
