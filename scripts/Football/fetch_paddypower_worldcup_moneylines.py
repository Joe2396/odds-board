#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "paddypower_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "paddypower_worldcup_text_debug.txt"

URL = "https://www.paddypower.com/fifa-world-cup"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|Evens)$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DATE_RE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d+$",
    re.I,
)

SKIP_LINES = {
    "Home",
    "Draw",
    "Away",
    "Offer",
    "FIFA World Cup",
    "Matches",
    "Outrights",
    "Awards",
    "Confederations",
    "Groups",
    "Main Outrights",
    "Stage of Elimination",
    "To Reach",
    "Specials",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_time(s):
    return bool(TIME_RE.match(clean(s)))


def is_date(s):
    return bool(DATE_RE.match(clean(s)))


def is_team_line(s):
    s = clean(s)

    if not s:
        return False

    if s in SKIP_LINES:
        return False

    if is_odds(s) or is_time(s) or is_date(s):
        return False

    bad_parts = [
        "Sports",
        "Search",
        "Login",
        "Sign Up",
        "Betslip",
        "Most Popular",
        "Horse Racing",
        "In-Play",
        "Lotteries",
        "Greyhound",
        "Golf",
        "For You",
        "Eliminator",
        "Beat The Drop",
        "Wonder Wheel",
        "Promotions",
        "Set a Limit",
        "Racing Results",
        "Shop Exclusives",
        "Virtuals",
        "Games",
        "Paddy",
        "Give Feedback",
        "Browse All",
        "American Football",
        "Australian Rules",
        "Baseball",
        "Basketball",
        "Boxing",
        "Cricket",
        "Cycling",
        "Darts",
        "Esports",
        "Futsal",
        "Gaelic",
        "Handball",
        "Ice Hockey",
        "Motor Sport",
        "Politics",
        "Rugby",
        "Snooker",
        "Special Bets",
        "Table Tennis",
        "Tennis",
        "Volleyball",
        "Looks like",
        "Help",
        "FREE BET",
        "promo",
        "T&Cs",
        "Warning",
        "Gambling",
        "Commission",
        "Malta",
        "Privacy",
        "Cookie",
        "Terms",
        "Underage",
        "World Cup 2026",
        "Winner Odds",
        "Group",
        "England Odds",
        "Spain Odds",
        "France Odds",
        "Argentina Odds",
        "Brazil Odds",
        "Germany Odds",
        "Portugal Odds",
    ]

    low = s.lower()

    for bad in bad_parts:
        if bad.lower() in low:
            return False

    if len(s) > 40:
        return False

    return True


def parse_sequential_worldcup_text(text):
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

        # Expected sequence from real PaddyPower debug text:
        # Team A
        # Team B
        # Home odds
        # Draw odds
        # Away odds
        # Time
        # Offer
        if (
            i + 5 < len(lines)
            and is_team_line(lines[i])
            and is_team_line(lines[i + 1])
            and is_odds(lines[i + 2])
            and is_odds(lines[i + 3])
            and is_odds(lines[i + 4])
            and is_time(lines[i + 5])
        ):
            home = lines[i]
            away = lines[i + 1]
            home_odds = lines[i + 2]
            draw_odds = lines[i + 3]
            away_odds = lines[i + 4]
            time_label = lines[i + 5]

            matches.append(
                {
                    "competition": "FIFA World Cup",
                    "bookmaker": "PaddyPower",
                    "date_label": current_date,
                    "time": time_label,
                    "match": f"{home} v {away}",
                    "home_team": home,
                    "away_team": away,
                    "market": "Match Odds",
                    "odds": {
                        "home": home_odds.upper(),
                        "draw": draw_odds.upper(),
                        "away": away_odds.upper(),
                    },
                    "source_url": URL,
                }
            )

            i += 7
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
        page.wait_for_timeout(7000)

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
            page.get_by_text("Matches", exact=True).first.click(timeout=4000)
            page.wait_for_timeout(2500)
        except Exception:
            pass

        for i in range(18):
            print(f"Loading page section {i + 1}/18...")
            page.mouse.wheel(0, 700)
            page.wait_for_timeout(650)

        text = page.locator("body").inner_text(timeout=30000)
        DEBUG_PATH.write_text(text, encoding="utf-8")

        matches = parse_sequential_worldcup_text(text)

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "PaddyPower",
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

        print(f"\nSaved {len(matches)} World Cup moneyline matches to:")
        print(OUT_PATH)

        if matches:
            print("\nSample:")
            for m in matches[:80]:
                print(
                    f"- {m['date_label']} {m['time']} | {m['match']} | "
                    f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}"
                )
        else:
            print("\nNo clean World Cup matches found.")
            print(f"Debug text saved to: {DEBUG_PATH}")

        

        browser.close()


if __name__ == "__main__":
    main()
