"""
Discordの分析コメント収集スクリプト。

指定チャンネルの投稿履歴を Discord REST API（GET /channels/{id}/messages）で
ページングして遡り、対象発信者（分析者さん）の「分析N回目」投稿とその後続を
1記事にまとめて `<out>/YYYY-MM-DD.md` として書き出す。画像は `<out>/images/` に
保存し、本文中に `![](images/...)` として挿入する。

CMSへの投入はしない（このスクリプトはローカルへの下書き出力のみ）。
出力後は `<out>/確認リスト.md` を見て内容を確認し、問題なければ
upload_drafts.py で一括投入する。

discord.py 等のライブラリは使わず requests のみで実装している
（常駐Bot・Gateway接続は不要。REST APIを叩くだけ）。

使い方:
  # 環境変数でBotトークンを渡す
  export DISCORD_BOT_TOKEN=xxxxxxxx

  # 全履歴を遡って収集（1500回分バックフィル用）
  python collect_discord.py --channel 123456789012345678 \
      --author 891983769358196756 --out drafts

  # 複数チャンネル（旧サーバー→新サーバーの切替などに対応）
  python collect_discord.py --channel 111111111111111111 --channel 222222222222222222 \
      --author 891983769358196756 --out drafts

  # 日次運用（直近3日分だけ取得。cron / Cloud Run Job での定期実行を想定）
  python collect_discord.py --channel 222222222222222222 \
      --author 891983769358196756 --out drafts --days 3

  # 旧サーバー形式（アンカー無し）: 朝4-10時JSTの投稿を日毎にまとめる
  python collect_discord.py --channel 933159394122809354 --author 891983769358196756 \
      --daily-window 4-10 --min-chars 100 --clean --out drafts_old

必要ライブラリ: requests（deploy/auth/requirements.txt に含まれる）
"""

import argparse
import mimetypes
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

DISCORD_API_BASE = "https://discord.com/api/v10"
PAGE_LIMIT = 100

# アンカー判定: 対象authorの投稿本文に「分析N回目」（空白ゆらぎ許容）を含むか
ANCHOR_RE = re.compile(r"分析\s*(\d+)\s*回目")

# 後続連結の打ち切り条件
MAX_MESSAGES_PER_ENTRY = 10
MAX_GAP_SECONDS = 30 * 60  # 30分

JST = timezone(timedelta(hours=9))

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- Discord REST API 呼び出し ----------------------------------------------


class DiscordAPIError(RuntimeError):
    pass


def _headers(token):
    return {"Authorization": f"Bot {token}"}


