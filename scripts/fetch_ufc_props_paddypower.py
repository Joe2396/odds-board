from playwright.sync_api import sync_playwright
import time
import json
import re
import os
from pathlib import Path
from datetime import datetime, timezone

print("RUNNING SAFE MULTI-FIGHT PADDYPOWER SCRIPT")

ROOT = Path(__file__).resolve().parents[1]
URLS_PATH = ROOT / "ufc" / "data" / "paddypower_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "props.json"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def is_odds(x):
    x = str(x).strip()
    return x == "EVS" or bool(re.match(r"^\d+/\d+$", x))


def load_existing_output():
    if OUT_PATH.exists():
        try:
            return json.load(open(OUT_PATH, encoding="utf-8"))
        except Exception:
            pass

    return {
        "updated_at": None,
        "source": "paddypower",
        "bookmaker": "PaddyPower",
        "markets_scraped": [
            "method_of_victory",
            "total_rounds",
            "go_the_distance"
        ],
        "fights": []
    }


def save_output(output):
    output["updated_at"] = datetime.now(timezone.utc).isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved progress to {OUT_PATH}")


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


def get_market_snippet(page, market_name, stop_words=None):
    if stop_words is None:
        stop_words = []

    text = page.locator("body").inner_text()
    start = text.find(market_name)

    if start == -1:
        return ""

    end = start + 1200

    for word in stop_words:
        idx = text.find(word, start + len(market_name))
        if idx != -1:
            end = min(end, idx)

    return text[start:end].strip()


def clean_lines(snippet):
    junk = {
        "Popular",
        "Fight Result",
        "Cash Out",
        "All Markets",
        "Method of Victory",
        "Total Rounds",
        "Go The Distance?",
        "Round & Minute",
        "UFC Matches",
    }

    return [
        line.strip()
        for line in snippet.splitlines()
        if line.strip() and line.strip() not in junk
    ]


def parse_method_of_victory(snippet):
    lines = clean_lines(snippet)
    results = []

    for i in range(len(lines) - 1):
        selection = lines[i]
        odds = lines[i + 1]

        if is_odds(odds) and (
            " by " in selection
            or "Draw" in selection
            or "KO/TKO" in selection
            or "Submission" in selection
            or "Dec" in selection
            or "Points" in selection
        ):
            results.append({
                "selection": selection,
                "odds": odds
            })

    return results


def parse_simple_pairs(snippet):
    lines = clean_lines(snippet)
    results = []

    for i in range(len(lines) - 1):
        selection = lines[i]
        odds = lines[i + 1]

        if not is_odds(selection) and is_odds(odds):
            results.append({
                "selection": selection,
                "odds": odds
            })

    return results


def scrape_fight(page, fight):
    fight_name = fight["fight"]
    fight_url = fight["url"]

    print("\n==============================")
    print(f"Scraping: {fight_name}")
    print("==============================")

    page.goto(fight_url, timeout=60000)
    time.sleep(4)

    close_cookie_popup(page)

    for market in [
        "Method of Victory",
        "Total Rounds",
        "Go The Distance?",
    ]:
        click_market(page, market)

    time.sleep(2)

    method_raw = get_market_snippet(
        page,
        "Method of Victory",
        stop_words=["Round Betting", "Total Rounds", "Go The Distance?"],
    )

    total_rounds_raw = get_market_snippet(
        page,
        "Total Rounds",
        stop_words=["Double Chance", "Go The Distance?", "How fight will End"],
    )

    go_distance_raw = get_market_snippet(
        page,
        "Go The Distance?",
        stop_words=["How fight will End", "What Round", "Show More"],
    )

    method = parse_method_of_victory(method_raw)
    total_rounds = parse_simple_pairs(total_rounds_raw)
    go_distance = parse_simple_pairs(go_distance_raw)

    has_props = bool(method or total_rounds or go_distance)

    print(f"Method of Victory: {len(method)}")
    print(f"Total Rounds: {len(total_rounds)}")
    print(f"Go The Distance: {len(go_distance)}")
    print(f"Has props: {has_props}")

    return {
        "fight": fight_name,
        "url": fight_url,
        "has_props": has_props,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markets": {
            "method_of_victory": method,
            "total_rounds": total_rounds,
            "go_the_distance": go_distance,
        },
        "raw_markets": {
            "method_of_victory": method_raw,
            "total_rounds": total_rounds_raw,
            "go_the_distance": go_distance_raw,
        }
    }


def upsert_fight(output, fight_data):
    existing = output.get("fights", [])
    url = fight_data.get("url")

    updated = False

    for i, item in enumerate(existing):
        if item.get("url") == url:
            existing[i] = fight_data
            updated = True
            break

    if not updated:
        existing.append(fight_data)

    output["fights"] = existing


def main():
    with open(URLS_PATH, "r", encoding="utf-8") as f:
        url_data = json.load(f)

    fights = url_data.get("fights", [])

    if not fights:
        raise SystemExit("No fights found in paddypower_fight_urls.json")

    output = load_existing_output()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=is_github_actions())
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        for index, fight in enumerate(fights, start=1):
            print(f"\nProgress: {index}/{len(fights)}")

            try:
                fight_data = scrape_fight(page, fight)
                upsert_fight(output, fight_data)
                save_output(output)
            except Exception as e:
                print(f"ERROR scraping {fight.get('fight')}: {e}")
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved props to {OUT_PATH}")


if __name__ == "__main__":
    main()