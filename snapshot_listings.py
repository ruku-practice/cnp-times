#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snapshot_listings.py — CNP Owner限定「最安リスト トップ10」日次スナップショット取得。

設計書: 設計_トップ10リスト表示.md（唯一の正）

NFTTのリストページ（https://cryptoninja.nftt.market/?collection=...）をPlaywrightで
スクレイプし、価格昇順の最安10件について
  - トークン番号・キャラクター・画像URL・価格(ETH/JPY)
  - リスト者ウォレット（= 現所有者。ownerOf(tokenId)で解決）
  - そのウォレットの現リスト数・CNP保有総数・ニックネーム（OpenSea参照）
  - 最初にリストした日・価格履歴（前日分のGCSスナップショットとの差分で構築）
を集計し、GCSバケットの listings/<data_date>.json に保存する。

使い方:
    # 通常実行（前日日付でGCSへ書き込み）
    python3 snapshot_listings.py

    # ドライラン（GCSに書かずローカルの dry_run_listings_<date>.json に出力して中身を確認）
    python3 snapshot_listings.py --dry-run

    # 日付を明示指定（省略時は実行時刻JSTの前日）
    python3 snapshot_listings.py --date 2026-07-01 --dry-run

環境変数:
    GOOGLE_CREDENTIALS_JSON … サービスアカウント鍵（JSON文字列）。設定時はこれで
                              storage.Client を作る。未設定ならADC（Application Default
                              Credentials）を使う
    GCS_BUCKET               … 書き込み先バケット名（デフォルト: cnp-times-exclusive）

依存: playwright（chromium）, google-cloud-storage（GCS書き込み時のみ遅延import）,
      requirements.txt に既存の yfinance 等は不要（ETH/JPYはyfinanceを流用）
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

CNP_CONTRACT = "0x138A5C693279b6Cd82F48d4bEf563251Bc15ADcE"
OPENSEA_COLLECTION_SLUG = "cryptoninjapartners-v2"
OPENSEA_COLLECTION_NAME = "CNP / CryptoNinja Partners"
NFTT_LISTING_URL = (
    "https://cryptoninja.nftt.market/?collection=0x138A5C693279b6Cd82F48d4bEf563251Bc15ADcE"
)
CHARACTERS = [
    "Orochi", "Mitama", "Narukami", "Leelee", "Luna", "Yama",
    "Makami", "Towa", "Setsuna", "Ema", "Taruto",
]
RPC_URLS = ("https://ethereum-rpc.publicnode.com", "https://1rpc.io/eth")
TOP_N = 10
# ウォレットのリスト数集計を全リストで行うと重いため、上位N件に限定する（設計書の実装判断枠）。
WALLET_COUNT_SCOPE_LIMIT = 40

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def now_jst():
    return datetime.now(JST)


def data_date_default():
    """既存の「取得日の前日をデータ日付にする」規約に合わせ、実行時刻JSTの前日を返す。"""
    return (now_jst() - timedelta(days=1)).strftime("%Y-%m-%d")


