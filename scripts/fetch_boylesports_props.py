from playwright.sync_api import sync_playwright
import time
import json
import re
import os
from pathlib import Path
from datetime import datetime, timezone, date, timedelta

print("FETCHING BOYLESPORTS UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = ROOT / "ufc" / "data" / "events.json"
OUT_PATH = ROOT / "ufc" / "data" / "boylesports_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

BOYLESPORTS_BASE = "https://www.boylesports.com"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_odds(x):
    x = str(x or "").strip().upper()
    return (
        x == "EVS"
        or bool(re.match(r"^\d+/\d+$", x))
        or bool(re.match(r"^\d+\.\d+$", x))
    )


def empty_output():
    return {
        "updated_at": now_iso(),
        "source": "boylesports",
        "bookmaker": "BoyleSports",
        "fights": [],
    }


def save_output(output):
    output["updated_at"] = now_iso()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"  Saved to {OUT_PATH}")


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=True)
        print(f"  Debug: {label}")
    except Exception:
        pass


# ─────────────────────────────────────────────
# URL construction from events.json
# ─────────────────────────────────────────────

def slugify_name(name):
    name = str(name or "").lower().strip()
    name = re.sub(r"[^a-z0-9 ]", "", name)
    return re.sub(r"\s+", "-", name).strip("-")


def slugify_event(event_name):
    name = str(event_name or "").lower().strip()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    name = re.sub(r"\s+", "-", name).strip("-")
    return f"fights-{name}"


def build_boylesports_url(event_name, fighter1, fighter2):
    event_slug = slugify_event(event_name)
    f1_slug = slugify_name(fighter1)
    f2_slug = slugify_name(fighter2)
    return f"{BOYLESPORTS_BASE}/sports/ufc-mma/event/{event_slug}/{f1_slug}-v-{f2_slug}"


def load_upcoming_fights():
    """Load fights from all events within the next 30 days."""
    if not EVENTS_PATH.exists():
        print(f"ERROR: events.json not found at {EVENTS_PATH}")
        return []

    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = data if isinstance(data, list) else data.get("events", [])
    today = date.today()
    cutoff = today + timedelta(days=30)

    result = []

    for event in events:
        event_date_str = event.get("date") or ""
        event_name = event.get("name") or ""

        try:
            event_date = datetime.strptime(event_date_str[:10], "%Y-%m-%d").date()
        except Exception:
            continue

        if event_date <= today:
            print(f"  Skipping past event: {event_name} ({event_date_str})")
            continue

        if event_date > cutoff:
            print(f"  Skipping future event (>30 days): {event_name} ({event_date_str})")
            continue

        fights = event.get("fights") or []
        if not fights:
            print(f"  No fights yet for: {event_name} ({event_date_str})")
            continue

        print(f"  Including event: {event_name} ({event_date_str}) - {len(fights)} fights")

        for fight in fights:
            red = fight.get("red") or {}
            blue = fight.get("blue") or {}
            f1 = red.get("name") or fight.get("fighter1") or ""
            f2 = blue.get("name") or fight.get("fighter2") or ""

            if f1 and f2:
                url = build_boylesports_url(event_name, f1, f2)
                result.append({
                    "fighter1": f1.strip(),
                    "fighter2": f2.strip(),
                    "event_name": event_name,
                    "fight_name": f"{f1} vs {f2}",
                    "url": url,
                })

    print(f"Upcoming fights from events.json: {len(result)}")
    return result


# ─────────────────────────────────────────────
# Page scraping
# ─────────────────────────────────────────────

