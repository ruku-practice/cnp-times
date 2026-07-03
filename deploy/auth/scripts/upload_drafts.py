"""
collect_discord.py が出力した下書き（drafts/YYYY-MM-DD.md ＋ drafts/images/…）を
確認済みの内容として GCS バケットへ一括投入するスクリプト。

処理内容:
  1. --dir 配下の `YYYY-MM-DD.md` を走査する（`_2.md` 等の同日重複ファイルはスキップし警告）
  2. 本文中の `![](images/…)` 参照の画像を `images/<uuid4hex>.<ext>` としてGCSへアップロードし、
     本文中の参照を `/api/images/<uuid名>` に書き換える（app.py の画像配信エンドポイントに合わせる）
  3. 記事を `entries/<日付>.json` として
     `{date, title, body_md, author_id, author_name, updated_at}` 形式でGCSへアップロードする
     （author_id="891983769358196756", author_name="分析者" 固定）
  4. 既にentriesに同日付の記事がある場合はスキップして報告する（Webエディタでの手直しを守るため）。
     --force を付けると上書きする

google-cloud-storage の Application Default Credentials を使う。
ローカルで `gcloud auth application-default login` 済みであることが前提。

使い方:
  # まずは --dry-run で何がアップロードされるか確認する
  python upload_drafts.py --dir drafts --bucket cnp-times-exclusive --dry-run

  # 確認後に本投入
  python upload_drafts.py --dir drafts --bucket cnp-times-exclusive

  # 既存記事を上書きしたい場合（Webエディタでの手直しを破棄することに注意）
  python upload_drafts.py --dir drafts --bucket cnp-times-exclusive --force

必要ライブラリ: google-cloud-storage（deploy/auth/requirements.txt に含まれる）
"""

import argparse
import glob
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DUP_SUFFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d+$")
TITLE_LINE_RE = re.compile(r"^#\s+(.+?)\s*$")
IMAGE_REF_RE = re.compile(r"!\[\]\(images/([^)\s]+)\)")

AUTHOR_ID = "891983769358196756"
AUTHOR_NAME = "分析者"

