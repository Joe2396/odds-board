#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "betfred_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "betfred_worldcup_text_debug.txt"

URL = "https://www.betfred.com/sports/football/competition/fifa-world-cup"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DATE_RE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+\w+$", re.I)

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
    "Jordan", "Portugal", "DR Congo", "Congo DR", "England", "Croatia",
    "Ghana", "Panama", "Colombia", "Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
    "Cape Verde Islands": "Cape Verde",
    "Congo DR": "DR Congo",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    return TEAM_ALIASES.get(clean(s), clean(s))


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_time(s):
    return bool(TIME_RE.match(clean(s)))


def is_date(s):
    return bool(DATE_RE.match(clean(s)))


def is_team_line(s):
    return clean(s) in WORLD_CUP_TEAMS


def dedupe(matches):
    seen = set()
    unique = []

    for m in matches:
        key = (m["date_label"], m["time"], m["match"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)

    return unique


def parse_betfred_text(text):
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

        # Betfred visible format from screenshot:
        # Mexico
        # South Africa
        # Thu 11 Jun 20:00
        # ITV
        # Home
        # 4/9
        # Draw
        # 16/5
        # Away
        # 7/1
        if (
            i + 8 < len(lines)
            and is_team_line(lines[i])
            and is_team_line(lines[i + 1])
        ):
            home = canonical_team(lines[i])
            away = canonical_team(lines[i + 1])

            nearby = lines[i:i + 22]
            date_label = current_date
            time_label = ""
            odds = []

            for item in nearby:
                # Handles "Thu 11 Jun 20:00"
                bits = item.split()
                if len(bits) >= 4 and is_date(" ".join(bits[:3])) and is_time(bits[-1]):
                    date_label = " ".join(bits[:3])
                    time_label = bits[-1]

                if is_odds(item):
                    odds.append(item.upper())
                    if len(odds) == 3:
                        break

            if not time_label:
                for item in nearby:
                    if is_time(item):
                        time_label = item
                        break

            if len(odds) == 3 and time_label:
                matches.append({
                    "competition": "FIFA World Cup",
                    "bookmaker": "Betfred",
                    "date_label": date_label,
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

                i += 8
                continue

        i += 1

    return dedupe(matches)


def expand_all_dates(page):
    """
    Betfred keeps most dates collapsed.
    Click visible date rows repeatedly while scrolling.
    """
    clicked_total = 0

    for pass_no in range(1, 5):
        print(f"Expanding date rows pass {pass_no}/4...")

        try:
            date_rows = page.locator("text=/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s+\\d{1,2}\\s+\\w+$/")
            count = date_rows.count()
        except Exception:
            count = 0

        for i in range(count):
            try:
                row = date_rows.nth(i)
                label = clean(row.inner_text(timeout=1000))
                box = row.bounding_box()

                if not box:
                    continue

                print(f"Clicking date row: {label}")
                row.click(timeout=2000)
                page.wait_for_timeout(650)
                clicked_total += 1
            except Exception:
                pass

        page.mouse.wheel(0, 900)
        page.wait_for_timeout(900)

    return clicked_total


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    all_text = []
    all_matches = []

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
            page.get_by_text("MATCHES", exact=True).first.click(timeout=3000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        try:
            page.get_by_text("Match Result", exact=True).first.click(timeout=3000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception:
            pass

        clicked = expand_all_dates(page)
        print(f"Date rows clicked: {clicked}")

        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception:
            pass

        for i in range(80):
            print(f"Loading page section {i + 1}/80...")

            text = page.locator("body").inner_text(timeout=30000)
            all_text.append(text)

            found = parse_betfred_text(text)
            all_matches.extend(found)
            all_matches = dedupe(all_matches)

            page.mouse.wheel(0, 650)
            page.wait_for_timeout(650)

        DEBUG_PATH.write_text(
            "\n\n--- PAGE SNAPSHOT ---\n\n".join(all_text),
            encoding="utf-8",
        )

        matches = dedupe(all_matches)

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "Betfred",
            "market": "Match Odds",
            "source_url": URL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "match_count": len(matches),
            "matches": matches,
        }

        OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"\nSaved {len(matches)} Betfred World Cup moneyline matches to:")
        print(OUT_PATH)

        if matches:
            print("\nSample:")
            for m in matches[:120]:
                print(
                    f"- {m['date_label']} {m['time']} | {m['match']} | "
                    f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}"
                )
        else:
            print("\nNo Betfred World Cup matches found.")
            print(f"Debug text saved to: {DEBUG_PATH}")


        browser.close()


if __name__ == "__main__":
    main()
