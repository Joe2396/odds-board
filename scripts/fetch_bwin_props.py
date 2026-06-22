from pathlib import Path
from datetime import datetime, timezone
import json
import re
from playwright.sync_api import sync_playwright
import os

def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


ROOT = Path(__file__).resolve().parents[1]

OUT_PATH = ROOT / "ufc" / "data" / "bwin_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

URL = "https://sports.bwin.com/en/sports/combat-sports-45/betting/north-america-9"

COUNTRIES = {
    "USA", "IRL", "BRA", "CHN", "GBR", "ENG", "FRA", "RUS", "CAN", "AUS",
    "MEX", "ESP", "GER", "POL", "SWE", "NOR", "KAZ", "GEO", "JPN", "KOR"
}

print("RUNNING BWIN UFC SCRAPER")


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def is_decimal(text):
    return bool(re.fullmatch(r"\d+\.\d+", clean(text)))


def strip_country(name):
    parts = clean(name).split()
    if parts and parts[-1].upper() in COUNTRIES:
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


def click_ufc_sections(page):
    for label in [
        "UFC 329",
        "UFC Fight Night",
        "UFC FIGHT NIGHT",
        "UFC Freedom 250",
    ]:
        try:
            page.get_by_text(label, exact=False).first.click(timeout=4000)
            print("CLICKED/TOUCHED:", label)
            page.wait_for_timeout(2500)
        except Exception:
            pass


def scroll_page(page):
    for _ in range(10):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(1000)


def is_fighter_line(text):
    text = clean(text)
    if not text:
        return False
    if is_decimal(text):
        return False
    if re.search(r"\d", text):
        return False
    if text.lower() in {
        "home", "matches", "competitions", "calendar", "media",
        "bet slip", "my bets", "north america", "combat sports betting"
    }:
        return False
    return bool(re.search(r"[A-Za-z]+ [A-Za-z]+", text))


def extract_bwin_fights(lines):
    fights = []

    for i in range(len(lines) - 4):
        a = strip_country(lines[i])
        b = strip_country(lines[i + 1])

        if not is_fighter_line(a) or not is_fighter_line(b):
            continue

        odds = []
        for j in range(i + 2, min(i + 10, len(lines))):
            if is_decimal(lines[j]):
                odds.append(clean(lines[j]))

        if len(odds) < 2:
            continue

        nearby = " ".join(lines[max(0, i - 30):min(len(lines), i + 30)]).lower()
        if "ufc" not in nearby:
            continue

        fight_name = f"{a} vs {b}"

        fights.append({
            "bookmaker": "Bwin",
            "fight": fight_name,
            "fight_name": fight_name,
            "url": URL,
            "markets": {
                "fight_betting": [
                    {"selection": a, "odds": odds[0]},
                    {"selection": b, "odds": odds[1]},
                ]
            },
        })

    return fights


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=is_github_actions())
        page = browser.new_page(viewport={"width": 1500, "height": 1000})

        print("OPENING:", URL)
        page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(12000)

        accept_cookies(page)
        page.wait_for_timeout(3000)

        click_ufc_sections(page)
        scroll_page(page)

        text = page.locator("body").inner_text(timeout=60000)

        lines = [clean(x) for x in text.splitlines() if clean(x)]

        (DEBUG_DIR / "bwin_lines.txt").write_text(
            "\n".join(f"{i}: {repr(x)}" for i, x in enumerate(lines)),
            encoding="utf-8"
        )

        print("LINES FOUND:", len(lines))

        fights = extract_bwin_fights(lines)

        browser.close()

    unique = {}
    for fight in fights:
        unique[fight["fight_name"]] = fight

    fights = list(unique.values())

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "bwin",
        "bookmaker": "Bwin",
        "url": URL,
        "count": len(fights),
        "fights": fights,
    }

    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✅ Saved {len(fights)} Bwin UFC fights")
    print(f"📁 {OUT_PATH}")

    for fight in fights:
        print(" -", fight["fight_name"])


if __name__ == "__main__":
    main()