def extract_number_from_text(text):
    if not text:
        return 0.0
    text = text.strip().replace(",", "").replace("WETH", "").replace("ETH", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


# --- NFTTリストページのスクレイプ ------------------------------------------------


def scrape_listings():
    """NFTTリストページから全リストを取得し、価格昇順の配列を返す。

    各要素: {"token": str, "image": str, "price_eth": float, "character": str|None}
    """
    from playwright.sync_api import sync_playwright

    items = []
    with sync_playwright() as p:
        print("ブラウザを起動中...")
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        page = context.new_page()
        page.set_default_timeout(60000)
        try:
            print(f"NFTT(リスト)へアクセス中: {NFTT_LISTING_URL}")
            page.goto(NFTT_LISTING_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            time.sleep(15)  # JSレンダリング待ち

            limit = 0
            while limit < 5:
                if len(page.locator("tr").all()) > 0:
                    break
                time.sleep(5)
                limit += 1

            rows = page.locator("tr").all()
            for row in rows:
                try:
                    buy_tag = row.locator(".tag.buy_now")
                    if buy_tag.count() == 0 or "購入する" not in buy_tag.text_content():
                        continue

                    # トークン番号: .nft_id のテキスト（例 "06127" → "6127" に正規化）
                    token = None
                    token_el = row.locator(".nft_id").first
                    if token_el.count() > 0:
                        raw = (token_el.text_content() or "").strip()
                        token = str(int(raw)) if raw.isdigit() else (raw or None)
                    if not token:
                        continue

                    # 画像URL: 先頭列(.td__sticky)内のimg src
                    image = ""
                    img_el = row.locator(".td__sticky img").first
                    if img_el.count() > 0:
                        image = img_el.get_attribute("src") or ""

                    # 価格: .td__price .price div の1つ目
                    price_eth = 0.0
                    price_el = row.locator(".td__price .price div").first
                    if price_el.count() > 0:
                        price_eth = extract_number_from_text(price_el.text_content())

                    # キャラクター: 先頭の text-left 列群から CHARACTERS と一致する最初のテキスト
                    character = None
                    tds = row.locator("td.text-left div")
                    for i in range(min(tds.count(), 5)):
                        t = (tds.nth(i).text_content() or "").strip()
                        if t in CHARACTERS:
                            character = t
                            break
                    if character is None:
                        # フォールバック: 行全体のテキストから照合（既存get_listingsと同じ方式）
                        row_text = row.text_content() or ""
                        for c in CHARACTERS:
                            if c in row_text:
                                character = c
                                break

                    items.append(
                        {"token": token, "image": image, "price_eth": price_eth, "character": character}
                    )
                except Exception as e:
                    print(f"  行の解析に失敗（スキップ）: {e}")
                    continue
        finally:
            browser.close()

    items.sort(key=lambda it: it["price_eth"] if it["price_eth"] > 0 else float("inf"))
    print(f"  ✓ リスト取得完了: {len(items)}件")
    return items


# --- オンチェーン参照（ownerOf / balanceOf） -------------------------------------


def _eth_call(data, to=CNP_CONTRACT):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }
    body = json.dumps(payload).encode()
    for rpc in RPC_URLS:
        try:
            req = urllib.request.Request(
                rpc,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            r = json.loads(urllib.request.urlopen(req, timeout=12).read())
            res = r.get("result")
            if res and res != "0x":
                return res
        except Exception:
            continue
    return None


def owner_of(token_id, memo=None):
    """CNPコントラクトの ownerOf(tokenId) を取得する。memo辞書を渡すとメモ化する。"""
    if memo is not None and token_id in memo:
        return memo[token_id]
    try:
        calldata = "0x6352211e" + format(int(token_id), "064x")
    except (TypeError, ValueError):
        if memo is not None:
            memo[token_id] = None
        return None
    res = _eth_call(calldata)
    owner = ("0x" + res[-40:]).lower() if res else None
    if memo is not None:
        memo[token_id] = owner
    return owner


def _extract_opensea_cnp_count(link_texts):
    """OpenSeaのコレクション一覧リンクからCNPの保有数を取り出す。"""
    pattern = re.compile(
        r"^" + re.escape(OPENSEA_COLLECTION_NAME) + r"\s+([\d,]+)$",
        re.MULTILINE,
    )
    for text in link_texts:
        match = pattern.search((text or "").strip())
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def opensea_cnp_balances(addresses, max_attempts=3, retry_waits=(3, 8)):
    """OpenSeaのウォレット画面を開き、CNP保有数をまとめて取得する。

    Chromiumは1プロセスを再利用し、各ウォレットは最大3回リトライする。
    取得できなかったアドレスはNoneのまま返し、理由をCloud Runログへ残す。
    """
    from playwright.sync_api import sync_playwright

    unique_addresses = list(dict.fromkeys(a.lower() for a in addresses if a))
    results = {address: None for address in unique_addresses}
    if not unique_addresses:
        return results

    playwright = None
    browser = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        for address in unique_addresses:
            url = (
                f"https://opensea.io/ja/{address}"
                f"?collectionSlugs={OPENSEA_COLLECTION_SLUG}"
            )
            for attempt in range(1, max_attempts + 1):
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    if response and response.status >= 400:
                        raise RuntimeError(f"HTTP {response.status}")

                    count = None
                    loaded_at = time.monotonic()
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline and count is None:
                        link_texts = page.locator("a").all_inner_texts()
                        count = _extract_opensea_cnp_count(link_texts)
                        # 0件ではサイドバーにCNP行が出ないため、選択中フィルターと
                        # 結果件数を併用する。初期描画の一時的な0件を避けて10秒待つ。
                        if count is None and time.monotonic() - loaded_at >= 10:
                            body_text = page.locator("body").inner_text()
                            if (
                                OPENSEA_COLLECTION_NAME in body_text
                                and re.search(r"(?m)^0 ITEMS?$", body_text)
                            ):
                                count = 0
                        if count is None:
                            page.wait_for_timeout(1000)
                    if count is None:
                        raise RuntimeError("CNPコレクション行の保有数を解析できません")

                    results[address] = count
                    print(f"  ✓ OpenSea保有数 {short_addr(address)}: {count}体")
                    break
                except Exception as exc:
                    print(
                        f"  ⚠ OpenSea保有数 {short_addr(address)} "
                        f"試行{attempt}/{max_attempts}失敗: {exc}"
                    )
                    if attempt < max_attempts:
                        wait = retry_waits[min(attempt - 1, len(retry_waits) - 1)]
                        time.sleep(wait)
            if results[address] is None:
                print(f"  ✗ OpenSea保有数 {short_addr(address)}: 全試行失敗")
        return results
    except Exception as exc:
        print(f"  ✗ OpenSea保有数ブラウザ起動失敗: {exc}")
        return results
    finally:
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()


def os_name(address):
    """OpenSeaのプロフィール名（未設定なら None）を取得する。get_CNP_stats_integrated_json.py の
    _os_name と同じ実装（APIキー不要・HTML埋め込みJSONから抽出）。
    ※リスト情報はNFTTのみを使うが、ウォレットのニックネームはセール情報と同様OpenSeaを参照する。"""
    al = address.lower()
    try:
        req = urllib.request.Request(
            f"https://opensea.io/{address}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept": "text/html",
            },
        )
        body = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r'"account":\{"address":"' + re.escape(al) + r'"[^}]*?\}', body)
    seg = m.group(0) if m else ""
    mu = re.search(r'"username":"([^"]+)"', seg)
    md = re.search(r'"displayName":"([^"]+)"', seg)
    name = (mu.group(1) if mu else None) or (md.group(1) if md else None)
    if not name:
        m2 = re.search(re.escape(al) + r'"[^{}]*?"username":"([^"]+)"', body)
        if m2:
            name = m2.group(1)
    if not name:
        return None
    name = name.strip()
    if re.fullmatch(r"0x[0-9a-fA-F]+", name):
        return None
    return name or None


