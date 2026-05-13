from playwright.sync_api import sync_playwright
import time
import json
import re
import os
from pathlib import Path
from datetime import datetime, timezone

print("RUNNING CLEAN PADDYPOWER PROPS-ONLY SCRIPT")

ROOT = Path(__file__).resolve().parents[1]
URLS_PATH = ROOT / "ufc" / "data" / "paddypower_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "props.json"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_odds(x):
    x = str(x or "").strip().upper()

    if not x:
        return False

    if x == "EVS":
        return True

    if re.match(r"^\d+/\d+$", x):
        return True

    if re.match(r"^\d+(\.\d+)?$", x):
        try:
            return float(x) > 1
        except Exception:
            return False

    return False


def empty_output():
    return {
        "updated_at": now_iso(),
        "source": "paddypower",
        "bookmaker": "PaddyPower",
        "note": "PaddyPower moneylines are intentionally disabled because page text can produce fake duplicated odds. Use OddsAPI for fight winner odds.",
        "markets_scraped": [
            "method_of_victory",
            "total_rounds",
            "go_the_distance"
        ],
        "fights": []
    }


def load_existing_output():
    if OUT_PATH.exists():
        try:
            with open(OUT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            data["source"] = "paddypower"
            data["bookmaker"] = "PaddyPower"
            data["markets_scraped"] = [
                "method_of_victory",
                "total_rounds",
                "go_the_distance"
            ]
            data["note"] = "PaddyPower moneylines are intentionally disabled because page text can produce fake duplicated odds. Use OddsAPI for fight winner odds."

            return data
        except Exception:
            pass

    return empty_output()


def save_output(output):
    output["updated_at"] = now_iso()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved progress to {OUT_PATH}")


def close_cookie_popup(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=2500, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            continue

    print("No cookie popup found")


def click_market(page, market_name):
    selectors = [
        f"text='{market_name}'",
        f"span:text('{market_name}')",
        f"div:text('{market_name}')",
        f"button:text('{market_name}')",
        f"[aria-label*='{market_name}']",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.scroll_into_view_if_needed(timeout=5000)
            time.sleep(0.5)
            locator.click(force=True, timeout=7000)
            print(f"Opened market: {market_name}")
            time.sleep(1.25)
            return True
        except Exception:
            continue

    print(f"Could not open market: {market_name}")
    return False


def get_body_text(page):
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


def get_market_snippet(page, market_name, stop_words=None):
    if stop_words is None:
        stop_words = []

    text = get_body_text(page)
    if not text:
        return ""

    start = text.find(market_name)

    if start == -1:
        return ""

    end = start + 3500

    for word in stop_words:
        idx = text.find(word, start + len(market_name))
        if idx != -1:
            end = min(end, idx)

    return text[start:end].strip()


def clean_lines(snippet):
    junk_exact = {
        "Popular",
        "Fight Result",
        "Match Betting",
        "Cash Out",
        "All Markets",
        "Method of Victory",
        "Total Rounds",
        "Go The Distance?",
        "Will the fight go the distance?",
        "Round & Minute",
        "Round Betting",
        "UFC Matches",
        "Bet Builder",
        "Show More",
        "Show Less",
        "Suspended",
    }

    junk_contains = [
        "if you bet",
        "current odds",
        "odds of",
        "payout",
        "powered by",
        "gambling can be addictive",
        "please gamble responsibly",
        "acca",
        "promotion",
        "boost",
    ]

    cleaned = []

    for line in snippet.splitlines():
        line = line.strip()

        if not line:
            continue

        if line in junk_exact:
            continue

        low = line.lower()

        if any(j in low for j in junk_contains):
            continue

        if len(line) > 90:
            continue

        cleaned.append(line)

    return cleaned


def parse_method_of_victory(snippet):
    lines = clean_lines(snippet)
    results = []

    allowed_terms = [
        " by ko",
        " ko/tko",
        " tko",
        "submission",
        "points",
        "decision",
        "draw",
        "technical decision",
    ]

    for i in range(len(lines) - 1):
        selection = lines[i].strip()
        odds = lines[i + 1].strip()

        selection_low = selection.lower()

        if not is_odds(odds):
            continue

        if is_odds(selection):
            continue

        if any(term in selection_low for term in allowed_terms):
            results.append({
                "selection": selection,
                "odds": odds
            })

    return dedupe_results(results)


def parse_total_rounds(snippet):
    lines = clean_lines(snippet)
    results = []

    for i in range(len(lines) - 1):
        selection = lines[i].strip()
        odds = lines[i + 1].strip()

        if not is_odds(odds):
            continue

        if is_odds(selection):
            continue

        selection_low = selection.lower()

        valid = (
            "over" in selection_low
            or "under" in selection_low
            or "rounds" in selection_low
            or re.search(r"\d+\.\d+", selection_low)
        )

        if valid:
            results.append({
                "selection": selection,
                "odds": odds
            })

    return dedupe_results(results)


def parse_go_distance(snippet):
    lines = clean_lines(snippet)
    results = []

    for i in range(len(lines) - 1):
        selection = lines[i].strip()
        odds = lines[i + 1].strip()

        if not is_odds(odds):
            continue

        if is_odds(selection):
            continue

        selection_low = selection.lower()

        valid = (
            selection_low in ["yes", "no"]
            or "yes" == selection_low
            or "no" == selection_low
            or "go the distance" in selection_low
            or "fight to go the distance" in selection_low
            or "fight not to go the distance" in selection_low
        )

        if valid:
            results.append({
                "selection": selection,
                "odds": odds
            })

    return dedupe_results(results)


def dedupe_results(results):
    seen = set()
    unique = []

    for item in results:
        selection = str(item.get("selection", "")).strip()
        odds = str(item.get("odds", "")).strip()

        if not selection or not odds:
            continue

        key = (selection.lower(), odds.upper())

        if key in seen:
            continue

        seen.add(key)
        unique.append({
            "selection": selection,
            "odds": odds
        })

    return unique


def scrape_fight(page, fight):
    fight_name = fight["fight"]
    fight_url = fight["url"]

    print("\n==============================")
    print(f"Scraping: {fight_name}")
    print("==============================")

    page.goto(fight_url, timeout=70000, wait_until="domcontentloaded")
    time.sleep(6)

    close_cookie_popup(page)

    markets_to_open = [
        "Method of Victory",
        "Total Rounds",
        "Go The Distance?",
        "Will the fight go the distance?",
    ]

    for market in markets_to_open:
        click_market(page, market)

    time.sleep(2)

    method_raw = get_market_snippet(
        page,
        "Method of Victory",
        stop_words=[
            "Round Betting",
            "Total Rounds",
            "Go The Distance?",
            "Will the fight go the distance?",
            "Method & Round Combo",
            "Round & Minute",
        ],
    )

    total_rounds_raw = get_market_snippet(
        page,
        "Total Rounds",
        stop_words=[
            "Double Chance",
            "Go The Distance?",
            "Will the fight go the distance?",
            "How fight will End",
            "Round Betting",
            "Method & Round Combo",
        ],
    )

    go_distance_raw = (
        get_market_snippet(
            page,
            "Go The Distance?",
            stop_words=[
                "How fight will End",
                "What Round",
                "Show More",
                "Method & Round Combo",
                "Round Betting",
            ],
        )
        or
        get_market_snippet(
            page,
            "Will the fight go the distance?",
            stop_words=[
                "How fight will End",
                "What Round",
                "Show More",
                "Method & Round Combo",
                "Round Betting",
            ],
        )
    )

    method = parse_method_of_victory(method_raw)
    total_rounds = parse_total_rounds(total_rounds_raw)
    go_distance = parse_go_distance(go_distance_raw)

    has_props = bool(method or total_rounds or go_distance)

    print(f"Method of Victory: {len(method)}")
    print(f"Total Rounds: {len(total_rounds)}")
    print(f"Go The Distance: {len(go_distance)}")
    print(f"Has props: {has_props}")

    return {
        "fight": fight_name,
        "url": fight_url,
        "bookmaker": "PaddyPower",
        "has_props": has_props,
        "scraped_at": now_iso(),
        "markets": {
            "fight_betting": [],
            "method_of_victory": method,
            "total_rounds": total_rounds,
            "go_the_distance": go_distance,
        },
        "raw_markets": {
            "fight_betting": "",
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
    if not URLS_PATH.exists():
        print(f"Missing fight URL file: {URLS_PATH}")
        output = empty_output()
        save_output(output)
        return

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        url_data = json.load(f)

    fights = url_data.get("fights", [])

    if not fights:
        print("No fights found in paddypower_fight_urls.json")
        output = empty_output()
        save_output(output)
        return

    output = load_existing_output()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_github_actions(),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )

        page = context.new_page()

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