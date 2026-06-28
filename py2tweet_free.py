#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
py2tweet_free.py  ―  公式API(tweepy)を使わず、保存済みCookie + twikit で
                     X にスレッド投稿する版（無料・APIキー不要）。
"""

import argparse
import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from twikit import Client

# ─────────────────────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
SERVICE_ACCOUNT_JSON = Path(os.environ.get("GOOGLE_CREDENTIALS_PATH", BASE_DIR / "service_account.json"))
if not SERVICE_ACCOUNT_JSON.exists():
    # ローカル実行時の代替パス
    SERVICE_ACCOUNT_JSON = Path(__file__).resolve().parent / "writeinfo2spreadsheet-d08cec7b431b.json"

SPREADSHEET_KEY = "1MNQuV9PODKDm9gqEddL3q7keBC92LkV5ZOYEPNa0ijY"
IMAGES_DIR = BASE_DIR / "99_images"

LANG = "ja-JP"
POST_INTERVAL_SEC = 2.0  # 連投の間隔（マナー＆凍結対策）


def _resolve_cookies_path() -> Path:
    env = os.environ.get("X_COOKIES_JSON")
    if env:
        if env.strip().startswith("[") or env.strip().startswith("{"):
            temp_path = Path("/tmp/x_cookies_temp.json")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(env)
            return temp_path
        return Path(env).expanduser()
    
    local = Path(__file__).resolve().parent / "x_cookies.json"
    if local.exists():
        return local
    return Path.home() / ".hermes" / "ruku_data" / "personal" / "x_cookies.json"


COOKIES_PATH = _resolve_cookies_path()


# ─────────────────────────────────────────────────────────────────────────────
# 認証
# ─────────────────────────────────────────────────────────────────────────────
def _normalize_cookies(raw) -> dict:
    if isinstance(raw, list):
        return {c["name"]: c["value"] for c in raw if "name" in c and "value" in c}
    if isinstance(raw, dict):
        return raw
    raise ValueError(f"不明なcookies形式: {type(raw)}")


def _make_client() -> Client:
    if not COOKIES_PATH.exists():
        raise FileNotFoundError(
            f"Cookieファイルが見つかりません: {COOKIES_PATH}\n"
            f"  環境変数 X_COOKIES_JSON を設定するか、x_cookies.json を配置してください。"
        )
    with open(COOKIES_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    client = Client(LANG)
    client.set_cookies(_normalize_cookies(raw))
    return client


# ─────────────────────────────────────────────────────────────────────────────
# 画像パス解決
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_image_paths(img_cell: str):
    if not img_cell or img_cell.strip().lower() == "null":
        return []
    paths = []
    for raw in img_cell.split(","):
        p = raw.strip()
        if not p:
            continue
        path = Path(p).expanduser()
        if not path.is_absolute():
            cand = (Path(__file__).resolve().parent / p).resolve()
            if not cand.exists():
                cand = (IMAGES_DIR / Path(p).name).resolve()
            if not cand.exists():
                cand = (BASE_DIR / p).resolve()
            path = cand
        if path.exists():
            paths.append(str(path))
        else:
            print(f"  ⚠ 画像が見つかりません: {p}（スキップ）")
    return paths


# ─────────────────────────────────────────────────────────────────────────────
# Googleスプレッド読み込み
# ─────────────────────────────────────────────────────────────────────────────
def _load_rows(sheetname: str):
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    
    if not SERVICE_ACCOUNT_JSON.exists():
        raise FileNotFoundError(f"サービスアカウントファイルが見つかりません: {SERVICE_ACCOUNT_JSON}")
        
    creds = Credentials.from_service_account_file(str(SERVICE_ACCOUNT_JSON), scopes=scope)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_KEY).worksheet(sheetname)

    col_msgs = ws.col_values(2)  # B列
    col_imgs = ws.col_values(3)  # C列

    rows = []
    for i, msg in enumerate(col_msgs):
        img_cell = col_imgs[i] if i < len(col_imgs) else "null"
        msg_val = (msg or "").strip()
        imgs = _resolve_image_paths(img_cell)
        if not msg_val and not imgs:
            break
        rows.append((msg or "", imgs))
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 投稿
# ─────────────────────────────────────────────────────────────────────────────
async def _post_thread_async(rows, dry_run: bool):
    client = _make_client()

    try:
        me = await client.user()
        print(f"投稿アカウント: @{me.screen_name}（{me.name}）")
    except Exception as e:
        print(f"⚠ アカウント名の取得をスキップ（settings APIの一時エラー）: {e}")

    prev_id = None
    for idx, (msg, imgs) in enumerate(rows):
        label = f"{idx + 1}投目"
        if dry_run:
            head = msg.replace("\n", " ")[:40]
            print(f"  [dry-run] {label}: 本文{len(msg)}字 / 画像{len(imgs)}枚 | {head}")
            for p in imgs:
                print(f"            └ img: {p}")
            continue

        media_ids = []
        for p in imgs:
            mid = await client.upload_media(p, wait_for_completion=True)
            media_ids.append(mid)

        tweet = await client.create_tweet(
            text=msg,
            media_ids=media_ids or None,
            reply_to=prev_id,
        )
        prev_id = tweet.id
        print(f"  ✓ {label} 投稿: id={tweet.id}（本文{len(msg)}字 / 画像{len(imgs)}枚）")

        if idx < len(rows) - 1:
            await asyncio.sleep(POST_INTERVAL_SEC)

    if dry_run:
        print("[dry-run] 実際の投稿は行っていません。")
    else:
        print(f"✓ スレッド投稿完了（{len(rows)}件）")


def GS2tweet(sheetname: str, dry_run: bool = False):
    print(f"=== シート '{sheetname}' を読み込み ===")
    print(f"Cookie: {COOKIES_PATH}")
    rows = _load_rows(sheetname)
    if not rows:
        print("投稿対象の行がありません。")
        return
    print(f"{len(rows)} 件を{'（dry-run）' if dry_run else ''}スレッド投稿します")
    try:
        asyncio.run(_post_thread_async(rows, dry_run=dry_run))
    except Exception as e:
        print(f"\nエラー: {e}")
        traceback.print_exc()
        sys.exit(1)


async def _whoami_async():
    client = _make_client()
    me = await client.user()
    print(f"✓ @{me.screen_name}（{me.name}） / followers={me.followers_count}")
    print(f"  Cookie: {COOKIES_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Xへ保存済みCookie+twikitでスレッド投稿（公式API不使用）"
    )
    parser.add_argument("--sheet", help="投稿するシート名（例: 01_CNPTIMES）")
    parser.add_argument("--dry-run", action="store_true", help="本文・画像の確認のみ（投稿しない）")
    parser.add_argument("--whoami", action="store_true", help="Cookieのアカウントを表示して終了")
    args = parser.parse_args()

    if args.whoami:
        asyncio.run(_whoami_async())
        return
    if args.sheet:
        GS2tweet(args.sheet, dry_run=args.dry_run)
        return
    parser.print_help()


if __name__ == "__main__":
    main()