def short_addr(address):
    return address[:6] + "…" + address[-4:] if address and len(address) >= 10 else (address or "")


# --- ETH/JPY ---------------------------------------------------------------


def fetch_eth_jpy():
    """ETH/JPYレートをyfinanceで取得する（get_nftt_listings_for_list_sheet.pyと同じ実装）。"""
    try:
        import yfinance as yf

        print("ETH価格取得中(yfinance)...")
        eth = yf.Ticker("ETH-USD")
        eth_hist = eth.history(period="1d")
        if eth_hist.empty:
            return None
        usdjpy = yf.Ticker("JPY=X")
        usdjpy_hist = usdjpy.history(period="1d")
        if usdjpy_hist.empty:
            return None
        eth_price = eth_hist["Close"].iloc[-1]
        jpy_rate = usdjpy_hist["Close"].iloc[-1]
        price = int(eth_price * jpy_rate)
        print(f"ETH価格: {price} JPY")
        return price
    except Exception as e:
        print(f"ETH価格取得エラー: {e}")
        return None


# --- GCS読み書き --------------------------------------------------------------


def _gcs_client():
    """GOOGLE_CREDENTIALS_JSON があればそれで、無ければADCでstorage.Clientを作る。"""
    from google.cloud import storage

    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if creds_json:
        from google.oauth2.service_account import Credentials

        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info)
        return storage.Client(credentials=creds, project=info.get("project_id"))
    return storage.Client()


