# クリプトニンジャ・ニュース 前日分取得（Cloud Run Job・A=保険）
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir twikit
ENV TZ=Asia/Tokyo PYTHONUNBUFFERED=1
COPY run.sh /run.sh
RUN chmod +x /run.sh
ENTRYPOINT ["/run.sh"]
