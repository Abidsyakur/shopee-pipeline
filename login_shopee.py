from playwright.sync_api import sync_playwright
import time

PROFILE_PATH = r"D:\shopee_pipeline\playwright-profile"

with sync_playwright() as p:

    context = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_PATH,

        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",

        channel="chrome",

        headless=False,

        args=[
            "--profile-directory=Default",
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
        ],

        ignore_default_args=[
            "--enable-automation"
        ],

        viewport=None
    )

    page = context.pages[0]

    print("Membuka Shopee...")

    page.goto(
        "https://shopee.co.id/",
        wait_until="domcontentloaded",
        timeout=120000
    )

    time.sleep(5)

    print("URL:", page.url)

    input("ENTER untuk keluar...")

    context.close()