def load_gcs_json(bucket_name, key):
    """GCS上のJSONを読む。存在しない/読めない場合は None。"""
    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(key)
        if not blob.exists():
            return None
        return json.loads(blob.download_as_bytes().decode("utf-8"))
    except Exception as e:
        print(f"  GCS読み込みエラー({key}): {e}")
        return None


def save_gcs_json(bucket_name, key, data):
    client = _gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(key)
    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=1), content_type="application/json"
    )


# --- メイン処理 ---------------------------------------------------------------


def build_snapshot(data_date, prev_snapshot=None):
    """スクレイプ〜enrich〜履歴引き継ぎまで行い、出力JSON(dict)を返す。"""
    listings = scrape_listings()
    total_listed = len(listings)
    top_items = listings[:TOP_N]

    if not top_items:
        print("警告: リストが1件も取得できませんでした。")

    eth_jpy = fetch_eth_jpy() or 0

    # --- ウォレット別リスト数の集計 ---
    # 設計書の実装判断枠: 全リスト(~160件相当)のownerOfは負荷が高いため、
    # 価格上位 WALLET_COUNT_SCOPE_LIMIT 件に限定してカウントする。
    scope_items = listings[:WALLET_COUNT_SCOPE_LIMIT]
    wallet_scope_note = (
        f"top{WALLET_COUNT_SCOPE_LIMIT}" if total_listed > WALLET_COUNT_SCOPE_LIMIT else None
    )

    owner_memo = {}
    wallet_listing_count = {}
    print(f"ウォレット解決中(ownerOf)... 対象 {len(scope_items)}件")
    for it in scope_items:
        owner = owner_of(it["token"], memo=owner_memo)
        if owner:
            wallet_listing_count[owner] = wallet_listing_count.get(owner, 0) + 1
        time.sleep(0.1)  # RPC負荷軽減（逐次・0.1s間隔）

    # トップ10のうち、まだ解決していないトークン（スコープ外にはならない想定だが念のため）も解決
    for it in top_items:
        if it["token"] not in owner_memo:
            owner_of(it["token"], memo=owner_memo)
            time.sleep(0.1)

    # --- ニックネーム・CNP保有数（OpenSea、トップ10のウォレットのみ） ---
    name_cache = {}
    cnp_cache = {}
    print("ニックネーム・CNP保有数を解決中...")
    for it in top_items:
        owner = owner_memo.get(it["token"])
        if not owner or owner in name_cache:
            continue
        name_cache[owner] = os_name(owner)
        time.sleep(1.0)  # OpenSeaへの負荷軽減
    top_owners = [owner_memo.get(it["token"]) for it in top_items]
    cnp_cache = opensea_cnp_balances(top_owners)

    # --- 前日スナップショットから first_seen_date / price_history を引き継ぐ ---
    prev_by_token = {}
    if prev_snapshot:
        for prev_it in prev_snapshot.get("items", []):
            prev_by_token[prev_it.get("token")] = prev_it

    out_items = []
    for rank, it in enumerate(top_items, start=1):
        token = it["token"]
        price_eth = it["price_eth"]
        owner = owner_memo.get(token)
        price_jpy = round(price_eth * eth_jpy) if eth_jpy else None

        prev_it = prev_by_token.get(token)
        if prev_it and prev_it.get("wallet", "").lower() == (owner or "").lower():
            # 前日も同じウォレットが同じトークンをリストしていた → 継続リストとみなす
            first_seen_date = prev_it.get("first_seen_date", data_date)
            price_history = list(prev_it.get("price_history", []))
            last_price = price_history[-1]["price"] if price_history else prev_it.get("price_eth")
            if last_price != price_eth:
                price_history.append({"date": data_date, "price": price_eth})
        else:
            # 新規リスト（または前日と別ウォレット＝再出品扱い）
            first_seen_date = data_date
            price_history = [{"date": data_date, "price": price_eth}]

        item = {
            "rank": rank,
            "token": token,
            "character": it["character"],
            "image": it["image"],
            "price_eth": price_eth,
            "price_jpy": price_jpy,
            "wallet": owner,
            "wallet_name": name_cache.get(owner) if owner else None,
            "wallet_listing_count": wallet_listing_count.get(owner) if owner else None,
            "wallet_cnp_total": cnp_cache.get(owner) if owner else None,
            "first_seen_date": first_seen_date,
            "price_history": price_history,
        }
        if wallet_scope_note:
            item["wallet_listing_count_scope"] = wallet_scope_note
        out_items.append(item)

    return {
        "date": data_date,
        "generated_at": now_jst().isoformat(),
        "eth_jpy": eth_jpy,
        "total_listed": total_listed,
        "items": out_items,
    }


