#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "boylesports_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "boylesports_worldcup_text_debug.txt"

URL = "https://www.boylesports.com/sports/football/competition/international-world-cup"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|Evens)$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DATE_RE = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}\s+\w+\s+\d{4}$",
    re.I,
)

WORLD_CUP_TEAMS = {
    "Mexico",
    "South Africa",
    "South Korea",
    "Czechia",
    "Canada",
    "Bosnia & Herzegovina",
    "Bosnia",
    "USA",
    "Paraguay",
    "Qatar",
    "Switzerland",
    "Brazil",
    "Morocco",
    "Haiti",
    "Scotland",
    "Australia",
    "Turkey",
    "Türkiye",
    "Germany",
    "Curacao",
    "Curacao",
    "Netherlands",
    "Japan",
    "Ivory Coast",
    "Ecuador",
    "Sweden",
    "Tunisia",
    "Spain",
    "Cape Verde",
    "Belgium",
    "Egypt",
    "Saudi Arabia",
    "Uruguay",
    "Iran",
    "New Zealand",
    "France",
    "Senegal",
    "Iraq",
    "Norway",
    "Argentina",
    "Algeria",
    "Austria",
    "Jordan",
    "Portugal",
    "DR Congo",
    "England",
    "Croatia",
    "Ghana",
    "Panama",
    "Colombia",
    "Uzbekistan",
}

TEAM_ALIASES = {
    "Bosnia & Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Ivory Coast": "Ivory Coast",
}


SKIP_LINES = {
    "Home",
    "Draw",
    "Away",
    "Match Betting",
    "Available offers",
    "World Cup",
    "Betslip",
    "My Bets",
    "Betslip Empty",
    "Gaming Quick Links",
    "Football",
    "Popular",
    "Time",
    "Competition",
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


def is_date(s):
    return bool(DATE_RE.match(clean(s)))


def is_worldcup_team(s):
    s = clean(s)
    return s in WORLD_CUP_TEAMS


def is_team_line(s):
    s = clean(s)

    if not s:
        return False

    if s in SKIP_LINES:
        return False

    if is_odds(s) or is_time(s) or is_date(s):
        return False

    if len(s) > 45:
        return False

    return is_worldcup_team(s)


def parse_boylesports_text(text):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    matches = []
    current_date = ""

    i = 0

    while i < len(lines):
        line = lines[i]

        if is_date(line):
            current_date = line
            i += 1
            continue

        # BoyleSports order:
        # Team A
        # Team B
        # Time
        # Home odds
        # Draw odds
        # Away odds
        if (
            i + 5 < len(lines)
            and is_team_line(lines[i])
            and is_team_line(lines[i + 1])
            and is_time(lines[i + 2])
            and is_odds(lines[i + 3])
            and is_odds(lines[i + 4])
            and is_odds(lines[i + 5])
        ):
            home = canonical_team(lines[i])
            away = canonical_team(lines[i + 1])

            if home == away:
                i += 1
                continue

            matches.append(
                {
                    "competition": "FIFA World Cup",
                    "bookmaker": "BoyleSports",
                    "date_label": current_date,
                    "time": lines[i + 2],
                    "match": f"{home} v {away}",
                    "home_team": home,
                    "away_team": away,
                    "market": "Match Odds",
                    "odds": {
                        "home": lines[i + 3].upper(),
                        "draw": lines[i + 4].upper(),
                        "away": lines[i + 5].upper(),
                    },
                    "source_url": URL,
                }
            )

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


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        print(f"Opening {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all"]:
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if btn.count():
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

        try:
            page.get_by_text("Match Betting", exact=True).first.click(timeout=4000)
            page.wait_for_timeout(2500)
        except Exception:
            pass

        for i in range(22):
            print(f"Loading page section {i + 1}/22...")
            page.mouse.wheel(0, 700)
            page.wait_for_timeout(650)

        text = page.locator("body").inner_text(timeout=30000)
        DEBUG_PATH.write_text(text, encoding="utf-8")

        matches = parse_boylesports_text(text)

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "BoyleSports",
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

        print(f"\nSaved {len(matches)} BoyleSports World Cup moneyline matches to:")
        print(OUT_PATH)

        if matches:
            print("\nSample:")
            for m in matches[:100]:
                print(
                    f"- {m['date_label']} {m['time']} | {m['match']} | "
                    f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}"
                )
        else:
            print("\nNo BoyleSports World Cup matches found.")
            print(f"Debug text saved to: {DEBUG_PATH}")

        print("\nDone. Press Enter to close browser...")
        input()

        browser.close()


if __name__ == "__main__":
    main()