from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import time
import re
import os
from dotenv import load_dotenv
import yfinance as yf
from google.oauth2.service_account import Credentials
import gspread
from gspread.exceptions import APIError
from google.auth.exceptions import TransportError

class CNPStatsIntegrated:
    """
    OpenSeaからCNPの統計情報を取得し、NFTTのアクティビティ情報と統合してスプレッドシートに書き込む
    """
    def __init__(self):
        self.browser = None
        self.page = None
        # NFTT Activity URL
        self.nftt_url = "https://cryptoninja.nftt.market/activity?collection=0x138A5C693279b6Cd82F48d4bEf563251Bc15ADcE"
        self.os_base_url = "https://opensea.io/collection/cryptoninjapartners-v2"
        self.characters = ['Orochi', 'Mitama', 'Narukami', 'Leelee', 'Luna', 'Yama', 'Makami', 'Towa', 'Setsuna', 'Ema', 'Taruto']
        
        # 認証情報の解決
        # 優先順位: ①環境変数（GitHub Actions等のCI） → ②ローカル .env（手元実行）
        # CIでは SPREADSHEET_ID / GOOGLE_CREDENTIALS_PATH を環境変数で渡す。
        if not (os.getenv('SPREADSHEET_ID') and os.getenv('GOOGLE_CREDENTIALS_PATH')):
            local_env_path = "/Users/kurokzhr/Library/CloudStorage/GoogleDrive-ruku.practice@gmail.com/マイドライブ/00_XXX_TIMES/00_CreateAutoTimes/60_GetInfoFromME/.env"
            if os.path.exists(local_env_path):
                load_dotenv(local_env_path)
        self.spreadsheet_id = os.getenv('SPREADSHEET_ID')
        self.credentials_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
        if not self.spreadsheet_id or not self.credentials_path:
            raise RuntimeError(
                "SPREADSHEET_ID / GOOGLE_CREDENTIALS_PATH が未設定です。"
                "環境変数か .env で指定してください。"
            )

        # スクリプト自身のディレクトリ（リポジトリのルート）を出力先の基準にする
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Google Sheetsの認証設定
        self.scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        self.credentials = Credentials.from_service_account_file(
            self.credentials_path,
            scopes=self.scopes
        )
        self.gc = gspread.authorize(self.credentials)
        self.workbook = self._open_workbook_with_retry()

    def _open_workbook_with_retry(self, retries=3, base_delay=5):
        """
        Google Sheets APIが一時的に503などを返す場合にリトライしてワークブックを開く
        """
        for attempt in range(1, retries + 1):
            try:
                return self.gc.open_by_key(self.spreadsheet_id)
            except APIError as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status == 503 or "UNAVAILABLE" in str(e):
                    wait = base_delay * attempt
                    print(f"Sheets APIが一時的に利用不可 (503)。{attempt}/{retries} 回目のリトライまで {wait} 秒待機します...")
                    time.sleep(wait)
                    continue
                raise
            except TransportError:
                wait = base_delay * attempt
                print(f"ネットワークエラーのため {attempt}/{retries} 回目のリトライまで {wait} 秒待機します...")
                time.sleep(wait)
        raise RuntimeError("Google Sheets を開けませんでした。ネットワークやAPIの状態を確認してください。")
        
    def setup_browser(self):
        """Playwrightブラウザの設定"""
        print("ブラウザを起動中...")
        playwright = sync_playwright().start()
        
        self.browser = playwright.chromium.launch(
            headless=True,  # 本番用はheadless=True
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-notifications',
                '--disable-popup-blocking',
            ]
        )
        
        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            locale='ja-JP',
            timezone_id='Asia/Tokyo',
            permissions=[],
            extra_http_headers={
                'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        )
        
        self.page = self.context.new_page()
        self._configure_page()
        print("ブラウザ起動完了")

    def reset_page(self):
        """ページをリセット（タブを閉じて開き直す）して状態をクリア"""
        try:
            if self.page:
                self.page.close()
        except: pass
        
        try:
            self.page = self.context.new_page()
            self._configure_page()
        except Exception as e:
            print(f"ページリセット失敗: {e}")

    def _configure_page(self):
        """ページの共通設定を適用"""
        self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        self.page.set_default_timeout(90000)
        self.page.set_default_navigation_timeout(90000)

    def extract_number_from_text(self, text):
        """テキストから数値を抽出"""
        if not text or text == '--':
            return 0.0
        text = text.strip().replace(',', '')
        if 'K' in text:
            text = text.replace('K', '000')
        try:
            return float(text)
        except ValueError:
            return 0.0

    def get_nftt_activity_stats(self):
        """NFTTから過去24時間のアクティビティ情報を取得"""
        try:
            self.reset_page()
            print("\n" + "="*60)
            print("=== NFTT: アクティビティ情報取得 ===")
            print("="*60)
            
            self.page.goto(self.nftt_url, wait_until='domcontentloaded')
            try:
                self.page.wait_for_load_state('networkidle', timeout=30000)
            except:
                pass
            time.sleep(8)
            
            stats = {
                'sales_24h': 0,
                'total_price_24h': 0.0,
                'avg_sale': 0.0
            }
            
            # 時間表示を持つ要素すべて取得
            # 24時間分遡るためにスクロールを行う
            max_scroll_attempts = 30
            last_item_count = 0
            now = datetime.now()
            cutoff_time = now - timedelta(hours=24)

            same_count_ticks = 0  # 同じ件数が連続した回数

            print("データを読み込み中...")
            
            for scroll_i in range(max_scroll_attempts):
                # 要素数をチェック
                try:
                    time_elements = self.page.locator('.td__sort__active .tooltip').all()
                    current_count = len(time_elements)
                except:
                    current_count = 0
                
                print(f"  スクロール {scroll_i}: 取得件数 {current_count}")
                
                if current_count == 0:
                     # まだ読み込めていない可能性
                     time.sleep(2)
                     continue
                
                # 末尾の要素の日付を確認
                try:
                    last_el = time_elements[-1]
                    last_text = last_el.text_content().strip()
                    
                    # 日付判定ロジック再利用の簡易版
                    is_old = False
                    
                    # ツールチップテキストがあればそちらを優先
                    tooltip_text_el = last_el.locator('.tooltiptext')
                    if tooltip_text_el.count() > 0:
                         time_str = tooltip_text_el.text_content().strip()
                         try:
                             dt = datetime.strptime(time_str, "%Y/%m/%d %H:%M")
                             if dt < cutoff_time:
                                 is_old = True
                                 print(f"  24時間以前のデータに到達しました: {time_str}")
                         except:
                             pass
                    elif "日前" in last_text:
                         is_old = True
                         print(f"  データの末尾が24時間以前です: {last_text}")
                    
                    if is_old:
                        break
                except Exception as e:
                    print(f"  日付チェックエラー: {e}")
                
                # 新しいデータが読み込まれなくなった場合の判定を緩和（3回連続で増加しない場合に終了）
                if current_count == last_item_count and scroll_i > 0:
                    same_count_ticks += 1
                    if same_count_ticks >= 3:
                        print("  3回連続で件数が増加しませんでした。これ以上データが読み込まれません。")
                        break
                    else:
                        print(f"  件数が増加しませんでした (同じ件数: {same_count_ticks}/3)。リトライします。")
                else:
                    same_count_ticks = 0
                
                last_item_count = current_count
                
                # スクロール実行
                try:
                    scroll_top_before = self.page.evaluate("document.documentElement.scrollTop || window.scrollY || 0")
                    scroll_height_before = self.page.evaluate("document.documentElement.scrollHeight || 0")
                    
                    # JavaScriptで確実にwindow全体を最下部までスクロールし、追加ロードをトリガー
                    self.page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                    
                    # 少しずつスクロール（スクロールイベントのトリガーをより確実にするため）
                    self.page.evaluate("""
                        (async () => {
                            const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
                            for (let i = 0; i < 3; i++) {
                                window.scrollBy(0, 500);
                                await delay(100);
                            }
                        })()
                    """)
                    
                    self.page.wait_for_timeout(2500)
                    
                    scroll_top_after = self.page.evaluate("document.documentElement.scrollTop || window.scrollY || 0")
                    scroll_height_after = self.page.evaluate("document.documentElement.scrollHeight || 0")
                    print(f"  [Debug] scrollY: {scroll_top_before:.0f} -> {scroll_top_after:.0f}, scrollHeight: {scroll_height_before} -> {scroll_height_after}")
                except Exception as scroll_err:
                    print(f"  スクロール操作エラー: {scroll_err}")
            
            # 最終的な要素取得
            time_elements = self.page.locator('.td__sort__active .tooltip').all()
            print(f"アクティビティ行数（候補）: {len(time_elements)}")

            valid_sales_count = 0
            total_price = 0.0
            
            for time_el in time_elements:
                try:
                    # フィルタリング: 時間関連のテキストか確認
                    full_text = time_el.text_content().strip()
                    
                    # 不要なツールチップ（アドレス、マーケットプレイス名）を除外
                    # 時間には "前" や 日付のスラッシュが含まれるはず
                    is_time_related = False
                    if re.search(r'\d{4}/\d{1,2}/\d{1,2}', full_text):
                        is_time_related = True
                    elif any(s in full_text for s in ["時間前", "分前", "秒前", "日前"]):
                        is_time_related = True
                    
                    if not is_time_related:
                        continue

                    # 「移動」や「トランスファー」を含む場合はスキップ (Transfer)
                    if "移動" in full_text or "Transfer" in full_text:
                        print(f"  スキップ(移動/Transfer): {full_text[:20]}...")
                        continue

                    # 時間の判定
                    tooltip_text_el = time_el.locator('.tooltiptext')
                    time_str = ""
                    
                    if tooltip_text_el.count() > 0:
                        time_str = tooltip_text_el.text_content().strip()
                    
                    is_target_time = False
                    if time_str:
                        # "2025/12/20 21:12" 形式
                        try:
                            dt = datetime.strptime(time_str, "%Y/%m/%d %H:%M")
                            if dt >= cutoff_time:
                                is_target_time = True
                        except ValueError:
                            pass
                    elif "分前" in full_text or "時間前" in full_text or "秒前" in full_text:
                        # 相対時間で直近ならOK
                        is_target_time = True
                    
                    if not is_target_time:
                        continue

                    # 時間内であれば価格を取得
                    # time_elの親の親...と遡って行全体を取得し、その中の .price を探す
                    parent2 = time_el.locator('xpath=../..')
                    
                    price_div = parent2.locator('.price').first
                    if price_div.count() == 0:
                        # parent3へのフォールバックは誤ってコンテナ全体の価格を拾う可能性があるため削除
                        # .priceがない＝Salesではないとみなす
                        continue
                        
                    # 金額数値（ETH/WETH）を取得
                    # price_div直下の最初のdivがETH価格
                    eth_val_div = price_div.locator('div').first
                    if eth_val_div.count() > 0:
                        eth_text_raw = eth_val_div.text_content()
                        # "0.09 WETH" -> "0.09"
                        eth_text = eth_text_raw.replace('WETH', '').replace('ETH', '').strip()
                        price_val = self.extract_number_from_text(eth_text)
                        
                        if price_val > 0:
                            valid_sales_count += 1
                            total_price += price_val
                            print(f"  売買検知: {time_str if time_str else full_text[:10]}... - {price_val} ETH")
                    
                except Exception as e:
                    print(f"  行解析エラー: {str(e)}")
                    continue
            
            stats['sales_24h'] = valid_sales_count
            if valid_sales_count > 0:
                stats['avg_sale'] = round(total_price / valid_sales_count, 4)
            
            print(f"NFTT集計結果: 24h販売数={stats['sales_24h']}, 平均価格={stats['avg_sale']} ETH")
            return stats
            
        except Exception as e:
            print(f"✗ NFTT アクティビティ情報取得エラー: {str(e)}")
            return {'sales_24h': 0, 'avg_sale': 0.0}

    def get_nftt_listings(self):
        """NFTTから販売中（購入するボタンあり）のアイテムを取得"""
        try:
            self.reset_page()
            print("\n" + "="*60)
            print("=== NFTT: リスト情報取得 ===")
            print("="*60)
            
            # コレクションページURL（アクティビティではない）
            url = "https://cryptoninja.nftt.market/?collection=0x138A5C693279b6Cd82F48d4bEf563251Bc15ADcE"
            
            self.page.goto(url, wait_until='domcontentloaded')
            try:
                self.page.wait_for_load_state('networkidle', timeout=30000)
            except:
                pass
            print("ページ読み込み待機中（15秒）...")
            time.sleep(15)
            
            listings = {
                'total_count': 0,
                'min_price': 0.0,
                'characters': {}  # char -> {'count': 0, 'min_price': 0.0}
            }
            
            # 初期化
            for char in self.characters:
                listings['characters'][char] = {'count': 0, 'min_price': 0.0}
            
            # リスト（テーブル行）を取得
            rows = self.page.locator('tr').all()
            print(f"行数: {len(rows)}")
            
            listing_prices = []
            
            for row in rows:
                try:
                    # 「購入する」ボタンがあるか確認
                    buy_tag = row.locator('.tag.buy_now')
                    if buy_tag.count() == 0 or "購入する" not in buy_tag.text_content():
                        continue
                        
                    # 販売中アイテム発見
                    listings['total_count'] += 1
                    
                    # 価格取得
                    price_val = 0.0
                    price_el = row.locator('.td__price .price').first
                    if price_el.count() > 0:
                        val_div = price_el.locator('div').first
                        if val_div.count() > 0:
                            eth_str = val_div.text_content().replace('WETH', '').replace('ETH', '').strip()
                            price_val = self.extract_number_from_text(eth_str)
                    
                    if price_val > 0:
                        listing_prices.append(price_val)
                    
                    # キャラクター判定
                    row_text = row.text_content()
                    target_char = None
                    for char in self.characters:
                        if char in row_text:
                            target_char = char
                            break
                    
                    if target_char:
                        char_stats = listings['characters'][target_char]
                        char_stats['count'] += 1
                        current_min = char_stats['min_price']
                        if price_val > 0:
                            if current_min == 0 or price_val < current_min:
                                char_stats['min_price'] = price_val
                        
                        print(f"  販売中: {target_char} - {price_val} ETH")
                    else:
                        print(f"  販売中: キャラ不明 - {price_val} ETH")
                        
                except Exception as e:
                    print(f"  行解析エラー: {str(e)}")
                    continue
            
            if listing_prices:
                listings['min_price'] = min(listing_prices)
                
            print(f"NFTTリスト集計: 合計={listings['total_count']}, 最安値={listings['min_price']} ETH")
            return listings
            
        except Exception as e:
            print(f"✗ NFTT リスト情報取得エラー: {str(e)}")
            return {
                'total_count': 0, 
                'min_price': 0.0, 
                'characters': {c: {'count': 0, 'min_price': 0.0} for c in self.characters}
            }

    def get_nftt_offers(self):
        """NFTTのオファーページから トップオファー額・オファー数(口数合計)・オファー総額 を取得。
        ページ構成: テーブル各行 = [オファー額(単価), 口数, 合計額]（.price が単価と合計額の2つ）。
        """
        try:
            self.reset_page()
            print("\n" + "=" * 60)
            print("=== NFTT: オファー情報取得 ===")
            print("=" * 60)
            url = "https://cryptoninja.nftt.market/offer?collection=0x138A5C693279b6Cd82F48d4bEf563251Bc15ADcE"
            self.page.goto(url, wait_until='domcontentloaded')
            try:
                self.page.wait_for_load_state('networkidle', timeout=30000)
            except:
                pass
            time.sleep(12)

            def _first_num(s):
                s = (s or '').replace(',', '').replace('WETH', '').replace('ETH', '').replace('¥', '')
                m = re.search(r'[\d.]+', s)
                return float(m.group(0)) if m else None

            offers = []  # (price, qty, total)
            for row in self.page.locator('tr').all():
                prices = row.locator('.price').all()
                if len(prices) < 2:
                    continue
                try:
                    price = _first_num(prices[0].locator('div').first.text_content())
                    total = _first_num(prices[-1].locator('div').first.text_content())
                    if price and total:
                        qty = int(round(total / price)) if price else 1
                        offers.append((price, qty, total))
                except Exception:
                    continue

            result = {'top_offer': 0.0, 'offer_count': 0, 'offer_total': 0.0}
            if offers:
                result['top_offer'] = max(o[0] for o in offers)
                result['offer_count'] = sum(o[1] for o in offers)
                result['offer_total'] = round(sum(o[2] for o in offers), 4)
            print(f"NFTTオファー集計: トップ={result['top_offer']} / 口数={result['offer_count']} / 総額={result['offer_total']} WETH")
            return result
        except Exception as e:
            print(f"✗ NFTT オファー情報取得エラー: {str(e)}")
            return {'top_offer': 0.0, 'offer_count': 0, 'offer_total': 0.0}

    def save_offers_json(self, offers):
        """オファー情報を data/offers.json に保存（サイトの本日カード用）。"""
        import json
        from datetime import datetime
        try:
            data_dir = os.path.join(self.base_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            payload = dict(offers)
            payload['fetched_at'] = datetime.now().isoformat(timespec='seconds')
            payload['date'] = datetime.now().strftime('%Y-%m-%d')
            path = os.path.join(data_dir, "offers.json")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(f"  ✓ offers.json を保存しました: {path}")
        except Exception as e:
            print(f"  ✗ offers.json 保存エラー: {str(e)}")

    def get_os_header_stats(self):
        """OpenSeaからヘッダー情報を取得"""
        try:
            self.reset_page()
            print("\n" + "="*60)
            print("=== OpenSea: ヘッダ情報取得 ===")
            print("="*60)
            
            self.page.goto(self.os_base_url, wait_until='domcontentloaded')
            try:
                self.page.wait_for_load_state('load', timeout=30000)
            except:
                pass
            time.sleep(10)
            
            stats = {}
            
            # Floor Price
            floor_element = self.page.wait_for_selector('[data-testid="floor-price"]', timeout=30000)
            if floor_element:
                floor_text = floor_element.evaluate("""
                    (element) => {
                        const numberElement = element.querySelector('[aria-label]');
                        return numberElement ? numberElement.getAttribute('aria-label') : null;
                    }
                """)
                if floor_text:
                    stats['floor_price'] = self.extract_number_from_text(floor_text)
                    print(f"Floor Price: {stats['floor_price']} ETH")
            
            # Top Offer
            top_offer_element = self.page.wait_for_selector('[data-testid="top-offer"]', timeout=30000)
            if top_offer_element:
                top_offer_text = top_offer_element.evaluate("""
                    (element) => {
                        const numberElement = element.querySelector('[aria-label]');
                        return numberElement ? numberElement.getAttribute('aria-label') : null;
                    }
                """)
                if top_offer_text:
                    stats['top_offer'] = self.extract_number_from_text(top_offer_text)
                    print(f"Top Offer: {stats['top_offer']} WETH")
            
            # Total Volume
            total_vol_element = self.page.locator('text=Total volume').locator('..').locator('span[aria-label]').first
            if total_vol_element:
                total_vol_text = total_vol_element.get_attribute('aria-label')
                if total_vol_text:
                    stats['all_vol'] = self.extract_number_from_text(total_vol_text)
                    print(f"Total Volume: {stats['all_vol']} ETH")
            
            # Listed（マウスホバー）
            listed_label = self.page.locator('text=Listed').locator('..').first
            if listed_label:
                listed_label.hover()
                time.sleep(2)
                try:
                    tooltip = self.page.locator('text=/\\d+ listed/i').first
                    if tooltip:
                        tooltip_text = tooltip.text_content(timeout=5000)
                        match = re.search(r'(\d+)\s*listed', tooltip_text, re.IGNORECASE)
                        if match:
                            stats['listed'] = int(match.group(1))
                            print(f"Listed: {stats['listed']}")
                except:
                    stats['listed'] = 0
            
            # Owners
            owners_element = self.page.wait_for_selector('[data-testid="owner-count"]', timeout=30000)
            if owners_element:
                owners_text = owners_element.get_attribute('aria-label')
                if owners_text:
                    stats['owners'] = int(self.extract_number_from_text(owners_text))
                    print(f"Owners: {stats['owners']}")
            
            return stats
            
        except Exception as e:
            print(f"✗ OpenSea ヘッダ情報取得エラー: {str(e)}")
            return {}

    # def get_os_all_character_stats(self):
    #     """
    #     OpenSeaから全キャラクターのデータを取得 (廃止: NFTTのみ使用のため)
    #     以前のロジックはコメントアウトして保持
    #     """
    #     pass

    def merge_stats(self, nftt_activity_stats, nftt_listing_stats, os_stats):
        """
        データを統合
        - Sales (24h), Avg Price: NFTT Activity
        - Floor Price: NFTT Min Listing
        - Listed: NFTT Listed
        - Owners, Top Offer, All Vol: OS (Top Offer, All Volは参考値として保持)
        """
        merged = {}
        
        # OpenSeaベース (Ownersのみが正、他は参考値)
        merged['top_offer'] = os_stats.get('top_offer', 0)
        merged['all_vol'] = os_stats.get('all_vol', 0)
        merged['owners'] = os_stats.get('owners', 0)
        
        # NFTT Activity統合
        merged['sales_24h'] = nftt_activity_stats.get('sales_24h', 0)
        merged['avg_sale'] = nftt_activity_stats.get('avg_sale', 0)
        merged['vol_24h'] = merged['sales_24h'] * merged['avg_sale']
        
        # NFTT Listing統合
        # リストもフロアもNFTTの値を使用
        merged['listed'] = nftt_listing_stats.get('total_count', 0)
        merged['floor_price'] = nftt_listing_stats.get('min_price', 0)
        
        return merged
    
    def merge_character_stats(self, nftt_listing_stats):
        """
        キャラクターデータの統合
        - NFTTの情報のみを使用
        """
        merged = {}
        nftt_chars = nftt_listing_stats.get('characters', {})
        
        for char in self.characters:
            nftt_data = nftt_chars.get(char, {'min_price': 0.0, 'count': 0})
            
            merged_data = {}
            merged_data['list_count'] = nftt_data.get('count', 0)
            merged_data['floor_price'] = nftt_data.get('min_price', 0)
            
            merged[char] = merged_data
            
        return merged

    def get_eth_price(self):
        """ETHの日本円価格を取得"""
        try:
            print("\nETH価格取得中...")
            eth = yf.Ticker("ETH-USD")
            eth_hist = eth.history(period="1d")
            if not eth_hist.empty:
                latest_price = eth_hist['Close'].iloc[-1]
                usdjpy = yf.Ticker("JPY=X")
                usdjpy_hist = usdjpy.history(period="1d")
                if not usdjpy_hist.empty:
                    jpy_rate = usdjpy_hist['Close'].iloc[-1]
                    eth_jpy = latest_price * jpy_rate
                    print(f"ETH価格（円）: ¥{eth_jpy:,.0f}")
                    return eth_jpy
            return 0
        except Exception as e:
            print(f"ETH価格取得エラー: {str(e)}")
            return 0

    def get_usd_price(self):
        """USD/JPYレートを取得"""
        try:
            print("USD/JPYレート取得中...")
            usdjpy = yf.Ticker("JPY=X")
            usdjpy_hist = usdjpy.history(period="1d")
            if not usdjpy_hist.empty:
                latest_price = usdjpy_hist['Close'].iloc[-1]
                print(f"USD/JPYレート: ¥{latest_price:,.2f}")
                return latest_price
            return 0
        except Exception as e:
            print(f"USD/JPYレート取得エラー: {str(e)}")
            return 0

    def update_spreadsheet(self, merged_stats, os_stats, nftt_activity_stats, 
                           nftt_listing_stats, merged_char_stats, os_char_stats):
        """
        eth_statsとfloorpriceシートを更新
        統合データ: merged_stats / merged_char_stats
        OSデータ: os_stats / os_char_stats
        NFTTデータ: nftt_activity_stats + nftt_listing_stats (Header & Char)
        """
        try:
            print("\n" + "="*60)
            print("=== Googleスプレッドシート書き込み（本番） ===")
            print("="*60)
            
            ws_eth = self.workbook.worksheet('eth_stats')
            ws_floor = self.workbook.worksheet('floorprice')
            
            now = datetime.now()
            date_str = now.strftime("%-m月%-d日")
            time_str = now.strftime("%H:%M")
            
            eth_price = self.get_eth_price()
            usd_price = self.get_usd_price()
            
            max_retries = 5
            retry_delay = 60
            
            # NFTTデータの成形 (Activity + Listings)
            nftt_header = nftt_activity_stats.copy()
            nftt_header['listed'] = nftt_listing_stats.get('total_count', 0)
            nftt_header['floor_price'] = nftt_listing_stats.get('min_price', 0)
            
            nftt_char_stats = {}
            if nftt_listing_stats and 'characters' in nftt_listing_stats:
                for char, data in nftt_listing_stats['characters'].items():
                    nftt_char_stats[char] = {
                        'list_count': data.get('count', 0),
                        'floor_price': data.get('min_price', 0)
                    }
            
            # データセットのリスト
            datasets = [
                (merged_stats, merged_char_stats, "統合")
            ]
            
            # ===== eth_stats シートへの書き込み =====
            print("\n[1] eth_stats シートへの書き込み")
            max_column_eth = ws_eth.col_count + 1
            ws_eth.add_cols(1)
            
            eth_datalist = []
            
            # eth_statsは33行分のデータ（キャラ個別部分はFloorpriceに任せるため）
            for dataset_idx, (header_stats, character_stats, label) in enumerate(datasets):
                print(f"  {label}データ準備中...")
                
                is_nftt = (label == "NFTT")
                
                for i in range(33):
                    if i == 0:
                        if dataset_idx == 0:
                            eth_datalist.append([max_column_eth])
                        else:
                            eth_datalist.append([label])
                    elif i == 1:
                        eth_datalist.append([date_str])
                    elif i == 2:
                        eth_datalist.append([time_str])
                    elif i == 3:
                        eth_datalist.append([eth_price])
                    elif i == 4:
                        eth_datalist.append([usd_price])
                    elif i == 5:
                        # 24h Vol
                        val = header_stats.get('vol_24h', "")
                        eth_datalist.append([val])
                    elif i == 7:
                        # 24h Sales
                        val = header_stats.get('sales_24h', "")
                        eth_datalist.append([val])
                    elif i == 8:
                        # Avg Sale
                        val = header_stats.get('avg_sale', "")
                        eth_datalist.append([val])
                    elif i == 20:
                        # All Vol - NFTTの場合は空
                        val = "" if is_nftt else header_stats.get('all_vol', "")
                        eth_datalist.append([val])
                    elif i == 24:
                        # Owners - NFTTの場合は空
                        val = "" if is_nftt else header_stats.get('owners', "")
                        eth_datalist.append([val])
                    elif i == 28:
                        # Floor Price - NFTTも表示
                        val = header_stats.get('floor_price', "")
                        # 0の場合は空文字にするか？既存ロジックは0でも表示される可能性があるが、
                        # 基本get('', "")で空文字返却が期待されるが、辞書に0が入っている場合は0になる。
                        # NFTTでリストがない場合はTotal Count 0, Min Price 0になる。
                        # 見やすさのため0は空文字にするなら:
                        if val == 0 and is_nftt: val = ""
                        eth_datalist.append([val])
                    elif i == 29:
                        # Top Offer - NFTTの場合は空
                        val = "" if is_nftt else header_stats.get('top_offer', "")
                        eth_datalist.append([val])
                    else:
                        eth_datalist.append([""])
            
            # eth_stats書き込み
            eth_cell_range = f'R1C{max_column_eth}:R{len(eth_datalist)}C{max_column_eth}'
            for attempt in range(max_retries):
                try:
                    ws_eth.update(values=eth_datalist, range_name=eth_cell_range, value_input_option='USER_ENTERED')
                    print(f"✓ eth_statsシートの書き込み完了（列{max_column_eth}、{len(eth_datalist)}行）")
                    time.sleep(1)
                    break
                except (APIError, TransportError) as e:
                    if attempt < max_retries - 1:
                        print(f"エラーが発生しました。{retry_delay}秒後に再試行します。")
                        time.sleep(retry_delay)
                    else:
                        print(f"最大再試行回数（{max_retries}回）に達しました。")
                        raise
            
            # ===== floorprice シートへの書き込み =====
            print("\n[2] floorprice シートへの書き込み")
            max_column_floor = ws_floor.col_count + 1
            ws_floor.add_cols(1)
            
            floor_datalist = []
            
            # 39行分のデータ
            for dataset_idx, (header_stats, character_stats, label) in enumerate(datasets):
                print(f"  {label}データ準備中...")
                
                is_nftt = (label == "NFTT")
                
                for i in range(39):
                    if i == 0:
                        if dataset_idx == 0:
                            floor_datalist.append([max_column_floor])
                        else:
                            floor_datalist.append([label])
                    elif i == 1:
                        floor_datalist.append([date_str])
                    elif i == 2:
                        floor_datalist.append([time_str])
                    elif i == 4:
                        # Floor Price
                        val = header_stats.get('floor_price', "")
                        if val == 0 and is_nftt: val = ""
                        floor_datalist.append([val])
                    elif i == 5:
                        # Listed
                        val = header_stats.get('listed', "")
                        if val == 0 and is_nftt: val = ""
                        floor_datalist.append([val])
                    else:
                        # キャラクター情報
                        if character_stats is None:
                            floor_datalist.append([""])
                        else:
                            char_index = (i - 7) // 3
                            if 0 <= char_index < len(self.characters):
                                char = self.characters[char_index]
                                char_data = character_stats.get(char, {})
                                if i % 3 == 1:  # フロア価格
                                    val = char_data.get('floor_price', "")
                                    if val == 0 and is_nftt: val = ""
                                    floor_datalist.append([val])
                                elif i % 3 == 2:  # リスト数
                                    val = char_data.get('list_count', "")
                                    if val == 0 and is_nftt: val = ""
                                    floor_datalist.append([val])
                                else:
                                    floor_datalist.append([""])
                            else:
                                floor_datalist.append([""])
            
            # floorprice書き込み
            floor_cell_range = f'R1C{max_column_floor}:R{len(floor_datalist)}C{max_column_floor}'
            for attempt in range(max_retries):
                try:
                    ws_floor.update(values=floor_datalist, range_name=floor_cell_range, value_input_option='USER_ENTERED')
                    print(f"✓ floorpriceシートの書き込み完了（列{max_column_floor}、{len(floor_datalist)}行）")
                    time.sleep(1)
                    break
                except (APIError, TransportError) as e:
                    if attempt < max_retries - 1:
                        print(f"エラーが発生しました。{retry_delay}秒後に再試行します。")
                        time.sleep(retry_delay)
                    else:
                        print(f"最大再試行回数（{max_retries}回）に達しました。")
                        raise
            
            print(f"\n✓ 全シート（eth_stats、floorprice）の書き込みが完了しました！")
                        
        except Exception as e:
            print(f"スプレッドシートの更新中にエラーが発生しました: {str(e)}")
            raise

    def _get_all_values_with_retry(self, worksheet_name, retries=5, base_delay=5):
        """ワークシートから全データを取得する（502/503などのAPIエラー時にリトライする）"""
        for attempt in range(1, retries + 1):
            try:
                ws = self.workbook.worksheet(worksheet_name)
                return ws.get_all_values()
            except Exception as e:
                if attempt == retries:
                    raise
                wait = base_delay * attempt
                print(f"  [Warning] {worksheet_name} 取得エラー: {str(e)}。{attempt}/{retries} 回目のリトライまで {wait} 秒待機します...")
                time.sleep(wait)

    def export_sheets_to_json(self):
        """
        HTML2シートとfloorpriceシートを読み込み、サーバー側のJSONファイルとして保存する
        これによりWebアプリ側で高速にデータをロードできるようにする
        """
        try:
            print("\n" + "="*60)
            print("=== スプレッドシートから JSON データを出力中 ===")
            print("="*60)
            
            import json
            # 1. HTML2シートのエクスポート（クラシック版が読む本日サマリ）
            try:
                html2_data = self._get_all_values_with_retry('HTML2')

                json_path_html2 = os.path.join(self.base_dir, "html2_data.json")
                with open(json_path_html2, 'w', encoding='utf-8') as f:
                    json.dump(html2_data, f, ensure_ascii=False, indent=2)
                print(f"  ✓ HTML2 データを保存しました: {json_path_html2}")
            except Exception as e:
                print(f"  ✗ HTML2 エクスポートエラー: {str(e)}")

            # 2. floorpriceシートのエクスポート（過去のデータ全取得）
            #    フル生データは floorprice_full.json（gitignore・履歴の元データ）に保存し、
            #    クラシック版が読む floorprice_data.json は build_site_data() で直近分にトリムして出力する。
            try:
                floor_data = self._get_all_values_with_retry('floorprice')

                json_path_floor_full = os.path.join(self.base_dir, "floorprice_full.json")
                with open(json_path_floor_full, 'w', encoding='utf-8') as f:
                    json.dump(floor_data, f, ensure_ascii=False, indent=2)
                print(f"  ✓ floorprice フルデータを保存しました: {json_path_floor_full}")
            except Exception as e:
                print(f"  ✗ floorprice エクスポートエラー: {str(e)}")

            # 3. eth_statsシートのエクスポート（全表の集計指標＝floorprice と同じ列構造）
            #    eth_stats_full.json（gitignore）。build_site_data() が集計値・ETH/円レートを抽出する。
            try:
                eth_stats_data = self._get_all_values_with_retry('eth_stats')

                json_path_eth_full = os.path.join(self.base_dir, "eth_stats_full.json")
                with open(json_path_eth_full, 'w', encoding='utf-8') as f:
                    json.dump(eth_stats_data, f, ensure_ascii=False, indent=2)
                print(f"  ✓ eth_stats フルデータを保存しました: {json_path_eth_full}")
            except Exception as e:
                print(f"  ✗ eth_stats エクスポートエラー: {str(e)}")
                
        except Exception as e:
            print(f"  ✗ JSON エクスポート処理全体でエラーが発生しました: {str(e)}")

    def run(self):
        """メイン実行関数"""
        try:
            self.setup_browser()
            
            # 1. NFTT Activity (Sales, Avg)
            nftt_activity = self.get_nftt_activity_stats()
            
            # 2. NFTT Listings (Count, Floor)
            nftt_listings = self.get_nftt_listings()

            # 2b. NFTT Offers (Top Offer, 口数, 総額) → data/offers.json
            nftt_offers = self.get_nftt_offers()
            self.save_offers_json(nftt_offers)

            # 3. OpenSea Header
            os_header = self.get_os_header_stats()
            
            # 4. OpenSea Characters (廃止)
            # os_chars = self.get_os_all_character_stats()
            os_chars = {} # 空の辞書を渡してエラー回避（書き込みロジックはOSカラムをどうせ空にするため）
            
            # 統合: Header
            merged_header = self.merge_stats(nftt_activity, nftt_listings, os_header)
            
            # 統合: Characters
            # merged_chars = self.merge_character_stats(os_chars, nftt_listings)
            merged_chars = self.merge_character_stats(nftt_listings)
            
            print("\n" + "="*60)
            print("=== ヘッダ情報統合結果 ===")
            print("="*60)
            for key, value in merged_header.items():
                print(f"  {key}: {value}")
            
            print("\n" + "="*60)
            print("=== キャラクター情報統合結果 ===")
            print("="*60)
            for char in self.characters:
                 d = merged_chars.get(char, {})
                 print(f"  {char}: リスト {d.get('list_count')}, フロア {d.get('floor_price')}")

            # スプレッドシート更新
            self.update_spreadsheet(
                merged_header, os_header, nftt_activity,
                nftt_listings, # 追加
                merged_chars, os_chars
            )
            
            # ローカルJSONファイルとしてエクスポート
            self.export_sheets_to_json()

            # サイト用の派生データ生成（history.json / snapshots / floorprice_data.json トリム）
            build_site_data(self.base_dir)

            print("\n✓✓✓ 完了: 全データを取得し、eth_stats・floorpriceシート（本番）に書き込みました！ ✓✓✓")
            
            return True
            
        except Exception as e:
            print(f"\n✗ 実行中にエラーが発生しました: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            if self.browser:
                print("\nブラウザを閉じています...")
                self.browser.close()
                print("ブラウザを閉じました")

def build_site_data(base_dir=None):
    """サイト用の派生データを生成する（スクレイピング不要・JSON変換のみ）。

    入力: floorprice_full.json（無ければ floorprice_data.json）, html2_data.json
    出力:
      - data/history.json … キャラ別フロア/出品数の長期時系列（1日1点に間引き、ISO日付付き）
      - floorprice_data.json … クラシック版グラフ用に直近 TRIM_COLS 列へトリム（見た目不変）
      - snapshots/YYYY-MM-DD.json … その日の html2_data.json をコピー（過去日のフル表再現用）
    """
    import json
    import re
    from datetime import datetime

    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    TRIM_COLS = 200  # クラシックのグラフは直近60点しか使わないので十分

    full_path = os.path.join(base_dir, "floorprice_full.json")
    if not os.path.exists(full_path):
        full_path = os.path.join(base_dir, "floorprice_data.json")
    if not os.path.exists(full_path):
        print("  ✗ build_site_data: floorprice データが見つかりません")
        return

    with open(full_path, "r", encoding="utf-8") as f:
        floor = json.load(f)

    if not floor or len(floor) < 6:
        print("  ✗ build_site_data: floorprice データが不正です")
        return

    print("\n" + "=" * 60)
    print("=== サイト用派生データ生成 (build_site_data) ===")
    print("=" * 60)

    n_cols = len(floor[0])
    date_row = floor[1]
    time_row = floor[2]

    # --- Block1 のエンティティ（ALL + 各キャラ）を行ラベルから動的に検出 ---
    # 行3を起点に、ラベル行→(floor=+1, listed=+2) が3行周期で並ぶ
    entities = []  # (label, floor_row_idx, listed_row_idx)
    base = 3
    while base + 2 < len(floor):
        label = (floor[base][1] or "").strip()
        if not label:
            break
        entities.append((label, base + 1, base + 2))
        base += 3

    # --- 列を「日ごと」にグループ化（同日の複数列＝intraday をまとめる）---
    day_groups = []  # [month, day, last_time, [col_idx, ...]]
    for c in range(2, n_cols):
        d = (date_row[c] or "").strip() if c < len(date_row) else ""
        if not d:
            continue
        m = re.match(r"(\d{1,2})月(\d{1,2})日", d)
        if not m:
            continue
        month, day = int(m.group(1)), int(m.group(2))
        t = (time_row[c] or "").strip() if c < len(time_row) else ""
        if day_groups and day_groups[-1][0] == month and day_groups[-1][1] == day:
            day_groups[-1][2] = t
            day_groups[-1][3].append(c)
        else:
            day_groups.append([month, day, t, [c]])

    # --- 年を推定して ISO 日付化（最新=実行日の年、過去へ遡って年跨ぎを補正） ---
    iso_dates = [None] * len(day_groups)
    if day_groups:
        year = datetime.now().year
        iso_dates[-1] = f"{year:04d}-{day_groups[-1][0]:02d}-{day_groups[-1][1]:02d}"
        for i in range(len(day_groups) - 2, -1, -1):
            if day_groups[i][0] > day_groups[i + 1][0]:  # 古い方の月が大きい＝年跨ぎ
                year -= 1
            iso_dates[i] = f"{year:04d}-{day_groups[i][0]:02d}-{day_groups[i][1]:02d}"

    def fnum(s):
        s = (s or "").strip().replace(",", "").replace("¥", "").replace("￥", "")
        if not s or s.startswith("#"):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def inum(s):
        v = fnum(s)
        return int(v) if v is not None else None

    def series_from(grid, ridx, conv):
        """各日について、その日の列のうち最後の非null値を採用した系列を返す。"""
        row = grid[ridx] if (grid and 0 <= ridx < len(grid)) else []
        out = []
        for g in day_groups:
            val = None
            for c in g[3]:
                if c < len(row):
                    v = conv(row[c])
                    if v is not None:
                        val = v
            out.append(val)
        return out

    history = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dates": iso_dates,
        "labels": [f"{g[0]}月{g[1]}日 {g[2]}".strip() for g in day_groups],
        "eth_jpy": [None] * len(day_groups),
        "usd": [None] * len(day_groups),
        "top_offer": [None] * len(day_groups),
        "all": {"floor": [], "listed": []},
        "agg": {k: [None] * len(day_groups) for k in ("avg", "volume", "day_volume", "mcap", "owners", "sales", "supply")},
        "chars": {},
    }
    for (label, fr, lr) in entities:
        floors = series_from(floor, fr, fnum)
        listeds = series_from(floor, lr, inum)
        if label == "ALL":
            history["all"]["floor"] = floors
            history["all"]["listed"] = listeds
        else:
            history["chars"][label] = {"floor": floors, "listed": listeds}

    # --- eth_stats から集計指標＋ETH/円・USDレートを抽出（floorprice と同じ列構造）---
    # 全表（時価総額・平均・出来高・オーナー・セールス・ETH円換算）を過去日でも出すための元データ。
    es_path = os.path.join(base_dir, "eth_stats_full.json")
    if os.path.exists(es_path):
        try:
            with open(es_path, "r", encoding="utf-8") as f:
                es = json.load(f)
            # eth_stats の行ラベル(col1)→行index
            es_label = {}
            for i, r in enumerate(es):
                lab = (r[1] or "").strip() if len(r) > 1 else ""
                if lab and lab not in es_label:
                    es_label[lab] = i

            def es_series(label, intf=False):
                ri = es_label.get(label)
                if ri is None:
                    return [None] * len(day_groups)
                return series_from(es, ri, inum if intf else fnum)

            # eth_stats と floorprice の列が一致している前提（同一スクリプトが並行で書き込む）
            if len(es) > 2 and len(es[0]) == n_cols:
                history["eth_jpy"] = es_series("eth")
                history["usd"] = es_series("USD=JPY")
                history["top_offer"] = es_series("Top Offer")
                history["agg"]["avg"] = es_series("one_day_average_price")
                history["agg"]["day_volume"] = es_series("one_day_volume")
                history["agg"]["volume"] = es_series("total_volume")
                history["agg"]["mcap"] = es_series("market_cap")
                history["agg"]["owners"] = es_series("num_owners", True)
                history["agg"]["sales"] = es_series("one_day_sales", True)
                history["agg"]["supply"] = es_series("total_supply", True)
                # market_cap が無い日は floor × supply で補完（classic相当: floor×総供給）
                # supply も無い日は CNP の総供給 22,222（固定コレクション）で代用
                SUPPLY_FALLBACK = 22222
                for i in range(len(day_groups)):
                    if history["agg"]["mcap"][i] is None:
                        fl = history["all"]["floor"][i]
                        sp = history["agg"]["supply"][i] or SUPPLY_FALLBACK
                        if fl is not None:
                            history["agg"]["mcap"][i] = round(fl * sp)
                # total_volume は OpenSea 由来だが現在は更新停止（フリーズ）しているため、
                # 末尾のフリーズ区間を「最後の実値 + その後の NFTT 日次出来高の累積」で補正する。
                tv = history["agg"]["volume"]
                odv = history["agg"]["day_volume"]
                last_v = next((v for v in reversed(tv) if v is not None), None)
                if last_v is not None:
                    fs = None  # フリーズ区間の開始 index
                    for i in range(len(tv) - 1, -1, -1):
                        if tv[i] == last_v:
                            fs = i
                        elif tv[i] is not None:
                            break
                    if fs is not None and fs < len(tv) - 1:
                        acc = last_v
                        for i in range(fs + 1, len(tv)):
                            acc += (odv[i] or 0)
                            tv[i] = round(acc, 4)
                        print(f"  ✓ total_volume 補正: idx{fs}以降を NFTT 日次出来高で累積（{last_v}→{round(acc,2)}）")
            else:
                print(f"  ! eth_stats の列数が floorprice と不一致のため集計をスキップ (es={len(es[0]) if es else 0} fp={n_cols})")
        except Exception as e:
            print(f"  ! eth_stats の取り込みに失敗: {e}")

    # --- 初期分(2022-06〜) と floorprice の歯抜けを data シート由来の static ファイルで補完 ---
    # 日付キーでマージし、各フィールドは「floorprice/eth_stats 側が値を持てば優先、
    # 無ければ data シート(history_early.json)の値で埋める」。
    # → 2022-08-28 以前の追加に加え、floorprice の値が空だった 8/28〜11/01 等の穴も埋まる。
    early_path = os.path.join(base_dir, "data", "history_early.json")
    if os.path.exists(early_path):
        try:
            with open(early_path, "r", encoding="utf-8") as f:
                early = json.load(f)
            h_dates = history["dates"]
            e_dates = early.get("dates", [])
            h_idx = {d: i for i, d in enumerate(h_dates)}
            e_idx = {d: i for i, d in enumerate(e_dates)}
            union = sorted(set(h_dates) | set(e_dates))

            def merge_series(h_arr, e_arr):
                out = []
                for d in union:
                    hv = h_arr[h_idx[d]] if (h_arr is not None and d in h_idx) else None
                    ev = e_arr[e_idx[d]] if (e_arr is not None and d in e_idx) else None
                    out.append(hv if hv is not None else ev)
                return out

            # 単純な系列（top-level）
            history["eth_jpy"] = merge_series(history["eth_jpy"], early.get("eth_jpy"))
            history["usd"] = merge_series(history["usd"], early.get("usd"))
            history["top_offer"] = merge_series(history["top_offer"], early.get("top_offer"))
            # all / agg / chars
            for key in ("floor", "listed"):
                history["all"][key] = merge_series(history["all"][key], early.get("all", {}).get(key))
            for key in history["agg"]:
                history["agg"][key] = merge_series(history["agg"][key], early.get("agg", {}).get(key))
            for name, ser in history["chars"].items():
                esrc = early.get("chars", {}).get(name, {})
                for key in ("floor", "listed"):
                    ser[key] = merge_series(ser[key], esrc.get(key))

            # labels / dates を union に合わせ直す
            def mk_label(d):
                if d in h_idx:
                    return history["labels"][h_idx[d]]
                _, mo, da = d.split("-")
                return f"{int(mo)}月{int(da)}日"
            history["labels"] = [mk_label(d) for d in union]
            history["dates"] = union
            added = len([d for d in e_dates if d not in h_idx])
            print(f"  ✓ data シートで補完: 全{len(union)}日（追加/補填 {len(e_dates)}日分を反映）")
        except Exception as e:
            print(f"  ! history_early.json の結合に失敗: {e}")

    # --- 累計取引量(volume)のクリーニング ---
    # 本来は単調増加（コントラクト移行で稀にリセット）。OpenSea由来の異常値を除去する:
    #  ・スパイク（直近の3倍超 かつ +3000ETH超）→ 直前値を維持
    #  ・一時的な下振れ（誤値）→ 直前値を維持（後で元水準に戻るものは異常とみなす）
    #  ・恒久的な大幅下落（その後も元水準に戻らない）→ 正当なリセットとして採用
    def clean_cumulative(series):
        n = len(series)
        s = list(series)
        # pass1: 異常スパイク除去（ロバストな上限=99パーセンタイル×3 を超える値は直前値に）
        vals = sorted(v for v in s if v is not None)
        if vals:
            p99 = vals[min(len(vals) - 1, int(len(vals) * 0.99))]
            ceil = max(p99 * 3, 100)
            prev = None
            for i in range(n):
                if s[i] is None:
                    continue
                if s[i] > ceil and prev is not None:
                    s[i] = prev
                else:
                    prev = s[i]
        # pass2: 大きな下振れ（誤値）と正当なリセットだけを処理し、通常のノイズは原値を維持。
        #   running = 直近の妥当値（水準）。強制的な単調化はしない（高ノイズが床になるのを防ぐ）。
        out = [None] * n
        running = None
        for i in range(n):
            v = s[i]
            if v is None:
                out[i] = running
                continue
            if running is None or running == 0:
                running = v
                out[i] = v
                continue
            if v < running * 0.2:  # 直近水準から大きく下振れ
                recovers = any(
                    (s[j] is not None and s[j] >= running * 0.8)
                    for j in range(i + 1, n)
                )
                if recovers:
                    out[i] = running          # 後で元水準に戻る＝誤値 → 直近水準を維持
                else:
                    running = v               # 戻らない＝正当なリセット
                    out[i] = v
            else:
                out[i] = v                    # 通常値はそのまま（ノイズも保持）
                running = v
        return out

    history["agg"]["volume"] = clean_cumulative(history["agg"]["volume"])
    print("  ✓ volume クリーニング完了（スパイク/誤下振れ除去・リセット保持）")

    os.makedirs(os.path.join(base_dir, "data"), exist_ok=True)
    history_path = os.path.join(base_dir, "data", "history.json")
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  ✓ history.json: {len(history['dates'])}日分 / {len(entities)}エンティティ -> {history_path}")

    # --- floorprice_data.json を直近 TRIM_COLS 列にトリム（クラシック用・見た目不変） ---
    trimmed = []
    for row in floor:
        head = row[:2]
        data_cols = row[2:]
        trimmed.append(head + data_cols[-TRIM_COLS:])
    trim_path = os.path.join(base_dir, "floorprice_data.json")
    with open(trim_path, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)
    print(f"  ✓ floorprice_data.json: 直近{TRIM_COLS}列にトリム -> {trim_path}")

    # --- 当日の html2 をスナップショット保存（過去日のフル表再現用） ---
    html2_path = os.path.join(base_dir, "html2_data.json")
    if os.path.exists(html2_path):
        with open(html2_path, "r", encoding="utf-8") as f:
            html2 = json.load(f)
        # html2 本文から日付（例: 2026/6/24(水)）を拾って ISO 化、無ければ実行日
        snap_iso = None
        for row in html2:
            joined = " ".join(x or "" for x in row)
            m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", joined)
            if m:
                snap_iso = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                break
        if not snap_iso:
            snap_iso = datetime.now().strftime("%Y-%m-%d")
        snap_dir = os.path.join(base_dir, "snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        snap_path = os.path.join(snap_dir, f"{snap_iso}.json")
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(html2, f, ensure_ascii=False, indent=2)
        print(f"  ✓ snapshot: {snap_path}")

        # スナップショットの索引（advanced の日付ピッカー用）を更新
        snap_dir = os.path.join(base_dir, "snapshots")
        files = sorted(fn[:-5] for fn in os.listdir(snap_dir) if fn.endswith(".json") and fn != "index.json")
        with open(os.path.join(snap_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump(files, f, ensure_ascii=False)
        print(f"  ✓ snapshots/index.json: {len(files)}日分")


if __name__ == "__main__":
    import sys
    # `--build-only` でスクレイピングせず派生データ生成のみ（ローカル検証/ブートストラップ用）
    if "--build-only" in sys.argv:
        build_site_data()
        print("\n✓ build_site_data 完了（build-only）")
        sys.exit(0)

    # `--offers-only` で NFTT オファーだけ取得して data/offers.json を更新
    if "--offers-only" in sys.argv:
        scraper = CNPStatsIntegrated()
        scraper.setup_browser()
        try:
            offers = scraper.get_nftt_offers()
            scraper.save_offers_json(offers)
        finally:
            if scraper.browser:
                scraper.browser.close()
        print("\n✓ offers 取得完了（offers-only）")
        sys.exit(0)

    print("="*60)
    print("CNP統計情報 統合取得スクリプト (OS + NFTT)")
    print("="*60)
    scraper = CNPStatsIntegrated()
    result = scraper.run()
    
    if result:
        print("\n✓ スクリプト実行完了")
    else:
        print("\n✗ スクリプト実行失敗")
