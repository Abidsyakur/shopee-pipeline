# scraper_server.py
# Flask server di laptop — menerima perintah dari Airflow DAG
# lalu menjalankan fetch_shopee_cdp.py
#
# Cara pakai:
#   1. Buka Chrome dengan CDP:
#      chrome.exe --remote-debugging-port=9222
#                 --user-data-dir="C:/Users/mohab/AppData/Local/Google/Chrome/User Data"
#   2. Buka shopee.co.id, pastikan sudah login
#   3. Jalankan server ini: python scraper_server.py
#   4. Biarkan terminal terbuka

import subprocess
import logging
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

SCRAPER_PATH = r"D:\shopee_pipeline\fetch_shopee_cdp.py"
PYTHON_PATH  = "python"
SECRET_KEY   = "shopee-pipeline-2025"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/run-scraper", methods=["POST"])
def run_scraper():
    key = request.headers.get("X-Secret-Key", "")
    if key != SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    logging.info("Menerima perintah scraping dari Airflow...")

    try:
        result = subprocess.run(
            [PYTHON_PATH, SCRAPER_PATH],
            capture_output=True,
            text=True,
            timeout=1800,
        )

        if result.returncode == 0:
            logging.info("Scraper selesai.")
            return jsonify({
                "status":  "success",
                "output":  result.stdout[-3000:],
            }), 200
        else:
            logging.error("Scraper gagal.")
            return jsonify({
                "status": "error",
                "output": result.stdout[-1000:],
                "error":  result.stderr[-1000:],
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "error": "Timeout 30 menit"}), 500
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    print("=" * 55)
    print("Scraper Server jalan di http://localhost:5000")
    print("Pastikan Chrome sudah dibuka dengan --remote-debugging-port=9222")
    print("Tekan Ctrl+C untuk stop.")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False)