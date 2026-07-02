"""
過去記事の一括インポートスクリプト。

ローカルディレクトリ内の `YYYY-MM-DD.md` ファイル（1行目 `# タイトル`、
空行を挟んで本文がMarkdownで続く）を読み込み、editorのJWTを使って
`PUT /api/entries/<date>` に投げ込む。

フォーマットの正は scripts/past_entries/2026-07-01.md を参照（このファイルは変更しない）。

使い方:
  python import_entries.py --base-url https://cnp-auth-xxxxx.a.run.app \
      --token <editorのJWT> --dir scripts/past_entries

必要ライブラリ: requests（deploy/auth/requirements.txt に含まれる）
"""

import argparse
import glob
import os
import re
import sys

import requests

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TITLE_LINE_RE = re.compile(r"^#\s+(.+?)\s*$")


def parse_entry_file(path):
    """`# タイトル` \n\n 本文... 形式のMarkdownファイルを (title, body_md) に分解する。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    lines = text.splitlines()
    if not lines:
        raise ValueError(f"{path}: ファイルが空です")

    title_match = TITLE_LINE_RE.match(lines[0])
    if not title_match:
        raise ValueError(f"{path}: 1行目が '# タイトル' 形式ではありません")
    title = title_match.group(1)

    # 1行目の直後の空行はスキップし、残りを本文とする
    rest = lines[1:]
    while rest and rest[0].strip() == "":
        rest = rest[1:]
    body_md = "\n".join(rest).rstrip("\n")

    if not body_md:
        raise ValueError(f"{path}: 本文が空です")

    return title, body_md


def import_dir(base_url, token, entries_dir):
    pattern = os.path.join(entries_dir, "*.md")
    paths = sorted(glob.glob(pattern))
    if not paths:
        print(f"対象ファイルが見つかりませんでした: {pattern}", file=sys.stderr)
        return 1

    ok_count = 0
    error_count = 0

    for path in paths:
        fname = os.path.basename(path)
        date = fname[: -len(".md")]
        if not DATE_RE.match(date):
            print(f"[SKIP] {fname}: ファイル名がYYYY-MM-DD.mdの形式ではありません")
            continue

        try:
            title, body_md = parse_entry_file(path)
        except ValueError as e:
            print(f"[ERROR] {e}")
            error_count += 1
            continue

        url = f"{base_url.rstrip('/')}/api/entries/{date}"
        resp = requests.put(
            url,
            json={"title": title, "body_md": body_md},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )

        if resp.status_code == 200:
            print(f"[OK] {date}: {title}")
            ok_count += 1
        else:
            print(f"[ERROR] {date}: HTTP {resp.status_code} {resp.text}")
            error_count += 1

    print(f"完了: 成功 {ok_count} 件 / 失敗 {error_count} 件")
    return 0 if error_count == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="過去記事の一括インポート")
    parser.add_argument("--base-url", required=True, help="cnp-auth の AUTH_BASE_URL")
    parser.add_argument("--token", required=True, help="editor権限を持つユーザーのJWT")
    parser.add_argument("--dir", required=True, help="YYYY-MM-DD.md が入ったディレクトリ")
    args = parser.parse_args()

    sys.exit(import_dir(args.base_url, args.token, args.dir))


if __name__ == "__main__":
    main()
