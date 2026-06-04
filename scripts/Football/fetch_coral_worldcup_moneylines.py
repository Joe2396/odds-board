#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "coral_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "coral_worldcup_text_debug.txt"

HOME_URL = "https://sports.coral.co.uk/en/sports"
WORLD_CUP_URL = "https://sports.coral.co.uk/en/sports/big-competition/world-cup/matches"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|Evens)$", re.I)
TIME_DATE_RE = re.compile(r"^\d{1,2}:\d{2},\s*\d{1,2}\s+\w+$", re.I)

WORLD_CUP_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czechia", "Canada", "Bosnia",
    "Bosnia & Herzegovina", "USA", "Paraguay", "Qatar", "Switzerland",
    "Brazil", "Morocco", "Haiti", "Scotland", "Australia", "Turkey",
    "Turkiye", "Türkiye", "Germany", "Curacao", "Curaçao", "Netherlands",
    "Japan", "Ivory Coast", "Ecuador", "Sweden", "Tunisia", "Spain",
    "Cape Verde", "Belgium", "Egypt", "Saudi Arabia", "Uruguay", "Iran",
    "New Zealand", "France", "Senegal", "Iraq", "Norway", "Argentina",
    "Algeria", "Austria", "Jordan", "Portugal", "DR Congo", "England",
    "Croatia", "Ghana", "Panama", "Colombia", "Uzbekistan",
}

TEAM_ALIASES = {
    "Bosnia & Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    s = clean(s)
    return TEAM_ALIASES.get(s, s)


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_time_date(s):
    return bool(TIME_DATE_RE.match(clean(s)))


def is_team_line(s):
    return clean(s) in WORLD_CUP_TEAMS


def parse_coral_text(text):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    matches = []
    i = 0

    while i < len(lines):
        if (
            i + 5 < len(lines)
            and is_team_line(lines[i])
            and is_team_line(lines[i + 1])
            and is_time_date(lines[i + 2])
            and is_odds(lines[i + 3])
            and is_odds(lines[i + 4])
            and is_odds(lines[i + 5])
        ):
            home = canonical_team(lines[i])
            away = canonical_team(lines[i + 1])
            time_part, date_part = [clean(x) for x in lines[i + 2].split(",", 1)]

            matches.append({
                "competition": "FIFA World Cup",
                "bookmaker": "Coral",
                "date_label": date_part,
                "time": time_part,
                "match": f"{home} v {away}",
                "home_team": home,
                "away_team": away,
                "market": "Match Odds",
                "odds": {
                    "home": lines[i + 3].upper(),
                    "draw": lines[i + 4].upper(),
                    "away": lines[i + 5].upper(),
                },
                "source_url": WORLD_CUP_URL,
            })

            i += 6
            continue

        i += 1

    seen = set()
    unique = []

    for m in matches:
        key = (m["date_label"], m["time"], m["match"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)

    return unique


def click_text(page, text, exact=True, timeout=6000):
    try:
        loc = page.get_by_text(text, exact=exact)
        count = loc.count()
        print(f"Found '{text}': {count}")
        if count:
            loc.first.click(timeout=timeout)
            page.wait_for_timeout(4000)
            return True
    except Exception as e:
        print(f"Could not click '{text}': {e}")
    return False


def open_worldcup_page(page):
    print("Opening Coral sports homepage...")
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    print("Current URL:", page.url)

    # Click the top nav WORLD CUP tab.
    clicked_wc = click_text(page, "WORLD CUP", exact=True, timeout=8000)

    # If click didn't navigate, try direct deep link after homepage session is warm.
    if not clicked_wc:
        print("Trying direct World Cup URL after session warm-up...")
        page.goto(WORLD_CUP_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

    print("After World Cup click URL:", page.url)

    # The World Cup page sometimes needs the big/tournament header clicked.
    click_text(page, "WORLD CUP 2026", exact=True, timeout=8000)

    # Click MATCHES tab.
    click_text(page, "MATCHES", exact=True, timeout=8000)

    # Wait for group games/match text.
    try:
        page.get_by_text("GROUP GAMES", exact=True).wait_for(timeout=12000)
        print("GROUP GAMES found.")
    except Exception:
        print("GROUP GAMES not found yet.")

    print("Final URL before scrape:", page.url)
    page.wait_for_timeout(4000)


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        open_worldcup_page(page)

        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1500)
        except Exception:
            pass

        for i in range(24):
            print(f"Loading page section {i + 1}/24...")
            page.mouse.wheel(0, 750)
            page.wait_for_timeout(650)

        text = page.locator("body").inner_text(timeout=30000)
        DEBUG_PATH.write_text(text, encoding="utf-8")

        matches = parse_coral_text(text)

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "Coral",
            "market": "Match Odds",
            "source_url": WORLD_CUP_URL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "match_count": len(matches),
            "matches": matches,
        }

        OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"\nSaved {len(matches)} Coral World Cup moneyline matches to:")
        print(OUT_PATH)

        if matches:
            print("\nSample:")
            for m in matches[:100]:
                print(
                    f"- {m['date_label']} {m['time']} | {m['match']} | "
                    f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}"
                )
        else:
            print("\nNo Coral World Cup matches found.")
            print(f"Debug text saved to: {DEBUG_PATH}")


        browser.close()


if __name__ == "__main__":
    main()
