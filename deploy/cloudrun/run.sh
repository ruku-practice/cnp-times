#!/usr/bin/env bash
# 勝手にCNP TIMES 日次更新（Cloud Run Job のエントリポイント）
# 必要env:
#   GH_TOKEN              … repo push 権限トークン（Secret Manager）
#   GOOGLE_CREDENTIALS_JSON … シート用サービスアカウント鍵の中身（Secret Manager）
#   SPREADSHEET_ID        … 対象スプレッドシートID（環境変数）
#   SMOKE_TEST=1          … 任意。--no-sheet でスクレイプ検証のみ（シート書込・pushなし）
set -euo pipefail

REPO="ruku-practice/cnp-times"
GH_TOKEN="$(printf '%s' "${GH_TOKEN:-}" | tr -d '\r\n[:space:]')"
ORIGIN="https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"
WORK=/work

echo "==================== $(date) cnp daily (cloud run) start ===================="
rm -rf "$WORK"
git clone --quiet "$ORIGIN" "$WORK"
cd "$WORK"
git config user.name  "cloud-run-bot"
git config user.email "cloud-run-bot@users.noreply.github.com"

# シート用サービスアカウント鍵をファイル化
printf '%s' "${GOOGLE_CREDENTIALS_JSON:-}" > /tmp/sa.json
export GOOGLE_CREDENTIALS_PATH=/tmp/sa.json
export PYTHONUNBUFFERED=1
# SPREADSHEET_ID は環境変数で注入される

# --- スモークテスト（非破壊）: スクレイプ＋シート読込＋JSON生成のみ。シート書込・pushなし ---
if [ "${SMOKE_TEST:-}" = "1" ]; then
  echo "[SMOKE] --no-sheet で実行（シート書込・pushなし）"
  python3 get_CNP_stats_integrated_json.py --no-sheet
  echo "[SMOKE] OK"
  exit 0
fi

# --- 本番: データ取得に失敗した時のみ最大3回リトライ（当日重複列は script の dedup が防ぐ） ---
ok=0
for a in 1 2 3; do
  echo "----- 試行 $a/3 $(date) -----"
  if python3 get_CNP_stats_integrated_json.py; then ok=1; break; fi
  if [ "$a" -lt 3 ]; then echo "失敗 → 120秒後に再試行"; sleep 120; fi
done
[ "$ok" -eq 1 ] || { echo "❌ 3回とも失敗"; exit 1; }

# --- Web用データを main へ push（Pagesはmainルート配信） ---
git add html2_data.json floorprice_data.json data/ snapshots/ 2>/dev/null || true
if git diff --staged --quiet; then
  echo "変更なし"
else
  git commit -q -m "chore: daily data update $(date -u +%Y-%m-%dT%H:%MZ) [cloud-run]"
  git push --quiet origin HEAD:main
  echo "✓ main に push"
fi
echo "==================== $(date) cnp daily done ===================="
