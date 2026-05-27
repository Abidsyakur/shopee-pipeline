

import json
from datetime import datetime
from playwright.sync_api import sync_playwright

KEYWORD     = "msi gaming"
AUTH_FILE   = r"D:\shopee_pipeline\dags\shopee_auth.json"


with sync_playwright() as p:

    print("=" * 55)
    print("🔐 Shopee Session Exporter")
    print("=" * 55)
    print("⚠️  Pastikan semua window Chrome sudah ditutup!")
    print()

    browser = p.chromium.launch(
        headless=False,
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        args=[
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
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

    page = context.new_page()

    print("🌍 Membuka Shopee...")
    page.goto(
        f"https://shopee.co.id/search?keyword={KEYWORD.replace(' ', '%20')}",
        timeout=60000,
        wait_until="domcontentloaded"
    )

    print()
    print("=" * 55)
    print("📋 INSTRUKSI:")
    print("   1. Kalau muncul halaman login → login ke akun Shopee")
    print("   2. Kalau muncul captcha → selesaikan")
    print("   3. Kalau muncul 'Pilih bahasa' → pilih Bahasa Indonesia")
    print("   4. Tunggu sampai produk MSI Gaming muncul di halaman")
    print("   5. Kembali ke terminal ini dan tekan ENTER")
    print("=" * 55)

    input("\n➡ Tekan ENTER setelah produk sudah muncul di browser...")

    # Navigasi ke halaman search sekali lagi supaya cookies ter-set penuh
    print("\n🔄 Refresh untuk generate cookies lengkap...")
    try:
        page.goto(
            f"https://shopee.co.id/search?keyword={KEYWORD.replace(' ', '%20')}&page=0",
            timeout=60000,
            wait_until="domcontentloaded"
        )
        page.wait_for_timeout(3000)
    except Exception:
        pass

    # Export storage state (cookies + localStorage)
    context.storage_state(path=AUTH_FILE)

    # Verifikasi isi file
    with open(AUTH_FILE, "r") as f:
        auth_data = json.load(f)

    cookie_names = [c["name"] for c in auth_data.get("cookies", [])]
    has_login    = any(
        name in cookie_names
        for name in ["SPC_U", "SPC_EC", "SPC_ST", "SPC_F"]
    )

    print()
    print("=" * 55)
    if has_login:
        print("✅ Session berhasil di-export!")
        print(f"   File    : {AUTH_FILE}")
        print(f"   Cookies : {len(cookie_names)} cookies tersimpan")
        print(f"   Login   : {'✅ Terdeteksi' if has_login else '❌ Tidak terdeteksi'}")
        print(f"   Waktu   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        print("💡 Session biasanya tahan 3-7 hari.")
        print("   Jalankan script ini lagi kalau scraper mulai gagal.")
    else:
        print("⚠️  Session tersimpan tapi cookies login tidak terdeteksi.")
        print("   Kemungkinan belum login. Coba jalankan ulang.")
    print("=" * 55)

    browser.close()
    print("🛑 Browser ditutup.")