def main():
    parser = argparse.ArgumentParser(description="CNP 最安リスト トップ10 日次スナップショット")
    parser.add_argument(
        "--dry-run", action="store_true", help="GCSに書き込まず、ローカルファイルに出力して確認する"
    )
    parser.add_argument(
        "--date", default=None, help="対象データ日付(YYYY-MM-DD)。省略時は実行時刻JSTの前日"
    )
    args = parser.parse_args()

    data_date = args.date or data_date_default()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", data_date):
        print(f"エラー: --date の形式が不正です: {data_date}")
        sys.exit(1)

    bucket_name = os.environ.get("GCS_BUCKET", "cnp-times-exclusive")
    prev_date = (datetime.strptime(data_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    prev_snapshot = None
    if args.dry_run:
        # ドライラン時はまずローカルの前回ドライラン出力があればそれを前日データとして使う
        local_prev = os.path.join(BASE_DIR, f"dry_run_listings_{prev_date}.json")
        if os.path.exists(local_prev):
            with open(local_prev, "r", encoding="utf-8") as f:
                prev_snapshot = json.load(f)
            print(f"  ✓ ローカルの前日分を読み込み: {local_prev}")
        else:
            prev_snapshot = load_gcs_json(bucket_name, f"listings/{prev_date}.json")
    else:
        prev_snapshot = load_gcs_json(bucket_name, f"listings/{prev_date}.json")

    print(f"対象データ日付: {data_date}（前日分参照: {prev_date}, 見つかった={'Yes' if prev_snapshot else 'No'}）")

    snapshot = build_snapshot(data_date, prev_snapshot=prev_snapshot)

    if args.dry_run:
        out_path = os.path.join(BASE_DIR, f"dry_run_listings_{data_date}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=1)
        print(f"\n[DRY-RUN] GCSへは書き込みません。ローカル出力: {out_path}")
        print(json.dumps(snapshot, ensure_ascii=False, indent=1)[:4000])
    else:
        key = f"listings/{data_date}.json"
        save_gcs_json(bucket_name, key, snapshot)
        print(f"✓ GCSへ保存しました: gs://{bucket_name}/{key}")


if __name__ == "__main__":
    main()
