#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.environ.get("GOOGLE_CREDENTIALS_PATH", os.path.join(BASE_DIR, "service_account.json"))
SPREADSHEET_KEY = "1MNQuV9PODKDm9gqEddL3q7keBC92LkV5ZOYEPNa0ijY"

def main():
    if not os.path.exists(CREDENTIALS_PATH):
        print(f"Error: Google credentials file not found at {CREDENTIALS_PATH}")
        sys.exit(1)

    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scope)
    gc = gspread.authorize(credentials)

    print("Opening spreadsheet...")
    workbook = gc.open_by_key(SPREADSHEET_KEY)
    ws = workbook.worksheet('win_htmlList')

    col_filenames = ws.col_values(2)
    col_urls = ws.col_values(3)
    col_widths = ws.col_values(4)
    col_heights = ws.col_values(5)

    items = []
    for i in range(len(col_filenames)):
        filename_val = (col_filenames[i] or "").strip()
        url_val = (col_urls[i] or "").strip()
        if not filename_val or not url_val or filename_val == "filename" or url_val == "url":
            continue
        items.append({
            "filename": filename_val,
            "url": url_val,
            "width": int(col_widths[i]) if i < len(col_widths) and col_widths[i] else 1920,
            "height": int(col_heights[i]) if i < len(col_heights) and col_heights[i] else 1080
        })

    if not items:
        print("No screenshots to take.")
        return

    # 保存先ディレクトリの作成
    img_dir = os.path.join(BASE_DIR, "99_images")
    os.makedirs(img_dir, exist_ok=True)

    print(f"Starting Playwright. Saving images to {img_dir}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for item in items:
            filename = os.path.join(img_dir, item["filename"])
            url = item["url"]
            if "pubhtml" in url:
                url += "&widget=false&headers=false" if "?" in url else "?widget=false&headers=false"

            print(f"Taking screenshot of {url} ({item['width']}x{item['height']}) -> {item['filename']}")
            
            page.set_viewport_size({"width": item["width"], "height": item["height"]})
            page.goto(url, wait_until="load")
            
            try:
                page.wait_for_selector("#sheets-viewport", timeout=60000)
                time.sleep(10)
                element = page.locator("#sheets-viewport")
                element.screenshot(path=filename)
                print(f"Successfully saved {item['filename']}")
            except Exception as e:
                print(f"Error capturing element for {item['filename']}: {e}")
                page.screenshot(path=filename)
                print(f"Saved fallback page screenshot for {item['filename']}")

        browser.close()

if __name__ == "__main__":
    main()
