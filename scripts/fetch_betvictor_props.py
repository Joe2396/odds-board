from playwright.sync_api import sync_playwright
import json
import time
import re
import os
import requests
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BETVICTOR UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = ROOT / "ufc" / "data" / "events.json"
OUT_PATH = ROOT / "ufc" / "data" / "betvictor_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

BETVICTOR_SPORT_ID = 1327866
BETVICTOR_API_URL = f"https://www.betvictor.com/en-ie/in-play/1/sport-events/{BETVICTOR_SPORT_ID}.json"
BETVICTOR_BASE = "https://www.betvictor.com"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def is_odds(x):
    x = str(x).strip().upper()
    return (
        x == "EVS"
        or bool(re.match(r"^\d+/\d+$", x))
        or bool(re.match(r"^\d+\.\d+$", x))
    )


def clean_name(name):
    """Lowercase, strip punctuation, normalise whitespace for fuzzy matching."""
    name = str(name or "").lower()
    name = re.sub(r"[^a-z0-9 ]", "", name)
    return re.sub(r"\s+", " ", name).strip()


def names_match(fighter, description):
    """Return True if fighter's last name (or full name) appears in description."""
    fighter_clean = clean_name(fighter)
    desc_clean = clean_name(description)
    # Try full name first, then just last name
    if fighter_clean in desc_clean:
        return True
    last = fighter_clean.split()[-1] if fighter_clean else ""
    return bool(last and last in desc_clean)


def event_is_upcoming(event_date_str):
    """Return True if event date is today or in the future."""
    try:
        # events.json dates are typically "YYYY-MM-DD" or ISO strings
        date_str = str(event_date_str or "").strip()[:10]
        event_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return event_date >= now
    except Exception:
        # If we can't parse the date, include it to be safe
        return True


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
    print(f"  Saved to {OUT_PATH}")


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=True)
        print(f"  Debug screenshot: {label}")
    except Exception as e:
        print(f"  Debug failed: {e}")


# ─────────────────────────────────────────────
# Step 1: Load upcoming fights from events.json
# ─────────────────────────────────────────────

def load_upcoming_fights():
    """
    Read events.json and return a flat list of upcoming fights.
    Each item: { "fighter1": str, "fighter2": str, "event_name": str, "date": str }
    Skips any event whose date has already passed.
    """
    if not EVENTS_PATH.exists():
        print(f"ERROR: events.json not found at {EVENTS_PATH}")
        return []

    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    upcoming = []

    # Support both a list of events or a dict with an "events" key
    events = data if isinstance(data, list) else data.get("events", [])

    for event in events:
        event_date = event.get("date") or event.get("event_date") or ""
        event_name = event.get("name") or event.get("event_name") or ""

        if not event_is_upcoming(event_date):
            print(f"  Skipping past event: {event_name} ({event_date})")
            continue

        fights = event.get("fights") or event.get("bouts") or []
        for fight in fights:
            # Support various fighter name key formats
            f1 = (
                fight.get("fighter1") or fight.get("fighter_1") or
                fight.get("home") or fight.get("competitor1") or ""
            )
            f2 = (
                fight.get("fighter2") or fight.get("fighter_2") or
                fight.get("away") or fight.get("competitor2") or ""
            )
            if f1 and f2:
                upcoming.append({
                    "fighter1": f1.strip(),
                    "fighter2": f2.strip(),
                    "event_name": event_name,
                    "date": event_date,
                })

    print(f"Upcoming fights from events.json: {len(upcoming)}")
    return upcoming


# ─────────────────────────────────────────────
# Step 2: Hit BetVictor API to find event URLs
# ─────────────────────────────────────────────