IMAGE_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def parse_entry_file(path):
    """`# タイトル` \n\n 本文... 形式のMarkdownファイルを (title, body_md) に分解する。

    import_entries.py の parse_entry_file と同じ形式。
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()

    lines = text.splitlines()
    if not lines:
        raise ValueError(f"{path}: ファイルが空です")

    title_match = TITLE_LINE_RE.match(lines[0])
    if not title_match:
        raise ValueError(f"{path}: 1行目が '# タイトル' 形式ではありません")
    title = title_match.group(1)

    rest = lines[1:]
    while rest and rest[0].strip() == "":
        rest = rest[1:]
    body_md = "\n".join(rest).rstrip("\n")

    if not body_md:
        raise ValueError(f"{path}: 本文が空です")

    return title, body_md


def get_gcs_bucket(bucket_name):
    from google.cloud import storage  # 遅延import（--dry-runでは不要にするため）

    client = storage.Client()
    return client.bucket(bucket_name)


def entry_exists(bucket, date):
    blob = bucket.blob(f"entries/{date}.json")
    return blob.exists()


def upload_image(bucket, local_path, dry_run):
    ext = local_path.rsplit(".", 1)[-1].lower() if "." in local_path else ""
    if ext not in IMAGE_CONTENT_TYPES:
        raise ValueError(f"{local_path}: 未対応の拡張子です（png/jpg/jpeg/gif/webpのみ）")

    name = f"{uuid.uuid4().hex}.{ext}"
    key = f"images/{name}"
    if dry_run:
        print(f"    [DRY-RUN] 画像アップロード予定: {local_path} -> {key}")
        return name

    with open(local_path, "rb") as f:
        data = f.read()
    blob = bucket.blob(key)
    blob.upload_from_string(data, content_type=IMAGE_CONTENT_TYPES[ext])
    print(f"    [OK] 画像アップロード: {local_path} -> {key}")
    return name


def rewrite_image_refs(body_md, images_dir, bucket, dry_run):
    """本文中の ![](images/xxx) を探し、GCSへアップロードして /api/images/<uuid名> に置き換える。"""
    missing = []

    def _replace(match):
        image_filename = match.group(1)
        local_path = os.path.join(images_dir, image_filename)
        if not os.path.exists(local_path):
            missing.append(image_filename)
            return match.group(0)
        uploaded_name = upload_image(bucket, local_path, dry_run)
        return f"![](/api/images/{uploaded_name})"

    new_body = IMAGE_REF_RE.sub(_replace, body_md)
    return new_body, missing


def is_duplicate_filename(stem):
    return bool(DUP_SUFFIX_RE.match(stem))


def upload_dir(entries_dir, bucket_name, dry_run, force):
    images_dir = os.path.join(entries_dir, "images")
    pattern = os.path.join(entries_dir, "*.md")
    paths = sorted(glob.glob(pattern))

    if not paths:
        print(f"対象ファイルが見つかりませんでした: {pattern}", file=sys.stderr)
        return 1

    bucket = None if dry_run else get_gcs_bucket(bucket_name)
    # dry-runでもGCSの既存チェック(entry_exists)のためにbucketが欲しいが、
    # 認証情報が無い環境でも --dry-run が動くように、既存チェックはスキップして常に「新規想定」で表示する。
    dry_run_bucket = None
    if dry_run:
        try:
            dry_run_bucket = get_gcs_bucket(bucket_name)
        except Exception as e:  # noqa: BLE001 - 認証未設定でもdry-runは継続したい
            print(
                f"[注意] GCSへの接続に失敗したため、既存記事の重複チェックはスキップします ({e})",
                file=sys.stderr,
            )

    ok_count = 0
    skip_count = 0
    error_count = 0

    for path in paths:
        fname = os.path.basename(path)
        stem = fname[: -len(".md")]

        if is_duplicate_filename(stem):
            print(f"[SKIP] {fname}: 同一掲載日の重複記事のため自動投入対象外です（手動で確認してください）")
            skip_count += 1
            continue

        if not DATE_RE.match(stem):
            print(f"[SKIP] {fname}: ファイル名がYYYY-MM-DD.mdの形式ではありません")
            skip_count += 1
            continue

        date = stem

        try:
            title, body_md = parse_entry_file(path)
        except ValueError as e:
            print(f"[ERROR] {e}")
            error_count += 1
            continue

        active_bucket = bucket if not dry_run else dry_run_bucket
        if active_bucket is not None and not force and entry_exists(active_bucket, date):
            print(f"[SKIP] {date}: 既にentriesに存在するため上書きしません（--forceで上書き可能）")
            skip_count += 1
            continue

        new_body_md, missing_images = rewrite_image_refs(body_md, images_dir, active_bucket, dry_run)
        if missing_images:
            print(
                f"[ERROR] {date}: 参照画像が見つかりません: {', '.join(missing_images)}"
            )
            error_count += 1
            continue

        entry = {
            "date": date,
            "title": title,
            "body_md": new_body_md,
            "author_id": AUTHOR_ID,
            "author_name": AUTHOR_NAME,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if dry_run:
            print(f"[DRY-RUN] {date}: {title} (entries/{date}.json としてアップロード予定)")
            ok_count += 1
            continue

        blob = bucket.blob(f"entries/{date}.json")
        blob.upload_from_string(
            json.dumps(entry, ensure_ascii=False).encode("utf-8"), content_type="application/json"
        )
        print(f"[OK] {date}: {title}")
        ok_count += 1

    print(f"完了: 成功 {ok_count} 件 / スキップ {skip_count} 件 / 失敗 {error_count} 件")
    return 0 if error_count == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="確認済み下書きの一括GCS投入")
    parser.add_argument("--dir", required=True, help="collect_discord.py の出力ディレクトリ（drafts）")
    parser.add_argument("--bucket", default="cnp-times-exclusive", help="GCSバケット名")
    parser.add_argument("--dry-run", action="store_true", help="実際にはアップロードせず予定だけ表示する")
    parser.add_argument("--force", action="store_true", help="既存のentriesがあっても上書きする")
    args = parser.parse_args()

    sys.exit(upload_dir(args.dir, args.bucket, args.dry_run, args.force))


if __name__ == "__main__":
    main()
