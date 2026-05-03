from playwright.sync_api import sync_playwright
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "props.json"

FIGHT_URL = "https://www.paddypower.com/mixed-martial-arts/ufc-matches/khamzat-chimaev-v-sean-strickland-35369952"


def close_cookie_popup(page):
    try:
        page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
        print("Accepted cookies")
    except:
        print("No cookie popup found")


def open_market(page, name):
    page.evaluate(
        """
        (name) => {
          const nodes = [...document.querySelectorAll('span.accordion__title')];
          const node = nodes.find(n => n.textContent.trim() === name);
          if (node) {
            node.scrollIntoView({ block: 'center' });
            node.click();
          }
        }
        """,
        name,
    )
    print(f"Opened market: {name}")
    page.wait_for_timeout(2000)


def scrape_market(page, market_name):
    results = []

    try:
        section = page.locator(f"span.accordion__title:has-text('{market_name}')").locator("..").locator("..")

        selections = section.locator(".selection__title")
        odds = section.locator(".selection__price")

        count = selections.count()

        for i in range(count):
            sel = selections.nth(i).inner_text().strip()
            odd = odds.nth(i).inner_text().strip()

            results.append({
                "selection": sel,
                "odds": odd
            })

    except Exception as e:
        print(f"Error scraping {market_name}: {e}")

    return results


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1400, "height": 1200}
        )
        page = context.new_page()

        page.goto(FIGHT_URL, timeout=60000)
        page.wait_for_timeout(6000)

        close_cookie_popup(page)

        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(2000)

        markets = ["Method of Victory", "Total Rounds", "Go The Distance?"]

        for m in markets:
            open_market(page, m)

        page.wait_for_timeout(4000)

        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "paddypower",
            "bookmaker": "PaddyPower",
            "fight": "Khamzat Chimaev vs Sean Strickland",
            "url": FIGHT_URL,
            "markets": {
                "method_of_victory": scrape_market(page, "Method of Victory"),
                "total_rounds": scrape_market(page, "Total Rounds"),
                "go_the_distance": scrape_market(page, "Go The Distance?")
            }
        }

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(OUT_PATH, "w") as f:
            json.dump(data, f, indent=2)

        print("Saved props JSON")
        print(json.dumps(data, indent=2))

        browser.close()


if __name__ == "__main__":
    main()
