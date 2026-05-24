import os
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
USER_DATA_DIR = r"D:\shopee_pipeline\chrome-shopee"

# MongoDB — pakai localhost karena script ini jalan di laptop
MONGO_URI  = "mongodb://mongouser:mongopassword@localhost:27017"
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
        return {
            "inserted": result.upserted_count,
            "matched":  result.matched_count,
        }
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
    """
    Shopee URL format: https://shopee.co.id/nama-produk-i.{shop_id}.{item_id}
    """
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

with sync_playwright() as p:

    print("🌐 Membuka Chrome dengan profile Shopee...")
    print(f"   Profile: {USER_DATA_DIR}")
    print(f"   Keyword: {KEYWORD}")
    print(f"   Halaman: {MAX_PAGES}")

    context = p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        channel="chrome",
        headless=False,
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="id-ID",
        timezone_id="Asia/Jakarta",
        args=[
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
        ]
    )

    page = context.pages[0] if context.pages else context.new_page()

    # Sembunyikan tanda automation
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    # ─── Buka halaman search ─────────────────────
    first_url = (
        f"https://shopee.co.id/search"
        f"?keyword={KEYWORD.replace(' ', '%20')}"
    )

    print("\n🌍 Membuka Shopee...")
    page.goto(first_url, timeout=120000)
    random_delay(5, 8)

    print("📄 URL   :", page.url)
    print("📄 TITLE :", page.title())

    # ─── Cek apakah perlu login manual ───────────
    if (
        "verify" in page.url.lower()
        or "login" in page.url.lower()
        or "Pilih bahasa" in page.content()
    ):
        print("\n⚠️  Perlu tindakan manual:")
        print("   - Pilih bahasa Indonesia (kalau muncul)")
        print("   - Login ke akun Shopee")
        print("   - Tunggu sampai produk muncul")
        input("\n➡ Tekan ENTER setelah produk sudah muncul di browser...")

    # ─── Koneksi MongoDB ─────────────────────────
    collection     = get_mongo_collection()
    all_rows       = []
    total_inserted = 0
    total_matched  = 0

    # ─── Loop halaman ────────────────────────────
    for current_page in range(MAX_PAGES):

        print(f"\n{'='*40}")
        print(f"📄 PAGE {current_page + 1}/{MAX_PAGES}")
        print(f"{'='*40}")

        page_url = (
            f"https://shopee.co.id/search"
            f"?keyword={KEYWORD.replace(' ', '%20')}"
            f"&page={current_page}"
        )

        print("🌍", page_url)

        try:
            page.goto(page_url, timeout=120000)
        except Exception as e:
            print(f"❌ Gagal buka halaman: {e}")
            continue

        random_delay(4, 7)

        # Cek kena verify
        if "verify" in page.url.lower():
            print("⚠️ Kena traffic verify, skip halaman ini.")
            continue

        # Human scroll
        print("🖱️ Scrolling...")
        for _ in range(5):
            page.mouse.wheel(0, random.randint(1500, 3500))
            time.sleep(random.uniform(1, 3))

        random_delay(2, 4)

        print("📄 URL   :", page.url)
        print("📄 TITLE :", page.title())

        # ─── Ambil produk ────────────────────────
        print("🔍 Mengambil produk...")
        items = page.locator('div[data-sqe="item"]')
        count = items.count()
        print(f"📦 Item ditemukan: {count}")

        if count == 0:
            print("❌ Produk kosong, skip halaman ini.")
            # Simpan HTML untuk debug
            with open(
                f"debug_page_{current_page+1}.html", "w", encoding="utf-8"
            ) as f:
                f.write(page.content())
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

                # Lokasi toko
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

                # Extract ID dari URL
                shop_id, item_id = extract_ids_from_link(link)

                # Skip kalau nama kosong
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

        # ─── Simpan ke MongoDB ───────────────────
        if page_rows:
            result          = save_to_mongo(collection, page_rows)
            total_inserted += result["inserted"]
            total_matched  += result["matched"]
            all_rows.extend(page_rows)

            print(f"\n💾 MongoDB halaman {current_page+1}:")
            print(f"   Inserted : {result['inserted']}")
            print(f"   Updated  : {result['matched']}")

        random_delay(3, 6)

    # ─── Selesai ─────────────────────────────────
    print(f"\n{'='*40}")
    print("📊 SELESAI")
    print(f"{'='*40}")
    print(f"Total scrape : {len(all_rows)}")
    print(f"Inserted     : {total_inserted}")
    print(f"Updated      : {total_matched}")
    print(f"{'='*40}")

    context.close()
    print("🛑 Browser ditutup.")