#!/usr/bin/env bash
# CNP listings 更新（Cloud Run Job）
# 必要env:
#   GH_TOKEN                ... repo clone 用 token
#   GOOGLE_CREDENTIALS_JSON ... シート用サービスアカウント鍵の中身
#   SMOKE_TEST=1            ... 任意。シート書込なしで重複ガード確認まで
set -euo pipefail

REPO="ruku-practice/cnp-times"
GH_TOKEN="$(printf '%s' "${GH_TOKEN:-}" | tr -d '\r\n[:space:]')"
ORIGIN="https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"
WORK=/work

echo "==================== $(date) cnp listings (cloud run) start ===================="
rm -rf "$WORK"
git clone --quiet "$ORIGIN" "$WORK"
cd "$WORK"

printf '%s' "${GOOGLE_CREDENTIALS_JSON:-}" > /tmp/sa.json
export GOOGLE_CREDENTIALS_PATH=/tmp/sa.json
export PYTHONUNBUFFERED=1
export TZ=Asia/Tokyo

if [ "${SMOKE_TEST:-}" = "1" ]; then
  echo "[SMOKE] listings fetcher を実行"
  python3 get_nftt_listings_for_list_sheet.py
  echo "[SMOKE] OK"
  exit 0
fi

ok=0
for a in 1 2 3; do
  echo "----- 試行 $a/3 $(date) -----"
  if python3 get_nftt_listings_for_list_sheet.py; then
    ok=1
    break
  fi
  if [ "$a" -lt 3 ]; then
    echo "失敗 -> 120秒後に再試行"
    sleep 120
  fi
done

[ "$ok" -eq 1 ] || { echo "❌ 3回とも失敗"; exit 1; }
echo "==================== $(date) cnp listings done ===================="
