#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH   = ROOT / "football" / "data" / "ladbrokes_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "ladbrokes_worldcup_text_debug.txt"

URL = "https://www.ladbrokes.com/en/sports/competitions/football/international/world-cup-2026"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")

WORLD_CUP_TEAMS = {
    "Mexico","South Africa","South Korea","Czech Republic","Czechia",
    "Canada","Bosnia & Herzegovina","Bosnia and Herzegovina","Bosnia",
    "USA","Paraguay","Qatar","Switzerland","Brazil","Morocco",
    "Haiti","Scotland","Australia","Turkey","Türkiye","Germany",
    "Curacao","Netherlands","Japan","Ivory Coast","Ecuador","Sweden",
    "Tunisia","Spain","Cape Verde","Belgium","Egypt","Saudi Arabia",
    "Uruguay","Iran","New Zealand","France","Senegal","Iraq","Norway",
    "Argentina","Algeria","Austria","Jordan","Portugal","DR Congo",
    "England","Croatia","Ghana","Panama","Colombia","Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic":"Czechia","Bosnia & Herzegovina":"Bosnia",
    "Bosnia and Herzegovina":"Bosnia","Turkey":"Türkiye","Turkiye":"Türkiye",
    "Curaçao":"Curacao","Bosnia &amp; Herzegovina":"Bosnia",
}

def clean(s):
    return re.sub(r"\s+"," ",str(s or "")).strip()

def canonical_team(s):
    return TEAM_ALIASES.get(clean(s), clean(s))

def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))

def is_time(s):
    return bool(TIME_RE.match(clean(s)))

def is_team(s):
    return clean(s) in WORLD_CUP_TEAMS

def dedupe(matches):
    seen = set(); unique = []
    for m in matches:
        key = (m["date_label"], m["time"], m["match"])
        if key not in seen:
            seen.add(key); unique.append(m)
    return unique

def parse_text(text):
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    matches = []
    current_date = ""
    i = 0
    while i < len(lines):
        line = lines[i]

        # Date headers: "11 Jun", "12 Jun" etc
        if re.match(r'^\d{1,2}\s+\w+$', line):
            current_date = line
            i += 1
            continue

        # Format: time / team1 / team2 / home_odds / draw_odds / away_odds
        # Ladbrokes shows: "20:00 11 Jun" or just "20:00"
        time_match = re.match(r'^(\d{1,2}:\d{2})', line)
        if time_match and i+2 < len(lines) and is_team(lines[i+1]) and is_team(lines[i+2]):
            time_label = time_match.group(1)
            home = canonical_team(lines[i+1])
            away = canonical_team(lines[i+2])
            odds = []
            for j in range(i+3, min(i+15, len(lines))):
                if is_odds(lines[j]):
                    odds.append(lines[j].upper())
                    if len(odds) == 3:
                        break
            if len(odds) == 3:
                matches.append({
                    "competition": "FIFA World Cup",
                    "bookmaker": "Ladbrokes",
                    "date_label": current_date,
                    "time": time_label,
                    "match": f"{home} v {away}",
                    "home_team": home, "away_team": away,
                    "market": "Match Odds",
                    "odds": {"home": odds[0], "draw": odds[1], "away": odds[2]},
                    "source_url": URL,
                })
                i += 6
                continue

        # Also try: team1 / team2 / time pattern
        if is_team(line) and i+1 < len(lines) and is_team(lines[i+1]):
            home = canonical_team(line)
            away = canonical_team(lines[i+1])
            # Find time nearby
            time_label = ""
            for j in range(max(0,i-3), i):
                if is_time(lines[j]) or re.match(r'^\d{1,2}:\d{2}', lines[j]):
                    time_label = re.match(r'^(\d{1,2}:\d{2})', lines[j]).group(1)
                    break
            odds = []
            for j in range(i+2, min(i+15, len(lines))):
                if is_odds(lines[j]):
                    odds.append(lines[j].upper())
                    if len(odds) == 3:
                        break
            if len(odds) == 3:
                matches.append({
                    "competition": "FIFA World Cup",
                    "bookmaker": "Ladbrokes",
                    "date_label": current_date,
                    "time": time_label,
                    "match": f"{home} v {away}",
                    "home_team": home, "away_team": away,
                    "market": "Match Odds",
                    "odds": {"home": odds[0], "draw": odds[1], "away": odds[2]},
                    "source_url": URL,
                })
                i += 5
                continue

        i += 1
    return dedupe(matches)

def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        print(f"Opening {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)

        for label in ["Accept All","Accept all","I Accept","Accept","Agree","Allow all","Got it"]:
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if btn.count():
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

        for i in range(30):
            print(f"Scrolling {i+1}/30...")
            page.mouse.wheel(0, 700)
            page.wait_for_timeout(500)

        text = page.locator("body").inner_text(timeout=30000)
        DEBUG_PATH.write_text(text, encoding="utf-8")
        browser.close()

    matches = parse_text(text)

    output = {
        "sport": "football", "competition": "FIFA World Cup",
        "bookmaker": "Ladbrokes", "market": "Match Odds",
        "source_url": URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(matches), "matches": matches,
    }
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved {len(matches)} Ladbrokes World Cup matches")
    for m in matches[:20]:
        print(f"- {m['date_label']} {m['time']} | {m['match']} | H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}")

    if not matches:
        print(f"Debug saved to: {DEBUG_PATH}")

if __name__ == "__main__":
    main()