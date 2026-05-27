import time
from playwright.sync_api import sync_playwright

AUTH_FILE = r"D:\shopee_pipeline\dags\shopee_auth.json"
KEYWORD   = "msi gaming"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # buka visual dulu

    context = browser.new_context(
        storage_state=AUTH_FILE,
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="id-ID",
    )

    page = context.new_page()
    page.goto(
        f"https://shopee.co.id/search?keyword={KEYWORD.replace(' ', '%20')}&page=0",
        timeout=60000,
        wait_until="domcontentloaded"
    )
    time.sleep(6)

    # Cek berapa item ditemukan
    items = page.locator('div[data-sqe="item"]')
    print("Items ditemukan:", items.count())
    print("URL:", page.url)

    # Simpan screenshot
    page.screenshot(path="debug_check.png", full_page=True)
    print("Screenshot tersimpan: debug_check.png")

    time.sleep(3)
    browser.close()