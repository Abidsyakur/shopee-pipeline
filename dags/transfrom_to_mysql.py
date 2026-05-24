"""
transform_to_mysql.py
Baca data dari MongoDB → transform → load ke MySQL star schema.
Bisa dijalankan manual atau dipanggil oleh Airflow DAG.
"""

import re
import sys
from datetime import datetime, timezone
from pymongo import MongoClient
import mysql.connector
from mysql.connector import Error


# =====================================
# CONFIG
# =====================================

MONGO_URI  = "mongodb://mongouser:mongopassword@mongodb:27017"
MONGO_DB   = "shopee_raw"
MONGO_COLL = "products"

MYSQL_CONFIG = {
    "host":     "mysql",   # nama service di docker-compose
    "port":     3306,
    "user":     "dwuser",
    "password": "dwpassword",
    "database": "shopee_dw",
}


# =====================================
# KONEKSI
# =====================================

def get_mongo_collection():
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB][MONGO_COLL]


def get_mysql_conn():
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    print("✅ Terhubung ke MySQL")
    return conn


# =====================================
# DDL — buat tabel kalau belum ada
# =====================================

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS dim_product (
        product_id INT AUTO_INCREMENT PRIMARY KEY,
        item_id    VARCHAR(50),
        name       TEXT,
        keyword    VARCHAR(100),
        link       TEXT,
        UNIQUE KEY uq_item (item_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_shop (
        shop_id       INT AUTO_INCREMENT PRIMARY KEY,
        shop_ref_id   VARCHAR(50),
        shop_location VARCHAR(200),
        UNIQUE KEY uq_shop (shop_ref_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_date (
        date_id     INT AUTO_INCREMENT PRIMARY KEY,
        full_date   DATE NOT NULL,
        year        SMALLINT,
        month       TINYINT,
        day         TINYINT,
        day_of_week TINYINT,
        month_name  VARCHAR(20),
        UNIQUE KEY uq_date (full_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_category (
        category_id INT AUTO_INCREMENT PRIMARY KEY,
        keyword     VARCHAR(100),
        UNIQUE KEY uq_keyword (keyword)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_sales (
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
]


def create_tables(cursor):
    for ddl in DDL_STATEMENTS:
        cursor.execute(ddl)
    print("✅ Tabel siap.")


# =====================================
# UPSERT HELPERS
# =====================================

def upsert_and_get_id(cursor, insert_sql, select_sql, insert_params, select_params) -> int:
    cursor.execute(insert_sql, insert_params)
    row_id = cursor.lastrowid
    if row_id and row_id > 0:
        return row_id
    cursor.execute(select_sql, select_params)
    row = cursor.fetchone()
    if row:
        return row[0]
    raise ValueError(f"Gagal ambil ID: {select_params}")


def upsert_product(cursor, item_id, name, keyword, link) -> int:
    return upsert_and_get_id(
        cursor,
        """INSERT INTO dim_product (item_id, name, keyword, link)
           VALUES (%s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE name=VALUES(name), link=VALUES(link)""",
        "SELECT product_id FROM dim_product WHERE item_id = %s",
        (item_id, name, keyword, link), (item_id,),
    )


def upsert_shop(cursor, shop_ref_id, location) -> int:
    return upsert_and_get_id(
        cursor,
        """INSERT INTO dim_shop (shop_ref_id, shop_location)
           VALUES (%s, %s)
           ON DUPLICATE KEY UPDATE shop_location=VALUES(shop_location)""",
        "SELECT shop_id FROM dim_shop WHERE shop_ref_id = %s",
        (shop_ref_id, location), (shop_ref_id,),
    )


def upsert_date(cursor, dt: datetime) -> int:
    full_date   = dt.strftime("%Y-%m-%d")
    month_names = ["","January","February","March","April","May","June",
                   "July","August","September","October","November","December"]
    return upsert_and_get_id(
        cursor,
        """INSERT INTO dim_date (full_date, year, month, day, day_of_week, month_name)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE full_date=VALUES(full_date)""",
        "SELECT date_id FROM dim_date WHERE full_date = %s",
        (full_date, dt.year, dt.month, dt.day, dt.weekday(), month_names[dt.month]),
        (full_date,),
    )


def upsert_category(cursor, keyword) -> int:
    return upsert_and_get_id(
        cursor,
        """INSERT INTO dim_category (keyword) VALUES (%s)
           ON DUPLICATE KEY UPDATE keyword=VALUES(keyword)""",
        "SELECT category_id FROM dim_category WHERE keyword = %s",
        (keyword,), (keyword,),
    )


# =====================================
# TRANSFORM & LOAD
# =====================================

def clean_rating(rating_str) -> str:
    if not rating_str:
        return None
    match = re.search(r"[\d.]+", str(rating_str))
    return match.group() if match else None


def transform_and_load(mongo_coll, conn):
    cursor    = conn.cursor()
    documents = list(mongo_coll.find())
    print(f"📦 Dokumen MongoDB: {len(documents)}")

    inserted = skipped = errors = 0

    for i, doc in enumerate(documents):
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
                       (product_id, shop_id, date_id, category_id,
                        price, price_raw, rating, page, scraped_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                       price=VALUES(price), price_raw=VALUES(price_raw),
                       rating=VALUES(rating)""",
                (product_id, shop_id, date_id, category_id,
                 price, price_raw, rating, page,
                 dt.strftime("%Y-%m-%d %H:%M:%S")),
            )
            inserted += 1

            if (i + 1) % 50 == 0:
                conn.commit()
                print(f"   [{i+1}/{len(documents)}] committed...")

        except Error as e:
            errors += 1
            print(f"   ❌ MySQL error dok {i+1}: {e}")
            conn.rollback()
        except Exception as e:
            errors += 1
            print(f"   ❌ Error dok {i+1}: {e}")

    conn.commit()
    cursor.close()
    return inserted, skipped, errors


# =====================================
# MAIN
# =====================================

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 Transform MongoDB → MySQL Star Schema")
    print("=" * 50)

    mongo_coll = get_mongo_collection()
    conn       = get_mysql_conn()

    try:
        cursor = conn.cursor()
        create_tables(cursor)
        conn.commit()
        cursor.close()

        inserted, skipped, errors = transform_and_load(mongo_coll, conn)

        print(f"\n✅ Selesai: {inserted} inserted, {skipped} skipped, {errors} errors")

        # Verifikasi singkat
        cursor = conn.cursor()
        for tbl in ["dim_product", "dim_shop", "dim_date", "fact_sales"]:
            cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
            print(f"   {tbl:20s}: {cursor.fetchone()[0]} rows")
        cursor.close()

        # Exit code 1 kalau ada error supaya Airflow bisa deteksi
        if errors > inserted:
            sys.exit(1)

    finally:
        conn.close()
        print("🛑 Selesai.")