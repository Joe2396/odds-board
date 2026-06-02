#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "williamhill_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "williamhill_worldcup_text_debug.txt"

URL = "https://sports.williamhill.com/betting/en-gb/football/competitions/OB_TY52321/world-cup-2026/matches"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DATE_RE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+\d{1,2}\s+\w+$", re.I)

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


def is_time_token(s):
    return bool(TIME_RE.match(clean(s)))


def extract_time(line):
    first = clean(line).split(" ")[0] if clean(line) else ""
    return first if is_time_token(first) else ""


def is_date(s):
    return bool(DATE_RE.match(clean(s)))


def is_team_line(s):
    return clean(s) in WORLD_CUP_TEAMS


def dedupe(matches):
    seen = set()
    unique = []
    for m in matches:
        key = (m["date_label"], m["time"], m["match"])
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


def parse_williamhill_text(text):
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

        time_label = extract_time(line)

        if time_label:
            # Look ahead for first two team lines.
            # This handles:
            # 03:00
            # ITV 1
            # South Korea
            # Czech Republic
            team_indexes = []
            for j in range(i + 1, min(i + 10, len(lines))):
                if is_team_line(lines[j]):
                    team_indexes.append(j)
                    if len(team_indexes) == 2:
                        break

            if len(team_indexes) == 2:
                home_idx, away_idx = team_indexes
                home = canonical_team(lines[home_idx])
                away = canonical_team(lines[away_idx])

                odds = []
                for j in range(away_idx + 1, min(away_idx + 30, len(lines))):
                    if is_odds(lines[j]):
                        odds.append(lines[j].upper())
                        if len(odds) == 3:
                            break

                if len(odds) == 3:
                    matches.append({
                        "competition": "FIFA World Cup",
                        "bookmaker": "WilliamHill",
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

                    i = away_idx + 4
                    continue

        i += 1

    return dedupe(matches)


def scrape_snapshot(page, all_text, all_matches, label):
    text = page.locator("body").inner_text(timeout=30000)
    all_text.append(f"\n\n--- {label} ---\n\n{text}")
    all_matches.extend(parse_williamhill_text(text))
    all_matches[:] = dedupe(all_matches)
    print(f"{label}: {len(all_matches)} matches")


def set_scroll_top(page, y):
    page.evaluate(
        """
        (y) => {
            document.scrollingElement.scrollTop = y;
            window.scrollTo(0, y);
        }
        """,
        y,
    )


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

        # Do NOT click Match Betting. It opens the markets popup.

        try:
            set_scroll_top(page, 0)
            page.wait_for_timeout(1200)
        except Exception:
            pass

        scroll_height = int(page.evaluate("document.scrollingElement.scrollHeight"))
        client_height = int(page.evaluate("document.scrollingElement.clientHeight"))
        max_y = max(scroll_height - client_height, 0)

        positions = list(range(0, max_y + 1, 160))
        if max_y not in positions:
            positions.append(max_y)

        for pass_no in range(1, 5):
            print(f"\nScroll pass {pass_no}/4")

            for idx, y in enumerate(positions):
                set_scroll_top(page, y)
                page.wait_for_timeout(500)
                scrape_snapshot(page, all_text, all_matches, f"pass {pass_no} y={y} step {idx + 1}/{len(positions)}")

            scroll_height = int(page.evaluate("document.scrollingElement.scrollHeight"))
            client_height = int(page.evaluate("document.scrollingElement.clientHeight"))
            max_y = max(scroll_height - client_height, 0)

            positions = list(range(0, max_y + 1, 160))
            if max_y not in positions:
                positions.append(max_y)

        DEBUG_PATH.write_text("\n\n".join(all_text), encoding="utf-8")

        matches = dedupe(all_matches)

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "WilliamHill",
            "market": "Match Odds",
            "source_url": URL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "match_count": len(matches),
            "matches": matches,
        }

        OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"\nSaved {len(matches)} William Hill World Cup moneyline matches to:")
        print(OUT_PATH)

        if matches:
            print("\nSample:")
            for m in matches[:140]:
                print(
                    f"- {m['date_label']} {m['time']} | {m['match']} | "
                    f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}"
                )
        else:
            print("\nNo William Hill World Cup matches found.")
            print(f"Debug text saved to: {DEBUG_PATH}")

        print("\nDone. Press Enter to close browser...")
        input()

        browser.close()


if __name__ == "__main__":
    main()