from playwright.sync_api import sync_playwright
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "props.json"

FIGHT_URL = "https://www.paddypower.com/mixed-martial-arts/ufc-matches/khamzat-chimaev-v-sean-strickland-35369952"


def close_cookie_popup(page):
    try:
        page.locator("#onetrust-accept-btn-handler").click(timeout=3000, force=True)
        print("Accepted cookies")
    except Exception:
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
    page.wait_for_timeout(2500)


def scrape_market(page, market_name):
    results = []

    try:
        page.evaluate(
            """
            (name) => {
              const nodes = [...document.querySelectorAll('span.accordion__title')];
              const node = nodes.find(n => n.textContent.trim() === name);
              if (node) node.scrollIntoView({ block: 'center' });
            }
            """,
            market_name,
        )

        page.wait_for_timeout(2000)

        selections = page.locator(".selection__title")
        odds = page.locator(".selection__price")

        count = selections.count()

        print(f"{market_name}: found {count} visible selections")

        for i in range(count):
            try:
                sel = selections.nth(i).inner_text().strip()
                odd = odds.nth(i).inner_text().strip()

                if sel and odd and len(sel) < 80:
                    results.append({
                        "selection": sel,
                        "odds": odd
                    })
            except Exception:
                continue

    except Exception as e:
        print(f"Error scraping {market_name}: {e}")

    return results


def main():
    print("Starting PaddyPower props scraper...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1400, "height": 1400},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        page.goto(FIGHT_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)

        close_cookie_popup(page)

        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1500)

        markets = [
            "Method of Victory",
            "Total Rounds",
            "Go The Distance?",
        ]

        for market in markets:
            open_market(page, market)

        page.wait_for_timeout(5000)

        props = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "paddypower",
            "bookmaker": "PaddyPower",
            "fight": "Khamzat Chimaev vs Sean Strickland",
            "url": FIGHT_URL,
            "markets": {
                "method_of_victory": scrape_market(page, "Method of Victory"),
                "total_rounds": scrape_market(page, "Total Rounds"),
                "go_the_distance": scrape_market(page, "Go The Distance?"),
            },
        }

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(props, f, indent=2, ensure_ascii=False)

        print("Saved props JSON")
        print(json.dumps(props, indent=2, ensure_ascii=False))

        browser.close()


if __name__ == "__main__":
    main()
