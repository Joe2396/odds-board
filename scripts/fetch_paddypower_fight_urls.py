from playwright.sync_api import sync_playwright
import json
import time
from pathlib import Path

print("FETCHING PADDYPOWER FIGHT URLS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "paddypower_fight_urls.json"

UFC_PAGE = "https://www.paddypower.com/mixed-martial-arts"

def close_cookie_popup(page):
    try:
        page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
        print("Accepted cookies")
        time.sleep(1)
    except:
        pass

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        page.goto(UFC_PAGE, timeout=60000)
        time.sleep(5)

        close_cookie_popup(page)

        print("Scrolling page to load fights...")
        for _ in range(5):
            page.mouse.wheel(0, 3000)
            time.sleep(1)

        links = page.locator("a[href*='/ufc-matches/']").all()

        fights = []
        seen = set()

        for link in links:
            try:
                url = link.get_attribute("href")
                name = link.inner_text().strip()

                if not url or not name:
                    continue

                if url.startswith("/"):
                    url = "https://www.paddypower.com" + url

                if url in seen:
                    continue

                seen.add(url)

                fights.append({
                    "fight": name,
                    "url": url
                })

            except:
                continue

        browser.close()

    print(f"Found {len(fights)} fights")

    output = {
        "fights": fights
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved to {OUT_PATH}")

if __name__ == "__main__":
    main()