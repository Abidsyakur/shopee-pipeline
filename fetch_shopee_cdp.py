# fetch_shopee_cdp.py
# Konek ke Chrome yang sudah login via CDP
# Cara pakai:
#   1. Buka Chrome dengan CDP:
#      chrome.exe --remote-debugging-port=9222
#                 --user-data-dir="C:/Users/mohab/AppData/Local/Google/Chrome/User Data"
#   2. Buka shopee.co.id di Chrome, pastikan sudah login
#   3. Jalankan: python fetch_shopee_cdp.py

import os
import sys
import time
import random
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright
from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError


# =====================================
# CONFIG
# =====================================

KEYWORD      = "msi gaming"
MAX_PAGES    = 7
CDP_ENDPOINT = "http://localhost:9222"

MONGO_URI  = "mongodb://mongouser:mongopassword@localhost:27017"
MONGO_DB   = "shopee_raw"
MONGO_COLL = "products"


# =====================================
# MONGODB
# =====================================

def get_mongo_collection():
    client = MongoClient(MONGO_URI)
    coll   = client[MONGO_DB][MONGO_COLL]
    try:
        coll.create_index(
            [("item_id", 1), ("shop_id", 1), ("scraped_date", 1)],
            unique=True,
            sparse=True,
            name="unique_product_daily"
        )
    except Exception as e:
        print(f"Index: {e}")
    print(f"Terhubung MongoDB: {MONGO_DB}.{MONGO_COLL}")
    return coll


def save_to_mongo(collection, rows):
    if not rows:
        return {"inserted": 0, "matched": 0}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ops = []
    for row in rows:
        ops.append(UpdateOne(
            {"item_id": row.get("item_id"), "shop_id": row.get("shop_id"), "scraped_date": today},
            {"$set": {**row, "scraped_date": today}},
            upsert=True
        ))
    try:
        r = collection.bulk_write(ops, ordered=False)
        return {"inserted": r.upserted_count, "matched": r.matched_count}
    except BulkWriteError:
        return {"inserted": 0, "matched": 0}


# =====================================
# UTILS
# =====================================

def parse_harga(s):
    if not s:
        return 0.0
    try:
        return float(s.replace("Rp","").replace(".","").replace(",",".").strip())
    except Exception:
        return 0.0


def extract_ids(link):
    try:
        if not link:
            return None, None
        parts = link.rstrip("/").split(".")
        if len(parts) >= 2:
            return parts[-2], parts[-1].split("?")[0]
    except Exception:
        pass
    return None, None


def rdelay(a=2, b=5):
    time.sleep(random.uniform(a, b))


def safe_url(page):
    try:
        return page.url
    except Exception:
        return ""


def safe_title(page):
    try:
        return page.title()
    except Exception:
        return ""


def is_blocked(url):
    return "verify" in url.lower() or "traffic" in url.lower()


# =====================================
# MAIN
# =====================================

