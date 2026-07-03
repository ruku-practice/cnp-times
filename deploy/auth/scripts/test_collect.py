"""
collect_discord.py のロジックテスト（Discord API不要・pytest不要）。

requests.Session.get / requests.get を unittest.mock でモックし、偽のDiscordメッセージ
履歴（fixture）を使って以下を確認する:
  1. アンカー検出（「分析1502回目」「分析 1503 回目」などの表記揺れ）
  2. 後続連結と打ち切り4条件（他人割り込み／30分超間隔／次アンカー／10件上限）
  3. 掲載日 = JST投稿日の前日（UTC境界のケース: JST朝6時投稿 = UTC前日21時）
  4. 画像の位置と命名
  5. 同一掲載日重複 → _2.md ＋確認リストへの警告
  6. ページング（before= で2ページ以上）と429リトライ
  7. 収集ルールv2（自動判定モード・--rule-v2）: ルール1/2/3の優先順位、
     クラスタ分割（30分間隔・アンカー前投稿含む・複数アンカー統合）、15件上限

実行方法:
  cd deploy/auth/scripts
  python3 test_collect.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))
import collect_discord as cd  # noqa: E402


AUTHOR_ID = "891983769358196756"
OTHER_ID = "999999999999999999"


def make_message(
    msg_id,
    author_id,
    content,
    timestamp,
    attachments=None,
):
    return {
        "id": msg_id,
        "author": {"id": author_id},
        "content": content,
        "timestamp": timestamp,
        "attachments": attachments or [],
    }


def make_image_attachment(url, filename, content_type):
    return {"url": url, "filename": filename, "content_type": content_type}


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, content=b""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.content = content
        self.text = str(json_data)

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestAnchorDetection(unittest.TestCase):
    def test_anchor_basic(self):
        self.assertEqual(cd.find_anchor_number("分析1502回目 本文…"), 1502)

    def test_anchor_with_spaces(self):
        self.assertEqual(cd.find_anchor_number("分析 1503 回目のコメントです"), 1503)

    def test_anchor_bracket_form(self):
        self.assertEqual(
            cd.find_anchor_number("相場分析【分析1504回目　フロア上昇】"), 1504
        )

    def test_no_anchor(self):
        self.assertIsNone(cd.find_anchor_number("普通のコメントです"))

    def test_no_anchor_empty(self):
        self.assertIsNone(cd.find_anchor_number(""))
        self.assertIsNone(cd.find_anchor_number(None))


class TestGrouping(unittest.TestCase):
    def test_basic_group_and_continuation(self):
        """アンカー＋同一author連続投稿が1グループに連結される。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文1行目", "2026-07-02T10:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "続き2", "2026-07-02T10:05:00.000000+00:00"),
            make_message("3", AUTHOR_ID, "続き3", "2026-07-02T10:10:00.000000+00:00"),
        ]
        groups = cd.group_messages_into_entries(messages, AUTHOR_ID)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["number"], 1502)
        self.assertEqual(len(groups[0]["messages"]), 3)

    def test_cutoff_other_author_interrupts(self):
        """(a) 他authorの投稿が挟まると打ち切り。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文", "2026-07-02T10:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "続き", "2026-07-02T10:05:00.000000+00:00"),
            make_message("3", OTHER_ID, "横から失礼", "2026-07-02T10:06:00.000000+00:00"),
            make_message("4", AUTHOR_ID, "本当は続きだが打ち切り後なので含まれない", "2026-07-02T10:07:00.000000+00:00"),
        ]
        groups = cd.group_messages_into_entries(messages, AUTHOR_ID)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 2)

    def test_cutoff_gap_over_30min(self):
        """(b) 前のメッセージから30分超で打ち切り。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文", "2026-07-02T10:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "続き（29分後・セーフ）", "2026-07-02T10:29:00.000000+00:00"),
            make_message("3", AUTHOR_ID, "続き（前から31分後・打ち切り）", "2026-07-02T11:00:01.000000+00:00"),
        ]
        groups = cd.group_messages_into_entries(messages, AUTHOR_ID)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 2)

    def test_cutoff_next_anchor(self):
        """(c) 次のアンカーが始まると打ち切り、次のグループとして扱われる。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文A", "2026-07-02T10:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "続きA", "2026-07-02T10:05:00.000000+00:00"),
            make_message("3", AUTHOR_ID, "分析1503回目\n本文B", "2026-07-02T10:10:00.000000+00:00"),
        ]
        groups = cd.group_messages_into_entries(messages, AUTHOR_ID)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["number"], 1502)
        self.assertEqual(len(groups[0]["messages"]), 2)
        self.assertEqual(groups[1]["number"], 1503)
        self.assertEqual(len(groups[1]["messages"]), 1)

    def test_cutoff_max_10_messages(self):
        """(d) アンカー含め最大10メッセージ。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文", "2026-07-02T10:00:00.000000+00:00")
        ]
        for k in range(2, 15):
            messages.append(
                make_message(
                    str(k), AUTHOR_ID, f"続き{k}", f"2026-07-02T10:{k:02d}:00.000000+00:00"
                )
            )
        groups = cd.group_messages_into_entries(messages, AUTHOR_ID)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 10)


