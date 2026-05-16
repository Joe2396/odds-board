from playwright.sync_api import sync_playwright
import time
import json
import re
import os
from pathlib import Path
from datetime import datetime, timezone

print("RUNNING FAST PADDYPOWER TEXT PARSER - MONEYLINE + PROPS")

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


def get_fighters_from_fight_name(fight_name):
    fight_name = str(fight_name or "").strip()
    if " vs " in fight_name.lower():
        parts = re.split(r"\s+vs\s+", fight_name, flags=re.I)
    elif " v " in fight_name.lower():
        parts = re.split(r"\s+v\s+", fight_name, flags=re.I)
    else:
        parts = []
    return [p.strip() for p in parts if p.strip()]


def empty_output():
    return {
        "updated_at": now_iso(),
        "source": "paddypower",
        "bookmaker": "PaddyPower",
        "markets_scraped": [
            "fight_betting",
            "method_of_victory",
            "total_rounds",
            "go_the_distance"
        ],
        "fights": []
    }


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


def click_tab(page, tab_name):
    for selector in [
        f"text={tab_name}",
        f"button:has-text('{tab_name}')",
        f"a:has-text('{tab_name}')",
        f"span:has-text('{tab_name}')",
    ]:
        try:
            page.locator(selector).first.click(force=True, timeout=4000)
            print(f"  Clicked tab: {tab_name}")
            time.sleep(2.5)
            return True
        except Exception:
            pass
    print(f"  Could not click tab: {tab_name}")
    return False


def expand_section(page, section_name):
    for selector in [
        f"text={section_name}",
        f"button:has-text('{section_name}')",
        f"span:has-text('{section_name}')",
    ]:
        try:
            page.locator(selector).first.click(force=True, timeout=3000)
            print(f"  Expanded: {section_name}")
            time.sleep(1.5)
            return True
        except Exception:
            pass
    return False


def get_body_text(page):
    try:
        return page.locator("body").inner_text(timeout=12000)
    except Exception:
        return ""


def normalize_lines(text):
    junk_contains = [
        "if you bet", "current odds", "odds of", "you would win",
        "popular english", "premier league", "gambling can be addictive",
        "please gamble responsibly", "privacy policy", "cookie policy",
        "underage gambling", "resolve a dispute", "give feedback",
        "paddy power rules", "all markets", "bet builder", "power prices",
        "shop exclusives", "racing results", "popular events",
        "bet on popular", "where can i bet", "how much could i win",
        "what are the other", "odds shown in the above", "ppb counterparty",
        "ppb entertainment", "ppb games", "malta gaming", "gambling commission",
        "method of victory betting", "ufc matches bets", "mixed martial arts betting",
        "show more",
    ]

    lines = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if any(j in low for j in junk_contains):
            continue
        if len(line) > 110:
            continue
        lines.append(line)

    return lines


def find_section_after_last(lines, start_terms, stop_terms):
    """Find LAST occurrence of section heading to skip nav tab duplicates."""
    start_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if any(term.lower() == low or term.lower() in low for term in start_terms):
            start_idx = i  # keep updating — want LAST occurrence

    if start_idx is None:
        return []

    end_idx = min(len(lines), start_idx + 80)
    for j in range(start_idx + 1, len(lines)):
        low = lines[j].lower()
        if any(term.lower() == low or term.lower() in low for term in stop_terms):
            end_idx = j
            break

    return lines[start_idx:end_idx]


def dedupe_results(results):
    seen = set()
    unique = []
    for item in results:
        selection = str(item.get("selection", "")).strip()
        odds = str(item.get("odds", "")).strip()
        if not selection or not odds or not is_odds(odds):
            continue
        key = (selection.lower(), odds.upper())
        if key in seen:
            continue
        seen.add(key)
        unique.append({"selection": selection, "odds": odds})
    return unique


def parse_fight_betting(lines, fight_name):
    fighters = get_fighters_from_fight_name(fight_name)
    if len(fighters) != 2:
        return []

    section = find_section_after_last(
        lines,
        ["Fight Result", "Match Betting", "Fight Betting"],
        [
            "Method of Victory", "Round Betting", "Round & Minute",
            "Method & Round Combo", "Total Rounds", "Go The Distance",
            "Double Chance", "Power Prices",
        ],
    )

    if not section:
        section = lines[:80]

    results = []
    for fighter in fighters:
        found = None
        fighter_low = fighter.lower()
        for i, line in enumerate(section):
            if line.lower() == fighter_low:
                for j in range(i + 1, min(i + 8, len(section))):
                    if is_odds(section[j]):
                        found = {"selection": fighter, "odds": section[j]}
                        break
            if found:
                break
        if found:
            results.append(found)

    return dedupe_results(results)


