"""
DAG: shopee_pipeline
Jadwal: setiap hari jam 08:00 WIB (01:00 UTC)

Alur:
  1. trigger_scraper   → HTTP ke Flask server di laptop
                         → jalankan fetch_shopee.py (Playwright)
                         → data masuk MongoDB
  2. verify_mongodb    → cek data hari ini sudah ada di MongoDB
  3. transform_mysql   → jalankan transform_to_mysql.py
                         → MongoDB → MySQL star schema
  4. notify_done       → log ringkasan akhir
"""

from datetime import datetime, timedelta
import logging
import subprocess

import requests as http_requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from pymongo import MongoClient


# ─── CONFIG ──────────────────────────────────────────────────
# host.docker.internal = IP laptop dari dalam Docker
SCRAPER_URL    = "http://host.docker.internal:5000/run-scraper"
SECRET_KEY     = "shopee-pipeline-2025"

MONGO_URI      = "mongodb://mongouser:mongopassword@mongodb:27017"
MONGO_DB       = "shopee_raw"
MONGO_COLL     = "products"
KEYWORD        = "msi gaming"

TRANSFORM_SCRIPT = "/opt/airflow/dags/transform_to_mysql.py"

default_args = {
    "owner":            "shopee-pipeline",
    "retries":          1,
    "retry_delay":      timedelta(minutes=5),
    "email_on_failure": False,
}


# ════════════════════════════════════════════════════════════
# TASK 1 — Trigger scraper di laptop via HTTP
# ════════════════════════════════════════════════════════════
def trigger_scraper(**context):
    logging.info("▶ Task 1: Trigger scraper Shopee...")

    # Cek dulu server masih hidup
    try:
        health = http_requests.get(
            "http://host.docker.internal:5000/health",
            timeout=5
        )
        logging.info(f"   Server health: {health.json()}")
    except Exception as e:
        raise Exception(
            f"Scraper server tidak bisa diakses: {e}\n"
            f"Pastikan scraper_server.py sudah dijalankan di laptop!"
        )

    # Trigger scraping
    logging.info(f"   Mengirim request ke {SCRAPER_URL}...")
    try:
        response = http_requests.post(
            SCRAPER_URL,
            headers={"X-Secret-Key": SECRET_KEY},
            timeout=1800,  # tunggu max 30 menit
        )
        data = response.json()

        if response.status_code == 200:
            logging.info("✅ Scraper berhasil!")
            logging.info("OUTPUT:\n" + data.get("output", "")[-2000:])
        else:
            raise Exception(
                f"Scraper gagal (HTTP {response.status_code}): "
                f"{data.get('error', 'Unknown')}"
            )

    except http_requests.exceptions.Timeout:
        raise Exception("Scraper timeout setelah 30 menit.")


# ════════════════════════════════════════════════════════════
# TASK 2 — Verifikasi data masuk MongoDB
# ════════════════════════════════════════════════════════════
def verify_mongodb(**context):
    logging.info("▶ Task 2: Verifikasi MongoDB...")

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    coll   = client[MONGO_DB][MONGO_COLL]

    today = datetime.utcnow().strftime("%Y-%m-%d")
    count = coll.count_documents({"scraped_date": today, "keyword": KEYWORD})
    total = coll.count_documents({})

    logging.info(f"   Tanggal      : {today}")
    logging.info(f"   Keyword      : {KEYWORD}")
    logging.info(f"   Dokumen baru : {count}")
    logging.info(f"   Total DB     : {total}")

    client.close()

    if count == 0:
        raise ValueError(
            f"Tidak ada data baru untuk '{KEYWORD}' pada {today}. "
            f"Cek output scraper di Task 1."
        )

    # Simpan ke XCom untuk dipakai task berikutnya
    context["ti"].xcom_push(key="scraped_count", value=count)
    logging.info(f"✅ MongoDB OK: {count} dokumen baru.")


# ════════════════════════════════════════════════════════════
# TASK 3 — Transform MongoDB → MySQL Star Schema
# ════════════════════════════════════════════════════════════
def transform_to_mysql(**context):
    logging.info("▶ Task 3: Transform MongoDB → MySQL...")
    logging.info(f"   Script: {TRANSFORM_SCRIPT}")

    result = subprocess.run(
        ["python", TRANSFORM_SCRIPT],
        capture_output=True,
        text=True,
        timeout=600,  # max 10 menit
    )

    if result.stdout:
        logging.info("OUTPUT:\n" + result.stdout)
    if result.stderr:
        logging.warning("STDERR:\n" + result.stderr[-500:])

    if result.returncode != 0:
        raise Exception(
            f"Transform gagal (exit code {result.returncode})\n"
            f"Error: {result.stderr[-500:]}"
        )

    logging.info("✅ Transform selesai.")


# ════════════════════════════════════════════════════════════
# TASK 4 — Log ringkasan akhir
# ════════════════════════════════════════════════════════════
def notify_done(**context):
    ti            = context["ti"]
    scraped_count = ti.xcom_pull(task_ids="verify_mongodb", key="scraped_count")
    today         = datetime.utcnow().strftime("%Y-%m-%d")

    logging.info("=" * 55)
    logging.info("✅ PIPELINE SHOPEE SELESAI")
    logging.info("=" * 55)
    logging.info(f"   Tanggal    : {today}")
    logging.info(f"   Keyword    : {KEYWORD}")
    logging.info(f"   MongoDB    : {scraped_count} dokumen baru")
    logging.info(f"   MySQL DW   : fact_sales updated")
    logging.info(f"   Pipeline   : shopee → mongodb → mysql star schema")
    logging.info("=" * 55)


# ════════════════════════════════════════════════════════════
# DEFINISI DAG
# ════════════════════════════════════════════════════════════
with DAG(
    dag_id="shopee_pipeline",
    default_args=default_args,
    description="Scrape Shopee → MongoDB → MySQL Data Warehouse",
    schedule_interval="0 1 * * *",  # 01:00 UTC = 08:00 WIB setiap hari
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["shopee", "mongodb", "mysql", "data-warehouse"],
) as dag:

    t1 = PythonOperator(
        task_id="trigger_scraper",
        python_callable=trigger_scraper,
    )

    t2 = PythonOperator(
        task_id="verify_mongodb",
        python_callable=verify_mongodb,
    )

    t3 = PythonOperator(
        task_id="transform_mysql",
        python_callable=transform_to_mysql,
    )

    t4 = PythonOperator(
        task_id="notify_done",
        python_callable=notify_done,
    )

    # Urutan eksekusi
    t1 >> t2 >> t3 >> t4