from playwright.sync_api import sync_playwright
import time

URLS = [
    "https://sports.williamhill.com/betting/en-gb/ufc/competitions/ufc-fight-night-fiziev-vs-torres/matches",
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/future/match-betting",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    for url in URLS:
        print(f"\n=== {url} ===")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(8)

        links = page.evaluate("""
            () => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                return [...new Set(anchors.map(a => a.href).filter(h => h.includes('/ufc/')))].slice(0, 30);
            }
        """)
        for l in links:
            print(" ", l)

    input("\nPress Enter to close...")
    browser.close()