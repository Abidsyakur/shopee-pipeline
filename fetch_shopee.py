"""
fetch_shopee.py
================
Script scraper Shopee yang jalan OTOMATIS — dijalankan oleh Airflow DAG.
Pakai session dari shopee_auth.json yang di-export oleh login_and_export.py.

Tidak butuh browser visual, tidak butuh interaksi manual.
Kalau session expired → raise error supaya Airflow kirim alert.
"""

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

KEYWORD   = "msi gaming"
MAX_PAGES = 7

# File session hasil login_and_export.py
# Di Docker, file ini ada di /opt/airflow/dags/shopee_auth.json
# Di laptop (test manual), pakai path lokal
AUTH_FILE = os.environ.get(
    "SHOPEE_AUTH_FILE",
    r"D:\shopee_pipeline\dags\shopee_auth.json"
)

MONGO_URI  = os.environ.get(
    "MONGO_URI",
    "mongodb://mongouser:mongopassword@localhost:27017"
)
MONGO_DB   = "shopee_raw"
MONGO_COLL = "products"


# =====================================
# MONGODB
# =====================================

def get_mongo_collection():
    client = MongoClient(MONGO_URI)
    db     = client[MONGO_DB]
    coll   = db[MONGO_COLL]
    try:
        coll.create_index(
            [("item_id", 1), ("shop_id", 1), ("scraped_date", 1)],
            unique=True,
            sparse=True,
            name="unique_product_daily"
        )
    except Exception as e:
        print(f"⚠️ Index: {e}")
    print(f"✅ Terhubung MongoDB: {MONGO_DB}.{MONGO_COLL}")
    return coll


def save_to_mongo(collection, rows: list) -> dict:
    if not rows:
        return {"inserted": 0, "matched": 0}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    operations = []
    for row in rows:
        filter_doc = {
            "item_id":      row.get("item_id"),
            "shop_id":      row.get("shop_id"),
            "scraped_date": today,
        }
        update_doc = {"$set": {**row, "scraped_date": today}}
        operations.append(UpdateOne(filter_doc, update_doc, upsert=True))
    try:
        result = collection.bulk_write(operations, ordered=False)
        return {"inserted": result.upserted_count, "matched": result.matched_count}
    except BulkWriteError as bwe:
        print(f"⚠️ BulkWriteError: {bwe.details.get('writeErrors', '')}")
        return {"inserted": 0, "matched": 0}


# =====================================
# UTILS
# =====================================

