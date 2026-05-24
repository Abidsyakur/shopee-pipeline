import time
import pandas as pd

from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options


# =====================================
# CONFIG
# =====================================

KEYWORD = "msi gaming"

SEARCH_URL = (
    "https://shopee.co.id/search"
    f"?keyword={KEYWORD.replace(' ', '%20')}"
)


# =====================================
# CHROME OPTIONS
# =====================================

options = Options()

# chrome asli
options.binary_location = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe"
)

# profile KHUSUS selenium
options.add_argument(
    r'--user-data-dir=D:\selenium_profile'
)

# penting
options.add_argument("--remote-debugging-port=9222")

# anti crash
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

# jangan headless
options.add_argument("--start-maximized")

# optional anti detection
options.add_argument(
    "--disable-blink-features=AutomationControlled"
)

options.add_experimental_option(
    "excludeSwitches",
    ["enable-automation"]
)

options.add_experimental_option(
    "useAutomationExtension",
    False
)




# =====================================
# DRIVER
# =====================================

print("🌐 Membuka Chrome...")

driver = webdriver.Chrome(
    service=Service("chromedriver.exe"),
    options=options
)


# =====================================
# OPEN SEARCH
# =====================================

print("🌍 Membuka Shopee...")

driver.get(SEARCH_URL)

print("⏳ Tunggu render...")

time.sleep(15)


# =====================================
# AUTO SCROLL
# =====================================

for i in range(1, 8):

    scroll_y = i * 1500

    driver.execute_script(
        f"window.scrollTo(0, {scroll_y})"
    )

    print(f"loading ke-{i}")

    time.sleep(2)


# =====================================
# HTML
# =====================================

content = driver.page_source

with open(
    "debug_shopee.html",
    "w",
    encoding="utf-8"
) as f:

    f.write(content)

print("💾 HTML disimpan")


# =====================================
# CLOSE
# =====================================

driver.quit()


# =====================================
# PARSE
# =====================================

print("🔍 Parsing HTML...")

soup = BeautifulSoup(
    content,
    "html.parser"
)

cards = soup.find_all(
    "div",
    attrs={"data-sqe": "item"}
)

print(f"📦 Total card: {len(cards)}")


# =====================================
# STORAGE
# =====================================

rows = []


# =====================================
# LOOP
# =====================================

for i, card in enumerate(cards, start=1):

    try:

        text = card.get_text(
            " ",
            strip=True
        )

        nama = text[:150]

        harga = None

        for span in card.find_all("span"):

            txt = span.get_text(strip=True)

            if "Rp" in txt:

                harga = txt
                break

        link = None

        a = card.find("a")

        if a and a.get("href"):

            link = (
                "https://shopee.co.id"
                + a.get("href")
            )

        rows.append({
            "nama": nama,
            "harga": harga,
            "link": link
        })

        print(f"✅ produk {i}")

    except Exception as e:

        print("❌ error:", e)


# =====================================
# DATAFRAME
# =====================================

df = pd.DataFrame(rows)

df.to_excel(
    "shopee_result.xlsx",
    index=False
)

print("\n✅ File berhasil disimpan")
print(df.head())