# Consumer 1: baca dari Kafka topic → simpan ke MongoDB
# Jalankan di terminal terpisah: python kafka_consumer_mongodb.py

import json
import signal
import sys
from datetime import datetime, timezone

from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError


# =====================================
# CONFIG
# =====================================

KAFKA_BROKER    = "localhost:9092"
KAFKA_TOPIC     = "shopee.products"
CONSUMER_GROUP  = "mongodb-consumer-group"

MONGO_URI  = "mongodb://mongouser:mongopassword@localhost:27017"
MONGO_DB   = "shopee_raw"
MONGO_COLL = "products"

BATCH_SIZE = 20  


# =====================================
# SETUP
# =====================================

def get_mongo_collection():
    client = MongoClient(MONGO_URI)
    coll   = client[MONGO_DB][MONGO_COLL]
    try:
        coll.create_index(
            [("item_id", 1), ("shop_id", 1), ("scraped_date", 1)],
            unique=True, sparse=True, name="unique_product_daily"
        )
    except Exception:
        pass
    print(f"Terhubung MongoDB: {MONGO_DB}.{MONGO_COLL}")
    return coll


def create_consumer():
    print(f"Konek ke Kafka: {KAFKA_BROKER}")
    try:
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BROKER,
            group_id=CONSUMER_GROUP,
            # Deserialize JSON bytes ke dict
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            key_deserializer=lambda k: k.decode("utf-8") if k else None,
            # Mulai dari awal kalau group baru
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            # Timeout untuk polling
            consumer_timeout_ms=5000,
        )
        print(f"Consumer group: {CONSUMER_GROUP}")
        print(f"Topic          : {KAFKA_TOPIC}")
        return consumer
    except NoBrokersAvailable:
        print(f"Kafka tidak bisa diakses di {KAFKA_BROKER}")
        sys.exit(1)


# =====================================
# SIMPAN KE MONGODB
# =====================================

def save_batch(collection, batch: list) -> dict:
    if not batch:
        return {"inserted": 0, "matched": 0}

    operations = []
    for doc in batch:
        filter_doc = {
            "item_id":      doc.get("item_id"),
            "shop_id":      doc.get("shop_id"),
            "scraped_date": doc.get("scraped_date"),
        }
        operations.append(UpdateOne(
            filter_doc,
            {"$set": doc},
            upsert=True
        ))

    try:
        result = collection.bulk_write(operations, ordered=False)
        return {
            "inserted": result.upserted_count,
            "matched":  result.matched_count
        }
    except BulkWriteError as bwe:
        print(f"BulkWriteError: {len(bwe.details.get('writeErrors', []))} errors")
        return {"inserted": 0, "matched": 0}


# =====================================
# MAIN LOOP
# =====================================

running = True

def handle_shutdown(sig, frame):
    global running
    print("\nShutdown signal diterima, menyelesaikan batch terakhir...")
    running = False

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def main():
    print("=" * 55)
    print("Consumer 1: Kafka → MongoDB")
    print("=" * 55)

    collection = get_mongo_collection()
    consumer   = create_consumer()

    print("\nMenunggu pesan dari Kafka...")
    print("Tekan Ctrl+C untuk stop.\n")

    batch         = []
    total_saved   = 0
    total_skipped = 0

    try:
        while running:
            # Poll pesan dari Kafka (timeout 1 detik)
            records = consumer.poll(timeout_ms=1000, max_records=50)

            for topic_partition, messages in records.items():
                for msg in messages:
                    doc = msg.value

                    # Skip kalau item_id atau shop_id kosong
                    if not doc.get("item_id") or not doc.get("shop_id"):
                        total_skipped += 1
                        continue

                    batch.append(doc)

                    # Flush kalau batch sudah penuh
                    if len(batch) >= BATCH_SIZE:
                        result = save_batch(collection, batch)
                        total_saved += result["inserted"] + result["matched"]
                        print(
                            f"[BATCH] Saved {len(batch)} docs | "
                            f"inserted={result['inserted']} "
                            f"updated={result['matched']} | "
                            f"total={total_saved}"
                        )
                        batch = []

            # Flush sisa batch yang belum penuh
            if batch and not running:
                result = save_batch(collection, batch)
                total_saved += result["inserted"] + result["matched"]
                print(f"[FINAL BATCH] Saved {len(batch)} docs")
                batch = []

    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Flush sisa batch
        if batch:
            result = save_batch(collection, batch)
            total_saved += result["inserted"] + result["matched"]
            print(f"[CLEANUP] Saved {len(batch)} remaining docs")

        consumer.close()
        print(f"\n{'='*40}")
        print("CONSUMER MONGODB STOPPED")
        print(f"{'='*40}")
        print(f"Total saved   : {total_saved}")
        print(f"Total skipped : {total_skipped}")


if __name__ == "__main__":
    main()