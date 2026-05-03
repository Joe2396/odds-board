from playwright.sync_api import sync_playwright
import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "props.json"

FIGHT_URL = "https://www.paddypower.com/mixed-martial-arts/ufc-matches/khamzat-chimaev-v-sean-strickland-35369952"


def is_odds(value):
    value = str(value).strip()
    return value == "EVS" or bool(re.match(r"^\d+/\d+$", value))


def close_cookie_popup(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept')",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=2500, force=True)
            print("Accepted cookies")
            page.wait_for_timeout(1000)
            return
        except Exception:
            pass

    print("No cookie popup found")


def open_market(page, market_name):
    try:
        page.evaluate(
            """
            (name) => {
              const nodes = [...document.querySelectorAll('span.accordion__title')];
              const node = nodes.find(n => n.textContent.trim() === name);
              if (node) node.click();
            }
            """,
            market_name,
        )

        print(f"Clicked market: {market_name}")

        page.wait_for_timeout(2500)
        page.wait_for_selector("span", timeout=5000)

    except Exception as e:
        print(f"Could not open market {market_name}: {e}")


def get_text(page):
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


def get_section(text, start_word, stop_words):
    start = text.find(start_word)
    if start == -1:
        return ""

    end = start + 1600

    for word in stop_words:
        idx = text.find(word, start + len(start_word))
        if idx != -1:
            end = min(end, idx)

    return text[start:end].strip()


def parse_pairs(snippet, title):
    if not snippet:
        return []

    junk = {
        title,
        "All Markets",
        "Popular",
        "Fight Result",
        "Cash Out",
        "Show More",
    }

    lines = [line.strip() for line in snippet.splitlines() if line.strip()]
    lines = [line for line in lines if line not in junk]

    results = []
    i = 0

    while i + 1 < len(lines):
        a = lines[i]
        b = lines[i + 1]

        if is_odds(a) and not is_odds(b):
            results.append({"selection": b, "odds": a})
            i += 2
        elif not is_odds(a) and is_odds(b):
            results.append({"selection": a, "odds": b})
            i += 2
        else:
            i += 1

    return results


def main():
    print("Starting PaddyPower props scraper...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        page = browser.new_page(
            viewport={"width": 1400, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        page.goto(FIGHT_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(7000)

        close_cookie_popup(page)

        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1000)

        for market in ["Method of Victory", "Total Rounds", "Go The Distance?"]:
            open_market(page, market)

        page.wait_for_timeout(4000)

        text = get_text(page)

        method_snippet = get_section(
            text,
            "Method of Victory",
            ["Round Betting", "Method & Round Combo", "Total Rounds"],
        )

        total_rounds_snippet = get_section(
            text,
            "Total Rounds",
            ["Double Chance", "Go The Distance?", "How fight will End"],
        )

        go_distance_snippet = get_section(
            text,
            "Go The Distance?",
            ["How fight will End", "What Round", "Show More"],
        )

        props = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "paddypower",
            "bookmaker": "PaddyPower",
            "fight": "Khamzat Chimaev vs Sean Strickland",
            "url": FIGHT_URL,
            "markets": {
                "method_of_victory": parse_pairs(method_snippet, "Method of Victory"),
                "total_rounds": parse_pairs(total_rounds_snippet, "Total Rounds"),
                "go_the_distance": parse_pairs(go_distance_snippet, "Go The Distance?"),
            },
        }

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(props, f, indent=2, ensure_ascii=False)

        print(f"Saved props to {OUT_PATH}")
        print(json.dumps(props, indent=2, ensure_ascii=False))

        browser.close()


if __name__ == "__main__":
    main()