def parse_harga(harga_str: str) -> float:
    if not harga_str:
        return 0.0
    cleaned = (
        harga_str
        .replace("Rp", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
    )
    try:
        return float(cleaned)
    except Exception:
        return 0.0


def extract_ids_from_link(link: str):
    try:
        if not link:
            return None, None
        parts = link.rstrip("/").split(".")
        if len(parts) >= 2:
            item_id = parts[-1].split("?")[0]
            shop_id = parts[-2]
            return shop_id, item_id
    except Exception:
        pass
    return None, None


def random_delay(min_sec=2, max_sec=5):
    time.sleep(random.uniform(min_sec, max_sec))


def safe_get_url(page) -> str:
    try:
        return page.url
    except Exception:
        return ""


def safe_get_title(page) -> str:
    try:
        return page.title()
    except Exception:
        return ""


def is_blocked(url: str) -> bool:
    return "verify" in url.lower() or "traffic" in url.lower()


# =====================================
# MAIN
# =====================================

def main():
    print("=" * 55)
    print("🤖 Shopee Auto Scraper (Headless)")
    print("=" * 55)
    print(f"   Keyword  : {KEYWORD}")
    print(f"   Halaman  : {MAX_PAGES}")
    print(f"   Auth file: {AUTH_FILE}")
    print(f"   MongoDB  : {MONGO_URI}")

    # Cek file auth ada
    if not os.path.exists(AUTH_FILE):
        print(f"\n❌ File session tidak ditemukan: {AUTH_FILE}")
        print("   Jalankan login_and_export.py terlebih dahulu!")
        sys.exit(1)

    # Cek umur file auth — ingatkan kalau sudah lebih dari 5 hari
    file_age_days = (
        datetime.now().timestamp() - os.path.getmtime(AUTH_FILE)
    ) / 86400
    if file_age_days > 5:
        print(f"\n⚠️  File session sudah {file_age_days:.1f} hari.")
        print("   Mungkin sudah expired. Kalau gagal, jalankan login_and_export.py lagi.")

    with sync_playwright() as p:

        print("\n🌐 Membuka Chromium headless dengan session Shopee...")

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
            ]
        )

        # Load session dari file JSON
        context = browser.new_context(
            storage_state=AUTH_FILE,
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )

        page = context.new_page()

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # ─── Buka halaman pertama ─────────────────
        first_url = (
            f"https://shopee.co.id/search"
            f"?keyword={KEYWORD.replace(' ', '%20')}"
        )

        print("🌍 Membuka Shopee...")
        try:
            page.goto(first_url, timeout=120000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"⚠️ Goto warning: {e}")

        random_delay(5, 8)

        current_url = safe_get_url(page)
        print(f"📄 URL   : {current_url}")
        print(f"📄 TITLE : {safe_get_title(page)}")

        # ─── Cek session masih valid ──────────────
        if is_blocked(current_url):
            print("\n❌ Session expired atau kena block!")
            print("   Jalankan login_and_export.py untuk refresh session.")
            browser.close()
            sys.exit(1)

        try:
            content = page.content()
            if "Pilih bahasa" in content or "is_logged_in=false" in current_url:
                print("\n❌ Tidak terdeteksi sebagai user login!")
                print("   Jalankan login_and_export.py untuk refresh session.")
                browser.close()
                sys.exit(1)
        except Exception:
            pass

        print("✅ Session valid, mulai scraping...")

        # ─── Koneksi MongoDB ──────────────────────
        collection     = get_mongo_collection()
        all_rows       = []
        total_inserted = 0
        total_matched  = 0

        # ─── Loop halaman ─────────────────────────
        for current_page_num in range(MAX_PAGES):

            print(f"\n{'='*40}")
            print(f"📄 PAGE {current_page_num + 1}/{MAX_PAGES}")
            print(f"{'='*40}")

            page_url = (
                f"https://shopee.co.id/search"
                f"?keyword={KEYWORD.replace(' ', '%20')}"
                f"&page={current_page_num}"
            )

            print("🌍", page_url)

            try:
                page.goto(page_url, timeout=120000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"⚠️ Goto warning: {e}")

            random_delay(4, 7)

            current_url = safe_get_url(page)

            if is_blocked(current_url):
                print(f"⚠️ Kena block di halaman {current_page_num+1}, skip.")
                continue

            # Human scroll
            print("🖱️ Scrolling...")
            for _ in range(5):
                try:
                    page.mouse.wheel(0, random.randint(1500, 3500))
                except Exception:
                    pass
                time.sleep(random.uniform(1, 3))

            random_delay(2, 4)

            print(f"📄 URL   : {safe_get_url(page)}")
            print(f"📄 TITLE : {safe_get_title(page)}")

            # ─── Ambil produk ──────────────────────
            print("🔍 Mengambil produk...")
            try:
                items = page.locator('div[data-sqe="item"]')
                count = items.count()
            except Exception as e:
                print(f"❌ Gagal ambil items: {e}")
                continue

            print(f"📦 Item ditemukan: {count}")

            if count == 0:
                print("❌ Produk kosong, skip.")
                try:
                    log_path = f"/opt/airflow/logs/debug_page_{current_page_num+1}.html"
                    with open(log_path, "w", encoding="utf-8") as f:
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

                    # Nama
                    try:
                        nama = item.locator(
                            'div.line-clamp-2'
                        ).first.inner_text(timeout=3000)
                    except Exception:
                        try:
                            nama = item.locator(
                                'div[data-sqe="name"]'
                            ).first.inner_text(timeout=3000)
                        except Exception:
                            pass

                    # Harga
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

                    # Link
                    try:
                        href = item.locator("a").first.get_attribute("href")
                        if href:
                            link = (
                                "https://shopee.co.id" + href
                                if href.startswith("/") else href
                            )
                    except Exception:
                        pass

                    # Lokasi
                    try:
                        lokasi = item.locator(
                            'div[class*="truncate"]'
                        ).last.inner_text(timeout=2000)
                    except Exception:
                        pass

                    # Rating
                    try:
                        for t in item.locator("div").all_inner_texts():
                            tx = t.strip()
                            if tx.startswith("4.") or tx.startswith("5."):
                                rating = tx
                                break
                    except Exception:
                        pass

                    shop_id, item_id = extract_ids_from_link(link)

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
                        "page":          current_page_num + 1,
                        "scraped_at":    datetime.now(timezone.utc).isoformat(),
                    }

                    page_rows.append(doc)
                    print(f"   ✅ {i+1}. {nama[:55]} | {harga_str}")

                except Exception as e:
                    print(f"   ❌ Error item {i+1}: {e}")

            # ─── Simpan ke MongoDB ─────────────────
            if page_rows:
                result          = save_to_mongo(collection, page_rows)
                total_inserted += result["inserted"]
                total_matched  += result["matched"]
                all_rows.extend(page_rows)
                print(f"\n💾 MongoDB halaman {current_page_num+1}:")
                print(f"   Inserted : {result['inserted']}")
                print(f"   Updated  : {result['matched']}")

            random_delay(3, 6)

        # ─── Selesai ──────────────────────────────
        print(f"\n{'='*40}")
        print("📊 SELESAI")
        print(f"{'='*40}")
        print(f"Total scrape : {len(all_rows)}")
        print(f"Inserted     : {total_inserted}")
        print(f"Updated      : {total_matched}")
        print(f"{'='*40}")

        browser.close()
        print("🛑 Browser ditutup.")

        # Exit code 1 kalau tidak ada data — Airflow akan deteksi sebagai FAILED
        if len(all_rows) == 0:
            print("⚠️  Tidak ada data yang berhasil di-scrape!")
            sys.exit(1)


if __name__ == "__main__":
    main()