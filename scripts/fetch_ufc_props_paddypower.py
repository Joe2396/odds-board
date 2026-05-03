from playwright.sync_api import sync_playwright
import json
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "props.json"

FIGHT_URL = "https://www.paddypower.com/mixed-martial-arts/ufc-matches/khamzat-chimaev-v-sean-strickland-35369952"


def close_cookie_popup(page):
    try:
        page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
        print("Accepted cookies")
        time.sleep(1)
    except Exception:
        print("No cookie popup found")


def click_market(page, market_name):
    try:
        market = page.locator("span.accordion__title", has_text=market_name).first
        market.scroll_into_view_if_needed(timeout=5000)
        time.sleep(0.5)
        market.click(force=True, timeout=5000)
        print(f"Opened market: {market_name}")
        time.sleep(1)
    except Exception:
        print(f"Could not open market: {market_name}")


def get_snippet(page, market_name, stop_words):
    text = page.locator("body").inner_text()
    start = text.find(market_name)

    if start == -1:
        return ""

    end = start + 900

    for word in stop_words:
        idx = text.find(word, start + len(market_name))
        if idx != -1:
            end = min(end, idx)

    return text[start:end].strip()


def parse_pairs(snippet, skip_words=None):
    if skip_words is None:
        skip_words = []

    lines = [line.strip() for line in snippet.splitlines() if line.strip()]

    junk = [
        "All Markets",
        "Popular",
        "Fight Result",
        "Cash Out",
    ]

    cleaned = []
    for line in lines:
        if line in skip_words:
            continue
        if line in junk:
            continue
        cleaned.append(line)

    if cleaned:
        cleaned = cleaned[1:]

    results = []
    i = 0

    while i + 1 < len(cleaned):
        a = cleaned[i]
        b = cleaned[i + 1]

        if "/" in a or a == "EVS":
            odds = a
            selection = b
        else:
            selection = a
            odds = b

        results.append({
            "selection": selection,
            "odds": odds,
        })

        i += 2

    return results


def main():
    print("Starting PaddyPower props scraper...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        page.goto(FIGHT_URL, timeout=60000)
        time.sleep(4)

        close_cookie_popup(page)

        markets = [
            "Method of Victory",
            "Total Rounds",
            "Go The Distance?",
        ]

        for market in markets:
            click_market(page, market)

        time.sleep(2)

        method_snippet = get_snippet(
            page,
            "Method of Victory",
            stop_words=["Round Betting", "Total Rounds", "Go The Distance?"],
        )

        total_rounds_snippet = get_snippet(
            page,
            "Total Rounds",
            stop_words=["Double Chance", "Go The Distance?", "How fight will End"],
        )

        go_distance_snippet = get_snippet(
            page,
            "Go The Distance?",
            stop_words=["How fight will End", "What Round", "Show More"],
        )

        props = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "paddypower",
            "bookmaker": "PaddyPower",
            "fight": "Khamzat Chimaev vs Sean Strickland",
            "url": FIGHT_URL,
            "markets": {
                "method_of_victory": parse_pairs(method_snippet, ["Method of Victory"]),
                "total_rounds": parse_pairs(total_rounds_snippet, ["Total Rounds"]),
                "go_the_distance": parse_pairs(go_distance_snippet, ["Go The Distance?"]),
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
