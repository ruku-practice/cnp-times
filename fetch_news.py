#!/usr/bin/env python3
"""クリプトニンジャ・ニュース投稿（前日まとめ）を取得して news.json に追記する共通コア。
twikit + Xログインcookie（@ruku_info・捨て垢）で各アカウントの直近投稿を検索し、
クリーニング規則に合うものだけを「対象日＝投稿JST日−1」で news.json にマージ。
既存エントリは上書きしない（手動修正・過去分を保護）。

cookie: 環境変数 X_COOKIES_JSON（中身JSON・クラウド用）優先、無ければ
        X_COOKIES_PATH（ファイル・ローカル用）。selenium形式list / {name:value} 両対応。
"""
import asyncio, json, os, re
from datetime import datetime, timedelta, timezone
from twikit import Client

JST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
NEWS_PATH = os.path.join(HERE, "news.json")
DEFAULT_COOKIE = "/Users/kurokzhr/Library/CloudStorage/GoogleDrive-ruku.practice@gmail.com/マイドライブ/00_XXX_TIMES/00_CreateAutoTimes/x_cookies.json"

DANKU_RE = re.compile(r'^[\s　🌟]*クリプトニンジャ最新情報')
SHACK_PH = ["昨日のクリプトニンジャ", "昨日のCryptoNinjaまとめ", "CryptoNinjaニュースまとめ",
            "昨日のNinjaDAOまとめ", "昨日のCryptoNinja振り返り"]

# (group, account, query) ※recentはカタカナ表記
ACCOUNTS = [
    ("danku", "DANKU_mj",        "from:DANKU_mj クリプトニンジャ"),
    ("shack", "SHACK_SAME_SAME", "from:SHACK_SAME_SAME クリプトニンジャ"),
    ("shack", "sharkrider000",   "from:sharkrider000 クリプトニンジャ"),
]


def load_cookies():
    js = os.getenv("X_COOKIES_JSON")
    raw = json.loads(js) if js else json.load(open(os.getenv("X_COOKIES_PATH", DEFAULT_COOKIE)))
    if isinstance(raw, list):
        return {c["name"]: c["value"] for c in raw}
    return raw


def keep(group, text):
    return bool(DANKU_RE.match(text)) if group == "danku" else any(p in text for p in SHACK_PH)


def target_date(created_at):
    dt = datetime.strptime(str(created_at), "%a %b %d %H:%M:%S %z %Y").astimezone(JST)
    return (dt.date() - timedelta(days=1)).isoformat()


async def main():
    client = Client(language="ja-JP")
    client.set_cookies(load_cookies())
    news = json.load(open(NEWS_PATH, encoding="utf-8")) if os.path.exists(NEWS_PATH) else {}
    added = 0
    for group, acct, q in ACCOUNTS:
        try:
            res = await client.search_tweet(q, "Latest")
        except Exception as e:
            print(f"  {acct} 検索失敗: {e}", flush=True)
            continue
        for t in list(res or [])[:15]:
            if not keep(group, t.text or ""):
                continue
            td = target_date(t.created_at)
            entry = news.setdefault(td, {})
            if group not in entry:                      # 既存は保護（上書きしない）
                entry[group] = {"id": str(t.id), "url": f"https://x.com/{acct}/status/{t.id}", "acct": acct}
                added += 1
                print(f"  + {td} [{group}] {acct} {t.id}", flush=True)
    json.dump(news, open(NEWS_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"news.json 更新: 追加{added} / 計{len(news)}日", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
