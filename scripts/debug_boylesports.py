from playwright.sync_api import sync_playwright
import time, json
from pathlib import Path

d = json.loads(Path(r'C:\Users\joete\odds-board\ufc\data\boylesports_fight_urls.json').read_text())
url = d['fights'][0]['url']
print('Opening:', url)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={'width': 1365, 'height': 768})
    page.goto(url, timeout=60000, wait_until='domcontentloaded')
    time.sleep(5)
    input('Press Enter to close')
    browser.close()