def fetch_betvictor_fight_urls(upcoming_fights):
    """
    Call BetVictor's internal JSON API — no browser needed.
    Returns a list of { fighter1, fighter2, event_name, date, url }
    """
    print(f"\nCalling BetVictor API: {BETVICTOR_API_URL}")

    try:
        resp = requests.get(
            BETVICTOR_API_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Referer": "https://www.betvictor.com/en-ie/sports/mma-ufc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  BetVictor API call failed: {e}")
        return []

    # Walk the API response tree: result -> meetings -> events
    meetings = []
    result = data.get("result", data)  # some endpoints wrap in "result"
    if isinstance(result, dict):
        meetings = result.get("meetings", result.get("events", []))
    elif isinstance(result, list):
        meetings = result

    # Flatten all BetVictor events into a lookup list
    bv_events = []
    for meeting in meetings:
        meeting_id = meeting.get("id") or meeting.get("meeting_id")
        for event in meeting.get("events", [meeting]):  # some APIs return events at top level
            event_id = event.get("id") or event.get("event_id")
            description = event.get("description") or event.get("name") or ""
            if meeting_id and event_id:
                bv_events.append({
                    "meeting_id": meeting_id,
                    "event_id": event_id,
                    "description": description,
                })

    print(f"  BetVictor events found: {len(bv_events)}")

    # Match each upcoming fight to a BetVictor event
    matched = []
    for fight in upcoming_fights:
        f1 = fight["fighter1"]
        f2 = fight["fighter2"]
        found = None

        for bv in bv_events:
            desc = bv["description"]
            if names_match(f1, desc) and names_match(f2, desc):
                found = bv
                break

        if found:
            url = (
                f"{BETVICTOR_BASE}/en-ie/sports/{BETVICTOR_SPORT_ID}"
                f"/meetings/{found['meeting_id']}/events/{found['event_id']}"
            )
            print(f"  MATCHED: {f1} vs {f2} -> {url}")
            matched.append({**fight, "url": url})
        else:
            print(f"  NO MATCH: {f1} vs {f2} (not on BetVictor yet)")

    return matched


# ─────────────────────────────────────────────
# Step 3: Browser scraping (unchanged logic)
# ─────────────────────────────────────────────

def accept_cookies(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
    ]:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("  Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def click_all_markets(page):
    for selector in [
        "button:has-text('All Markets')",
        "a:has-text('All Markets')",
        "text=All Markets",
    ]:
        try:
            el = page.locator(selector).first
            el.scroll_into_view_if_needed(timeout=3000)
            time.sleep(0.5)
            el.click(force=True, timeout=5000)
            print("  Clicked All Markets")
            time.sleep(4)
            return True
        except Exception:
            pass
    print("  All Markets button not found")
    return False


def parse_page_text(page):
    try:
        body_text = page.locator("body").inner_text(timeout=15000)
    except Exception as e:
        print(f"  Could not get body text: {e}")
        return {}

    lines = [l.strip() for l in body_text.splitlines() if l.strip()]
    print(f"  Total text lines: {len(lines)}")

    section_map = {
        "to win the bout": "fight_betting",
        "to win bout": "fight_betting",
        "method of victory": "method_of_victory",
        "winning method": "method_of_victory",
        "round betting": "rounds",
        "go the distance": "go_the_distance",
        "will the fight go the distance": "go_the_distance",
    }

    junk = {
        "popular", "all markets", "bet boosts", "lucky dip",
        "in-play", "sports home", "offers", "horse racing",
        "football", "betvictor predictor", "casino", "live casino",
        "bingo", "search", "a-z sports", "casino categories", "settings",
        "help & contact", "betvictor news", "bet calculator", "log in",
        "sign up", "betslip", "in play", "slots", "mini games",
        "ufc fight night", "fairness", "affiliates", "contact us",
        "terms and conditions", "privacy notice", "safer gambling",
        "cookies notice",
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

        matched = None
        for heading, key in section_map.items():
            if lower == heading or lower.startswith(heading):
                matched = key
                break

        if matched:
            current_section = matched
            print(f"  Section: {line} -> {current_section}")
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
    f1 = fight["fighter1"]
    f2 = fight["fighter2"]
    fight_name = f"{f1} vs {f2}"
    fight_url = fight["url"]

    print(f"\n{'='*50}")
    print(f"[{index}] {fight_name}")
    print(f"URL: {fight_url}")
    print(f"{'='*50}")

    try:
        page.goto(fight_url, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"  Page load failed: {e}")
        return None

    print("  Waiting for page...")
    time.sleep(8)
    accept_cookies(page)
    time.sleep(2)
    click_all_markets(page)

    for _ in range(5):
        page.mouse.wheel(0, 1200)
        time.sleep(0.8)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)

    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", fight_name).strip("_").lower()
    save_debug(page, f"betvictor_{index}_{safe_label}")

    markets = parse_page_text(page)

    fight_betting = markets.get("fight_betting", [])
    method = markets.get("method_of_victory", [])
    rounds = markets.get("rounds", [])
    go_distance = markets.get("go_the_distance", [])

    if not go_distance:
        go_distance = [r for r in rounds if r["selection"].strip().lower() in ["yes", "no"]]

    has_props = bool(fight_betting or method or rounds or go_distance)

    print(f"\n  -- {fight_name} --")
    print(f"  Fight Betting:     {len(fight_betting)}")
    print(f"  Method of Victory: {len(method)}")
    print(f"  Rounds:            {len(rounds)}")
    print(f"  Go The Distance:   {len(go_distance)}")
    print(f"  Has props:         {has_props}")

    return {
        "fight": fight_name,
        "url": fight_url,
        "has_props": has_props,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markets": {
            "fight_betting": fight_betting,
            "method_of_victory": method,
            "rounds": rounds,
            "go_the_distance": go_distance,
        },
    }


def upsert_fight(output, fight_data):
    existing = output.get("fights", [])
    url = fight_data.get("url")
    for i, item in enumerate(existing):
        if item.get("url") == url:
            existing[i] = fight_data
            return
    existing.append(fight_data)
    output["fights"] = existing


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    # 1. Load upcoming fights from events.json (skips past events by date)
    upcoming_fights = load_upcoming_fights()
    if not upcoming_fights:
        print("No upcoming fights found in events.json.")
        save_output(empty_output())
        return

    # 2. Hit BetVictor API to resolve numeric IDs and build URLs (no browser needed)
    fights_with_urls = fetch_betvictor_fight_urls(upcoming_fights)
    if not fights_with_urls:
        print("No BetVictor URLs resolved. Possibly too early or API structure changed.")
        save_output(empty_output())
        return

    print(f"\nFights to scrape: {len(fights_with_urls)}")

    output = empty_output()

    # 3. Use Playwright only to scrape odds from the resolved fight pages
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
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
        )

        page = context.new_page()

        for index, fight in enumerate(fights_with_urls, start=1):
            print(f"\nProgress: {index}/{len(fights_with_urls)}")
            try:
                fight_data = scrape_fight(page, fight, index)
                if fight_data:
                    upsert_fight(output, fight_data)
                    save_output(output)
            except Exception as e:
                print(f"ERROR on {fight.get('fighter1')} vs {fight.get('fighter2')}: {e}")
                import traceback
                traceback.print_exc()
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()