

import sys
import time
import json
import random
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable


# =====================================
# CONFIG
# =====================================

KEYWORD      = "msi gaming"
MAX_PAGES    = 7
CDP_ENDPOINT = "http://localhost:9222"

KAFKA_BROKER = "localhost:9092"
KAFKA_TOPIC  = "shopee.products"


# =====================================
# KAFKA PRODUCER SETUP
# =====================================

def create_producer():
    print("Konek ke Kafka broker...")
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            # Serialize dict ke JSON bytes
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            # Tunggu konfirmasi dari broker
            acks="all",
            retries=3,
        )
        print(f"Terhubung ke Kafka: {KAFKA_BROKER}")
        return producer
    except NoBrokersAvailable:
        print(f"Kafka tidak bisa diakses di {KAFKA_BROKER}")
        print("Pastikan Docker sudah jalan: docker compose up -d kafka")
        sys.exit(1)


def send_to_kafka(producer, data: dict):
    """Kirim satu produk ke Kafka topic."""
    # Pakai item_id sebagai key supaya produk yang sama
    # selalu masuk ke partition yang sama (ordering terjaga)
    key = data.get("item_id") or "unknown"
    future = producer.send(KAFKA_TOPIC, key=key, value=data)
    return future


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
        path  = link.split("?")[0]
        parts = path.split(".")
        if "-i." in path:
            after_i = path.split("-i.")[-1]
            ids = after_i.split(".")
            if len(ids) >= 2:
                return ids[0], ids[1]
        if len(parts) >= 2:
            return parts[-2], parts[-1]
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
    print("Shopee Kafka Producer")
    print("=" * 55)
    print(f"Keyword : {KEYWORD}")
    print(f"Halaman : {MAX_PAGES}")
    print(f"Topic   : {KAFKA_TOPIC}")

    # Setup Kafka producer
    producer = create_producer()

    with sync_playwright() as p:

        print("\nKonek ke Chrome via CDP...")
        try:
            browser = p.chromium.connect_over_cdp(CDP_ENDPOINT)
        except Exception as e:
            print(f"Gagal konek ke Chrome: {e}")
            print("Buka Chrome dengan: chrome.exe --remote-debugging-port=9222")
            producer.close()
            sys.exit(1)

        context = browser.contexts[0]

        # Cari tab Shopee atau buat baru
        page = None
        for pg in context.pages:
            if "shopee.co.id" in pg.url:
                page = pg
                break
        if not page:
            page = context.new_page()

        # Buka halaman search
        first_url = f"https://shopee.co.id/search?keyword={KEYWORD.replace(' ', '%20')}"
        print(f"\nMembuka: {first_url}")
        try:
            page.goto(first_url, timeout=120000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"Warning: {e}")

        rdelay(5, 8)

        if is_blocked(safe_url(page)):
            print("Kena block! Selesaikan di browser lalu jalankan ulang.")
            producer.close()
            sys.exit(1)

        print(f"Session valid. Mulai streaming ke Kafka...\n")

        total_sent = 0
        total_failed = 0

        for pg_num in range(MAX_PAGES):

            print(f"\n{'='*40}")
            print(f"PAGE {pg_num + 1}/{MAX_PAGES}")
            print(f"{'='*40}")

            url = (
                f"https://shopee.co.id/search"
                f"?keyword={KEYWORD.replace(' ', '%20')}"
                f"&page={pg_num}"
            )

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

            # Ambil produk
            try:
                items = page.locator('div[role="group"][aria-label^="Product card:"]')
                count = items.count()
            except Exception as e:
                print(f"Gagal ambil items: {e}")
                continue

            print(f"Item ditemukan: {count}")

            if count == 0:
                print("Produk kosong, skip.")
                continue

            for i in range(count):
                try:
                    item = items.nth(i)

                    nama = None
                    harga_str = None
                    harga_num = 0.0
                    link = None
                    lokasi = None
                    rating = None

                    # Nama dari aria-label
                    try:
                        aria = item.get_attribute("aria-label") or ""
                        if aria.startswith("Product card:"):
                            nama = aria.replace("Product card:", "").strip()
                    except Exception:
                        pass

                    if not nama:
                        try:
                            nama = item.locator(
                                'div.line-clamp-2'
                            ).first.inner_text(timeout=3000)
                        except Exception:
                            pass

                    # Link
                    try:
                        href = item.locator("a.contents").first.get_attribute("href")
                        if not href:
                            href = item.locator("a").first.get_attribute("href")
                        if href:
                            link = "https://shopee.co.id" + href.split("?")[0] if href.startswith("/") else href.split("?")[0]
                    except Exception:
                        pass

                    shop_id, item_id = extract_ids(link)

                    # Harga
                    try:
                        spans = item.locator('span[class*="text-base"]')
                        for h in range(spans.count()):
                            txt = spans.nth(h).inner_text().strip()
                            if txt and any(c.isdigit() for c in txt):
                                harga_str = "Rp " + txt
                                harga_num = parse_harga(txt)
                                break
                    except Exception:
                        pass

                    # Lokasi
                    try:
                        lokasi = item.locator('span.ml-\\[3px\\]').first.inner_text(timeout=2000)
                    except Exception:
                        pass

                    # Rating
                    try:
                        for t in item.locator("div").all_inner_texts():
                            tx = t.strip()
                            if len(tx) <= 5 and (tx.startswith("4.") or tx.startswith("5.")):
                                rating = tx
                                break
                    except Exception:
                        pass

                    if not nama:
                        continue

                    # Susun dokumen
                    doc = {
                        "item_id":       item_id,
                        "shop_id":       shop_id,
                        "name":          nama[:500],
                        "price":         harga_num,
                        "price_raw":     harga_str,
                        "shop_location": lokasi,
                        "rating":        rating,
                        "link":          link,
                        "keyword":       KEYWORD,
                        "page":          pg_num + 1,
                        "scraped_at":    datetime.now(timezone.utc).isoformat(),
                        "scraped_date":  datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    }

                    # Kirim ke Kafka — inilah bedanya dari sebelumnya!
                    # Tidak perlu tunggu semua selesai, langsung publish
                    future = send_to_kafka(producer, doc)
                    total_sent += 1

                    print(
                        f"  [{total_sent}] SENT → Kafka | "
                        f"{nama[:45]} | {harga_str}"
                    )

                except Exception as e:
                    total_failed += 1
                    print(f"  Error item {i+1}: {e}")

            # Flush setiap halaman supaya tidak ada pesan tertahan
            producer.flush()
            print(f"\nHalaman {pg_num+1} selesai. Flushed ke Kafka.")

            rdelay(3, 6)

        # Final flush
        producer.flush()
        producer.close()

        print(f"\n{'='*40}")
        print("PRODUCER SELESAI")
        print(f"{'='*40}")
        print(f"Terkirim ke Kafka : {total_sent}")
        print(f"Gagal             : {total_failed}")
        print(f"Topic             : {KAFKA_TOPIC}")
        print(f"{'='*40}")

        if total_sent == 0:
            print("Tidak ada data yang terkirim!")
            sys.exit(1)


if __name__ == "__main__":
    main()