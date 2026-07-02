# CNP Owner限定コンテンツ認証API（Cloud Run サービス・常駐/scale to zero）
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./

ENV TZ=Asia/Tokyo \
    PYTHONUNBUFFERED=1

# Cloud Runは PORT 環境変数でリッスンポートを指定してくる（未設定時は8080）
CMD exec gunicorn --bind :${PORT:-8080} --workers 1 --threads 8 --timeout 0 app:app
