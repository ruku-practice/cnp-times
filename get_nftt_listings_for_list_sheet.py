#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import time
import os
import re
import yfinance as yf
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
import gspread
from gspread.exceptions import APIError
from google.auth.exceptions import TransportError

class CNPListingsFetcher:
    """
    NFTT Listing, Activity, ETH Price, FiNANCiE data fetcher
    Target Sheet: 'list'
    """
    def __init__(self):
        self.browser = None
        self.page = None
        # URLs
        self.nftt_listing_url = "https://cryptoninja.nftt.market/?collection=0x138A5C693279b6Cd82F48d4bEf563251Bc15ADcE"
        self.nftt_activity_url = "https://cryptoninja.nftt.market/activity?collection=0x138A5C693279b6Cd82F48d4bEf563251Bc15ADcE"
        self.os_url = "https://opensea.io/collection/cryptoninjapartners-v2"
        
        # FiNANCiE Slugs
        self.financie_targets = [
            {'slug': 'cnpninjadao', 'member_row': 39, 'price_row': 40},
            {'slug': 'orochi_cnp', 'member_row': 41, 'price_row': 42}
        ]
        
        # Characters
        self.characters = ['Orochi', 'Mitama', 'Narukami', 'Leelee', 'Luna', 'Yama', 'Makami', 'Towa', 'Setsuna', 'Ema', 'Taruto']
        
        # Output Config
        self.target_spreadsheet_id = "1HXOVwMvUWsYT0mgLKXzFn1iuR-CvdUF2ceRKvU7L9dY"
        self.target_sheet_name = "list"
        
        # Credentials
        self.credentials_path = os.environ.get("GOOGLE_CREDENTIALS_PATH")
        if not self.credentials_path:
            # フォールバックとしてローカルのデフォルトパス
            BASE_DIR = os.path.dirname(os.path.abspath(__file__))
            self.credentials_path = os.path.join(BASE_DIR, "service_account.json")
            if not os.path.exists(self.credentials_path):
                # 旧ローカル環境（Google Drive）の .env からロードを試みる
                env_path = "/Users/kurokzhr/Library/CloudStorage/GoogleDrive-ruku.practice@gmail.com/マイドライブ/00_XXX_TIMES/00_CreateAutoTimes/60_GetInfoFromME/.env"
                if os.path.exists(env_path):
                    load_dotenv(env_path)
                    self.credentials_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
        
        # GSpread Setup
        self.scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        self.credentials = Credentials.from_service_account_file(
            self.credentials_path,
            scopes=self.scopes
        )
        self.gc = gspread.authorize(self.credentials)

    def setup_browser(self):
        """Playwright Browser Setup"""
        print("ブラウザを起動中...")
        playwright = sync_playwright().start()
        self.browser = playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-gpu',
            ]
        )
        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            locale='ja-JP',
            timezone_id='Asia/Tokyo'
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(60000)
        print("ブラウザ起動完了")

    def reset_page(self):
        """Close current page and open a new one to clean state"""
        try:
            if self.page:
                self.page.close()
        except: pass
        try:
            self.page = self.context.new_page()
            self.page.set_default_timeout(60000)
        except Exception as e:
            print(f"ページリセット失敗: {e}")

    def extract_number_from_text(self, text):
        if not text or text == '--': return 0.0
        text = text.strip().replace(',', '')
        if 'K' in text: text = text.replace('K', '000')
        try:
            return float(text)
        except ValueError:
            return 0.0

    # --- Data Fetching Methods ---

    def fetch_eth_jpy(self):
        """Fetch ETH/JPY price via yfinance"""
        try:
            print("ETH価格取得中(yfinance)...")
            eth = yf.Ticker("ETH-USD")
            eth_hist = eth.history(period="1d")
            if eth_hist.empty: return None
            
            usdjpy = yf.Ticker("JPY=X")
            usdjpy_hist = usdjpy.history(period="1d")
            if usdjpy_hist.empty: return None
            
            eth_price = eth_hist['Close'].iloc[-1]
            jpy_rate = usdjpy_hist['Close'].iloc[-1]
            
            price = int(eth_price * jpy_rate)
            print(f"ETH価格: {price} JPY")
            return price
        except Exception as e:
            print(f"ETH価格取得エラー: {e}")
            return None

    def get_listings(self):
        """Fetch listings from NFTT"""
        try:
            self.reset_page()
            print(f"NFTT(リスト)へアクセス中: {self.nftt_listing_url}")
            self.page.goto(self.nftt_listing_url, wait_until='domcontentloaded')
            try: self.page.wait_for_load_state('networkidle', timeout=30000)
            except: pass
            time.sleep(15) # Wait for JS render
            
            # Scroll/Wait logic
            limit=0
            while limit < 5:
                rows = self.page.locator('tr').all()
                if len(rows) > 0: break
                time.sleep(5); limit+=1
                
            char_stats = {char: {'count': 0, 'min_price': 0.0} for char in self.characters}
            all_prices = []
            total_list_count = 0
            
            rows = self.page.locator('tr').all()
            for row in rows:
                try:
                    buy_tag = row.locator('.tag.buy_now')
                    if buy_tag.count() == 0 or "購入する" not in buy_tag.text_content():
                        continue
                    
                    total_list_count += 1
                    price_val = 0.0
                    price_el = row.locator('.td__price .price div').first
                    if price_el.count() > 0:
                        eth_str = price_el.text_content().replace('WETH', '').replace('ETH', '').strip()
                        price_val = self.extract_number_from_text(eth_str)
                    
                    if price_val > 0: all_prices.append(price_val)
                    
                    row_text = row.text_content()
                    for char in self.characters:
                        if char in row_text:
                            stats = char_stats[char]
                            stats['count'] += 1
                            if price_val > 0:
                                if stats['min_price'] == 0 or price_val < stats['min_price']:
                                    stats['min_price'] = price_val
                            break
                except: continue
                
            all_prices.sort()
            return char_stats, all_prices, total_list_count
        except Exception as e:
            print(f"リスト取得エラー: {e}")
            return None, None, None

    def get_nftt_activity_stats(self):
        """Fetch Sales Count & Volume (24h) from NFTT Activity"""
        try:
            self.reset_page()
            print(f"NFTT(アクティビティ)へアクセス中: {self.nftt_activity_url}")
            self.page.goto(self.nftt_activity_url, wait_until='domcontentloaded')
            try: self.page.wait_for_load_state('networkidle', timeout=30000)
            except: pass
            time.sleep(5)
            
            sales_24h = 0
            vol_24h = 0.0
            cutoff_time = datetime.now() - timedelta(hours=24)
            
            # Scroll to load history
            for i in range(20):
                self.page.keyboard.press("End")
                time.sleep(1.5)
            
            items = self.page.locator('.tooltip').all()
            for item in items:
                try:
                    full_text = item.text_content().strip()
                    if "移動" in full_text or "Transfer" in full_text: continue
                    
                    is_target = False
                    tooltip_text = item.locator('.tooltiptext')
                    if tooltip_text.count() > 0:
                        ts = tooltip_text.text_content().strip()
                        try:
                            dt = datetime.strptime(ts, "%Y/%m/%d %H:%M")
                            if dt >= cutoff_time: is_target = True
                        except: pass
                    elif any(s in full_text for s in ["分前", "時間前", "秒前"]):
                        is_target = True
                        
                    if not is_target: continue
                    
                    # Price check
                    parent2 = item.locator('xpath=../..')
                    price_div = parent2.locator('.price div').first
                    if price_div.count() > 0:
                        sales_24h += 1
                        eth_s = price_div.text_content().replace('WETH','').replace('ETH','').strip()
                        vol_24h += self.extract_number_from_text(eth_s)
                        
                except: continue
                
            avg_sale = 0.0
            if sales_24h > 0:
                avg_sale = round(vol_24h / sales_24h, 4)
                
            return vol_24h, sales_24h, avg_sale
        except Exception as e:
            print(f"アクティビティ取得エラー: {e}")
            return None, None, None

    def get_os_owners(self):
        """Fetch Owner count from OpenSea"""
        try:
            self.reset_page()
            print(f"OpenSeaへアクセス中: {self.os_url}")
            self.page.goto(self.os_url, wait_until='domcontentloaded')
            try: self.page.wait_for_load_state('load', timeout=30000)
            except: pass
            time.sleep(5)
            
            owners = 0
            el = self.page.wait_for_selector('[data-testid="owner-count"]', timeout=30000)
            if el:
                owners = int(self.extract_number_from_text(el.get_attribute('aria-label')))
            return owners
        except Exception: 
            return None

    def get_financie_data(self, slug):
        """Fetch Member Count and Token Price via FiNANCiE"""
        try:
            self.reset_page()
            # 1. Member Count (User Page)
            user_url = f"https://financie.jp/users/{slug}"
            print(f"FiNANCiE(User): {user_url}")
            self.page.goto(user_url, wait_until='domcontentloaded')
            time.sleep(3)
            
            members = 0
            try:
                el = self.page.query_selector('#script__trading_card_rate')
                if el:
                    txt = el.text_content().replace('人','').replace(',','').strip()
                    members = int(txt)
            except: pass
            
            # 2. Token Price (Market Page)
            market_url = f"https://financie.jp/communities/{slug}/market"
            print(f"FiNANCiE(Market): {market_url}")
            self.page.goto(market_url, wait_until='domcontentloaded')
            time.sleep(3)
            
            price = 0.0
            try:
                el = self.page.query_selector('.connector-price')
                if el:
                    i_part = el.query_selector('.int-part').text_content().strip()
                    f_part = el.query_selector('.float-part').text_content().strip()
                    price = float(f"{i_part}{f_part}".replace(',',''))
            except: pass
            
            print(f"Slug {slug}: {members}人, {price}円")
            return members, price
            
        except Exception as e:
            print(f"FiNANCiE取得エラー({slug}): {e}")
            return None, None

    # --- Write Method ---

    def write_to_sheet(self, char_stats, all_prices, total_list_count, 
                       vol_24h, sales_24h, avg_sale, 
                       owners, eth_price, 
                       financie_data):
        try:
            wb = self.gc.open_by_key(self.target_spreadsheet_id)
            ws = wb.worksheet(self.target_sheet_name)
            
            print("スプレッドシート書き込み開始...")
            now = datetime.now()
            col_data = [] # 1D list, will convert to column
            
            # 1-2. Date/Time
            col_data.append([now.strftime("%-m月%-d日")])
            col_data.append([now.strftime("%H:%M")])
            
            # 3. Vol 24h (ETH)
            col_data.append([vol_24h if vol_24h is not None else "アクセス不可"])
            
            # 4. Empty
            col_data.append([""])
            
            # 5. Owners
            col_data.append([owners if owners is not None else "アクセス不可"])
            
            # 6. List Total
            col_data.append([total_list_count if total_list_count is not None else "アクセス不可"])
            
            # 7. List Rate
            if total_list_count is not None:
                rate = (total_list_count / 22222 * 100)
                col_data.append([f"{rate:.2f}%"])
            else:
                col_data.append(["アクセス不可"])
            
            # 8-18. Characters (Orochi..Makami + T&S)
            target_chars = ['Orochi', 'Mitama', 'Narukami', 'Leelee', 'Luna', 'Yama', 'Makami']
            for char in target_chars:
                if char_stats:
                    s = char_stats[char]
                    col_data.append([s['count']])
                    val = s['min_price'] if s['min_price'] > 0 else ""
                    col_data.append([val])
                else:
                    col_data.append(["アクセス不可"])
                    col_data.append(["アクセス不可"])
                
            # Towa+Setsuna (22-23)
            if char_stats:
                t = char_stats['Towa']; s = char_stats['Setsuna']
                ts_count = t['count'] + s['count']
                col_data.append([ts_count])
                
                ts_price = 0.0
                if t['min_price'] > 0 and s['min_price'] > 0: ts_price = min(t['min_price'], s['min_price'])
                elif t['min_price'] > 0: ts_price = t['min_price']
                elif s['min_price'] > 0: ts_price = s['min_price']
                col_data.append([ts_price if ts_price > 0 else ""])
            else:
                col_data.append(["アクセス不可"])
                col_data.append(["アクセス不可"])
                
            # Ema (24-25)
            if char_stats:
                ema = char_stats['Ema']
                col_data.append([ema['count']])
                col_data.append([ema['min_price'] if ema['min_price'] > 0 else ""])
            else:
                col_data.append(["アクセス不可"])
                col_data.append(["アクセス不可"])
                
            # Taruto (26-27)
            if char_stats:
                taruto = char_stats['Taruto']
                col_data.append([taruto['count']])
                col_data.append([taruto['min_price'] if taruto['min_price'] > 0 else ""])
            else:
                col_data.append(["アクセス不可"])
                col_data.append(["アクセス不可"])
            
            # 28. Empty
            col_data.append([""])
            
            # 29. ETH Price (JPY)
            col_data.append([eth_price if eth_price is not None else "アクセス不可"])
            
            # 30. Avg Sale (CNP売買平均)
            col_data.append([avg_sale if avg_sale is not None else "アクセス不可"])
            
            # 31. Avg Sale Diff (Row 30 Current - Row 30 Previous)
            diff_val = ""
            if avg_sale is not None:
                try:
                    last_col = ws.col_count
                    if last_col > 0:
                        prev_val = ws.cell(30, last_col).value
                        if prev_val:
                            diff = float(avg_sale) - float(prev_val)
                            diff_val = round(diff, 4)
                except Exception as e:
                    print(f"差分計算エラー: {e}")
            else:
                diff_val = "アクセス不可"
            col_data.append([diff_val])
            
            # 32. Sales 24h
            col_data.append([sales_24h if sales_24h is not None else "アクセス不可"])
            
            # 33. Floor Price (CNP Overall)
            if all_prices is not None:
                floor_all = min(all_prices) if all_prices else 0
                col_data.append([floor_all if floor_all > 0 else ""])
            else:
                col_data.append(["アクセス不可"])
            
            # 34-38. List Counts by Price Range
            if all_prices is not None:
                counts = [
                    len([p for p in all_prices if p < 0.6]),
                    len([p for p in all_prices if p < 0.5]),
                    len([p for p in all_prices if p < 0.4]),
                    len([p for p in all_prices if p < 0.3]),
                    len([p for p in all_prices if p < 0.2]),
                ]
                for c in counts: col_data.append([c])
            else:
                for _ in range(5): col_data.append(["アクセス不可"])
            
            # 39-42. FiNANCiE Data
            cnp = financie_data.get('cnpninjadao', (None, None))
            col_data.append([cnp[0] if cnp[0] is not None else "アクセス不可"])
            col_data.append([cnp[1] if cnp[1] is not None else "アクセス不可"])
            
            orochi = financie_data.get('orochi_cnp', (None, None))
            col_data.append([orochi[0] if orochi[0] is not None else "アクセス不可"])
            col_data.append([orochi[1] if orochi[1] is not None else "アクセス不可"])
            
            # 43. Spacing
            col_data.append([""])

            # 40-. All Prices
            if all_prices is not None:
                for p in all_prices: col_data.append([p])
            else:
                 col_data.append(["アクセス不可"])
            
            # Write
            next_col = ws.col_count + 1
            ws.add_cols(1)
            cell_range = f'R1C{next_col}:R{len(col_data)}C{next_col}'
            ws.update(values=col_data, range_name=cell_range, value_input_option='USER_ENTERED')
            print(f"書き込み完了: 列 {next_col}, 行数 {len(col_data)}")
            
        except Exception as e:
            print(f"書き込みエラー: {e}")

    def is_already_updated_today(self):
        """スプレッドシートの最終列の1行目を確認し、本日すでにデータが書き込み済みかを判定"""
        try:
            wb = self.gc.open_by_key(self.target_spreadsheet_id)
            ws = wb.worksheet(self.target_sheet_name)
            last_col = ws.col_count
            if last_col > 0:
                # 最終列の1行目の値を取得 (例: "6月29日")
                last_date_val = ws.cell(1, last_col).value
                if last_date_val:
                    today_str = datetime.now().strftime("%-m月%-d日")
                    if last_date_val.strip() == today_str:
                        return True
            return False
        except Exception as e:
            print(f"本日更新済みチェックエラー: {e}")
            return False

    def run(self):
        print("本日更新済みチェックを実行中...")
        if self.is_already_updated_today():
            print("【ガード】本日分のデータは既にスプレッドシートに書き込み済みです。処理をスキップして終了します。")
            import sys
            sys.exit(0)

        self.setup_browser()
        
        # 1. ETH Price
        eth_jpy = self.fetch_eth_jpy()
        
        # 2. Activity (Vol, Sales, Avg)
        vol_24h, sales_24h, avg_sale = self.get_nftt_activity_stats()
        
        # 3. Listings
        char_stats, all_prices, total_count = self.get_listings()
        
        # 4. OS Owners
        owners = self.get_os_owners()
        
        # 5. FiNANCiE
        financie_data = {}
        for target in self.financie_targets:
            slug = target['slug']
            mem, pri = self.get_financie_data(slug)
            financie_data[slug] = (mem, pri)
            
        self.write_to_sheet(char_stats, all_prices, total_count, 
                            vol_24h, sales_24h, avg_sale, 
                            owners, eth_jpy, financie_data)
        
        self.browser.close()

if __name__ == "__main__":
    fetcher = CNPListingsFetcher()
    fetcher.run()
