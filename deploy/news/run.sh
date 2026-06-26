#!/usr/bin/env bash
# クリプトニンジャ・ニュース 前日分（Cloud Run Job・A=保険）。
# 7:00 JST起動。前日分が既に news.json にあれば（B=ローカルが成功）スキップ＝XをGCP IPから叩かない。
# 無い日だけ取得して push する。
# env: GH_TOKEN（push用secret）, X_COOKIES_JSON（Xcookie secret）
set -euo pipefail
REPO="ruku-practice/cnp-times"
GH_TOKEN="$(printf '%s' "${GH_TOKEN:-}" | tr -d '\r\n[:space:]')"
ORIGIN="https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"
WORK=/work

echo "==================== $(date) cnp news (cloud fallback) start ===================="
rm -rf "$WORK"; git clone --quiet "$ORIGIN" "$WORK"; cd "$WORK"
git config user.name "cloud-run-bot"; git config user.email "cloud-run-bot@users.noreply.github.com"

YDAY=$(python3 -c "import datetime,zoneinfo; print((datetime.datetime.now(zoneinfo.ZoneInfo('Asia/Tokyo')).date()-datetime.timedelta(days=1)).isoformat())")
if python3 -c "import json,sys; d=json.load(open('news.json')); sys.exit(0 if d.get('$YDAY') else 1)"; then
  echo "前日($YDAY)分は既にあり（ローカルBが成功）→ スキップ"
  exit 0
fi
echo "前日($YDAY)分が無い → クラウドで取得"
python3 fetch_news.py
git add news.json
if git diff --staged --quiet; then
  echo "変更なし"
else
  git commit -q -m "news: 前日分追記 $(date -u +%Y-%m-%dT%H:%MZ) [cloud-fallback]"
  git push --quiet origin HEAD:main
  echo "✓ push完了"
fi
echo "==================== $(date) done ===================="
