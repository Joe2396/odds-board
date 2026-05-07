from playwright.sync_api import sync_playwright
import time
import json
import re
import os
from pathlib import Path
from datetime import datetime, timezone

print("RUNNING BOYLESPORTS ALL-FIGHTS PROPS SCRIPT")

ROOT = Path(__file__).resolve().parents[1]
URLS_PATH = ROOT / "ufc" / "data" / "boylesports_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "boylesports_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def is_odds(x):
    x = str(x).strip()
    return (
        x == "EVS"
        or bool(re.match(r"^\d+/\d+$", x))
        or bool(re.match(r"^\d+\.\d+$", x))
    )


def empty_output():
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "boylesports",
        "bookmaker": "BoyleSports",
        "markets_scraped": [
            "method_of_victory",
            "rounds",
            "go_the_distance",
        ],
        "fights": [],
    }


def save_output(output):
    output["updated_at"] = datetime.now(timezone.utc).isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved progress to {OUT_PATH}")


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        html_path = DEBUG_DIR / f"{label}.html"
        png_path = DEBUG_DIR / f"{label}.png"

        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(png_path), full_page=True)

        print(f"Saved debug HTML: {html_path}")
        print(f"Saved debug screenshot: {png_path}")
    except Exception as e:
        print(f"Could not save debug files: {e}")