class TestDailyWindow(unittest.TestCase):
    """--daily-window（時間窓・日毎まとめモード）のテスト。"""

    def test_only_within_window_jst_boundary(self):
        """(a) JST4-10時台のみ拾う。JST4時=UTC前日19時の境界を含む。"""
        messages = [
            # JST 2026-07-02T03:59:59 (窓外・直前) -> UTC 2026-07-01T18:59:59
            make_message("1", AUTHOR_ID, "窓の直前（対象外）", "2026-07-01T18:59:59.000000+00:00"),
            # JST 2026-07-02T04:00:00 (窓の開始・境界) -> UTC 2026-07-01T19:00:00
            make_message("2", AUTHOR_ID, "窓の開始（対象）", "2026-07-01T19:00:00.000000+00:00"),
            # JST 2026-07-02T09:59:59 (窓の終端直前・対象) -> UTC 2026-07-02T00:59:59
            make_message("3", AUTHOR_ID, "窓の終端直前（対象）", "2026-07-02T00:59:59.000000+00:00"),
            # JST 2026-07-02T10:00:00 (窓外・終端) -> UTC 2026-07-02T01:00:00
            make_message("4", AUTHOR_ID, "窓の終端（対象外）", "2026-07-02T01:00:00.000000+00:00"),
        ]
        groups = cd.group_messages_by_daily_window(messages, AUTHOR_ID, (4, 10))
        self.assertEqual(len(groups), 1)
        contents = [m["content"] for m in groups[0]["messages"]]
        self.assertEqual(contents, ["窓の開始（対象）", "窓の終端直前（対象）"])

    def test_same_day_multiple_messages_combined(self):
        """(b) 同日複数メッセージが1記事に連結される（30分超間隔でも打ち切らない）。"""
        messages = [
            make_message("1", AUTHOR_ID, "朝1件目", "2026-07-01T19:00:00.000000+00:00"),  # JST 4:00
            make_message("2", AUTHOR_ID, "朝2件目（1時間後）", "2026-07-01T20:00:00.000000+00:00"),  # JST 5:00
            make_message("3", AUTHOR_ID, "朝3件目（さらに2時間後）", "2026-07-01T22:00:00.000000+00:00"),  # JST 7:00
        ]
        groups = cd.group_messages_by_daily_window(messages, AUTHOR_ID, (4, 10))
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 3)

    def test_multiple_days_become_separate_entries(self):
        """(c) 複数日にまたがる投稿は日毎に別記事になる。"""
        messages = [
            make_message("1", AUTHOR_ID, "1日目", "2026-07-01T19:00:00.000000+00:00"),  # JST 7/2 4:00
            make_message("2", AUTHOR_ID, "2日目", "2026-07-02T19:00:00.000000+00:00"),  # JST 7/3 4:00
        ]
        groups = cd.group_messages_by_daily_window(messages, AUTHOR_ID, (4, 10))
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0]["messages"]), 1)
        self.assertEqual(len(groups[1]["messages"]), 1)

    def test_other_author_and_out_of_window_ignored_but_no_cutoff(self):
        """他authorの投稿や窓外投稿が間に挟まっても対象メッセージの連結は打ち切られない。"""
        messages = [
            make_message("1", AUTHOR_ID, "朝1件目", "2026-07-01T19:00:00.000000+00:00"),  # JST 4:00
            make_message("2", OTHER_ID, "野次馬（窓内だが他author）", "2026-07-01T19:30:00.000000+00:00"),
            make_message("3", AUTHOR_ID, "朝2件目", "2026-07-01T20:00:00.000000+00:00"),  # JST 5:00
        ]
        groups = cd.group_messages_by_daily_window(messages, AUTHOR_ID, (4, 10))
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 2)

    def test_title_is_first_non_empty_line_of_first_message(self):
        """(d) タイトル=その日の最初のメッセージの最初の非空行。"""
        messages = [
            make_message("1", AUTHOR_ID, "\n\n本日の分析タイトル\n続きの本文", "2026-07-01T19:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "続き2件目", "2026-07-01T20:00:00.000000+00:00"),
        ]
        groups = cd.group_messages_by_daily_window(messages, AUTHOR_ID, (4, 10))
        out_dir = tempfile.mkdtemp(prefix="cnp_collect_dw_title_")
        try:
            session = MagicMock()
            entry = cd.build_entry(session, "fake-token", groups[0], out_dir, dup_index=0)
            self.assertEqual(entry["title"], "本日の分析タイトル")
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_anchor_number_detected_if_present(self):
        """(e) 連結後の本文に「分析N回目」があれば番号を設定、無ければNone。"""
        messages_with_anchor = [
            make_message("1", AUTHOR_ID, "おはようございます", "2026-07-01T19:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "分析1502回目の内容です", "2026-07-01T20:00:00.000000+00:00"),
        ]
        groups = cd.group_messages_by_daily_window(messages_with_anchor, AUTHOR_ID, (4, 10))
        self.assertEqual(groups[0]["number"], 1502)

        messages_without_anchor = [
            make_message("1", AUTHOR_ID, "おはようございます", "2026-07-01T19:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "今日も相場をみていきます", "2026-07-01T20:00:00.000000+00:00"),
        ]
        groups2 = cd.group_messages_by_daily_window(messages_without_anchor, AUTHOR_ID, (4, 10))
        self.assertIsNone(groups2[0]["number"])

    def test_parse_daily_window_valid_and_invalid(self):
        self.assertEqual(cd.parse_daily_window("4-10"), (4, 10))
        with self.assertRaises(ValueError):
            cd.parse_daily_window("10-4")
        with self.assertRaises(ValueError):
            cd.parse_daily_window("not-a-window")

    def test_daily_window_and_anchor_keyword_conflict_in_cli(self):
        """CLIレベルで --daily-window と --anchor-keyword の同時指定はエラーになる。"""
        import subprocess

        script_path = os.path.join(os.path.dirname(__file__), "collect_discord.py")
        env = dict(os.environ)
        env["DISCORD_BOT_TOKEN"] = "dummy"
        result = subprocess.run(
            [
                sys.executable, script_path,
                "--channel", "1", "--author", AUTHOR_ID,
                "--daily-window", "4-10", "--anchor-keyword", "分析",
            ],
            capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(result.returncode, 0)


class TestMinChars(unittest.TestCase):
    def test_min_chars_excludes_short_followups(self):
        """--min-chars 指定時、短い後続メッセージは連結対象から除外される。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文", "2026-07-02T10:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "OK", "2026-07-02T10:05:00.000000+00:00"),  # 短いので除外
            make_message("3", AUTHOR_ID, "これはそこそこ長い後続コメントです", "2026-07-02T10:10:00.000000+00:00"),
        ]
        groups = cd.group_messages_into_entries(messages, AUTHOR_ID, min_chars=5)
        self.assertEqual(len(groups), 1)
        contents = [m["content"] for m in groups[0]["messages"]]
        self.assertNotIn("OK", contents)
        self.assertIn("これはそこそこ長い後続コメントです", contents)

    def test_min_chars_applied_in_daily_window_mode(self):
        """時間窓モードでも --min-chars で短いメッセージが除外される。"""
        messages = [
            make_message("1", AUTHOR_ID, "おはよう", "2026-07-01T19:00:00.000000+00:00"),  # 4文字・除外
            make_message("2", AUTHOR_ID, "本日の分析はこちらになります", "2026-07-01T20:00:00.000000+00:00"),
        ]
        groups = cd.group_messages_by_daily_window(messages, AUTHOR_ID, (4, 10), min_chars=10)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 1)
        self.assertEqual(groups[0]["messages"][0]["content"], "本日の分析はこちらになります")


class TestCleanContent(unittest.TestCase):
    def test_mentions_removed(self):
        text = "こんにちは<@123456>さん <@!789>くん <@&555>ロール <#222>チャンネル"
        cleaned = cd.clean_content(text)
        self.assertNotIn("<@123456>", cleaned)
        self.assertNotIn("<@!789>", cleaned)
        self.assertNotIn("<@&555>", cleaned)
        self.assertNotIn("<#222>", cleaned)

    def test_custom_emoji_replaced(self):
        text = "上昇しました<:pepe_up:1234567890> 参考<a:loading:987>"
        cleaned = cd.clean_content(text)
        self.assertIn(":pepe_up:", cleaned)
        self.assertIn(":loading:", cleaned)
        self.assertNotIn("<:pepe_up:1234567890>", cleaned)
        self.assertNotIn("<a:loading:987>", cleaned)

    def test_blank_lines_compressed(self):
        text = "1行目\n\n\n\n\n2行目"
        cleaned = cd.clean_content(text)
        self.assertEqual(cleaned, "1行目\n\n2行目")

    def test_trailing_spaces_stripped(self):
        text = "1行目   \n2行目\t\t\n3行目"
        cleaned = cd.clean_content(text)
        self.assertEqual(cleaned, "1行目\n2行目\n3行目")

    def test_symbols_and_unicode_emoji_preserved(self):
        """矢印記号やUnicode絵文字は分析内容なので消さずに残す。"""
        text = "フロア↑↓－⇒上昇トレンド 🚀📈"
        cleaned = cd.clean_content(text)
        self.assertIn("↑", cleaned)
        self.assertIn("↓", cleaned)
        self.assertIn("－", cleaned)
        self.assertIn("⇒", cleaned)
        self.assertIn("🚀", cleaned)
        self.assertIn("📈", cleaned)

    def test_clean_applied_via_build_entry(self):
        """--clean 指定時、build_entry経由でも本文がクリーンになる。"""
        messages = [
            make_message(
                "1", AUTHOR_ID,
                "分析1502回目<@123>さん\nフロア↑上昇中<:pepe:999>\n\n\n\n続き",
                "2026-07-02T10:00:00.000000+00:00",
            ),
        ]
        groups = cd.group_messages_into_entries(messages, AUTHOR_ID)
        out_dir = tempfile.mkdtemp(prefix="cnp_collect_clean_")
        try:
            session = MagicMock()
            entry = cd.build_entry(session, "fake-token", groups[0], out_dir, dup_index=0, clean=True)
            self.assertNotIn("<@123>", entry["body_md"])
            self.assertNotIn("<:pepe:999>", entry["body_md"])
            self.assertIn(":pepe:", entry["body_md"])
            self.assertIn("↑", entry["body_md"])
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


class TestPublishedDate(unittest.TestCase):
    def test_published_date_is_previous_day_jst(self):
        """掲載日 = 投稿日時(JST)の前日。7/2 21:15 JST投稿 -> 掲載日7/1。"""
        msg = make_message("1", AUTHOR_ID, "分析1502回目", "2026-07-02T12:15:00.000000+00:00")
        # UTC 12:15 -> JST 21:15 (7/2) -> 前日 7/1
        date = cd.posted_date_to_published_date(msg)
        self.assertEqual(date.isoformat(), "2026-07-01")

    def test_utc_boundary_jst_early_morning(self):
        """JST朝6時投稿 = UTC前日21時。日付繰り上がりを跨いでも正しく前日になる。"""
        # UTC 2026-07-01T21:00:00 -> JST 2026-07-02T06:00:00 -> 前日 2026-07-01
        msg = make_message("1", AUTHOR_ID, "分析1600回目", "2026-07-01T21:00:00.000000+00:00")
        date = cd.posted_date_to_published_date(msg)
        self.assertEqual(date.isoformat(), "2026-07-01")

    def test_z_suffix_timestamp(self):
        """タイムスタンプ末尾がZ表記でもパースできる。"""
        msg = make_message("1", AUTHOR_ID, "分析1502回目", "2026-07-02T12:15:00.000000Z")
        date = cd.posted_date_to_published_date(msg)
        self.assertEqual(date.isoformat(), "2026-07-01")


class TestBuildEntryAndImages(unittest.TestCase):
    def setUp(self):
        self.out_dir = tempfile.mkdtemp(prefix="cnp_collect_test_")

    def tearDown(self):
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_title_and_body_and_image_position(self):
        messages = [
            make_message(
                "1",
                AUTHOR_ID,
                "相場分析【分析1502回目　フロア上昇】\nアンカー残りの本文",
                "2026-07-02T10:00:00.000000+00:00",
                attachments=[
                    make_image_attachment(
                        "https://cdn.discordapp.com/attachments/x/y/chart.png",
                        "chart.png",
                        "image/png",
                    )
                ],
            ),
            make_message("2", AUTHOR_ID, "続きのコメント", "2026-07-02T10:05:00.000000+00:00"),
        ]
        groups = cd.group_messages_into_entries(messages, AUTHOR_ID)
        self.assertEqual(len(groups), 1)

        session = MagicMock()
        session.get.return_value = FakeResponse(200, content=b"FAKEPNGDATA")

        entry = cd.build_entry(session, "fake-token", groups[0], self.out_dir, dup_index=0)

        self.assertEqual(entry["title"], "相場分析【分析1502回目　フロア上昇】")
        self.assertIn("アンカー残りの本文", entry["body_md"])
        self.assertIn("続きのコメント", entry["body_md"])
        self.assertEqual(entry["image_count"], 1)

        # 画像参照が本文中に挿入されている
        self.assertIn("![](images/2026-07-01_1.png)", entry["body_md"])
        # アンカー残り本文より後、続きコメントより前に画像参照がある想定
        idx_anchor = entry["body_md"].index("アンカー残りの本文")
        idx_image = entry["body_md"].index("![](images/2026-07-01_1.png)")
        idx_next = entry["body_md"].index("続きのコメント")
        self.assertTrue(idx_anchor < idx_image < idx_next)

        # 画像が実際に保存されている
        image_path = os.path.join(self.out_dir, "images", "2026-07-01_1.png")
        self.assertTrue(os.path.exists(image_path))
        with open(image_path, "rb") as f:
            self.assertEqual(f.read(), b"FAKEPNGDATA")

    def test_non_image_attachment_ignored(self):
        messages = [
            make_message(
                "1",
                AUTHOR_ID,
                "分析1502回目\n本文",
                "2026-07-02T10:00:00.000000+00:00",
                attachments=[
                    make_image_attachment(
                        "https://cdn.discordapp.com/attachments/x/y/data.pdf",
                        "data.pdf",
                        "application/pdf",
                    )
                ],
            ),
        ]
        groups = cd.group_messages_into_entries(messages, AUTHOR_ID)
        session = MagicMock()
        entry = cd.build_entry(session, "fake-token", groups[0], self.out_dir, dup_index=0)
        self.assertEqual(entry["image_count"], 0)
        session.get.assert_not_called()


class TestDuplicatePublishedDate(unittest.TestCase):
    def test_duplicate_date_gets_suffix_and_warning(self):
        """同一掲載日に複数記事 -> 2件目以降は _2.md 扱いになり、確認リストに警告が出る。"""
        out_dir = tempfile.mkdtemp(prefix="cnp_collect_dup_test_")
        try:
            # 両方とも 7/2 JSTの朝(=掲載日7/1)に投稿された想定で、同じ掲載日になる2つのアンカー
            messages = [
                make_message("1", AUTHOR_ID, "分析1502回目\n本文A", "2026-07-01T22:00:00.000000+00:00"),
                make_message("2", AUTHOR_ID, "分析1503回目\n本文B", "2026-07-01T23:00:00.000000+00:00"),
            ]
            groups = cd.group_messages_into_entries(messages, AUTHOR_ID)
            self.assertEqual(len(groups), 2)

            groups_with_dates = []
            for g in groups:
                anchor = g["messages"][0]
                date = cd.posted_date_to_published_date(anchor)
                groups_with_dates.append((g, date))

            # 両方 2026-07-01 になっているはず
            self.assertEqual(groups_with_dates[0][1].isoformat(), "2026-07-01")
            self.assertEqual(groups_with_dates[1][1].isoformat(), "2026-07-01")

            assigned = cd.assign_dup_indices(groups_with_dates)
            session = MagicMock()
            entries = []
            for group, _date, dup_index in assigned:
                entry = cd.build_entry(session, "fake-token", group, out_dir, dup_index=dup_index)
                entries.append(entry)
                cd.write_entry_file(entry, out_dir)

            self.assertTrue(os.path.exists(os.path.join(out_dir, "2026-07-01.md")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "2026-07-01_2.md")))

            report = cd.build_confirmation_report(entries)
            self.assertIn("同一掲載日の重複", report)
            self.assertIn("2026-07-01", report)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_missing_number_and_reversal_warnings(self):
        """番号の欠番・逆転が確認リストに警告として出る。"""
        entries = [
            {
                "number": 1502,
                "published_date": cd.datetime(2026, 7, 1).date(),
                "title": "t1502",
                "message_count": 1,
                "image_count": 0,
                "anchor_message_id": "1",
            },
            {
                "number": 1505,  # 1503, 1504 が欠番
                "published_date": cd.datetime(2026, 7, 2).date(),
                "title": "t1505",
                "message_count": 1,
                "image_count": 0,
                "anchor_message_id": "2",
            },
            {
                "number": 1504,  # 直前(1505)より小さい = 逆転
                "published_date": cd.datetime(2026, 7, 3).date(),
                "title": "t1504",
                "message_count": 1,
                "image_count": 0,
                "anchor_message_id": "3",
            },
        ]
        report = cd.build_confirmation_report(entries)
        self.assertIn("欠番", report)
        self.assertIn("逆転", report)


class TestPagingAndRateLimit(unittest.TestCase):
    def test_paging_two_pages(self):
        """before= を使って2ページ以上を正しく連結して取得する。"""
        # 新しい順(id降順)で返る想定。IDは3桁ゼロ埋めで文字列比較=数値比較になるようにする。
        # 1ページ目: id 105..006 (100件, 新しい順), 2ページ目: id 005..001 (5件, limit未満で終了)
        page1 = [
            make_message(f"{105 - k:03d}", AUTHOR_ID, f"msg{105-k}", "2026-07-02T10:00:00.000000+00:00")
            for k in range(100)
        ]
        page2 = [
            make_message(f"{k:03d}", AUTHOR_ID, f"msg{k}", "2026-07-02T09:00:00.000000+00:00")
            for k in range(5, 0, -1)
        ]

        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append(dict(params or {}))
            if "before" not in (params or {}):
                return FakeResponse(200, json_data=page1, headers={"X-RateLimit-Remaining": "5"})
            else:
                return FakeResponse(200, json_data=page2, headers={"X-RateLimit-Remaining": "5"})

        session = MagicMock()
        session.get.side_effect = fake_get

        all_messages = cd.fetch_all_messages(session, "fake-token", "channel-1")
        self.assertEqual(len(all_messages), 105)
        # 古い順にソートされている
        ids = [int(m["id"]) for m in all_messages]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(calls), 2)
        self.assertNotIn("before", calls[0])
        self.assertEqual(calls[1]["before"], "006")  # 1ページ目最後(最古)のID

    def test_rate_limit_429_then_success(self):
        """429を受けたらRetry-After秒待って再試行する。"""
        responses = [
            FakeResponse(429, json_data={"retry_after": 0.01}, headers={}),
            FakeResponse(200, json_data=[], headers={"X-RateLimit-Remaining": "10"}),
        ]

        session = MagicMock()
        session.get.side_effect = responses

        with patch("time.sleep") as mock_sleep:
            page = cd.fetch_messages_page(session, "fake-token", "channel-1")
        self.assertEqual(page, [])
        mock_sleep.assert_called_once()
        self.assertEqual(session.get.call_count, 2)

    def test_rate_limit_remaining_zero_waits_before_returning(self):
        """X-RateLimit-Remainingが0ならreset-afterまで待機してから結果を返す。"""
        resp = FakeResponse(
            200,
            json_data=[],
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "0.02"},
        )
        session = MagicMock()
        session.get.return_value = resp

        with patch("time.sleep") as mock_sleep:
            page = cd.fetch_messages_page(session, "fake-token", "channel-1")
        self.assertEqual(page, [])
        mock_sleep.assert_called_once()

    def test_403_raises_clear_error(self):
        session = MagicMock()
        session.get.return_value = FakeResponse(403, json_data={})
        with self.assertRaises(cd.DiscordAPIError) as ctx:
            cd.fetch_messages_page(session, "fake-token", "channel-1")
        self.assertIn("403", str(ctx.exception))

    def test_404_raises_clear_error(self):
        session = MagicMock()
        session.get.return_value = FakeResponse(404, json_data={})
        with self.assertRaises(cd.DiscordAPIError) as ctx:
            cd.fetch_messages_page(session, "fake-token", "channel-1")
        self.assertIn("404", str(ctx.exception))


class TestEndToEndCollect(unittest.TestCase):
    """collect() 関数の統合テスト（requestsのgetを丸ごとモック）。"""

    def setUp(self):
        self.out_dir = tempfile.mkdtemp(prefix="cnp_collect_e2e_")

    def tearDown(self):
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_collect_end_to_end(self):
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文A", "2026-07-02T10:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "続きA", "2026-07-02T10:05:00.000000+00:00"),
            make_message("3", OTHER_ID, "野次馬コメント", "2026-07-02T10:06:00.000000+00:00"),
            make_message("4", AUTHOR_ID, "分析1503回目\n本文B", "2026-07-03T10:00:00.000000+00:00"),
        ]

        def fake_get(url, headers=None, params=None, timeout=None):
            if url.endswith("/messages"):
                if "before" not in (params or {}):
                    return FakeResponse(200, json_data=list(reversed(messages)), headers={})
                return FakeResponse(200, json_data=[], headers={})
            if "/channels/" in url:
                return FakeResponse(200, json_data={"name": "test-channel"})
            raise AssertionError(f"unexpected url {url}")

        with patch.object(cd.requests, "Session") as MockSession:
            mock_session = MagicMock()
            mock_session.get.side_effect = fake_get
            MockSession.return_value = mock_session

            entries = cd.collect(["channel-1"], AUTHOR_ID, self.out_dir, "fake-token")

        self.assertEqual(len(entries), 2)
        self.assertTrue(os.path.exists(os.path.join(self.out_dir, "2026-07-01.md")))
        self.assertTrue(os.path.exists(os.path.join(self.out_dir, "2026-07-02.md")))
        self.assertTrue(os.path.exists(os.path.join(self.out_dir, "確認リスト.md")))

        with open(os.path.join(self.out_dir, "2026-07-01.md"), encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(content.startswith("# 分析1502回目"))
        self.assertIn("本文A", content)
        self.assertIn("続きA", content)
        self.assertNotIn("野次馬コメント", content)


class TestRuleV2(unittest.TestCase):
    """収集ルールv2（自動判定モード・--rule-v2）のテスト。"""

    def test_rule1_priority_over_date_header(self):
        """ルール1優先: 「分析N回目」がある日は日付ヘッダーがあってもルール1として拾う。"""
        messages = [
            make_message(
                "1", AUTHOR_ID, "3/16（木）06：30頃\nおはようございます",
                "2026-03-15T21:00:00.000000+00:00",  # JST 3/16 6:00
            ),
            make_message(
                "2", AUTHOR_ID, "分析1502回目\n本文",
                "2026-03-15T21:10:00.000000+00:00",  # JST 3/16 6:10
            ),
        ]
        warnings = []
        groups = cd.group_messages_rule_v2(messages, AUTHOR_ID, warnings=warnings)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["rule"], 1)
        self.assertEqual(groups[0]["number"], 1502)
        # ルール1: 30分以内で繋がる同じクラスタなので両方含まれる
        self.assertEqual(len(groups[0]["messages"]), 2)

    def test_rule2_date_header_variants(self):
        """ルール2: 日付ヘッダーの表記揺れ（全角/半角括弧・全角コロン・「頃」なし）を検出する。"""
        variants = [
            "3/16（木）06：30頃",  # 全角括弧+全角コロン+頃
            "3/16(木) 06:30頃",     # 半角括弧+半角コロン+頃
            "3/16（木）06：30",     # 頃なし
            "3/16(木)06:30",        # 半角・頃なし・空白なし
        ]
        for text in variants:
            with self.subTest(text=text):
                self.assertTrue(cd.has_date_header(text), f"検出できませんでした: {text}")

    def test_rule2_used_when_no_rule1(self):
        """分析N回目が無い日は日付ヘッダーをアンカーとしてルール2で拾う。"""
        messages = [
            make_message(
                "1", AUTHOR_ID, "3/16（木）06：30頃\n本日の相場は…",
                "2026-03-15T21:00:00.000000+00:00",  # JST 3/16 6:00
            ),
            make_message(
                "2", AUTHOR_ID, "続きのコメント",
                "2026-03-15T21:10:00.000000+00:00",
            ),
        ]
        warnings = []
        groups = cd.group_messages_rule_v2(messages, AUTHOR_ID, warnings=warnings)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["rule"], 2)
        self.assertIsNone(groups[0]["number"])
        self.assertEqual(len(groups[0]["messages"]), 2)

    def test_rule3_fallback_window(self):
        """ルール3フォールバック: アンカー無しの日は朝4-10時窓、窓外のみの日は記事なし。"""
        messages = [
            # 3/16: アンカー無し、朝5時台の投稿のみ -> ルール3で拾われる
            make_message("1", AUTHOR_ID, "朝の一言", "2026-03-15T20:00:00.000000+00:00"),  # JST 3/16 5:00
            # 3/17: アンカー無し、投稿は昼(窓外)のみ -> 記事なし
            make_message("2", AUTHOR_ID, "昼の一言", "2026-03-17T03:00:00.000000+00:00"),  # JST 3/17 12:00
        ]
        warnings = []
        groups = cd.group_messages_rule_v2(messages, AUTHOR_ID, warnings=warnings)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["rule"], 3)
        self.assertEqual(len(groups[0]["messages"]), 1)
        self.assertEqual(groups[0]["messages"][0]["content"], "朝の一言")

    def test_other_author_interrupt_does_not_break_cluster(self):
        """他authorの割り込みがあってもクラスタが繋がる（対象author投稿だけを見るため）。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文", "2026-07-02T01:00:00.000000+00:00"),
            make_message("2", OTHER_ID, "横から失礼", "2026-07-02T01:05:00.000000+00:00"),
            make_message("3", AUTHOR_ID, "続き（他人の割り込み後でも連結）", "2026-07-02T01:10:00.000000+00:00"),
        ]
        warnings = []
        groups = cd.group_messages_rule_v2(messages, AUTHOR_ID, warnings=warnings)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 2)
        contents = [m["content"] for m in groups[0]["messages"]]
        self.assertIn("続き（他人の割り込み後でも連結）", contents)

    def test_messages_before_anchor_included_in_cluster(self):
        """アンカーより前の投稿もクラスタ内なら含まれる。"""
        messages = [
            make_message("1", AUTHOR_ID, "おはようございます", "2026-07-02T01:00:00.000000+00:00"),
            make_message("2", AUTHOR_ID, "分析1502回目\n本文", "2026-07-02T01:10:00.000000+00:00"),
            make_message("3", AUTHOR_ID, "続き", "2026-07-02T01:15:00.000000+00:00"),
        ]
        warnings = []
        groups = cd.group_messages_rule_v2(messages, AUTHOR_ID, warnings=warnings)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 3)
        self.assertEqual(groups[0]["messages"][0]["content"], "おはようございます")

    def test_gap_over_30min_splits_cluster_only_anchor_side_kept(self):
        """30分超の間隔でクラスタが分かれ、アンカーを含む方だけ採用される。"""
        messages = [
            # クラスタA（アンカー無し）
            make_message("1", AUTHOR_ID, "昨夜の雑談メモ", "2026-07-02T00:00:00.000000+00:00"),
            # 31分以上の間隔 -> クラスタ分割
            make_message("2", AUTHOR_ID, "分析1502回目\n本文", "2026-07-02T01:00:00.000000+00:00"),
            make_message("3", AUTHOR_ID, "続き", "2026-07-02T01:05:00.000000+00:00"),
        ]
        warnings = []
        groups = cd.group_messages_rule_v2(messages, AUTHOR_ID, warnings=warnings)
        self.assertEqual(len(groups), 1)
        contents = [m["content"] for m in groups[0]["messages"]]
        self.assertNotIn("昨夜の雑談メモ", contents)
        self.assertIn("分析1502回目\n本文", contents)
        self.assertIn("続き", contents)

    def test_multiple_anchors_same_day_merged_into_one_entry(self):
        """同日複数アンカー→1記事に統合される。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文A", "2026-07-02T00:00:00.000000+00:00"),
            # 31分以上あけて2つ目のクラスタ（別アンカー）
            make_message("2", AUTHOR_ID, "分析1503回目\n本文B", "2026-07-02T02:00:00.000000+00:00"),
        ]
        warnings = []
        groups = cd.group_messages_rule_v2(messages, AUTHOR_ID, warnings=warnings)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 2)
        # 番号は結合後の本文から検出される最初の一致（1502）
        self.assertEqual(groups[0]["number"], 1502)

    def test_cluster_message_limit_15_with_warning(self):
        """15件上限で打ち切られ、警告が記録される。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文", "2026-07-02T00:00:00.000000+00:00"),
        ]
        for k in range(2, 20):  # 合計19件（上限15を超える）
            messages.append(
                make_message(
                    str(k), AUTHOR_ID, f"続き{k}",
                    f"2026-07-02T00:{k:02d}:00.000000+00:00",
                )
            )
        warnings = []
        groups = cd.group_messages_rule_v2(messages, AUTHOR_ID, warnings=warnings)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), cd.RULE_V2_MAX_CLUSTER_MESSAGES)
        self.assertTrue(any("15" in w or "件を超え" in w for w in warnings))

    def test_rule_v2_and_anchor_keyword_conflict_in_cli(self):
        """CLIレベルで --rule-v2 と --anchor-keyword の同時指定はエラーになる。"""
        import subprocess

        script_path = os.path.join(os.path.dirname(__file__), "collect_discord.py")
        env = dict(os.environ)
        env["DISCORD_BOT_TOKEN"] = "dummy"
        result = subprocess.run(
            [
                sys.executable, script_path,
                "--channel", "1", "--author", AUTHOR_ID,
                "--rule-v2", "--anchor-keyword", "分析",
            ],
            capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_rule_v2_and_daily_window_conflict_in_cli(self):
        """CLIレベルで --rule-v2 と --daily-window の同時指定はエラーになる。"""
        import subprocess

        script_path = os.path.join(os.path.dirname(__file__), "collect_discord.py")
        env = dict(os.environ)
        env["DISCORD_BOT_TOKEN"] = "dummy"
        result = subprocess.run(
            [
                sys.executable, script_path,
                "--channel", "1", "--author", AUTHOR_ID,
                "--rule-v2", "--daily-window", "4-10",
            ],
            capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_confirmation_report_includes_rule_column(self):
        """確認リストに「どのルールで拾ったか」の列が出力される。"""
        messages = [
            make_message("1", AUTHOR_ID, "分析1502回目\n本文", "2026-07-02T00:00:00.000000+00:00"),
        ]
        warnings = []
        groups = cd.group_messages_rule_v2(messages, AUTHOR_ID, warnings=warnings)
        out_dir = tempfile.mkdtemp(prefix="cnp_collect_rulev2_report_")
        try:
            session = MagicMock()
            entry = cd.build_entry(session, "fake-token", groups[0], out_dir, dup_index=0)
            self.assertEqual(entry["rule"], 1)
            report = cd.build_confirmation_report([entry])
            self.assertIn("ルール", report)
            self.assertIn("ルール1", report)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
