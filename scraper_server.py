"""
scraper_server.py
Jalankan SEKALI di laptop dan biarkan berjalan terus.
Flask server ini menerima perintah dari Airflow DAG
lalu menjalankan script scraper Playwright.

Cara pakai:
  1. Buka terminal baru di laptop
  2. cd D:\shopee_pipeline
  3. python scraper_server.py
  4. Biarkan terminal ini terbuka
"""

import subprocess
import logging
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ─── CONFIG ──────────────────────────────────────
SCRAPER_PATH = r"D:\shopee_pipeline\fetch_shopee.py"
PYTHON_PATH  = "python"
SECRET_KEY   = "shopee-pipeline-2025"


@app.route("/health", methods=["GET"])
def health():
    """Airflow pakai ini untuk cek server masih hidup."""
    return jsonify({"status": "ok", "server": "scraper_server"}), 200


@app.route("/run-scraper", methods=["POST"])
def run_scraper():
    # Validasi secret key
    key = request.headers.get("X-Secret-Key", "")
    if key != SECRET_KEY:
        logging.warning("❌ Unauthorized request!")
        return jsonify({"error": "Unauthorized"}), 401

    logging.info("▶ Menerima perintah scraping dari Airflow...")

    try:
        result = subprocess.run(
            [PYTHON_PATH, SCRAPER_PATH],
            capture_output=True,
            text=True,
            timeout=1800,  # max 30 menit
        )

        if result.returncode == 0:
            logging.info("✅ Scraper selesai.")
            return jsonify({
                "status":      "success",
                "returncode":  result.returncode,
                "output":      result.stdout[-3000:],
            }), 200
        else:
            logging.error("❌ Scraper gagal.")
            return jsonify({
                "status":     "error",
                "returncode": result.returncode,
                "output":     result.stdout[-1000:],
                "error":      result.stderr[-1000:],
            }), 500

    except subprocess.TimeoutExpired:
        logging.error("❌ Scraper timeout!")
        return jsonify({"status": "error", "error": "Timeout 30 menit"}), 500
    except Exception as e:
        logging.error(f"❌ Error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    print("=" * 55)
    print("🚀 Scraper Server berjalan di http://localhost:5000")
    print("   Airflow akan otomatis trigger scraper lewat sini.")
    print("   Tekan Ctrl+C untuk stop.")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False)