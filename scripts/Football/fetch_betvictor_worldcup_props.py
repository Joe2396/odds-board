#!/usr/bin/env python3
"""
fetch_betvictor_worldcup_props.py

Scrapes World Cup props from BetVictor.
Collects match links by clicking each match row on the competition page,
then scrapes Popular + Goals + Player + Half tabs per match.

Usage:
    pip install playwright beautifulsoup4 lxml
    playwright install chromium
    python fetch_betvictor_worldcup_props.py
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH  = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "betvictor_worldcup_props"

COMPETITION_URL = "https://www.betvictor.com/en-ie/sports/240/sections/custom-list/7199/group/world-cup-matches/item/matches"
MAX_MATCHES = 15

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)

WORLD_CUP_TEAMS = {
    "Mexico","South Africa","South Korea","Czech Republic","Czechia",
    "Canada","Bosnia and Herzegovina","Bosnia & Herzegovina","Bosnia",
    "USA","Paraguay","Qatar","Switzerland","Brazil","Morocco",
    "Haiti","Scotland","Australia","Turkey","Türkiye","Germany",
    "Curacao","Netherlands","Japan","Ivory Coast","Ecuador","Sweden",
    "Tunisia","Spain","Cape Verde","Belgium","Egypt","Saudi Arabia",
    "Uruguay","Iran","New Zealand","France","Senegal","Iraq","Norway",
    "Argentina","Algeria","Austria","Jordan","Portugal","DR Congo",
    "England","Croatia","Ghana","Panama","Colombia","Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic":"Czechia","Bosnia and Herzegovina":"Bosnia",
    "Bosnia & Herzegovina":"Bosnia","Turkey":"Türkiye","Turkiye":"Türkiye",
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
    s = clean(s)
    return TEAM_ALIASES.get(s,s)

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
    if idx == -1:
        return mkt("Match Betting", selections)
    block = lines[idx:idx+15]
    valid = {home, "Draw", away}
    for i, line in enumerate(block):
        label = clean(line)
        if label in valid and i+1 < len(block) and is_odds(block[i+1]):
            side = "home" if label==home else ("draw" if label=="Draw" else "away")
            selections.append(sel(label, block[i+1], {"side":side}))
    return mkt("Match Betting", selections)


def parse_total_goals(lines):
    selections = []
    idx = next((i for i,l in enumerate(lines) if "Total Goals" in clean(l) and i+1<len(lines) and "Over" in lines[i+1]), -1)
    if idx == -1:
        # Try alternate header
        idx = next((i for i,l in enumerate(lines) if clean(l) == "Total Goals"), -1)
    if idx == -1:
        return mkt("Total Goals Over / Under", selections)

    block = lines[idx:idx+40]
    for i, line in enumerate(block):
        label = clean(line)
        # BetVictor uses "O 2.5" and "U 2.5" format
        over_match  = re.match(r'^O\s*(\d+\.?\d*)$', label)
        under_match = re.match(r'^U\s*(\d+\.?\d*)$', label)
        # Also handle plain "Over X.X" / "Under X.X"
        if not over_match:  over_match  = re.match(r'^Over\s*(\d+\.?\d*)$', label)
        if not under_match: under_match = re.match(r'^Under\s*(\d+\.?\d*)$', label)

        if over_match and i+1 < len(block) and is_odds(block[i+1]):
            t = over_match.group(1)
            selections.append(sel(f"Over {t}", block[i+1], {"side":"over","line":t}))
        elif under_match and i+1 < len(block) and is_odds(block[i+1]):
            t = under_match.group(1)
            selections.append(sel(f"Under {t}", block[i+1], {"side":"under","line":t}))

    return mkt("Total Goals Over / Under", selections)


def parse_btts(lines):
    selections = []
    idx = next((i for i,l in enumerate(lines) if "Both Teams to Score" in clean(l) or "Both Teams To Score" in clean(l)), -1)
    if idx == -1:
        return mkt("Both Teams To Score", selections)
    block = lines[idx:idx+10]
    for i, line in enumerate(block):
        label = clean(line)
        if label in {"Yes","No"} and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(f"Both Teams To Score - {label}", block[i+1], {"side":label.lower()}))
    return mkt("Both Teams To Score", selections)


def parse_goalscorers(lines):
    """First / Anytime / Last goalscorer — BetVictor shows all three side by side."""
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Goalscorers"), -1)
    if idx == -1:
        return mkt("Player to Score", selections)

    skip = {"Goalscorers","First","Anytime","Last","Show More","Search",
            "Multi Scorers","Score & Win"} | WORLD_CUP_TEAMS

    block = lines[idx:idx+200]
    i = 0
    while i < len(block):
        player = clean(block[i])
        if not player or player in skip or is_odds(player) or len(player) > 50:
            i += 1
            continue
        # BetVictor: player name then First odds, Anytime odds, Last odds
        if i+3 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]) and is_odds(block[i+3]):
            selections.append(sel(f"{player} First Goalscorer",   block[i+1], {"player":player,"prop_type":"first_goalscorer"}))
            selections.append(sel(f"{player} Anytime Goalscorer", block[i+2], {"player":player,"prop_type":"anytime_goalscorer"}))
            i += 4
        else:
            i += 1

    return mkt("Player to Score", selections)


def parse_first_half_goals(lines):
    selections = []
    idx = next((i for i,l in enumerate(lines) if "1st Half" in clean(l) and i+1<len(lines)), -1)
    if idx == -1:
        return mkt("1st Half Goals Over / Under", selections)

    block = lines[idx:idx+20]
    for i, line in enumerate(block):
        label = clean(line)
        over_match  = re.match(r'^O\s*(\d+\.?\d*)$', label) or re.match(r'^Over\s*(\d+\.?\d*)$', label)
        under_match = re.match(r'^U\s*(\d+\.?\d*)$', label) or re.match(r'^Under\s*(\d+\.?\d*)$', label)
        if over_match and i+1 < len(block) and is_odds(block[i+1]):
            t = over_match.group(1)
            selections.append(sel(f"Over {t}", block[i+1], {"side":"over","line":t}))
        elif under_match and i+1 < len(block) and is_odds(block[i+1]):
            t = under_match.group(1)
            selections.append(sel(f"Under {t}", block[i+1], {"side":"under","line":t}))

    return mkt("1st Half Goals Over / Under", selections)


def parse_half_time_result(lines, home, away):
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) in {"Half Time","1st Half Result","Half-Time Result"}), -1)
    if idx == -1:
        return mkt("Half Time Result", selections)
    block = lines[idx:idx+10]
    valid = {home, "Draw", away}
    for i, line in enumerate(block):
        label = clean(line)
        if label in valid and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label, block[i+1]))
    return mkt("Half Time Result", selections)


def parse_double_chance(lines):
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Double Chance"), -1)
    if idx == -1:
        return mkt("Double Chance", selections)
    label_map = {"1X":"Home or Draw","X2":"Away or Draw","12":"Home or Away"}
    block = lines[idx:idx+10]
    for i, line in enumerate(block):
        label = clean(line)
        if label in label_map and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label_map[label], block[i+1]))
    return mkt("Double Chance", selections)


def parse_correct_score(lines):
    selections = []
    idx = next((i for i,l in enumerate(lines) if "Correct Score" in clean(l)), -1)
    if idx == -1:
        return mkt("Correct Score", selections)
    block = lines[idx:idx+60]
    for i, line in enumerate(block):
        label = clean(line)
        if re.match(r'^\d+\s*-\s*\d+$', label) and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label, block[i+1]))
    return mkt("Correct Score", selections)


def parse_all(text, home, away):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    markets = []
    for parser, args in [
        (parse_match_betting,   (lines, home, away)),
        (parse_total_goals,     (lines,)),
        (parse_btts,            (lines,)),
        (parse_correct_score,   (lines,)),
        (parse_first_half_goals,(lines,)),
        (parse_half_time_result,(lines, home, away)),
        (parse_double_chance,   (lines,)),
        (parse_goalscorers,     (lines,)),
    ]:
        try:
            m = parser(*args)
            if m["selections"]:
                markets.append(m)
        except Exception as e:
            print(f"    Parser error ({parser.__name__}): {e}")
    # Dedupe
    seen, unique = set(), []
    for m in markets:
        k = m["normalized_market"]
        if k not in seen: seen.add(k); unique.append(m)
    return unique

# ── Browser helpers ────────────────────────────────────────────────────────────

def accept_cookies(page):
    for label in ["Accept All","Accept all","I Accept","Accept","Agree","Allow all"]:
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
        btn = page.get_by_role("button", name=re.compile(f"^{tab_name}$", re.I))
        if not btn.count():
            btn = page.get_by_text(tab_name, exact=True)
        if btn.count():
            btn.first.click(timeout=4000)
            page.wait_for_timeout(2500)
            return True
    except Exception:
        pass
    return False


def expand_show_more(page):
    try:
        btn = page.get_by_text("Show More", exact=True)
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

    # Get team pairs from page text
    text = page.locator("body").inner_text(timeout=15000)
    lines = [clean(l) for l in text.splitlines() if clean(l)]

    match_pairs = []
    seen_pairs = set()
    for i, line in enumerate(lines):
        if line in WORLD_CUP_TEAMS and i+1 < len(lines) and lines[i+1] in WORLD_CUP_TEAMS:
            home = canonical_team(line)
            away = canonical_team(lines[i+1])
            key = (home, away)
            if key not in seen_pairs:
                seen_pairs.add(key)
                match_pairs.append((home, away))

    print(f"  Found {len(match_pairs)} match pairs in text")

    # Click each home team to navigate to the match page
    fixtures = []
    seen_urls = set()

    for home, away in match_pairs[:MAX_MATCHES]:
        try:
            # Go back to competition page
            page.goto(COMPETITION_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)

            # Click the home team name
            page.get_by_text(home, exact=True).first.click(timeout=5000)
            page.wait_for_timeout(4000)

            current_url = page.url.split("?")[0]
            if "/events/" in current_url and current_url not in seen_urls:
                seen_urls.add(current_url)
                fixtures.append({"url": current_url, "name": f"{home} v {away}", "home": home, "away": away})
                print(f"  ✓ {home} v {away}: {current_url}")
            else:
                print(f"  ⚠ {home}: unexpected URL {current_url}")

        except Exception as e:
            print(f"  ⚠ {home}: {e}")

    print(f"Found {len(fixtures)} fixtures")
    return fixtures[:MAX_MATCHES]


def scrape_match(page, fixture):
    url  = fixture["url"]
    name = fixture["name"]
    home = fixture.get("home","")
    away = fixture.get("away","")
    print(f"  Scraping: {name}")

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    accept_cookies(page)

    # Wait for match content to load
    try:
        page.wait_for_function(
            f"() => document.body.innerText.includes('{home}')",
            timeout=10000
        )
    except Exception:
        page.wait_for_timeout(3000)

    all_text = ""

    # Popular tab (default)
    scroll_page(page, 12)
    all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Goals tab
    if click_tab(page, "Goals"):
        print(f"    ✓ Goals tab")
        scroll_page(page, 8)
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Player tab — navigate back to base URL to reset state, then click Player
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    if click_tab(page, "Player"):
        print(f"    ✓ Player tab")
        page.wait_for_timeout(1500)
        expand_show_more(page)
        scroll_page(page, 12)
        player_text = page.locator("body").inner_text(timeout=15000)
        # Only include if it contains the right team
        if not home or home in player_text:
            all_text += "\n" + player_text
        else:
            print(f"    ⚠ Player tab has wrong team data — skipping")

    # Half tab
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    if click_tab(page, "Half"):
        print(f"    ✓ Half tab")
        scroll_page(page, 8)
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(all_text, encoding="utf-8")

    # Always detect teams from the actual page content
    lines = [clean(l) for l in all_text.splitlines() if clean(l)]
    detected_home, detected_away = "", ""
    for i, line in enumerate(lines):
        if line in WORLD_CUP_TEAMS and i+1 < len(lines) and lines[i+1] in WORLD_CUP_TEAMS:
            detected_home = canonical_team(line)
            detected_away = canonical_team(lines[i+1])
            break

    if detected_home:
        home, away = detected_home, detected_away
        name = f"{home} v {away}"

    markets = parse_all(all_text, home, away) if home else []
    print(f"  ✓ {home} v {away} — {len(markets)} markets: {[m['market'] for m in markets]}")

    return {
        "match":     f"{home} v {away}" if home else name,
        "home_team": home,
        "away_team": away,
        "url":       url,
        "markets":   markets,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("BetVictor World Cup Props Scraper")
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
                results.append({
                    "match": fixture["name"], "home_team": "", "away_team": "",
                    "url": fixture["url"], "markets": []
                })

        browser.close()

    output = {
        "sport":        "football",
        "competition":  "FIFA World Cup",
        "bookmaker":    "BetVictor",
        "source_url":   COMPETITION_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count":  len(results),
        "matches":      results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved → {OUT_PATH}")
    print("\n── Summary ─────────────────────────────────────────────")
    for r in results:
        print(f"  {r['match']:<40} {len(r['markets'])} markets")
    print("─" * 60)


if __name__ == "__main__":
    main()