def fetch_channel_name(session, token, channel_id):
    """エラーメッセージをわかりやすくするためにチャンネル名を取得する（失敗してもIDのままでよい）。"""
    try:
        resp = session.get(
            f"{DISCORD_API_BASE}/channels/{channel_id}", headers=_headers(token), timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("name") or channel_id
    except requests.RequestException:
        pass
    return channel_id


def fetch_messages_page(session, token, channel_id, before=None, after=None):
    """1ページ分（最大100件）のメッセージを新しい順で取得する。レート制限は自動リトライ。"""
    params = {"limit": PAGE_LIMIT}
    if before:
        params["before"] = before
    if after:
        params["after"] = after

    while True:
        resp = session.get(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=_headers(token),
            params=params,
            timeout=30,
        )

        if resp.status_code == 429:
            retry_after = _retry_after_seconds(resp)
            print(
                f"  [レート制限] 429を受信。{retry_after:.1f}秒待機して再試行します…",
                file=sys.stderr,
            )
            time.sleep(retry_after)
            continue

        if resp.status_code == 403:
            raise DiscordAPIError(
                f"チャンネル {channel_id} へのアクセス権がありません（403）。"
                "Botがサーバーに参加しているか、チャンネル閲覧権限があるか確認してください。"
            )
        if resp.status_code == 404:
            raise DiscordAPIError(
                f"チャンネル {channel_id} が見つかりません（404）。チャンネルIDを確認してください。"
            )
        if resp.status_code != 200:
            raise DiscordAPIError(
                f"チャンネル {channel_id}: メッセージ取得に失敗しました "
                f"(HTTP {resp.status_code}) {resp.text[:200]}"
            )

        # X-RateLimit-Remaining が0なら reset まで待ってから返す（次呼び出しの429を予防）
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset_after = resp.headers.get("X-RateLimit-Reset-After")
            if reset_after:
                wait = float(reset_after)
                if wait > 0:
                    print(f"  [レート制限] 残数0のため{wait:.1f}秒待機します…", file=sys.stderr)
                    time.sleep(wait)

        return resp.json()


def _retry_after_seconds(resp):
    try:
        data = resp.json()
        if isinstance(data, dict) and "retry_after" in data:
            return float(data["retry_after"]) + 0.1
    except ValueError:
        pass
    header_val = resp.headers.get("Retry-After")
    if header_val:
        try:
            return float(header_val) + 0.1
        except ValueError:
            pass
    return 1.0


def fetch_all_messages(session, token, channel_id, after_snowflake=None):
    """チャンネルの全メッセージ（or after_snowflake以降）を古い順にして返す。"""
    all_messages = []
    before = None
    while True:
        page = fetch_messages_page(session, token, channel_id, before=before, after=after_snowflake)
        if not page:
            break
        all_messages.extend(page)
        before = page[-1]["id"]  # ページは新しい順で返るので最後(最古)のIDを次のbeforeにする
        if len(page) < PAGE_LIMIT:
            break
    all_messages.sort(key=lambda m: m["id"])  # 古い順（時系列昇順）に統一
    return all_messages


def days_to_after_snowflake(days):
    """直近N日分だけを取るためのDiscord snowflake（afterパラメータ用）を計算する。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return timestamp_to_snowflake(cutoff)


DISCORD_EPOCH_MS = 1420070400000  # 2015-01-01T00:00:00Z


def timestamp_to_snowflake(dt):
    ms = int(dt.timestamp() * 1000)
    return str((ms - DISCORD_EPOCH_MS) << 22)


# --- まとまり判定（アンカー検出・後続連結） ----------------------------------


def parse_created_at(message):
    # 例: "2026-07-02T21:15:00.123000+00:00" / 末尾がZの場合もある
    ts = message["timestamp"]
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def find_anchor_number(content):
    m = ANCHOR_RE.search(content or "")
    if not m:
        return None
    return int(m.group(1))


# --- Discordノイズ除去（--clean） ---------------------------------------------

# メンション: <@123> <@!123>（ユーザー）<@&123>（ロール）<#123>（チャンネル）
MENTION_RE = re.compile(r"<@!?\d+>|<@&\d+>|<#\d+>")
# カスタム絵文字: <:name:123> <a:name:123>
CUSTOM_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")
# 行末の連続空白
TRAILING_SPACES_RE = re.compile(r"[ \t]+$", re.MULTILINE)
# 3行以上の連続空行 -> 空行1つに圧縮
MULTI_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_content(content):
    """Discord記法のノイズを除去する（--clean指定時に各メッセージ本文へ適用）。

    - メンション（ユーザー/ロール/チャンネル）は削除
    - カスタム絵文字は :name: 表記に置換
    - 行末の連続空白を除去し、3行以上の連続空行は2行（空行1つ）に圧縮
    - Unicode絵文字や矢印などの記号はそのまま残す
    """
    if not content:
        return content
    text = MENTION_RE.sub("", content)
    text = CUSTOM_EMOJI_RE.sub(r":\1:", text)
    text = TRAILING_SPACES_RE.sub("", text)
    text = MULTI_BLANK_LINES_RE.sub("\n\n", text)
    return text


def group_messages_into_entries(messages, author_id, anchor_keyword=None, max_follow=None, min_chars=0):
    """時系列昇順のメッセージ列から、対象authorのアンカー投稿を起点とする記事グループを作る。

    anchor_keyword を指定すると「その文字列を含む」ことがアンカー条件になる
    （番号は抽出しない）。省略時は既定の「分析N回目」パターン。
    max_follow は後続として連結する最大メッセージ数（0でアンカーのみ・省略時は既定上限）。
    min_chars を指定すると、本文がN文字未満の後続メッセージは連結対象から除外する
    （アンカー自体には適用しない）。

    戻り値: [{"number": int|None, "messages": [msg, ...]}, ...]
    """
    def anchor_of(content):
        """アンカーなら (True, number|None)、違えば (False, None) を返す。"""
        if anchor_keyword is not None:
            return (anchor_keyword in (content or ""), None)
        num = find_anchor_number(content)
        return (num is not None, num)

    max_len = 1 + (max_follow if max_follow is not None else MAX_MESSAGES_PER_ENTRY - 1)

    groups = []
    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]
        if str(msg.get("author", {}).get("id")) != str(author_id):
            i += 1
            continue

        is_anchor, number = anchor_of(msg.get("content", ""))
        if not is_anchor:
            i += 1
            continue

        # アンカー発見。後続を連結する
        group_messages = [msg]
        last_time = parse_created_at(msg)
        j = i + 1
        while j < n and len(group_messages) < max_len:
            nxt = msg_j = messages[j]
            nxt_author = str(msg_j.get("author", {}).get("id"))

            # (a) 他authorの投稿が挟まる → 打ち切り
            if nxt_author != str(author_id):
                break

            # (c) 次のアンカーが始まる → 打ち切り（このメッセージは次グループの先頭として再処理）
            if anchor_of(msg_j.get("content", ""))[0]:
                break

            nxt_time = parse_created_at(msg_j)
            # (b) 直前メッセージから30分超の間隔 → 打ち切り
            if (nxt_time - last_time).total_seconds() > MAX_GAP_SECONDS:
                break

            # min_chars未満の短いメッセージは連結対象から除外（雑談混入防止）。
            # 打ち切りにはせず読み飛ばして次を見る。
            if min_chars and len(msg_j.get("content", "") or "") < min_chars:
                last_time = nxt_time
                j += 1
                continue

            group_messages.append(msg_j)
            last_time = nxt_time
            j += 1
            # (d) 最大10メッセージは while条件で担保

        groups.append({"number": number, "messages": group_messages})
        i = j  # 消費したメッセージ分だけ進める（次のアンカー探索はjから再開）

    return groups


# --- 時間窓・日毎まとめモード（--daily-window） -------------------------------


def parse_daily_window(spec):
    """"4-10" のような文字列を (start_hour, end_hour) のタプルに変換する。

    窓は [start_hour:00:00, end_hour:00:00) のJST半開区間として扱う
    （例: "4-10" なら 4:00:00〜9:59:59）。
    """
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", spec)
    if not m:
        raise ValueError(f"--daily-window の形式が不正です（例: 4-10）: {spec}")
    start_hour, end_hour = int(m.group(1)), int(m.group(2))
    if not (0 <= start_hour < 24 and 0 < end_hour <= 24 and start_hour < end_hour):
        raise ValueError(f"--daily-window の時刻範囲が不正です: {spec}")
    return start_hour, end_hour


def group_messages_by_daily_window(messages, author_id, window, min_chars=0):
    """対象authorの投稿のうち、JSTの指定時間帯に含まれるものだけを日毎に1グループへまとめる。

    - 30分間隔や他者割り込みでは打ち切らない（--max-follow・アンカー判定は無視）
    - min_chars指定時はN文字未満のメッセージを対象から除外する
    - 番号は連結後の本文からANCHOR_REで検索し、見つかればその番号、無ければNone

    戻り値: [{"number": int|None, "messages": [msg, ...]}, ...]（JST日付の昇順）
    """
    start_hour, end_hour = window

    by_date = {}
    order = []
    for msg in messages:
        if str(msg.get("author", {}).get("id")) != str(author_id):
            continue
        content = msg.get("content", "") or ""
        if min_chars and len(content) < min_chars:
            continue

        jst_dt = parse_created_at(msg).astimezone(JST)
        if not (start_hour <= jst_dt.hour < end_hour):
            continue

        jst_date = jst_dt.date()
        if jst_date not in by_date:
            by_date[jst_date] = []
            order.append(jst_date)
        by_date[jst_date].append(msg)

    groups = []
    for jst_date in order:
        group_messages = by_date[jst_date]
        combined_content = "\n".join(m.get("content", "") or "" for m in group_messages)
        number = find_anchor_number(combined_content)
        groups.append({"number": number, "messages": group_messages})

    return groups


# --- 変換（掲載日・タイトル・本文・画像） -------------------------------------


IMAGE_EXT_BY_CONTENT_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


def posted_date_to_published_date(message):
    """投稿日時(JST)の前日を掲載日として返す（date型）。"""
    created_at = parse_created_at(message)
    jst_dt = created_at.astimezone(JST)
    return (jst_dt.date() - timedelta(days=1))


def guess_image_ext(attachment):
    content_type = (attachment.get("content_type") or "").split(";")[0].strip().lower()
    if content_type in IMAGE_EXT_BY_CONTENT_TYPE:
        return IMAGE_EXT_BY_CONTENT_TYPE[content_type]
    # content_typeが取れない場合はファイル名の拡張子から推測
    filename = attachment.get("filename", "")
    guessed, _ = mimetypes.guess_type(filename)
    if guessed in IMAGE_EXT_BY_CONTENT_TYPE:
        return IMAGE_EXT_BY_CONTENT_TYPE[guessed]
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return None


def is_image_attachment(attachment):
    content_type = (attachment.get("content_type") or "").lower()
    return content_type.startswith("image/")


def download_image(session, token, attachment, dest_path):
    url = attachment.get("url")
    resp = session.get(url, headers=_headers(token), timeout=60)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)


def _first_non_empty_line(text):
    """テキストの最初の非空行（前後空白を除去）を返す。全行空なら空文字列。"""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def build_entry(session, token, group, out_dir, dup_index=0, clean=False):
    """1記事グループを (published_date, title, body_md, image_count, message_count) に変換し、
    画像をダウンロードして out_dir/images に保存する。

    dup_index: 同一掲載日で2件目以降の場合の連番（0なら重複なし）。画像ファイル名の掲載日部分に反映する。
    clean: Trueの場合、各メッセージ本文にclean_content()を適用してから使う（--clean）。
    """
    messages = group["messages"]
    anchor = messages[0]
    published_date = posted_date_to_published_date(anchor)
    date_str = published_date.isoformat()
    file_stem = date_str if dup_index == 0 else f"{date_str}_{dup_index + 1}"

    anchor_content = anchor.get("content") or ""
    if clean:
        anchor_content = clean_content(anchor_content)
    anchor_lines = anchor_content.splitlines()
    title = _first_non_empty_line(anchor_content) or (
        f"分析{group['number']}回目" if group["number"] is not None else "（無題）"
    )
    anchor_rest = "\n".join(anchor_lines[1:]).strip("\n")

    images_dir = os.path.join(out_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    body_parts = []
    if anchor_rest:
        body_parts.append(anchor_rest)

    image_seq = 1
    image_count = 0
    for idx, msg in enumerate(messages):
        # 後続メッセージ本文（アンカー自身の本文は上ですでに処理済み）
        if idx > 0:
            text = (msg.get("content") or "").strip("\n")
            if clean:
                text = clean_content(text)
            if text:
                body_parts.append(text)

        for att in msg.get("attachments", []):
            if not is_image_attachment(att):
                continue
            ext = guess_image_ext(att) or "png"
            image_name = f"{file_stem}_{image_seq}.{ext}"
            image_seq += 1
            image_count += 1
            dest_path = os.path.join(images_dir, image_name)
            download_image(session, token, att, dest_path)
            body_parts.append(f"![](images/{image_name})")

    body_md = "\n\n".join(body_parts).strip("\n")

    return {
        "number": group["number"],
        "published_date": published_date,
        "file_stem": file_stem,
        "title": title,
        "body_md": body_md,
        "message_count": len(messages),
        "image_count": image_count,
        "anchor_message_id": anchor["id"],
    }


# --- 検算レポート -------------------------------------------------------------


def build_confirmation_report(entries):
    """全記事の一覧＋警告を確認リスト.mdの本文として組み立てる。"""
    lines = ["# 確認リスト", ""]
    lines.append("| 番号 | 掲載日 | タイトル | メッセージ数 | 画像数 |")
    lines.append("|---|---|---|---|---|")

    sorted_entries = sorted(entries, key=lambda e: (e["published_date"], e["number"] or 0))
    for e in sorted_entries:
        lines.append(
            f"| {e['number'] if e['number'] is not None else '-'} | {e['published_date'].isoformat()} | {e['title']} | "
            f"{e['message_count']} | {e['image_count']} |"
        )

    warnings = []

    # 番号の欠番・逆転チェック（投稿順=時系列順で判定。キーワードモード等で番号が無い場合はスキップ）
    by_time_order = sorted(entries, key=lambda e: e["anchor_message_id"])
    numbers_in_order = [e["number"] for e in by_time_order if e["number"] is not None]
    for idx in range(1, len(numbers_in_order)):
        prev_n = numbers_in_order[idx - 1]
        cur_n = numbers_in_order[idx]
        if cur_n <= prev_n:
            warnings.append(
                f"番号の逆転: {prev_n}回目 の次に {cur_n}回目 が投稿されています（時系列順）"
            )
        elif cur_n - prev_n > 1:
            missing = ", ".join(str(x) for x in range(prev_n + 1, cur_n))
            warnings.append(f"番号の欠番の可能性: {prev_n}回目 と {cur_n}回目 の間（{missing}）")

    # 同一掲載日の重複チェック
    date_counts = {}
    for e in entries:
        date_counts.setdefault(e["published_date"], []).append(e)
    for date, group in sorted(date_counts.items()):
        if len(group) > 1:
            numbers = ", ".join(str(e["number"] if e["number"] is not None else "-") for e in group)
            warnings.append(
                f"同一掲載日の重複: {date.isoformat()} に {len(group)}件（番号: {numbers}）"
                f" → 2件目以降は *_2.md 等として出力済み。自動投入対象外です。"
            )

    # 日付連続性の食い違い（掲載日が時系列で前後しないか）
    prev_date = None
    for e in by_time_order:
        if prev_date is not None and e["published_date"] < prev_date:
            label = f"{e['number']}回目" if e["number"] is not None else e["title"][:20]
            warnings.append(
                f"日付の逆転: {label} の掲載日 {e['published_date'].isoformat()} が"
                f" 直前の記事より前になっています"
            )
        prev_date = e["published_date"]

    lines.append("")
    lines.append("## 警告")
    lines.append("")
    if warnings:
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("（警告なし）")

    lines.append("")
    return "\n".join(lines) + "\n"


# --- ファイル出力 -------------------------------------------------------------


def write_entry_file(entry, out_dir):
    path = os.path.join(out_dir, f"{entry['file_stem']}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {entry['title']}\n\n{entry['body_md']}\n")
    return path


def assign_dup_indices(groups_with_dates):
    """同一掲載日の記事に連番を振る。1件目は無印、2件目以降は _2, _3, ... とする。

    groups_with_dates: [(group, published_date), ...] 時系列昇順
    戻り値: [(group, published_date, dup_index), ...] dup_index=0が無印
    """
    seen_counts = {}
    result = []
    for group, date in groups_with_dates:
        count = seen_counts.get(date, 0)
        result.append((group, date, count))
        seen_counts[date] = count + 1
    return result


# --- メイン処理 ---------------------------------------------------------------


def collect(
    channels, author_id, out_dir, token, days=None, anchor_keyword=None, max_follow=None,
    daily_window=None, min_chars=0, clean=False,
):
    session = requests.Session()
    os.makedirs(out_dir, exist_ok=True)

    after_snowflake = days_to_after_snowflake(days) if days else None

    all_groups = []
    for channel_id in channels:
        channel_name = fetch_channel_name(session, token, channel_id)
        print(f"[収集] チャンネル {channel_name} ({channel_id}) のメッセージを取得中…")
        try:
            messages = fetch_all_messages(session, token, channel_id, after_snowflake=after_snowflake)
        except DiscordAPIError as e:
            print(f"[エラー] {e}", file=sys.stderr)
            continue
        print(f"  {len(messages)} 件のメッセージを取得しました")

        if daily_window is not None:
            groups = group_messages_by_daily_window(
                messages, author_id, daily_window, min_chars=min_chars
            )
            print(f"  {len(groups)} 日分の投稿をまとめました（時間窓モード）")
        else:
            groups = group_messages_into_entries(
                messages, author_id, anchor_keyword=anchor_keyword, max_follow=max_follow,
                min_chars=min_chars,
            )
            anchor_label = f"「{anchor_keyword}」" if anchor_keyword else "（分析N回目）"
            print(f"  {len(groups)} 件のアンカー{anchor_label}を検出しました")
        all_groups.extend(groups)

    if not all_groups:
        print("対象メッセージが見つかりませんでした。チャンネルID・authorIDを確認してください。")
        return []

    # 掲載日を計算し、時系列（アンカーmessage_id）順にソートして重複連番を割り当てる
    groups_with_dates = []
    for g in all_groups:
        anchor = g["messages"][0]
        published_date = posted_date_to_published_date(anchor)
        groups_with_dates.append((g, published_date))
    groups_with_dates.sort(key=lambda gd: gd[0]["messages"][0]["id"])

    assigned = assign_dup_indices(groups_with_dates)

    entries = []
    for group, _date, dup_index in assigned:
        entry = build_entry(session, token, group, out_dir, dup_index=dup_index, clean=clean)
        entries.append(entry)
        path = write_entry_file(entry, out_dir)
        suffix = "" if dup_index == 0 else "（同日重複・自動投入対象外）"
        print(f"[出力] {path} ({entry['image_count']}枚の画像){suffix}")

    report = build_confirmation_report(entries)
    report_path = os.path.join(out_dir, "確認リスト.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[出力] {report_path}")

    return entries


def main():
    parser = argparse.ArgumentParser(description="Discordの分析コメント収集スクリプト")
    parser.add_argument(
        "--channel", action="append", required=True, dest="channels", help="収集対象チャンネルID（複数指定可）"
    )
    parser.add_argument("--author", required=True, help="対象発信者（分析者さん）のDiscordユーザーID")
    parser.add_argument("--out", default="drafts", help="出力先ディレクトリ（デフォルト: drafts）")
    parser.add_argument(
        "--days", type=int, default=None, help="指定時は直近N日分のみ収集（日次運用モード）。省略時は全履歴"
    )
    parser.add_argument(
        "--anchor-keyword", default=None,
        help="アンカー判定を「この文字列を含む」に変更する（省略時は「分析N回目」パターン）"
    )
    parser.add_argument(
        "--max-follow", type=int, default=None,
        help="アンカーに連結する後続メッセージの最大数（0でアンカーのみ。省略時は既定上限9）"
    )
    parser.add_argument(
        "--daily-window", default=None, metavar="HH-HH",
        help="時間窓・日毎まとめモード。例: 4-10 でJST4:00〜9:59台の対象author投稿を"
             "日毎に1記事へ連結する（--anchor-keywordとは併用不可。--max-follow・アンカー判定は無視）"
    )
    parser.add_argument(
        "--min-chars", type=int, default=0,
        help="本文がN文字未満のメッセージを対象から除外する（雑談・短い返信の混入防止。デフォルト0=無効）"
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Discordのメンション・カスタム絵文字表記・余分な空行を本文から除去する"
    )
    args = parser.parse_args()

    if args.daily_window is not None and args.anchor_keyword is not None:
        print("--daily-window と --anchor-keyword は同時に指定できません。", file=sys.stderr)
        sys.exit(1)

    daily_window = None
    if args.daily_window is not None:
        try:
            daily_window = parse_daily_window(args.daily_window)
        except ValueError as e:
            print(f"[エラー] {e}", file=sys.stderr)
            sys.exit(1)

    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("環境変数 DISCORD_BOT_TOKEN が設定されていません。", file=sys.stderr)
        sys.exit(1)

    collect(
        args.channels, args.author, args.out, token, days=args.days,
        anchor_keyword=args.anchor_keyword, max_follow=args.max_follow,
        daily_window=daily_window, min_chars=args.min_chars, clean=args.clean,
    )


if __name__ == "__main__":
    main()
