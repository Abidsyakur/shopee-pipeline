"""
Jalankan di laptop untuk export cookies lengkap dari Chrome.
Chrome harus sudah login ke Shopee sebelum menjalankan script ini.

Cara pakai:
  1. Buka Chrome, login ke shopee.co.id
  2. Jalankan: python export_cookies.py
  3. Browser akan terbuka, tunggu halaman load
  4. Tekan ENTER
  5. File shopee_cookies.json akan terbentuk
  6. Copy file tersebut ke D:\shopee_pipeline\dags\
"""

import json
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "./shopee_cookies.json"
KEYWORD     = "msi gaming"

with sync_playwright() as p:

    print("🌐 Membuka Chrome yang sudah login...")

    # Pakai Chrome yang terinstall di laptop (bukan Chromium)
    browser = p.chromium.launch(
        headless=False,
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        args=["--start-maximized"]
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

    print("\n" + "=" * 50)
    print("🔐 Kalau belum login, login dulu sekarang.")
    print("   Tunggu sampai produk muncul di halaman.")
    print("=" * 50)
    input("\n➡ Tekan ENTER setelah produk sudah muncul...")

    # Navigasi ke beberapa halaman supaya Shopee set lebih banyak cookies
    print("🔄 Navigasi untuk generate lebih banyak cookies...")
    page.goto(
        f"https://shopee.co.id/search?keyword={KEYWORD.replace(' ', '%20')}&page=0",
        timeout=60000,
        wait_until="domcontentloaded"
    )
    page.wait_for_timeout(3000)

    # Export SEMUA cookies (termasuk HttpOnly)
    all_cookies = context.cookies()

    # Konversi ke format yang bisa dipakai Playwright di Docker
    output_cookies = []
    for c in all_cookies:
        cookie = {
            "name":   c["name"],
            "value":  c["value"],
            "domain": c["domain"],
            "path":   c["path"],
        }
        if c.get("secure"):
            cookie["secure"] = c["secure"]
        if c.get("httpOnly"):
            cookie["httpOnly"] = c["httpOnly"]
        if c.get("sameSite") in ("Strict", "Lax", "None"):
            cookie["sameSite"] = c["sameSite"]
        output_cookies.append(cookie)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_cookies, f, indent=2, ensure_ascii=False)

    print(f"\n✅ {len(output_cookies)} cookies tersimpan ke {OUTPUT_FILE}")
    print(f"   Sekarang copy file ini ke D:\\shopee_pipeline\\dags\\")

    browser.close()
    print("🛑 Selesai!")