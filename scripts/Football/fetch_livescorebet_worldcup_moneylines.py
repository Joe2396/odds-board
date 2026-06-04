#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "livescorebet_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "livescorebet_worldcup_text_debug.txt"

URL = "https://www.livescorebet.com/ie/coupon/21127/"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
DATE_TIME_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}$")

WORLD_CUP_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic", "Czechia",
    "Canada", "Bosnia & Herzegovina", "Bosnia and Herzegovina", "Bosnia",
    "USA", "Paraguay", "Qatar", "Switzerland", "Brazil", "Morocco",
    "Haiti", "Scotland", "Australia", "Turkey", "Turkiye", "Türkiye",
    "Germany", "Curacao", "Curaçao", "Netherlands", "Japan",
    "Ivory Coast", "Ecuador", "Sweden", "Tunisia", "Spain",
    "Cape Verde", "Cape Verde Islands", "Belgium", "Egypt",
    "Saudi Arabia", "Uruguay", "Iran", "New Zealand", "France",
    "Senegal", "Iraq", "Norway", "Argentina", "Algeria", "Austria",
    "Jordan", "Portugal", "DR Congo", "England", "Croatia", "Ghana",
    "Panama", "Colombia", "Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
    "Cape Verde Islands": "Cape Verde",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    s = clean(s)
    return TEAM_ALIASES.get(s, s)


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_datetime(s):
    return bool(DATE_TIME_RE.match(clean(s)))


def is_team_line(s):
    return clean(s) in WORLD_CUP_TEAMS


def split_datetime(s):
    s = clean(s)
    try:
        date_part, time_part = s.split(" ", 1)
        return date_part, time_part
    except Exception:
        return "", ""


def parse_livescorebet_text(text):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    matches = []
    i = 0

    while i < len(lines):
        # LiveScoreBet actual format from debug:
        # Mexico
        # South Africa
        # 21/50
        # 17/5
        # 15/2
        # 11/6/2026 20:00
        if (
            i + 5 < len(lines)
            and is_team_line(lines[i])
            and is_team_line(lines[i + 1])
            and is_odds(lines[i + 2])
            and is_odds(lines[i + 3])
            and is_odds(lines[i + 4])
            and is_datetime(lines[i + 5])
        ):
            home = canonical_team(lines[i])
            away = canonical_team(lines[i + 1])
            date_label, time_label = split_datetime(lines[i + 5])

            matches.append({
                "competition": "FIFA World Cup",
                "bookmaker": "LiveScoreBet",
                "date_label": date_label,
                "time": time_label,
                "match": f"{home} v {away}",
                "home_team": home,
                "away_team": away,
                "market": "Match Odds",
                "odds": {
                    "home": lines[i + 2].upper(),
                    "draw": lines[i + 3].upper(),
                    "away": lines[i + 4].upper(),
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


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        print(f"Opening {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)

        for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "Got it"]:
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if btn.count():
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

        try:
            page.get_by_text("1 X 2", exact=True).first.click(timeout=3000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception:
            pass

        for i in range(28):
            print(f"Loading page section {i + 1}/28...")
            page.mouse.wheel(0, 750)
            page.wait_for_timeout(650)

        text = page.locator("body").inner_text(timeout=30000)
        DEBUG_PATH.write_text(text, encoding="utf-8")

        matches = parse_livescorebet_text(text)

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "LiveScoreBet",
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

        print(f"\nSaved {len(matches)} LiveScoreBet World Cup moneyline matches to:")
        print(OUT_PATH)

        if matches:
            print("\nSample:")
            for m in matches[:100]:
                print(
                    f"- {m['date_label']} {m['time']} | {m['match']} | "
                    f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}"
                )
        else:
            print("\nNo LiveScoreBet World Cup matches found.")
            print(f"Debug text saved to: {DEBUG_PATH}")


        browser.close()


if __name__ == "__main__":
    main()
