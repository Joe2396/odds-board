from playwright.sync_api import sync_playwright
import json
import time
import re
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING CORAL UFC PROPS - ALL FIGHTS")

ROOT = Path(__file__).resolve().parents[1]

URLS_PATH = ROOT / "ufc" / "data" / "coral_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "coral_props.json"
DEBUG_HTML = ROOT / "ufc" / "data" / "coral_props_debug.html"
DEBUG_PNG = ROOT / "ufc" / "data" / "coral_props_debug.png"


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def accept_cookies(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=4000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def is_odds(text):
    return bool(re.fullmatch(r"\d+/\d+|EVS", clean_text(text), flags=re.I))


def extract_structured_markets(page):
    page_text = page.locator("body").inner_text(timeout=10000)
    lines = [clean_text(x) for x in page_text.splitlines() if clean_text(x)]

    markets = {
        "fight_betting": [],
        "go_the_distance": [],
        "method_of_victory": [],
        "total_rounds": [],
        "raw": [],
    }

    current_market = None
    pending_selection = None

    market_headings = {
        "Fight Betting": "fight_betting",
        "Fight To Go The Distance?": "go_the_distance",
        "Method Of Victory (5 Way)": "method_of_victory",
        "Method Of Victory (7 Way)": "method_of_victory",
        "Total Rounds": "total_rounds",
    }

    junk = {
        "ALL",
        "MAIN",
        "TOTAL ROUNDS",
        "BETSLIP",
        "MY BETS",
        "Your betslip is empty",
        "Please add one or more selections to place a bet",
        "FAVOURITES",
        "MINI GAMES",
        "Home",
    }

    for line in lines:
        if line in market_headings:
            current_market = market_headings[line]
            pending_selection = None
            continue

        if line in junk:
            continue

        if is_odds(line):
            if current_market and pending_selection:
                item = {
                    "market": current_market,
                    "selection": pending_selection,
                    "odds": line,
                }

                markets[current_market].append({
                    "selection": pending_selection,
                    "odds": line,
                })

                markets["raw"].append(item)
                pending_selection = None

            continue

        if current_market:
            if len(line) <= 90:
                lower = line.lower()

                if not any(x in lower for x in [
                    "log in",
                    "join",
                    "please",
                    "cash out",
                    "responsible",
                    "gambling",
                    "betslip",
                    "favourites",
                    "mini games",
                ]):
                    pending_selection = line

    for key in markets:
        seen = set()
        unique = []

        for item in markets[key]:
            if not isinstance(item, dict):
                continue

            sig = (
                item.get("market", ""),
                item.get("selection", ""),
                item.get("odds", ""),
            )

            if sig in seen:
                continue

            seen.add(sig)
            unique.append(item)

        markets[key] = unique

    return markets


def main():
    with open(URLS_PATH, "r", encoding="utf-8") as f:
        url_data = json.load(f)

    fights_to_scrape = url_data.get("fights", []) or []

    print(f"Loaded Coral fights: {len(fights_to_scrape)}")

    all_fights = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        page = browser.new_page(
            viewport={"width": 1500, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        for idx, fight in enumerate(fights_to_scrape, start=1):
            fight_name = fight.get("fight_name") or fight.get("fight") or "Unknown fight"
            url = fight.get("url")

            print("\n==============================")
            print(f"{idx}/{len(fights_to_scrape)}")
            print("FIGHT:", fight_name)
            print("URL:", url)
            print("==============================")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=80000)
                time.sleep(7)

                accept_cookies(page)
                time.sleep(2)

                for _ in range(5):
                    page.mouse.wheel(0, 1800)
                    time.sleep(0.8)

                markets = extract_structured_markets(page)

                total = sum(
                    len(markets.get(k, []))
                    for k in [
                        "fight_betting",
                        "go_the_distance",
                        "method_of_victory",
                        "total_rounds",
                    ]
                )

                print("Fight betting:", len(markets["fight_betting"]))
                print("GTD:", len(markets["go_the_distance"]))
                print("Method:", len(markets["method_of_victory"]))
                print("Total rounds:", len(markets["total_rounds"]))
                print("Total:", total)

                all_fights.append({
                    "bookmaker": "Coral",
                    "fight_name": fight_name,
                    "fight": fight_name,
                    "url": url,
                    "market_count": total,
                    "markets": markets,
                })

            except Exception as e:
                print("FAILED:", e)

                all_fights.append({
                    "bookmaker": "Coral",
                    "fight_name": fight_name,
                    "fight": fight_name,
                    "url": url,
                    "market_count": 0,
                    "markets": {
                        "fight_betting": [],
                        "go_the_distance": [],
                        "method_of_victory": [],
                        "total_rounds": [],
                        "raw": [],
                    },
                    "error": str(e),
                })

        try:
            with open(DEBUG_HTML, "w", encoding="utf-8") as f:
                f.write(page.content())
            page.screenshot(path=str(DEBUG_PNG), full_page=True)
        except Exception:
            pass

        browser.close()

    output = {
        "bookmaker": "Coral",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "fight_count": len(all_fights),
        "fights": all_fights,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("\nDONE")
    print(f"Saved: {OUT_PATH}")
    print(f"Total fights scraped: {len(all_fights)}")


if __name__ == "__main__":
    main()