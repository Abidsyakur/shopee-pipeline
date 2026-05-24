import json
import time
from datetime import datetime

import pandas as pd

from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


KEYWORD = "bisikan petersburg"


# ====================================
# CREATE DRIVER
# ====================================

def create_driver():

    print("🌐 Membuka Chrome...")

    options = Options()

    options.binary_location = (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    )

    options.add_argument("--start-maximized")

    service = Service(
        r"D:\drivers\chromedriver.exe"
    )

    driver = webdriver.Chrome(
        service=service,
        options=options
    )

    return driver


# ====================================
# OPEN SEARCH PAGE
# ====================================

def open_search_page(driver):

    url = (
        "https://shopee.co.id/search"
        f"?keyword={KEYWORD.replace(' ', '%20')}"
    )

    print(f"🌍 Membuka: {url}")

    driver.get(url)

    print("⏳ Tunggu render...")

    time.sleep(10)


# ====================================
# AUTO SCROLL
# ====================================

def auto_scroll(driver):

    print("🖱️ Auto scrolling...")

    for i in range(3):

        driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);"
        )

        print(f"   Scroll {i+1}/3")

        time.sleep(3)


# ====================================
# PARSE PRODUCTS
# ====================================

def parse_products(driver):

    print("🔍 Parsing HTML...")

    soup = BeautifulSoup(
        driver.page_source,
        "html.parser"
    )

    cards = soup.select(
        "div[data-sqe='item']"
    )

    print(f"📦 Total card ditemukan: {len(cards)}")

    products = []

    for card in cards:

        try:

            full_text = card.get_text(
                " ",
                strip=True
            )

            link = None

            link_el = card.select_one("a")

            if link_el:

                href = link_el.get("href")

                if href:

                    link = (
                        "https://shopee.co.id"
                        + href
                    )

            products.append({
                "text": full_text,
                "link": link,
                "keyword": KEYWORD,
                "scraped_at": (
                    datetime.utcnow().isoformat()
                )
            })

        except Exception as e:

            print(f"[ERROR PARSE] {e}")

    return products


# ====================================
# SAVE JSON
# ====================================

def save_json(products):

    filename = "shopee_products.json"

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            products,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"💾 JSON disimpan: {filename}")


# ====================================
# SAVE CSV
# ====================================

def save_csv(products):

    df = pd.DataFrame(products)

    filename = "shopee_products.csv"

    df.to_csv(
        filename,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"📊 CSV disimpan: {filename}")


# ====================================
# MAIN
# ====================================

if __name__ == "__main__":

    print("=" * 50)
    print("🚀 SHOPEE HTML SCRAPER")
    print("=" * 50)

    driver = create_driver()

    try:

        open_search_page(driver)

        auto_scroll(driver)

        products = parse_products(driver)

        print(
            f"\n✅ Total produk: "
            f"{len(products)}"
        )

        if products:

            print("\n📦 Sample:\n")

            for item in products[:3]:

                print(item)
                print()

            save_json(products)

            save_csv(products)

        else:

            print("❌ Produk kosong")

            with open(
                "debug_page.html",
                "w",
                encoding="utf-8"
            ) as f:

                f.write(driver.page_source)

            print(
                "💾 HTML debug disimpan "
                "ke debug_page.html"
            )

    finally:

        print("🛑 Menutup browser...")

        driver.quit()