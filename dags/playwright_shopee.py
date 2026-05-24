
#IMPORT LIBRARY
import os
import json
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
MAX_PAGES = 5

MONGO_URI  = "mongodb://mongouser:mongopassword@mongodb:27017"
MONGO_DB   = "shopee_raw"
MONGO_COLL = "products"

# File cookies hasil export dari Cookie-Editor Chrome
COOKIES_FILE = "/opt/airflow/dags/shopee_cookies.json"


# =====================================
# LOAD & CONVERT COOKIES
# =====================================

def load_cookies(path: str) -> list:
    """
    Load cookies dari file JSON hasil export Cookie-Editor.
    Cookie-Editor export format sedikit beda dari format Playwright,
    jadi perlu dikonversi.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    cookies = []
    for c in raw:
        cookie = {
            "name":   c.get("name", ""),
            "value":  c.get("value", ""),
            "domain": c.get("domain", ".shopee.co.id"),
            "path":   c.get("path", "/"),
        }
        # Tambahkan field opsional kalau ada
        if c.get("secure") is not None:
            cookie["secure"] = c["secure"]
        if c.get("httpOnly") is not None:
            cookie["httpOnly"] = c["httpOnly"]
        if c.get("sameSite") in ("Strict", "Lax", "None"):
            cookie["sameSite"] = c["sameSite"]

        # Skip cookie yang name/value kosong
        if cookie["name"] and cookie["value"]:
            cookies.append(cookie)

    print(f"✅ {len(cookies)} cookies berhasil diload dari {path}")
    return cookies


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


def save_to_mongo(collection, rows: list):
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
        print(f"⚠️ BulkWriteError (sebagian data mungkin duplikat): {bwe.details}")
        return {"inserted": 0, "matched": 0}


# =====================================
# UTILS
# =====================================

def parse_harga(harga_str: str):
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


# =====================================
# MAIN
# =====================================

# Cek file cookies ada
if not os.path.exists(COOKIES_FILE):
    raise FileNotFoundError(
        f"File cookies tidak ditemukan: {COOKIES_FILE}\n"
        f"Export cookies dari Chrome pakai Cookie-Editor extension,\n"
        f"simpan sebagai shopee_cookies.json di folder dags/"
    )

with sync_playwright() as p:

    print("🌐 Membuka Chromium...")

    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ]
    )

    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="id-ID",
        timezone_id="Asia/Jakarta",
    )

    # Inject cookies sebelum buka halaman
    print("🍪 Inject cookies Shopee...")
    cookies = load_cookies(COOKIES_FILE)
    context.add_cookies(cookies)

    page = context.new_page()

    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    # =====================================
    # OPEN SHOPEE
    # =====================================

    first_url = (
        "https://shopee.co.id/search"
        f"?keyword={KEYWORD.replace(' ', '%20')}"
    )

    print("🌍 Membuka Shopee search...")
    page.goto(first_url, timeout=120000, wait_until="domcontentloaded")
    random_delay(5, 8)

    print("📄 URL   :", page.url)
    print("📄 TITLE :", page.title())
    page.screenshot(path="/opt/airflow/logs/debug_first.png")

    # Cek apakah kena verify/traffic
    current_url = page.url.lower()
    if "traffic" in current_url or "captcha" in current_url:
        print("❌ Kena traffic verify — cookies mungkin expired.")
        print("⚠️  Export ulang cookies dari Chrome dan update shopee_cookies.json")
        page.screenshot(path="/opt/airflow/logs/verify_detected.png")
        browser.close()
        raise RuntimeError(
            "Shopee traffic verify detected. "
            "Update shopee_cookies.json dari Cookie-Editor."
        )

    # Cek apakah login berhasil
    content = page.content()
    if "is_logged_in=false" in page.url or "Pilih bahasa" in content:
        print("❌ Cookies tidak valid atau sudah expired.")
        browser.close()
        raise RuntimeError("Cookies tidak valid. Export ulang dari Chrome.")

    print("✅ Session valid, mulai scraping...")

    # =====================================
    # MONGODB
    # =====================================

    collection     = get_mongo_collection()
    all_rows       = []
    total_inserted = 0
    total_matched  = 0

    # =====================================
    # LOOP PAGE
    # =====================================

    for current_page in range(MAX_PAGES):

        print("\n=================================")
        print(f"📄 PAGE {current_page + 1}/{MAX_PAGES}")
        print("=================================")

        page_url = (
            "https://shopee.co.id/search"
            f"?keyword={KEYWORD.replace(' ', '%20')}"
            f"&page={current_page}"
        )

        print("🌍", page_url)

        try:
            page.goto(page_url, timeout=120000, wait_until="domcontentloaded")
        except Exception as e:
            print("❌ Gagal buka halaman:", e)
            continue

        random_delay(4, 7)

        # Cek kena verify di tengah scraping
        if "traffic" in page.url.lower() or "verify" in page.url.lower():
            print("❌ Kena verify di halaman ini, skip.")
            page.screenshot(
                path=f"/opt/airflow/logs/verify_{current_page+1}.png"
            )
            continue

        # Human scroll
        print("🖱️ Scrolling...")
        for _ in range(5):
            page.mouse.wheel(0, random.randint(2000, 4000))
            time.sleep(random.uniform(1, 3))

        random_delay(2, 4)

        print("📄 URL   :", page.url)
        print("📄 TITLE :", page.title())

        page.screenshot(path=f"/opt/airflow/logs/page_{current_page+1}.png")

        # =====================================
        # SCRAPE ITEMS
        # =====================================

        print("🔍 Mengambil item produk...")
        items = page.locator('div[data-sqe="item"]')
        count = items.count()
        print(f"📦 Total item ditemukan: {count}")

        if count == 0:
            print("❌ Produk kosong, simpan HTML debug.")
            html = page.content()
            with open(
                f"/opt/airflow/logs/page_{current_page+1}.html",
                "w", encoding="utf-8"
            ) as f:
                f.write(html)
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
                    nama = item.locator('div.line-clamp-2').first.inner_text(timeout=3000)
                except Exception:
                    try:
                        nama = item.locator('div[data-sqe="name"]').first.inner_text(timeout=3000)
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
                        link = "https://shopee.co.id" + href if href.startswith("/") else href
                except Exception:
                    pass

                # Lokasi
                try:
                    lokasi = item.locator('div[class*="truncate"]').last.inner_text(timeout=2000)
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
                    "page":          current_page + 1,
                    "scraped_at":    datetime.now(timezone.utc).isoformat(),
                }

                page_rows.append(doc)
                print(f"   ✅ {i+1}. {nama[:55]} | {harga_str}")

            except Exception as e:
                print(f"   ❌ Error item {i+1}: {e}")

        # Save ke MongoDB
        if page_rows:
            result          = save_to_mongo(collection, page_rows)
            total_inserted += result["inserted"]
            total_matched  += result["matched"]
            all_rows.extend(page_rows)
            print(f"\n💾 MongoDB halaman {current_page+1}:")
            print(f"   Inserted : {result['inserted']}")
            print(f"   Updated  : {result['matched']}")

        random_delay(3, 6)

    # =====================================
    # SELESAI
    # =====================================

    print("\n=================================")
    print("📊 SELESAI")
    print("=================================")
    print(f"Total scrape : {len(all_rows)}")
    print(f"Inserted     : {total_inserted}")
    print(f"Updated      : {total_matched}")
    print("=================================")

    browser.close()
    print("🛑 Browser ditutup")