from playwright.sync_api import sync_playwright
import json
import time
import re
import os
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BETVICTOR UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]

URLS_PATH = ROOT / "ufc" / "data" / "betvictor_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "betvictor_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def is_odds(x):
    x = str(x or "").strip().upper()
    return (
        x == "EVS"
        or bool(re.match(r"^\d+/\d+$", x))
        or bool(re.match(r"^\d+\.\d+$", x))
    )


def empty_output():
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "betvictor",
        "bookmaker": "BetVictor",
        "fights": [],
    }


def save_output(output):
    output["updated_at"] = datetime.now(timezone.utc).isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved to {OUT_PATH}")


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=True)
        print(f"Debug screenshot: {label}")
    except Exception as e:
        print(f"Debug failed: {e}")


def accept_cookies(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
    ]:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def load_fight_urls():
    if not URLS_PATH.exists():
        print(f"ERROR: URL file missing: {URLS_PATH}")
        return []

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    fights = data.get("fights", [])

    clean = []
    for fight in fights:
        name = fight.get("fight_name") or fight.get("fight") or ""
        url = fight.get("url") or ""

        if not name or not url:
            continue

        clean.append({
            "fight": name,
            "fight_name": name,
            "url": url,
            "fighter1": fight.get("fighter1", ""),
            "fighter2": fight.get("fighter2", ""),
            "event_name": fight.get("event_name", ""),
            "date": fight.get("date", ""),
            "fight_id": fight.get("fight_id", ""),
        })

    print(f"BetVictor matched URLs loaded: {len(clean)}")
    for x in clean[:10]:
        print(f" - {x['fight_name']} -> {x['url']}")

    return clean


def click_all_markets(page):
    clicked = False

    selectors = [
        "button:has-text('All Markets')",
        "a:has-text('All Markets')",
        "text=All Markets",
        "button:has-text('Show More')",
        "button:has-text('More')",
        "text=More"
    ]

    for selector in selectors:
        try:
            buttons = page.locator(selector)
            count = buttons.count()

            for i in range(count):
                try:
                    btn = buttons.nth(i)

                    if btn.is_visible():
                        btn.scroll_into_view_if_needed()
                        page.wait_for_timeout(500)

                        btn.click(timeout=3000)

                        print(f"Clicked: {selector}")

                        clicked = True
                        page.wait_for_timeout(1500)

                except:
                    pass

        except:
            pass

    if not clicked:
        print("All Markets not found")
        return False

        return True

def parse_page_text(page):
    try:
        body_text = page.locator("body").inner_text(timeout=20000)
    except Exception as e:
        print(f"Could not get body text: {e}")
        return {
            "fight_betting": [],
            "method_of_victory": [],
            "rounds": [],
            "go_the_distance": [],
        }

    lines = [l.strip() for l in body_text.splitlines() if l.strip()]

    section_map = {
        "fight betting": "fight_betting",
        "to win bout": "fight_betting",
        "to win the bout": "fight_betting",
        "method of victory": "method_of_victory",
        "winning method": "method_of_victory",
        "round betting": "rounds",
        "total rounds": "rounds",
        "go the distance": "go_the_distance",
        "will the fight go the distance": "go_the_distance",
    }

    junk = {
        "sports",
        "in-play",
        "offers",
        "casino",
        "live casino",
        "bingo",
        "search",
        "a-z sports",
        "settings",
        "help & contact",
        "log in",
        "sign up",
        "betslip",
        "slots",
        "mini games",
        "affiliates",
        "fairness",
        "cookies notice",
        "terms & conditions",
        "privacy notice",
        "safer gambling",
    }

    results = {
        "fight_betting": [],
        "method_of_victory": [],
        "rounds": [],
        "go_the_distance": [],
    }

    current_section = None
    i = 0

    while i < len(lines):
        line = lines[i]
        lower = line.lower().strip()

        if lower in junk:
            i += 1
            continue

        matched_section = None
        for heading, key in section_map.items():
            if lower == heading or lower.startswith(heading):
                matched_section = key
                break

        if matched_section:
            current_section = matched_section
            i += 1
            continue

        if current_section is None:
            i += 1
            continue

        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()

            if not is_odds(line) and is_odds(next_line):
                results[current_section].append({
                    "selection": line,
                    "odds": next_line,
                })
                i += 2
                continue

        i += 1

    return results


def scrape_fight(page, fight, index):
    fight_name = fight["fight_name"]
    fight_url = fight["url"]

    print(f"\n{'=' * 50}")
    print(f"[{index}] {fight_name}")
    print(f"URL: {fight_url}")
    print(f"{'=' * 50}")

    try:
        page.goto(fight_url, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"Page load failed: {e}")
        return None

    time.sleep(8)
    accept_cookies(page)
    time.sleep(1)

    click_all_markets(page)

    for _ in range(8):
        page.mouse.wheel(0, 900)
        time.sleep(0.6)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)

    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", fight_name).strip("_").lower()
    save_debug(page, f"betvictor_props_{index}_{safe_label}")

    markets = parse_page_text(page)
    total = sum(len(v) for v in markets.values())

    print(f"Fight Betting: {len(markets['fight_betting'])}")
    print(f"Method: {len(markets['method_of_victory'])}")
    print(f"Rounds: {len(markets['rounds'])}")
    print(f"Distance: {len(markets['go_the_distance'])}")
    print(f"Total markets found: {total}")

    return {
        "bookmaker": "BetVictor",
        "fight": fight_name,
        "fight_name": fight_name,
        "url": fight_url,
        "has_props": total > 0,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
    }


def upsert_fight(output, fight_data):
    existing = output.get("fights", [])
    key = fight_data.get("fight_name")

    for i, item in enumerate(existing):
        if item.get("fight_name") == key:
            existing[i] = fight_data
            output["fights"] = existing
            return

    existing.append(fight_data)
    output["fights"] = existing


def main():
    fights = load_fight_urls()

    if not fights:
        print("No BetVictor fight URLs found.")
        save_output(empty_output())
        return

    output = empty_output()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_github_actions(),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
        )

        page = context.new_page()

        for index, fight in enumerate(fights, start=1):
            try:
                fight_data = scrape_fight(page, fight, index)

                if fight_data:
                    upsert_fight(output, fight_data)
                    save_output(output)

            except Exception as e:
                print(f"ERROR on {fight.get('fight_name')}: {e}")
                import traceback
                traceback.print_exc()
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()