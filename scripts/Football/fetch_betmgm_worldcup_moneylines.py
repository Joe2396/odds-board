#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "betmgm_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "betmgm_worldcup_text_debug.txt"

URL = "https://www.betmgm.co.uk/sports#all-sports"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|Evens)$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DATE_SHORT_RE = re.compile(r"^\d{1,2}\s+\w+$", re.I)

WORLD_CUP_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic", "Czechia",
    "Canada", "Bosnia & Herzegovina", "Bosnia and Herzegovina", "Bosnia",
    "USA", "Paraguay", "Qatar", "Switzerland", "Brazil", "Morocco",
    "Haiti", "Scotland", "Australia", "Turkey", "Turkiye", "Türkiye",
    "Germany", "Curacao", "Curaçao", "Netherlands", "Japan",
    "Ivory Coast", "Ecuador", "Sweden", "Tunisia", "Spain",
    "Cape Verde", "Belgium", "Egypt", "Saudi Arabia", "Uruguay", "Iran",
    "New Zealand", "France", "Senegal", "Iraq", "Norway", "Argentina",
    "Algeria", "Austria", "Jordan", "Portugal", "DR Congo", "England",
    "Croatia", "Ghana", "Panama", "Colombia", "Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
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


def is_time(s):
    return bool(TIME_RE.match(clean(s)))


def is_date_short(s):
    return bool(DATE_SHORT_RE.match(clean(s)))


def is_team_line(s):
    return clean(s) in WORLD_CUP_TEAMS


def parse_betmgm_text(text):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    matches = []
    current_date = ""

    i = 0

    while i < len(lines):
        line = lines[i]

        if is_date_short(line):
            current_date = line
            i += 1
            continue

        # BetMGM format:
        # Mexico
        # South Africa
        # 20:00
        # 2/5
        # 17/5
        # 7/1
        if (
            i + 5 < len(lines)
            and is_team_line(lines[i])
            and is_team_line(lines[i + 1])
            and is_time(lines[i + 2])
        ):
            home = canonical_team(lines[i])
            away = canonical_team(lines[i + 1])
            time_label = lines[i + 2]

            odds = []
            for j in range(i + 3, min(i + 15, len(lines))):
                if is_odds(lines[j]):
                    odds.append(lines[j].upper())
                    if len(odds) == 3:
                        break

            if len(odds) == 3:
                matches.append({
                    "competition": "FIFA World Cup",
                    "bookmaker": "BetMGM",
                    "date_label": current_date,
                    "time": time_label,
                    "match": f"{home} v {away}",
                    "home_team": home,
                    "away_team": away,
                    "market": "Match Odds",
                    "odds": {
                        "home": odds[0],
                        "draw": odds[1],
                        "away": odds[2],
                    },
                    "source_url": URL,
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


def open_search_and_type_world_cup(page):
    print("Opening BetMGM search box...")

    # Click the search icon using coordinates from the top bar.
    # Your screenshot shows the icon around x=1340, y=128 on 1700px viewport.
    clicked = False
    for x, y in [
        (1340, 130),
        (1300, 130),
        (1240, 198),
        (1100, 198),
    ]:
        try:
            page.mouse.click(x, y)
            page.wait_for_timeout(1200)
            clicked = True
            break
        except Exception:
            pass

    # Now fill the real visible search input.
    filled = False

    selectors = [
        "input[data-testid='search-input']",
        "input[placeholder='Find events or leagues...']",
        "input[placeholder*='Find events']",
        "input[type='search']",
    ]

    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count():
                loc.first.click(timeout=3000)
                loc.first.fill("world cup", timeout=3000)
                page.wait_for_timeout(1500)

                # BetMGM needs Enter to actually trigger/confirm the search.
                page.keyboard.press("Enter")
                page.wait_for_timeout(5000)

                filled = True
                break
        except Exception:
            pass

    # Fallback if selector failed but search panel is open.
    if not filled:
        try:
            page.keyboard.type("world cup", delay=70)
            page.wait_for_timeout(1000)
            page.keyboard.press("Enter")
            page.wait_for_timeout(5000)
            filled = True
        except Exception:
            pass

    print(f"Search icon clicked: {clicked}, search filled: {filled}")

    try:
        page.get_by_text("World Cup 2026", exact=True).wait_for(timeout=10000)
        print("World Cup 2026 found.")
    except Exception:
        print("World Cup 2026 not found yet. Continuing anyway.")


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        print(f"Opening {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)

        for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all"]:
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if btn.count():
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

        open_search_and_type_world_cup(page)

        # Make sure we are near the top of the filtered results.
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception:
            pass

        for i in range(24):
            print(f"Loading page section {i + 1}/24...")
            page.mouse.wheel(0, 750)
            page.wait_for_timeout(650)

        text = page.locator("body").inner_text(timeout=30000)
        DEBUG_PATH.write_text(text, encoding="utf-8")

        matches = parse_betmgm_text(text)

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "BetMGM",
            "market": "Match Odds",
            "source_url": URL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "match_count": len(matches),
            "matches": matches,
        }

        OUT_PATH.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"\nSaved {len(matches)} BetMGM World Cup moneyline matches to:")
        print(OUT_PATH)

        if matches:
            print("\nSample:")
            for m in matches[:100]:
                print(
                    f"- {m['date_label']} {m['time']} | {m['match']} | "
                    f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}"
                )
        else:
            print("\nNo BetMGM World Cup matches found.")
            print(f"Debug text saved to: {DEBUG_PATH}")

        print("\nDone. Press Enter to close browser...")
        input()

        browser.close()


if __name__ == "__main__":
    main()