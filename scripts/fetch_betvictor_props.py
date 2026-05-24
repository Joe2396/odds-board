from playwright.sync_api import sync_playwright
import json
import time
import re
import os
import unicodedata
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BETVICTOR UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]

URLS_PATH = ROOT / "ufc" / "data" / "betvictor_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "betvictor_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def clean_text(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()


def normalize_name(name):
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def last_name(name):
    parts = normalize_name(name).split()
    return parts[-1] if parts else ""


def fighter_line_match(line, fighter):
    line_n = normalize_name(line)
    fighter_n = normalize_name(fighter)
    fighter_last = last_name(fighter)

    if not line_n or not fighter_n:
        return False

    if fighter_n in line_n:
        return True

    return bool(fighter_last and fighter_last in line_n)


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

    fights = []

    for fight in data.get("fights", []):
        name = fight.get("fight_name") or fight.get("fight") or ""
        url = fight.get("url") or ""

        fighter1 = fight.get("fighter1", "")
        fighter2 = fight.get("fighter2", "")

        if not fighter1 or not fighter2:
            if " vs " in name:
                fighter1, fighter2 = name.split(" vs ", 1)

        if not name or not url or not fighter1 or not fighter2:
            continue

        fights.append({
            "fight": name,
            "fight_name": name,
            "url": url,
            "fighter1": fighter1,
            "fighter2": fighter2,
            "event_name": fight.get("event_name", ""),
            "date": fight.get("date", ""),
            "fight_id": fight.get("fight_id", ""),
        })

    print(f"BetVictor matched URLs loaded: {len(fights)}")
    for x in fights[:10]:
        print(f" - {x['fight_name']} -> {x['url']}")

    return fights


def get_page_lines(page):
    body_text = page.locator("body").inner_text(timeout=20000)
    return [clean_text(l) for l in body_text.splitlines() if clean_text(l)]


def extract_fight_betting(lines, fighter1, fighter2):
    for i, line in enumerate(lines):
        if not fighter_line_match(line, fighter1):
            continue

        second_index = None

        for j in range(i + 1, min(i + 8, len(lines))):
            if fighter_line_match(lines[j], fighter2):
                second_index = j
                break

        if second_index is None:
            continue

        window = lines[i:min(second_index + 20, len(lines))]
        odds = [x for x in window if is_odds(x)]

        if len(odds) >= 2:
            return [
                {"selection": fighter1, "odds": odds[0]},
                {"selection": fighter2, "odds": odds[1]},
            ]

    return []


def scrape_meeting_page(page, meeting_url):
    print(f"\nOpening BetVictor meeting: {meeting_url}")

    page.goto(meeting_url, timeout=60000, wait_until="domcontentloaded")
    time.sleep(8)
    accept_cookies(page)

    for _ in range(8):
        page.mouse.wheel(0, 900)
        time.sleep(0.5)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)

    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", meeting_url).strip("_").lower()[-80:]
    save_debug(page, f"betvictor_meeting_{safe_label}")

    return get_page_lines(page)


def build_fight_result(fight, lines):
    fight_name = fight["fight_name"]
    fighter1 = fight["fighter1"]
    fighter2 = fight["fighter2"]

    fight_betting = extract_fight_betting(lines, fighter1, fighter2)

    markets = {
        "fight_betting": fight_betting,
        "method_of_victory": [],
        "rounds": [],
        "go_the_distance": [],
    }

    total = sum(len(v) for v in markets.values())

    print(f"\n{fight_name}")
    print(f"Fight Betting: {len(fight_betting)}")
    print(f"Total markets found: {total}")

    return {
        "bookmaker": "BetVictor",
        "fight": fight_name,
        "fight_name": fight_name,
        "url": fight["url"],
        "has_props": total > 0,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
    }


def main():
    fights = load_fight_urls()

    if not fights:
        print("No BetVictor fight URLs found.")
        save_output(empty_output())
        return

    output = empty_output()

    unique_urls = sorted(set(f["url"] for f in fights))
    meeting_lines = {}

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

        for url in unique_urls:
            try:
                meeting_lines[url] = scrape_meeting_page(page, url)
            except Exception as e:
                print(f"ERROR scraping meeting {url}: {e}")
                meeting_lines[url] = []

        for fight in fights:
            lines = meeting_lines.get(fight["url"], [])
            fight_data = build_fight_result(fight, lines)

            if fight_data:
                output["fights"].append(fight_data)
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()