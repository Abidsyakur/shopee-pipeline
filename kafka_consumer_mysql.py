import json
import re
import signal
import sys
from datetime import datetime, timezone

from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
import mysql.connector
from mysql.connector import Error


# =====================================
# CONFIG
# =====================================

KAFKA_BROKER   = "localhost:9092"
KAFKA_TOPIC    = "shopee.products"
CONSUMER_GROUP = "mysql-consumer-group"

MYSQL_CONFIG = {
    "host":     "localhost",
    "port":     3306,
    "user":     "dwuser",
    "password": "dwpassword",
    "database": "shopee_dw",
}

BATCH_SIZE = 20


# =====================================
# MYSQL SETUP
# =====================================

def get_mysql_conn():
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    print("Terhubung ke MySQL")
    return conn


def create_tables(cursor):
    ddls = [
        """CREATE TABLE IF NOT EXISTS dim_product (
            product_id INT AUTO_INCREMENT PRIMARY KEY,
            item_id    VARCHAR(50),
            name       TEXT,
            keyword    VARCHAR(100),
            link       TEXT,
            UNIQUE KEY uq_item (item_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

        """CREATE TABLE IF NOT EXISTS dim_shop (
            shop_id       INT AUTO_INCREMENT PRIMARY KEY,
            shop_ref_id   VARCHAR(50),
            shop_location VARCHAR(200),
            UNIQUE KEY uq_shop (shop_ref_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

        """CREATE TABLE IF NOT EXISTS dim_date (
            date_id     INT AUTO_INCREMENT PRIMARY KEY,
            full_date   DATE NOT NULL,
            year        SMALLINT,
            month       TINYINT,
            day         TINYINT,
            day_of_week TINYINT,
            month_name  VARCHAR(20),
            UNIQUE KEY uq_date (full_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

        """CREATE TABLE IF NOT EXISTS dim_category (
            category_id INT AUTO_INCREMENT PRIMARY KEY,
            keyword     VARCHAR(100),
            UNIQUE KEY uq_keyword (keyword)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

        """CREATE TABLE IF NOT EXISTS fact_sales (
            fact_id     INT AUTO_INCREMENT PRIMARY KEY,
            product_id  INT NOT NULL,
            shop_id     INT NOT NULL,
            date_id     INT NOT NULL,
            category_id INT NOT NULL,
            price       DECIMAL(15,2) DEFAULT 0,
            price_raw   VARCHAR(100),
            rating      VARCHAR(20),
            page        TINYINT,
            scraped_at  DATETIME,
            FOREIGN KEY (product_id)  REFERENCES dim_product(product_id),
            FOREIGN KEY (shop_id)     REFERENCES dim_shop(shop_id),
            FOREIGN KEY (date_id)     REFERENCES dim_date(date_id),
            FOREIGN KEY (category_id) REFERENCES dim_category(category_id),
            UNIQUE KEY uq_fact (product_id, shop_id, date_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    ]
    for ddl in ddls:
        cursor.execute(ddl)
    print("Tabel siap.")


# =====================================
# UPSERT HELPERS
# =====================================

def upsert_and_get_id(cursor, insert_sql, select_sql, insert_params, select_params):
    cursor.execute(insert_sql, insert_params)
    row_id = cursor.lastrowid
    if row_id and row_id > 0:
        return row_id
    cursor.execute(select_sql, select_params)
    row = cursor.fetchone()
    if row:
        return row[0]
    raise ValueError(f"Gagal ambil ID: {select_params}")


def upsert_product(cursor, item_id, name, keyword, link):
    return upsert_and_get_id(
        cursor,
        """INSERT INTO dim_product (item_id, name, keyword, link)
           VALUES (%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE name=VALUES(name), link=VALUES(link)""",
        "SELECT product_id FROM dim_product WHERE item_id=%s",
        (item_id, name, keyword, link), (item_id,)
    )


def upsert_shop(cursor, shop_ref_id, location):
    return upsert_and_get_id(
        cursor,
        """INSERT INTO dim_shop (shop_ref_id, shop_location)
           VALUES (%s,%s)
           ON DUPLICATE KEY UPDATE shop_location=VALUES(shop_location)""",
        "SELECT shop_id FROM dim_shop WHERE shop_ref_id=%s",
        (shop_ref_id, location), (shop_ref_id,)
    )


def upsert_date(cursor, dt):
    full_date   = dt.strftime("%Y-%m-%d")
    month_names = ["","January","February","March","April","May","June",
                   "July","August","September","October","November","December"]
    return upsert_and_get_id(
        cursor,
        """INSERT INTO dim_date (full_date,year,month,day,day_of_week,month_name)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE full_date=VALUES(full_date)""",
        "SELECT date_id FROM dim_date WHERE full_date=%s",
        (full_date, dt.year, dt.month, dt.day, dt.weekday(), month_names[dt.month]),
        (full_date,)
    )


def upsert_category(cursor, keyword):
    return upsert_and_get_id(
        cursor,
        """INSERT INTO dim_category (keyword) VALUES (%s)
           ON DUPLICATE KEY UPDATE keyword=VALUES(keyword)""",
        "SELECT category_id FROM dim_category WHERE keyword=%s",
        (keyword,), (keyword,)
    )


def clean_rating(r):
    if not r:
        return None
    m = re.search(r"[\d.]+", str(r))
    return m.group() if m else None


# =====================================
# PROSES SATU BATCH
# =====================================

def process_batch(conn, batch):
    cursor   = conn.cursor()
    inserted = skipped = errors = 0

    for doc in batch:
        try:
            item_id     = doc.get("item_id")
            shop_ref_id = doc.get("shop_id")

            if not item_id or not shop_ref_id:
                skipped += 1
                continue

            name       = (doc.get("name", "") or "")[:500]
            keyword    = doc.get("keyword", "msi gaming") or "msi gaming"
            link       = doc.get("link", "") or ""
            location   = doc.get("shop_location", "") or ""
            price      = float(doc.get("price", 0) or 0)
            price_raw  = doc.get("price_raw", "") or ""
            rating     = clean_rating(doc.get("rating"))
            page       = int(doc.get("page", 1) or 1)
            scraped_at = doc.get("scraped_at", "") or ""

            try:
                dt = datetime.fromisoformat(
                    scraped_at.replace("Z", "+00:00")
                ) if scraped_at else datetime.now(timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)

            product_id  = upsert_product(cursor, item_id, name, keyword, link)
            shop_id     = upsert_shop(cursor, shop_ref_id, location)
            date_id     = upsert_date(cursor, dt)
            category_id = upsert_category(cursor, keyword)

            cursor.execute(
                """INSERT INTO fact_sales
                       (product_id,shop_id,date_id,category_id,
                        price,price_raw,rating,page,scraped_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                       price=VALUES(price),
                       price_raw=VALUES(price_raw),
                       rating=VALUES(rating)""",
                (product_id, shop_id, date_id, category_id,
                 price, price_raw, rating, page,
                 dt.strftime("%Y-%m-%d %H:%M:%S"))
            )
            inserted += 1

        except Error as e:
            errors += 1
            conn.rollback()
            print(f"  MySQL Error: {e}")
        except Exception as e:
            errors += 1
            print(f"  Error: {e}")

    conn.commit()
    cursor.close()
    return inserted, skipped, errors


# =====================================
# KAFKA CONSUMER SETUP
# =====================================

def create_consumer():
    print(f"Konek ke Kafka: {KAFKA_BROKER}")
    try:
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BROKER,
            group_id=CONSUMER_GROUP,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            key_deserializer=lambda k: k.decode("utf-8") if k else None,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
        )
        print(f"Consumer group: {CONSUMER_GROUP}")
        print(f"Topic          : {KAFKA_TOPIC}")
        return consumer
    except NoBrokersAvailable:
        print(f"Kafka tidak bisa diakses di {KAFKA_BROKER}")
        sys.exit(1)


# =====================================
# MAIN LOOP
# =====================================

running = True

def handle_shutdown(sig, frame):
    global running
    print("\nShutdown signal, menyelesaikan batch terakhir...")
    running = False

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def main():
    print("=" * 55)
    print("Consumer 2: Kafka → MySQL Star Schema")
    print("=" * 55)

    conn     = get_mysql_conn()
    cursor   = conn.cursor()
    create_tables(cursor)
    conn.commit()
    cursor.close()

    consumer = create_consumer()

    print("\nMenunggu pesan dari Kafka...")
    print("Tekan Ctrl+C untuk stop.\n")

    batch         = []
    total_inserted = 0
    total_skipped  = 0
    total_errors   = 0

    try:
        while running:
            records = consumer.poll(timeout_ms=1000, max_records=50)

            for topic_partition, messages in records.items():
                for msg in messages:
                    batch.append(msg.value)

                    if len(batch) >= BATCH_SIZE:
                        ins, skip, err = process_batch(conn, batch)
                        total_inserted += ins
                        total_skipped  += skip
                        total_errors   += err
                        print(
                            f"[BATCH] {len(batch)} docs → "
                            f"inserted={ins} skipped={skip} errors={err} | "
                            f"total={total_inserted}"
                        )
                        batch = []

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if batch:
            ins, skip, err = process_batch(conn, batch)
            total_inserted += ins
            print(f"[CLEANUP] {len(batch)} remaining docs saved")

        consumer.close()
        conn.close()

        print(f"\n{'='*40}")
        print("CONSUMER MYSQL STOPPED")
        print(f"{'='*40}")
        print(f"Total inserted : {total_inserted}")
        print(f"Total skipped  : {total_skipped}")
        print(f"Total errors   : {total_errors}")


if __name__ == "__main__":
    main()