def parse_method_of_victory(lines):
    section = find_section_after_last(
        lines,
        ["Method of Victory"],
        [
            "Round Betting", "Round & Minute", "Method & Round Combo",
            "Total Rounds", "Go The Distance", "Double Chance", "How fight will End",
        ],
    )

    results = []
    allowed_terms = [" by ko", " ko/tko", " tko", "submission", "points", "decision", "draw"]

    for i in range(len(section) - 1):
        selection = section[i].strip()
        odds = section[i + 1].strip()
        if is_odds(selection) or not is_odds(odds):
            continue
        low = selection.lower()
        if any(term in low for term in allowed_terms):
            results.append({"selection": selection, "odds": odds})

    return dedupe_results(results)


def parse_total_rounds(lines):
    section = find_section_after_last(
        lines,
        ["Total Rounds"],
        ["Double Chance", "Go The Distance", "Round Betting", "Method & Round Combo", "How fight will End"],
    )

    results = []
    for i in range(len(section) - 1):
        selection = section[i].strip()
        odds = section[i + 1].strip()
        if is_odds(selection) or not is_odds(odds):
            continue
        low = selection.lower()
        valid = "over" in low or "under" in low or "rounds" in low or re.search(r"\d+\.\d+", low)
        if valid:
            results.append({"selection": selection, "odds": odds})

    return dedupe_results(results)


def parse_go_distance(lines):
    section = find_section_after_last(
        lines,
        ["Go The Distance?", "Go The Distance", "Will the fight go the distance?"],
        ["Double Chance", "Method & Round Combo", "Round Betting", "Total Rounds", "How fight will End"],
    )

    results = []
    for i in range(len(section) - 1):
        selection = section[i].strip()
        odds = section[i + 1].strip()
        if is_odds(selection) or not is_odds(odds):
            continue
        low = selection.lower()
        valid = low in ["yes", "no"] or "go the distance" in low or "fight to go" in low
        if valid:
            results.append({"selection": selection, "odds": odds})

    return dedupe_results(results)


def scrape_fight(page, fight):
    fight_name = fight["fight"]
    fight_url = fight["url"]

    print("\n==============================")
    print(f"Scraping: {fight_name}")
    print("==============================")

    page.goto(fight_url, timeout=70000, wait_until="domcontentloaded")
    time.sleep(6)
    close_cookie_popup(page)
    time.sleep(1)

    # Step 1: Click Popular tab — Fight Result is expanded here by default
    click_tab(page, "Popular")

    # Get moneylines from Popular tab
    text = get_body_text(page)
    lines = normalize_lines(text)
    fight_betting = parse_fight_betting(lines, fight_name)
    print(f"  Moneylines after Popular tab: {len(fight_betting)}")

    # Step 2: Scroll back up and click Method of Victory tab
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)
    click_tab(page, "Method of Victory")
    text = get_body_text(page)
    lines_method = normalize_lines(text)
    method = parse_method_of_victory(lines_method)
    print(f"  Method of Victory: {len(method)}")

    # Step 3: Go back to All Markets and expand Total Rounds + GTD
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)
    click_tab(page, "All Markets")

    # Expand Total Rounds
    expand_section(page, "Total Rounds")
    # Expand Go The Distance
    expand_section(page, "Go The Distance?")

    # Scroll to load content
    for _ in range(4):
        page.mouse.wheel(0, 1200)
        time.sleep(0.5)
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)

    text = get_body_text(page)
    lines_all = normalize_lines(text)
    total_rounds = parse_total_rounds(lines_all)
    go_distance = parse_go_distance(lines_all)

    has_props = bool(fight_betting or method or total_rounds or go_distance)

    print(f"Fight Betting: {len(fight_betting)}")
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
            "fight_betting": fight_betting,
            "method_of_victory": method,
            "total_rounds": total_rounds,
            "go_the_distance": go_distance,
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
        return

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        url_data = json.load(f)

    fights = url_data.get("fights", [])

    if not fights:
        print("No fights found in paddypower_fight_urls.json")
        output = empty_output()
        save_output(output)
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