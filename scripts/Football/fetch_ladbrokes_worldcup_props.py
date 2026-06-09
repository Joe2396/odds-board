#!/usr/bin/env python3
"""
fetch_ladbrokes_worldcup_props.py

Scrapes World Cup props from Ladbrokes.
Match URL: /en/sports/event/football/international/world-cup-2026/{slug}/{id}/main-markets

Markets:
- Match Betting (90 Mins)
- Both Teams To Score
- Over/Under Total Goals
- Goalscorer (1st/Anytime)
- Correct Score
- Half Time Result (1st Half Betting)
- Double Chance

Usage:
    pip install playwright
    playwright install chromium
    python fetch_ladbrokes_worldcup_props.py
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH  = ROOT / "football" / "data" / "ladbrokes_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "ladbrokes_worldcup_props"

COMPETITION_URL = "https://www.ladbrokes.com/en/sports/competitions/football/international/world-cup-2026"
MAX_MATCHES = 15

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)

WORLD_CUP_TEAMS = {
    "Mexico","South Africa","South Korea","Czech Republic","Czechia",
    "Canada","Bosnia & Herzegovina","Bosnia","USA","Paraguay","Qatar",
    "Switzerland","Brazil","Morocco","Haiti","Scotland","Australia",
    "Turkey","Türkiye","Germany","Curacao","Netherlands","Japan",
    "Ivory Coast","Ecuador","Sweden","Tunisia","Spain","Cape Verde",
    "Belgium","Egypt","Saudi Arabia","Uruguay","Iran","New Zealand",
    "France","Senegal","Iraq","Norway","Argentina","Algeria","Austria",
    "Jordan","Portugal","DR Congo","England","Croatia","Ghana",
    "Panama","Colombia","Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic":"Czechia","Bosnia & Herzegovina":"Bosnia",
    "Bosnia and Herzegovina":"Bosnia","Turkey":"Türkiye","Turkiye":"Türkiye",
    "Curaçao":"Curacao",
}

def clean(s):
    return re.sub(r"\s+"," ",str(s or "")).strip()

def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))

def normalize(s):
    s = clean(s).lower().replace("&","and").replace("?","")
    return re.sub(r"[^a-z0-9]+","_",s).strip("_")

def slugify(s):
    return normalize(s).replace("_","-")

def canonical_team(s):
    return TEAM_ALIASES.get(clean(s), clean(s))

def sel(name, odds, extra=None):
    obj = {"selection":clean(name),"normalized_selection":normalize(name),"odds":clean(odds).upper()}
    if extra: obj.update(extra)
    return obj

def mkt(name, selections):
    return {"market":name,"normalized_market":normalize(name),"selection_count":len(selections),"selections":selections}

# ── Parsers ────────────────────────────────────────────────────────────────────

def parse_match_betting(lines, home, away):
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Match Betting"), -1)
    if idx == -1: return mkt("Match Betting", selections)
    block = lines[idx:idx+15]
    for i, line in enumerate(block):
        label = clean(line)
        # Layout 1: "90 Mins" / home_odds / draw_odds / away_odds
        if label == "90 Mins" and i+3 < len(block):
            if is_odds(block[i+1]) and is_odds(block[i+2]) and is_odds(block[i+3]):
                return mkt("Match Betting", [
                    sel(home,   block[i+1], {"side":"home"}),
                    sel("Draw", block[i+2], {"side":"draw"}),
                    sel(away,   block[i+3], {"side":"away"}),
                ])
        # Layout 2: home / Draw / away as column headers, then "90 Mins" / odds / odds / odds
        if label == home and i+2 < len(block) and clean(block[i+1]) == "Draw" and clean(block[i+2]) == away:
            # Next non-label line should be "90 Mins" then odds
            for j in range(i+3, min(i+8, len(block))):
                if clean(block[j]) == "90 Mins" and j+3 < len(block):
                    if is_odds(block[j+1]) and is_odds(block[j+2]) and is_odds(block[j+3]):
                        return mkt("Match Betting", [
                            sel(home,   block[j+1], {"side":"home"}),
                            sel("Draw", block[j+2], {"side":"draw"}),
                            sel(away,   block[j+3], {"side":"away"}),
                        ])
    return mkt("Match Betting", selections)


def parse_btts(lines):
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Both Teams To Score"), -1)
    if idx == -1: return mkt("Both Teams To Score", selections)
    block = lines[idx:idx+15]
    for i, line in enumerate(block):
        label = clean(line)
        # Layout 1: "90 Mins" / yes_odds / no_odds
        if label == "90 Mins" and i+2 < len(block):
            if is_odds(block[i+1]) and is_odds(block[i+2]):
                selections.append(sel("Both Teams To Score - Yes", block[i+1], {"side":"yes"}))
                selections.append(sel("Both Teams To Score - No",  block[i+2], {"side":"no"}))
                break
        # Layout 2: Yes / No column headers then "90 Mins" / odds / odds
        if label == "Yes" and i+1 < len(block) and clean(block[i+1]) == "No":
            for j in range(i+2, min(i+6, len(block))):
                if clean(block[j]) == "90 Mins" and j+2 < len(block):
                    if is_odds(block[j+1]) and is_odds(block[j+2]):
                        selections.append(sel("Both Teams To Score - Yes", block[j+1], {"side":"yes"}))
                        selections.append(sel("Both Teams To Score - No",  block[j+2], {"side":"no"}))
                        break
            break
    return mkt("Both Teams To Score", selections)


def parse_total_goals(lines):
    selections = []
    # Find the occurrence that has actual data (followed by Show Stats then 90 Mins)
    idx = -1
    for i, l in enumerate(lines):
        if clean(l) == "Over/Under Total Goals":
            # Check if this one has data - look for "90 Mins" within next 5 lines
            block_check = [clean(lines[j]) for j in range(i, min(i+6, len(lines)))]
            if "90 Mins" in block_check or "Show Stats" in block_check:
                idx = i  # keep searching for the best one
    if idx == -1: return mkt("Total Goals Over / Under", selections)

    block = lines[idx:idx+25]
    i = 0
    collecting = False
    while i < len(block):
        label = clean(block[i])
        if label in {"Over/Under Total Goals","Show Stats","90 Mins","Match",
                     "Total Goals","1st Half","2nd Half","Over","Under"}:
            if label == "90 Mins":
                collecting = True
            i += 1
            continue
        if label in {"Show All","Show Less"} and collecting:
            break
        if collecting and re.match(r'^\d+\.?\d*$', label):
            if i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
                selections.append(sel(f"Over {label}",  block[i+1], {"side":"over",  "line":label}))
                selections.append(sel(f"Under {label}", block[i+2], {"side":"under", "line":label}))
                i += 3
                continue
        i += 1
    return mkt("Total Goals Over / Under", selections)


def parse_goalscorers(lines):
    """Ladbrokes: Popular Goalscorer Markets / Mexico / South Africa headers / player / 1st / anytime / last"""
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) in {
        "Popular Goalscorer Markets","Goalscorer","Goalscorers","Player To Score"
    }), -1)
    if idx == -1: return mkt("Player to Score", selections)

    skip = {"Popular Goalscorer Markets","Goalscorer","Goalscorers","Player To Score",
            "Show All","Show Less","No Goalscorer","Show Stats","First Team Goalscorer",
            "Other Goalscorer Markets","Player To Score First & Result",
            "Player To Score And Their Team To Win"} | WORLD_CUP_TEAMS

    block = lines[idx:idx+200]
    i = 0
    while i < len(block):
        player = clean(block[i])
        if not player or player in skip or is_odds(player) or len(player) > 50:
            # Stop if we hit another major section
            if player in {"First Team Goalscorer","Other Goalscorer Markets",
                         "Player To Score First & Result","Player To Score And Their Team To Win"}:
                break
            i += 1
            continue
        # Ladbrokes: player / 1st_odds / anytime_odds / last_odds
        if i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
            selections.append(sel(f"{player} First Goalscorer",   block[i+1], {"player":player,"prop_type":"first_goalscorer"}))
            selections.append(sel(f"{player} Anytime Goalscorer", block[i+2], {"player":player,"prop_type":"anytime_goalscorer"}))
            i += 3
            if i < len(block) and is_odds(block[i]):
                i += 1  # skip last goalscorer odds
        else:
            i += 1
    return mkt("Player to Score", selections)


def parse_first_half_goals(lines):
    """After clicking 1st Half sub-tab, the Over/Under Total Goals shows 1st half data."""
    selections = []
    # Find last occurrence of Over/Under Total Goals (after 1st Half click)
    idx = -1
    for i, l in enumerate(lines):
        if clean(l) == "Over/Under Total Goals":
            block_check = [clean(lines[j]) for j in range(i, min(i+6, len(lines)))]
            if "90 Mins" in block_check or "Show Stats" in block_check:
                idx = i

    if idx == -1: return mkt("1st Half Goals Over / Under", selections)

    block = lines[idx:idx+25]
    i = 0
    collecting = False
    while i < len(block):
        label = clean(block[i])
        if label in {"Over/Under Total Goals","Show Stats","90 Mins","Match",
                     "Total Goals","1st Half","2nd Half","Over","Under"}:
            if label == "90 Mins":
                collecting = True
            i += 1
            continue
        if label in {"Show All","Show Less"} and collecting:
            break
        if collecting and re.match(r'^\d+\.?\d*$', label):
            if i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
                selections.append(sel(f"Over {label}",  block[i+1], {"side":"over",  "line":label}))
                selections.append(sel(f"Under {label}", block[i+2], {"side":"under", "line":label}))
                i += 3
                continue
        i += 1
    return mkt("1st Half Goals Over / Under", selections)


def parse_correct_score(lines):
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Correct Score"), -1)
    if idx == -1: return mkt("Correct Score", selections)
    block = lines[idx:idx+80]
    for i, line in enumerate(block):
        label = clean(line)
        if re.match(r'^\d+\s*-\s*\d+$', label) and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label, block[i+1]))
    return mkt("Correct Score", selections)


def parse_half_time_result(lines, home, away):
    selections = []
    # Ladbrokes calls it "Half Time Or Full Time Result" on the Half tab
    idx = next((i for i,l in enumerate(lines) if clean(l) in {
        "Half Time Or Full Time Result","Half Time Result","1st Half Betting","Half-Time Result"
    }), -1)
    if idx == -1: return mkt("Half Time Result", selections)
    block = lines[idx:idx+15]
    valid = {home, "Draw", away}
    for i, line in enumerate(block):
        label = clean(line)
        if label in valid and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label, block[i+1]))
    return mkt("Half Time Result", selections)


def parse_double_chance(lines):
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Double Chance"), -1)
    if idx == -1: return mkt("Double Chance", selections)
    label_map = {"1X":"Home or Draw","X2":"Away or Draw","12":"Home or Away"}
    block = lines[idx:idx+10]
    for i, line in enumerate(block):
        label = clean(line)
        if label in label_map and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label_map[label], block[i+1]))
    return mkt("Double Chance", selections)


def parse_all(text, home, away):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    markets = []
    for parser, args in [
        (parse_match_betting,    (lines, home, away)),
        (parse_btts,             (lines,)),
        (parse_total_goals,      (lines,)),
        (parse_first_half_goals, (lines,)),
        (parse_goalscorers,      (lines,)),
        (parse_correct_score,    (lines,)),
        (parse_half_time_result, (lines, home, away)),
        (parse_double_chance,    (lines,)),
    ]:
        try:
            m = parser(*args)
            if m["selections"]: markets.append(m)
        except Exception as e:
            print(f"    Parser error ({parser.__name__}): {e}")
    seen, unique = set(), []
    for m in markets:
        k = m["normalized_market"]
        if k not in seen: seen.add(k); unique.append(m)
    return unique

# ── Browser helpers ────────────────────────────────────────────────────────────

def accept_cookies(page):
    for label in ["Accept All","Accept all","I Accept","Accept","Agree","Allow all","Got it"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


def click_tab(page, tab_name):
    try:
        loc = page.get_by_role("link", name=re.compile(f"^{tab_name}$", re.I))
        if not loc.count():
            loc = page.get_by_text(tab_name, exact=True)
        if loc.count():
            loc.first.click(timeout=4000)
            page.wait_for_timeout(2500)
            return True
    except Exception:
        pass
    return False


def expand_show_all(page):
    try:
        btn = page.get_by_text("Show All", exact=True)
        if btn.count():
            btn.first.click(timeout=3000)
            page.wait_for_timeout(1500)
    except Exception:
        pass


def scroll_page(page, steps=12):
    for _ in range(steps):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(300)


def get_match_links(page):
    print(f"Opening: {COMPETITION_URL}")
    page.goto(COMPETITION_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)
    accept_cookies(page)

    for _ in range(20):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(400)

    # Ladbrokes uses clean <a> tags with /sports/event/ in href
    links = page.evaluate("""
        () => [...new Set(
            Array.from(document.querySelectorAll('a[href*="/sports/event/football/international/world-cup-2026/"]'))
                .map(a => a.href)
                .filter(h => {
                    // Must contain a match slug with -v- pattern
                    const path = h.split('/world-cup-2026/')[1] || '';
                    return path.includes('-v-') && !h.includes('outright') && !h.includes('top-goalscorer');
                })
        )]
    """)

    print(f"  Found {len(links)} links from DOM")

    # Ensure they all end with /main-markets
    fixtures = []
    seen = set()
    for url in links:
        base = url.split("?")[0]
        if not base.endswith("/main-markets"):
            base = base.rstrip("/") + "/main-markets"
        if base in seen: continue
        seen.add(base)
        # Extract slug: ".../mexico-v-south-africa/253494590/main-markets"
        parts = base.split("/world-cup-2026/")[-1].split("/")
        slug = parts[0] if parts else ""
        name = slug.replace("-v-"," v ").replace("-"," ").title()
        fixtures.append({"url": base, "name": name})

    # If DOM approach failed, use click approach
    if not fixtures:
        print("  DOM failed, using click approach...")
        text = page.locator("body").inner_text(timeout=15000)
        lines = [clean(l) for l in text.splitlines() if clean(l)]
        match_pairs = []
        seen_pairs = set()
        for i, line in enumerate(lines):
            if line in WORLD_CUP_TEAMS and i+1 < len(lines) and lines[i+1] in WORLD_CUP_TEAMS:
                home = canonical_team(line)
                away = canonical_team(lines[i+1])
                if (home,away) not in seen_pairs:
                    seen_pairs.add((home,away))
                    match_pairs.append((home,away))

        seen_urls = set()
        for home, away in match_pairs[:MAX_MATCHES]:
            try:
                page.goto(COMPETITION_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                page.get_by_text(home, exact=True).first.click(timeout=5000)
                page.wait_for_timeout(4000)
                url = page.url.split("?")[0]
                if url not in seen_urls and "/event/" in url:
                    seen_urls.add(url)
                    if not url.endswith("/main-markets"):
                        url = url.rstrip("/") + "/main-markets"
                    fixtures.append({"url": url, "name": f"{home} v {away}"})
                    print(f"  ✓ {home} v {away}: {url}")
            except Exception as e:
                print(f"  ⚠ {home}: {e}")

    print(f"Found {len(fixtures)} fixtures")
    return fixtures[:MAX_MATCHES]


def detect_teams(text):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    for line in lines[:30]:
        m = re.match(r'^(.+?)\s+[Vv]\s+(.+?)$', line)
        if m:
            h, a = m.group(1).strip(), m.group(2).strip()
            if h in WORLD_CUP_TEAMS and a in WORLD_CUP_TEAMS:
                return canonical_team(h), canonical_team(a)
    for i, line in enumerate(lines):
        if line in WORLD_CUP_TEAMS and i+1 < len(lines) and lines[i+1] in WORLD_CUP_TEAMS:
            return canonical_team(line), canonical_team(lines[i+1])
    return "", ""


def scrape_match(page, fixture):
    url  = fixture["url"]  # ends in /main-markets
    base = url.replace("/main-markets", "")
    name = fixture["name"]
    print(f"  Scraping: {name}")

    all_text = ""

    # Main tab
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookies(page)
    try:
        page.wait_for_function("() => document.body.innerText.includes('Match Betting')", timeout=10000)
    except Exception:
        pass
    scroll_page(page, 15)
    expand_show_all(page)
    scroll_page(page, 5)
    all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Goals tab — navigate directly, click 1st Half sub-tab
    page.goto(f"{base}/goals", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    try:
        page.wait_for_function("() => document.body.innerText.includes('Total Goals')", timeout=8000)
    except Exception:
        pass
    # Click 1st Half sub-tab inside goals section
    try:
        page.get_by_text("1st Half", exact=True).first.click(timeout=3000)
        page.wait_for_timeout(1500)
    except Exception:
        pass
    try:
        page.get_by_text("Show All", exact=True).first.click(timeout=3000)
        page.wait_for_timeout(1000)
    except Exception:
        pass
    scroll_page(page, 10)
    goals_text = page.locator("body").inner_text(timeout=15000)
    if "Total Goals" in goals_text or "Over/Under" in goals_text:
        print(f"    ✓ Goals tab")
    else:
        print(f"    ⚠ Goals text NOT found")
    all_text += "\n" + goals_text

    # Goalscorer tab — navigate directly
    page.goto(f"{base}/goalscorer", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    try:
        expand_show_all(page)
    except Exception:
        pass
    scroll_page(page, 10)
    all_text += "\n" + page.locator("body").inner_text(timeout=15000)
    print(f"    ✓ Goalscorer tab")

    # Half tab — navigate directly
    page.goto(f"{base}/half", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    scroll_page(page, 8)
    all_text += "\n" + page.locator("body").inner_text(timeout=15000)
    print(f"    ✓ Half tab")

    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(all_text, encoding="utf-8")

    home, away = detect_teams(all_text)
    if not home:
        slug_part = url.split("/world-cup-2026/")[-1].split("/")[0]
        if "-v-" in slug_part:
            parts = slug_part.split("-v-", 1)
            home = parts[0].replace("-", " ").title()
            away = parts[1].replace("-", " ").title()
            caps = {"Usa":"USA","Dr":"DR","Bosnia Herzegovina":"Bosnia"}
            for k,v in caps.items():
                home = home.replace(k,v)
                away = away.replace(k,v)

    markets = parse_all(all_text, home, away) if home else []
    print(f"  ✓ {home} v {away} — {len(markets)} markets: {[m['market'] for m in markets]}")

    return {
        "match":     f"{home} v {away}" if home else name,
        "home_team": home, "away_team": away,
        "url":       url, "markets": markets,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Ladbrokes World Cup Props Scraper")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        fixtures = get_match_links(page)
        results = []

        for i, fixture in enumerate(fixtures):
            print(f"\n[{i+1}/{len(fixtures)}]")
            try:
                result = scrape_match(page, fixture)
                results.append(result)
            except Exception as e:
                print(f"  ⚠ Error: {e}")
                results.append({"match": fixture["name"], "home_team": "", "away_team": "", "url": fixture["url"], "markets": []})

        browser.close()

    output = {
        "sport": "football", "competition": "FIFA World Cup",
        "bookmaker": "Ladbrokes", "source_url": COMPETITION_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results), "matches": results,
    }
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved → {OUT_PATH}")
    print("\n── Summary ─────────────────────────────────────────────")
    for r in results:
        print(f"  {r['match']:<40} {len(r['markets'])} markets")
    print("─" * 60)

if __name__ == "__main__":
    main()