def main():
    print("=" * 55)
    print("Shopee Scraper via CDP")
    print("=" * 55)
    print(f"Keyword     : {KEYWORD}")
    print(f"Halaman     : {MAX_PAGES}")
    print(f"CDP         : {CDP_ENDPOINT}")

    with sync_playwright() as p:

        print("\nKonek ke Chrome via CDP...")
        try:
            browser = p.chromium.connect_over_cdp(CDP_ENDPOINT)
        except Exception as e:
            print(f"\nGagal konek ke Chrome: {e}")
            print("Pastikan Chrome sudah dibuka dengan --remote-debugging-port=9222")
            sys.exit(1)

        print("Berhasil konek ke Chrome!")

        contexts = browser.contexts
        if not contexts:
            print("Tidak ada browser context aktif.")
            sys.exit(1)

        context = contexts[0]

        # Cari tab Shopee atau buka baru
        page = None
        for pg in context.pages:
            if "shopee.co.id" in pg.url:
                page = pg
                print(f"Pakai tab Shopee: {pg.url}")
                break

        if not page:
            print("Buka tab Shopee baru...")
            page = context.new_page()

        # Buka halaman search
        first_url = f"https://shopee.co.id/search?keyword={KEYWORD.replace(' ', '%20')}"
        print(f"\nMembuka: {first_url}")
        try:
            page.goto(first_url, timeout=120000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"Warning: {e}")

        rdelay(5, 8)
        print(f"URL   : {safe_url(page)}")
        print(f"TITLE : {safe_title(page)}")

        if is_blocked(safe_url(page)):
            print("\nKena traffic verify! Selesaikan di browser lalu jalankan ulang.")
            sys.exit(1)

        print("Session valid, mulai scraping...")

        collection     = get_mongo_collection()
        all_rows       = []
        total_inserted = 0
        total_matched  = 0

        for pg_num in range(MAX_PAGES):

            print(f"\n{'='*40}")
            print(f"PAGE {pg_num + 1}/{MAX_PAGES}")
            print(f"{'='*40}")

            url = f"https://shopee.co.id/search?keyword={KEYWORD.replace(' ', '%20')}&page={pg_num}"
            print("URL:", url)

            try:
                page.goto(url, timeout=120000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"Warning: {e}")

            rdelay(4, 7)

            if is_blocked(safe_url(page)):
                print(f"Kena block halaman {pg_num+1}, skip.")
                continue

            # Scroll
            print("Scrolling...")
            for _ in range(5):
                try:
                    page.mouse.wheel(0, random.randint(1500, 3500))
                except Exception:
                    pass
                time.sleep(random.uniform(1, 3))

            rdelay(2, 4)
            print(f"URL   : {safe_url(page)}")
            print(f"TITLE : {safe_title(page)}")

            # Ambil produk
            try:
                items = page.locator('div[data-sqe="item"]')
                count = items.count()
            except Exception as e:
                print(f"Gagal ambil items: {e}")
                continue

            print(f"Item ditemukan: {count}")

            if count == 0:
                print("Produk kosong, skip.")
                try:
                    with open(f"debug_page_{pg_num+1}.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                except Exception:
                    pass
                continue

            page_rows = []

            for i in range(count):
                try:
                    item      = items.nth(i)
                    nama      = None
                    harga_str = None
                    harga_num = 0.0
                    link      = None
                    lokasi    = None
                    rating    = None

                    try:
                        nama = item.locator('div.line-clamp-2').first.inner_text(timeout=3000)
                    except Exception:
                        try:
                            nama = item.locator('div[data-sqe="name"]').first.inner_text(timeout=3000)
                        except Exception:
                            pass

                    try:
                        spans = item.locator("span")
                        for h in range(spans.count()):
                            txt = spans.nth(h).inner_text()
                            if "Rp" in txt:
                                harga_str = txt
                                harga_num = parse_harga(harga_str)
                                break
                    except Exception:
                        pass

                    try:
                        href = item.locator("a").first.get_attribute("href")
                        if href:
                            link = "https://shopee.co.id" + href if href.startswith("/") else href
                    except Exception:
                        pass

                    try:
                        lokasi = item.locator('div[class*="truncate"]').last.inner_text(timeout=2000)
                    except Exception:
                        pass

                    try:
                        for t in item.locator("div").all_inner_texts():
                            tx = t.strip()
                            if tx.startswith("4.") or tx.startswith("5."):
                                rating = tx
                                break
                    except Exception:
                        pass

                    shop_id, item_id = extract_ids(link)

                    if not nama:
                        continue

                    doc = {
                        "item_id":       item_id,
                        "shop_id":       shop_id,
                        "name":          nama,
                        "price":         harga_num,
                        "price_raw":     harga_str,
                        "shop_location": lokasi,
                        "rating":        rating,
                        "link":          link,
                        "keyword":       KEYWORD,
                        "page":          pg_num + 1,
                        "scraped_at":    datetime.now(timezone.utc).isoformat(),
                    }

                    page_rows.append(doc)
                    print(f"  {i+1}. {nama[:55]} | {harga_str}")

                except Exception as e:
                    print(f"  Error item {i+1}: {e}")

            if page_rows:
                result          = save_to_mongo(collection, page_rows)
                total_inserted += result["inserted"]
                total_matched  += result["matched"]
                all_rows.extend(page_rows)
                print(f"\nMongoDB hal {pg_num+1}: inserted={result['inserted']} updated={result['matched']}")

            rdelay(3, 6)

        print(f"\n{'='*40}")
        print("SELESAI")
        print(f"{'='*40}")
        print(f"Total  : {len(all_rows)}")
        print(f"Insert : {total_inserted}")
        print(f"Update : {total_matched}")

        print("\nScraping selesai. Chrome tetap terbuka.")

        if len(all_rows) == 0:
            print("Tidak ada data!")
            sys.exit(1)


if __name__ == "__main__":
    main()