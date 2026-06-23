from pathlib import Path
from datetime import datetime, timezone
import json
import re
from playwright.sync_api import sync_playwright
import os

def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"

ROOT      = Path(__file__).resolve().parents[1]
OUT_PATH  = ROOT / "ufc" / "data" / "bwin_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

BASE_URL = "https://sports.bwin.com/en/sports/combat-sports-45/betting/north-america-9"

# All 3-letter country codes Bwin appends to fighter names
COUNTRIES = {
    "USA", "IRL", "BRA", "CHN", "GBR", "ENG", "FRA", "RUS", "CAN", "AUS",
    "MEX", "ESP", "GER", "POL", "SWE", "NOR", "KAZ", "GEO", "JPN", "KOR",
    "AZE", "TUR", "ARM", "UKR", "UZB", "KGZ", "TJK", "MNG", "PHL", "IDN",
    "NZL", "SCO", "WAL", "ITA", "NLD", "BEL", "PRT", "CZE", "SVK", "HUN",
    "ROU", "BGR", "SRB", "HRV", "SVN", "EST", "LVA", "LTU", "FIN", "DNK",
    "ISL", "MAR", "EGY", "NGA", "GHA", "CMR", "SEN", "CIV", "ETH", "KEN",
    "ZAF", "ARG", "COL", "CHL", "PER", "VEN", "ECU", "URY", "PRY", "BOL",
}

# Lines we never want to treat as fighter names
JUNK_LINES = {
    "home", "matches", "competitions", "calendar", "media", "bet slip",
    "my bets", "north america", "combat sports betting", "in-play",
    "football", "horse racing", "tennis", "basketball", "virtuals",
    "casino", "live casino", "poker", "offers", "register", "featured",
    "top competitions", "all competitions", "all north america",
    "ufc fight night", "ufc 329", "ufc fight night betting", "2way - who will win?",
    "saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday",
    "mini games", "build a bet+", "favourites",
}

print("RUNNING BWIN UFC SCRAPER")


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def is_decimal(text):
    return bool(re.fullmatch(r"\d+\.\d+", clean(text)))


def strip_country(name):
    parts = clean(name).split()
    if len(parts) >= 2 and parts[-1].upper() in COUNTRIES:
        return " ".join(parts[:-1])
    return clean(name)


def accept_cookies(page):
    for label in ["Allow All", "Necessary Only", "Accept", "Accept All"]:
        try:
            page.get_by_text(label, exact=True).click(timeout=3000)
            print("COOKIE CLICKED:", label)
            page.wait_for_timeout(2000)
            return
        except Exception:
            pass


def scroll_and_capture(page, label="page"):
    """Scroll down fully to trigger lazy loading, then return body text."""
    print(f"  Scrolling {label}...")
    for i in range(20):
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(400)
    page.wait_for_timeout(1500)
    return page.locator("body").inner_text(timeout=60000)


def is_fighter_line(text):
    text = clean(text)
    if not text or len(text) < 4 or len(text) > 60:
        return False
    if is_decimal(text):
        return False
    # Lines with digits (dates, times, counts) are not fighters
    if re.search(r"\d", text):
        return False
    if text.lower() in JUNK_LINES:
        return False
    # Must contain at least two words (first + last name)
    if not re.search(r"[A-Za-z]+ [A-Za-z]+", text):
        return False
    return True


def extract_bwin_fights(lines, section_label=""):
    """
    Parse fighter pairs + decimal odds from a list of body-text lines.
    Does NOT require "ufc" nearby — we've already navigated to the right section.
    """
    fights = []
    seen = set()

    for i in range(len(lines) - 3):
        raw_a = lines[i]
        raw_b = lines[i + 1]

        a = strip_country(raw_a)
        b = strip_country(raw_b)

        if not is_fighter_line(a) or not is_fighter_line(b):
            continue

        # Skip if same name or obviously junk pair
        if a.lower() == b.lower():
            continue

        # Collect decimal odds immediately after the fighter pair
        odds = []
        for j in range(i + 2, min(i + 8, len(lines))):
            if is_decimal(lines[j]):
                odds.append(clean(lines[j]))
            elif odds:
                break  # stop at first non-odds line after finding some

        if len(odds) < 2:
            continue

        fight_key = f"{a.lower()}_{b.lower()}"
        if fight_key in seen:
            continue
        seen.add(fight_key)

        fight_name = f"{a} vs {b}"
        print(f"    FOUND: {fight_name} @ {odds[0]} / {odds[1]}")

        fights.append({
            "bookmaker": "Bwin",
            "fight": fight_name,
            "fight_name": fight_name,
            "url": BASE_URL,
            "section": section_label,
            "has_props": True,
            "markets": {
                "fight_betting": [
                    {"selection": a, "odds": odds[0]},
                    {"selection": b, "odds": odds[1]},
                ]
            },
        })

    return fights


def scrape_section(page, section_label, click_labels):
    """
    Navigate to a UFC section by clicking its sidebar link,
    scroll to load all fights, parse and return fights found.
    """
    print(f"\n--- Scraping section: {section_label} ---")

    # Try each possible label until one clicks
    clicked = False
    for label in click_labels:
        try:
            page.get_by_text(label, exact=False).first.click(timeout=5000)
            print(f"  Clicked: {label!r}")
            page.wait_for_timeout(3000)
            clicked = True
            break
        except Exception:
            pass

    if not clicked:
        print(f"  WARNING: could not click any label for {section_label}")
        return []

    text = scroll_and_capture(page, section_label)

    # Save debug
    safe = re.sub(r"[^a-z0-9]+", "_", section_label.lower()).strip("_")
    (DEBUG_DIR / f"bwin_{safe}_lines.txt").write_text(
        text, encoding="utf-8"
    )

    lines = [clean(x) for x in text.splitlines() if clean(x)]
    print(f"  Lines captured: {len(lines)}")

    return extract_bwin_fights(lines, section_label)


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_fights = {}  # keyed by fight_name to deduplicate

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=is_github_actions())
        page = browser.new_page(viewport={"width": 1500, "height": 1000})

        print("OPENING:", BASE_URL)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(12000)

        accept_cookies(page)
        page.wait_for_timeout(3000)

        # Scrape UFC Fight Night section
        fn_fights = scrape_section(
            page,
            "UFC Fight Night",
            ["UFC Fight Night", "UFC FIGHT NIGHT"],
        )
        for f in fn_fights:
            all_fights[f["fight_name"]] = f

        # Go back to base and scrape UFC 329 section
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)

        ufc329_fights = scrape_section(
            page,
            "UFC 329",
            ["UFC 329"],
        )
        for f in ufc329_fights:
            all_fights[f["fight_name"]] = f

        browser.close()

    fights = list(all_fights.values())

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "bwin",
        "bookmaker": "Bwin",
        "url": BASE_URL,
        "count": len(fights),
        "fights": fights,
    }

    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ Saved {len(fights)} Bwin UFC fights")
    print(f"📁 {OUT_PATH}")
    for f in fights:
        print(f"  - {f['fight_name']}")


if __name__ == "__main__":
    main()