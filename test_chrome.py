from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time

options = Options()

options.binary_location = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe"
)

service = Service(r"D:\drivers\chromedriver.exe")

driver = webdriver.Chrome(
    service=service,
    options=options
)

driver.get("https://google.com")

print(driver.title)

time.sleep(5)

driver.quit()