def accept_cookies(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
        "button:has-text('Got it')",
    ]:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("  Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def get_body_text(page):
    try:
        return page.locator("body").inner_text(timeout=15000)
    except Exception:
        return ""


def normalize_lines(text):
    junk_exact = {
        "popular", "cash out", "all markets", "method of victory",
        "method of result", "winning method", "rounds", "total rounds",
        "go the distance?", "fight goes the distance", "to go distance",
        "go the distance", "round betting", "show more", "show less",
        "bet builder", "fight betting", "match betting",
        "fight result", "show ufc stats", "hide ufc stats",
        "bet builder boost", "full t&cs", "close", "all competitions",
        "ufc and mma", "ufc", "mma", "in-play", "sports a-z",
        "safer gambling", "promotions", "casino",
    }
    junk_contains = [
        "create your bet builder", "min odds", "apply on betslip",
        "enjoy your boosted", "gaming quick links", "home / ufc",
        "please add one", "ufc stats", "cookie", "privacy",
        "back to fight card", "matchup", "tape", "significant strikes",
        "grappling", "previous fights", "ufc wins by",
    ]
    lines = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low in junk_exact:
            continue
        if any(j in low for j in junk_contains):
            continue
        if re.match(r"^\d+%$", line):
            continue
        if len(line) > 120:
            continue
        lines.append(line)
    return lines


def find_section_last(lines, start_terms, stop_terms):
    start_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if any(term.lower() == low or term.lower() in low for term in start_terms):
            start_idx = i
    if start_idx is None:
        return []
    end_idx = min(len(lines), start_idx + 100)
    for j in range(start_idx + 1, len(lines)):
        low = lines[j].lower()
        if any(term.lower() == low or term.lower() in low for term in stop_terms):
            end_idx = j
            break
    return lines[start_idx:end_idx]


def dedupe(results):
    seen = set()
    unique = []
    for item in results:
        sel = str(item.get("selection", "")).strip()
        odds = str(item.get("odds", "")).strip()
        if not sel or not odds or not is_odds(odds):
            continue
        key = (sel.lower(), odds.upper())
        if key in seen:
            continue
        seen.add(key)
        unique.append({"selection": sel, "odds": odds})
    return unique


def parse_fight_betting(lines, fight_name):
    fighters = []
    for sep in [" vs ", " v "]:
        if sep in fight_name.lower():
            parts = re.split(sep, fight_name, flags=re.I)
            fighters = [p.strip() for p in parts if p.strip()]
            break
    if len(fighters) != 2:
        return []
    section = find_section_last(
        lines,
        ["To Win Fight", "Fight Betting", "Match Betting", "Fight Result", "Bout Betting"],
        ["Method of Victory", "Method Of Victory", "Winning Method", "Rounds",
         "Total Rounds", "Go The Distance", "Round Betting"],
    )
    if not section:
        section = lines[:60]
    results = []
    i = 0
    while i < len(section) - 1:
        sel = section[i].strip()
        odds = section[i + 1].strip()
        if not is_odds(sel) and is_odds(odds):
            for fighter in fighters:
                if fighter.lower() in sel.lower() or sel.lower() in fighter.lower():
                    results.append({"selection": fighter, "odds": odds})
                    break
            i += 2
        else:
            i += 1
    return dedupe(results)


def parse_method_of_victory(lines):
    section = find_section_last(
        lines,
        ["Method Of Victory", "Method of Victory", "Winning Method", "Method of Result"],
        ["Rounds", "Total Rounds", "Go The Distance", "Round Betting",
         "Double Chance", "To Win Fight"],
    )
    results = []
    allowed = [" by ", "draw", "ko/tko", "ko,", "submission", "decision", "disqualification"]
    for i in range(len(section) - 1):
        sel = section[i].strip()
        odds = section[i + 1].strip()
        if is_odds(sel) or not is_odds(odds):
            continue
        if any(term in sel.lower() for term in allowed):
            results.append({"selection": sel, "odds": odds})
    return dedupe(results)


def parse_go_distance(lines):
    section = find_section_last(
        lines,
        ["Go The Distance", "Fight Goes The Distance", "To Go The Distance"],
        ["Round Betting", "Total Rounds", "Method", "Double Chance"],
    )
    results = []
    for i in range(len(section) - 1):
        sel = section[i].strip()
        odds = section[i + 1].strip()
        if is_odds(sel) or not is_odds(odds):
            continue
        if sel.lower() in ["yes", "no"]:
            results.append({"selection": sel, "odds": odds})
    return dedupe(results)


def parse_rounds(lines):
    section = find_section_last(
        lines,
        ["Rounds", "Total Rounds", "Round Betting"],
        ["Go The Distance", "Method", "Double Chance", "To Win Fight"],
    )
    results = []
    for i in range(len(section) - 1):
        sel = section[i].strip()
        odds = section[i + 1].strip()
        if is_odds(sel) or not is_odds(odds):
            continue
        low = sel.lower()
        valid = (
            "round" in low
            or "over" in low
            or "under" in low
            or re.search(r"\d+\.\d+", low)
        )
        if valid:
            results.append({"selection": sel, "odds": odds})
    return dedupe(results)


def click_tab(page, tab_name):
    for selector in [
        f"button:has-text('{tab_name}')",
        f"a:has-text('{tab_name}')",
        f"div[role='tab']:has-text('{tab_name}')",
        f"text={tab_name}",
    ]:
        try:
            page.locator(selector).first.click(force=True, timeout=4000)
            print(f"  Clicked: {tab_name}")
            time.sleep(3)
            return True
        except Exception:
            pass
    return False


def scrape_fight(page, fight, index):
    fight_name = fight["fight_name"]
    fight_url = fight["url"]

    print(f"\n{'='*50}")
    print(f"[{index}] {fight_name}")
    print(f"URL: {fight_url}")
    print(f"{'='*50}")

    try:
        page.goto(fight_url, timeout=60000, wait_until="networkidle")
    except Exception as e:
        print(f"  Page load failed: {e}")
        return None

    print("  Waiting for page...")
    time.sleep(15)
    accept_cookies(page)
    time.sleep(2)

    for _ in range(4):
        page.mouse.wheel(0, 1200)
        time.sleep(0.8)
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)

    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", fight_name).strip("_").lower()
    save_debug(page, f"boylesports_{index}_{safe_label}")

    text = get_body_text(page)
    lines = normalize_lines(text)
    fight_betting = parse_fight_betting(lines, fight_name)
    print(f"  Fight Betting: {len(fight_betting)}")

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)
    clicked = click_tab(page, "Method Of Victory")
    if not clicked:
        clicked = click_tab(page, "Method of Victory")
    if clicked:
        text = get_body_text(page)
        method = parse_method_of_victory(normalize_lines(text))
    else:
        method = []
    print(f"  Method of Victory: {len(method)}")

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)
    clicked = click_tab(page, "Rounds")
    if clicked:
        text = get_body_text(page)
        lines_rounds = normalize_lines(text)
        rounds = parse_rounds(lines_rounds)
        go_distance = parse_go_distance(lines_rounds)
    else:
        rounds = []
        go_distance = []
    print(f"  Rounds: {len(rounds)}")
    print(f"  Go The Distance: {len(go_distance)}")

    has_props = bool(fight_betting or method or rounds or go_distance)
    print(f"  Has props: {has_props}")

    return {
        "fight": fight_name,
        "url": fight_url,
        "has_props": has_props,
        "scraped_at": now_iso(),
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


def main():
    fights = load_upcoming_fights()
    if not fights:
        print("No upcoming fights found.")
        save_output(empty_output())
        return

    print(f"\nFights to scrape: {len(fights)}")
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
                "Chrome/124.0.0.0 Safari/537.36"
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