def close_cookie_popup(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
        "button:has-text('Got it')",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass

    print("No cookie popup found")


def wait_for_boylesports_page(page):
    print("Waiting for BoyleSports React app...")
    time.sleep(10)

    try:
        page.wait_for_selector("body", timeout=15000)
    except Exception:
        pass

    try:
        body_text = page.locator("body").inner_text(timeout=10000)
        print(f"Body text length after wait: {len(body_text)}")
    except Exception:
        print("Could not read body text after wait")


def click_tab(page, tab_name):
    print(f"Trying tab: {tab_name}")

    selectors = [
        f"button:has-text('{tab_name}')",
        f"a:has-text('{tab_name}')",
        f"div[role='tab']:has-text('{tab_name}')",
        f"text={tab_name}",
    ]

    for selector in selectors:
        try:
            tab = page.locator(selector).first
            tab.scroll_into_view_if_needed(timeout=5000)
            time.sleep(0.5)
            tab.click(force=True, timeout=5000)
            print(f"Clicked tab: {tab_name}")
            time.sleep(3)

            page.mouse.wheel(0, 1200)
            time.sleep(2)

            return True
        except Exception:
            pass

    print(f"Could not click tab: {tab_name}")
    return False


def get_body_text(page):
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


def strip_before_useful_market(text):
    markers = [
        "Winning Method",
        "Method Of Victory",
        "Method of Victory",
        "Round Betting",
        "Rounds",
        "Go The Distance",
        "To Go Distance",
        "Fight Goes The Distance",
    ]

    lower_text = text.lower()
    starts = []

    for marker in markers:
        idx = lower_text.find(marker.lower())
        if idx != -1:
            starts.append(idx)

    if starts:
        return text[min(starts):]

    return text


def clean_lines(snippet):
    junk_exact = {
        "",
        "Popular",
        "Cash Out",
        "All Markets",
        "Method of Victory",
        "Method Of Victory",
        "Winning Method",
        "Rounds",
        "Total Rounds",
        "Go The Distance?",
        "Fight Goes The Distance",
        "Fight To Go The Distance",
        "To Go Distance",
        "Go The Distance",
        "Round Betting",
        "Round Betting Groups",
        "Grouped Round Betting I",
        "Grouped Round Betting Ii",
        "Method & Round Combo",
        "Round Groups",
        "Fight To Go The Distance",
        "Show More",
        "Show Less",
        "Bet Builder",
        "To Win Fight",
        "Show UFC Stats",
        "Hide UFC Stats",
        "Bet Builder Boost",
        "Get a Boost on this match",
        "Full T&Cs",
        "Close",
        "All competitions",
        "Betslip",
        "My Bets",
        "Betslip Empty",
        "Please add one or more selections in order to place a bet.",
        "Back To Fight Card",
        "BACK TO FIGHT CARD",
        "MATCHUP",
        "TAPE",
        "FORM",
        "SIGNIFICANT STRIKES",
        "GRAPPLING",
        "UFC WINS BY",
        "KO/TKO",
        "SUBMISSION",
        "DECISION",
    }

    junk_contains = [
        "create your bet builder",
        "min odds for boost",
        "apply on betslip",
        "enjoy your boosted winnings",
        "receive more in cash",
        "gaming quick links",
        "home / ufc",
        "fights ufc",
        "please add one or more selections",
        "ufc stats",
        "promotions",
        "casino",
        "live casino",
        "sports a-z",
        "safer gambling",
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

        if re.match(r"^\d+%$", line):
            continue

        if re.match(r"^\d+\s*-\s*\d+\s*-\s*\d+$", line):
            continue

        if re.match(r"^\d{1,2}:\d{2}$", line):
            continue

        if re.match(r"^\d+\s*mins?$", low):
            continue

        if low in ["w-l-d", "previous fights", "middleweight", "rank 3", "usa", "rus"]:
            continue

        cleaned.append(line)

    return cleaned


def parse_pairs_from_text(text):
    lines = clean_lines(strip_before_useful_market(text))
    results = []

    for i in range(len(lines) - 1):
        selection = lines[i]
        odds = lines[i + 1]

        if not is_odds(selection) and is_odds(odds):
            results.append({
                "selection": selection,
                "odds": odds,
            })

    return results


def parse_method_of_victory(text):
    pairs = parse_pairs_from_text(text)
    results = []

    for item in pairs:
        selection = item["selection"].lower()

        if (
            " by " in selection
            or "draw" in selection
            or "ko/tko" in selection
            or "submission" in selection
            or "decision" in selection
            or "technical decision" in selection
            or "disqualification" in selection
            or "points" in selection
        ):
            results.append(item)

    return results


def parse_go_distance(text):
    pairs = parse_pairs_from_text(text)
    results = []

    for item in pairs:
        selection = item["selection"].strip().lower()

        if selection in ["yes", "no"]:
            results.append(item)

    return results


def scrape_tab_market(page, tab_name, fight_name, index, market_key):
    clicked = click_tab(page, tab_name)

    if not clicked:
        return "", []

    text = get_body_text(page)

    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", fight_name).strip("_").lower()
    save_debug(page, f"boylesports_{index}_{safe_label}_{market_key}")

    if market_key == "method_of_victory":
        parsed = parse_method_of_victory(text)
    elif market_key == "go_the_distance":
        parsed = parse_go_distance(text)
    else:
        parsed = parse_pairs_from_text(text)

    return text[:3000], parsed


def scrape_fight(page, fight, index):
    fight_name = fight["fight"]
    fight_url = fight["url"]

    print("\n==============================")
    print(f"Scraping BoyleSports: {fight_name}")
    print("==============================")

    page.goto(fight_url, timeout=60000, wait_until="domcontentloaded")

    wait_for_boylesports_page(page)

    close_cookie_popup(page)
    time.sleep(2)

    method_raw, method = scrape_tab_market(
        page,
        "Method Of Victory",
        fight_name,
        index,
        "method_of_victory",
    )

    try:
        page.mouse.wheel(0, -2500)
        time.sleep(1)
    except Exception:
        pass

    rounds_raw, rounds = scrape_tab_market(
        page,
        "Rounds",
        fight_name,
        index,
        "rounds",
    )

    go_distance = []
    go_distance_raw = ""

    if rounds_raw:
        go_distance = parse_go_distance(rounds_raw)
        go_distance_raw = rounds_raw if go_distance else ""

    has_props = bool(method or rounds or go_distance)

    print(f"Method Of Victory: {len(method)}")
    print(f"Rounds: {len(rounds)}")
    print(f"Go The Distance: {len(go_distance)}")
    print(f"Has props: {has_props}")

    if not has_props:
        body_text = get_body_text(page)
        print("No props parsed. Body text sample:")
        print(body_text[:1500])

    return {
        "fight": fight_name,
        "url": fight_url,
        "has_props": has_props,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markets": {
            "method_of_victory": method,
            "rounds": rounds,
            "go_the_distance": go_distance,
        },
        "raw_markets": {
            "method_of_victory": method_raw,
            "rounds": rounds_raw,
            "go_the_distance": go_distance_raw,
        },
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
        print("No fight URL file found. Exiting cleanly.")
        return

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        url_data = json.load(f)

    fights = url_data.get("fights", [])

    print(f"Scraping fights: {len(fights)}")

    if not fights:
        print("No fights found in boylesports_fight_urls.json")
        output = empty_output()
        save_output(output)
        print("Saved empty boylesports_props.json. Exiting cleanly.")
        return

    output = empty_output()

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
                fight_data = scrape_fight(page, fight, index)
                upsert_fight(output, fight_data)
                save_output(output)
            except Exception as e:
                print(f"ERROR scraping {fight.get('fight')}: {e}")
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved BoyleSports props to {OUT_PATH}")


if __name__ == "__main__":
    main()