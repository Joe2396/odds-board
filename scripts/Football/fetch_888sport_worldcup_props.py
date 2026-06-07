#!/usr/bin/env python3
"""
fetch_888sport_worldcup_props.py

Scrapes World Cup props from 888Sport using Playwright (headless=False).
Navigates to each match page and clicks through Goals/Half/All Markets tabs.

Markets captured:
- Match Winner
- Total Goals Over/Under
- 1st Half Total Goals Over/Under
- Correct Score
- 1st Half Result
- Half Time/Full Time
- Both Teams To Score
- Double Chance

Usage:
    pip install playwright
    playwright install chromium
    python fetch_888sport_worldcup_props.py
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH  = ROOT / "football" / "data" / "888sport_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "888sport_worldcup_props"

COMPETITION_URL = "https://www.888sport.com/football/world-cup/"
MAX_MATCHES     = 15

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)

# ── Helpers ────────────────────────────────────────────────────────────────────

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))

def normalize(s):
    s = clean(s).lower().replace("&","and").replace("?","")
    return re.sub(r"[^a-z0-9]+","_",s).strip("_")

def slugify(s):
    return normalize(s).replace("_","-")

def sel(name, odds, extra=None):
    obj = {"selection":clean(name),"normalized_selection":normalize(name),"odds":clean(odds).upper()}
    if extra: obj.update(extra)
    return obj

def mkt(name, selections):
    return {"market":name,"normalized_market":normalize(name),"selection_count":len(selections),"selections":selections}

# ── Parsers ────────────────────────────────────────────────────────────────────

def parse_match_winner(lines, home, away):
    """Match Winner — Home / Draw / Away."""
    selections = []
    for i, line in enumerate(lines):
        label = clean(line)
        if label in {home, "Draw", away} and i+1 < len(lines) and is_odds(lines[i+1]):
            selections.append(sel(label, lines[i+1], {"side": "home" if label==home else ("draw" if label=="Draw" else "away")}))
        if len(selections) == 3:
            break
    return mkt("Match Betting", selections)


def parse_total_goals(lines, header="TOTAL GOALS OVER/UNDER", market_name="Total Goals Over / Under"):
    """Total Goals Over/Under — stops before 1ST HALF section."""
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l).upper() == header), -1)
    if idx == -1:
        return mkt(market_name, selections)

    block = lines[idx:idx+40]
    for i, line in enumerate(block):
        label = clean(line)
        # Stop if we hit the 1st half section
        if "1ST HALF" in label.upper() and i > 0:
            break
        if re.match(r'^\d+\.?\d*$', label) and i+2 < len(block):
            over_odds  = clean(block[i+1])
            under_odds = clean(block[i+2])
            if is_odds(over_odds) and is_odds(under_odds):
                selections.append(sel(f"Over {label}",  over_odds,  {"side":"over",  "line":label}))
                selections.append(sel(f"Under {label}", under_odds, {"side":"under", "line":label}))
    return mkt(market_name, selections)


def parse_first_half_result(lines, home, away):
    """1st Half Result — finds the actual half time result section."""
    selections = []
    idx = next((i for i,l in enumerate(lines) if "1ST HALF - RESULT" in clean(l).upper()), -1)
    if idx == -1:
        return mkt("Half Time Result", selections)

    block = lines[idx:idx+15]
    valid_labels = {home, away, "Draw"}
    for i, line in enumerate(block[1:], 1):  # skip header
        label = clean(line)
        if label in valid_labels and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label, block[i+1]))
        # Stop if we hit another market header
        if i > 1 and label.isupper() and len(label) > 5:
            break
    return mkt("Half Time Result", selections)


def parse_btts(lines):
    """Both Teams To Score — Yes / No."""
    selections = []
    idx = next((i for i,l in enumerate(lines) if "BOTH TEAMS TO SCORE" in clean(l).upper()
                and "RESULT" not in clean(l).upper()), -1)
    if idx == -1:
        return mkt("Both Teams To Score", selections)

    block = lines[idx:idx+15]
    for i, line in enumerate(block):
        label = clean(line)
        if label in {"Yes","No"} and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(f"Both Teams To Score - {label}", block[i+1], {"side": label.lower()}))
    return mkt("Both Teams To Score", selections)


def parse_double_chance(lines):
    """Double Chance — 1X / X2 / 12."""
    selections = []
    idx = next((i for i,l in enumerate(lines) if "DOUBLE CHANCE" in clean(l).upper()), -1)
    if idx == -1:
        return mkt("Double Chance", selections)

    label_map = {"1X":"Home or Draw","X2":"Away or Draw","12":"Home or Away"}
    block = lines[idx:idx+15]
    for i, line in enumerate(block):
        label = clean(line)
        if label in label_map and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label_map[label], block[i+1]))
    return mkt("Double Chance", selections)


def parse_all_markets(text, home, away):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    markets = []

    parsers = [
        lambda: parse_match_winner(lines, home, away),
        lambda: parse_total_goals(lines, "TOTAL GOALS OVER/UNDER", "Total Goals Over / Under"),
        lambda: parse_total_goals(lines, "1ST HALF - TOTAL GOALS OVER/UNDER", "1st Half Goals Over / Under"),
        lambda: parse_correct_score(lines),
        lambda: parse_first_half_result(lines, home, away),
        lambda: parse_ht_ft(lines),
        lambda: parse_btts(lines),
        lambda: parse_double_chance(lines),
    ]

    for parser in parsers:
        try:
            m = parser()
            if m["selections"]:
                markets.append(m)
        except Exception as e:
            print(f"    Parser error: {e}")

    return markets

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
        btn = page.get_by_role("button", name=re.compile(f"^{tab_name}$", re.I))
        if not btn.count():
            btn = page.get_by_text(tab_name, exact=True)
        if btn.count():
            btn.first.click(timeout=3000)
            page.wait_for_timeout(2000)
            return True
    except Exception:
        pass
    return False


def scroll_page(page, steps=12):
    for _ in range(steps):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(300)


def get_match_links(page):
    """Collect World Cup match page URLs from competition page."""
    print(f"Opening: {COMPETITION_URL}")
    page.goto(COMPETITION_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)
    accept_cookies(page)

    # Scroll to load all fixtures
    for _ in range(15):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(400)

    links = page.evaluate("""
        () => [...new Set(
            Array.from(document.querySelectorAll('a[href*="/world-cup-2026/"]'))
                .map(a => a.href)
                .filter(h => h.includes('-e-') && !h.includes('outrights'))
        )]
    """)

    fixtures = []
    seen = set()
    for url in links:
        base_url = url.split("?")[0]
        if base_url in seen: continue
        seen.add(base_url)
        slug = base_url.split("/world-cup-2026/")[-1].rstrip("/")
        # Extract teams from slug: "mexico-vs-south-africa-e-6818790"
        name = re.sub(r'-e-\d+$', '', slug).replace("-vs-", " v ").replace("-", " ").title()
        fixtures.append({"url": base_url, "name": name})

    print(f"Found {len(fixtures)} match links")
    return fixtures[:MAX_MATCHES]


def detect_teams(text):
    """Extract home/away from page text."""
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    for line in lines[:30]:
        # Strip common suffixes like "Betting Odds"
        line = re.sub(r'\s*(Betting Odds|Odds|Betting).*$', '', line, flags=re.I).strip()
        m = re.match(r'^(.+?)\s+vs\s+(.+?)$', line, re.I)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    TEAMS = {"Mexico","South Africa","South Korea","Czechia","Czech Republic","Canada","Bosnia",
             "USA","Paraguay","Qatar","Switzerland","Brazil","Morocco","Haiti","Scotland",
             "Australia","Turkey","Türkiye","Germany","Curacao","Netherlands","Japan",
             "Ivory Coast","Ecuador","Sweden","Tunisia","Spain","Cape Verde","Belgium",
             "Egypt","Saudi Arabia","Uruguay","Iran","New Zealand","France","Senegal",
             "Iraq","Norway","Argentina","Algeria","Austria","Jordan","Portugal","DR Congo",
             "England","Croatia","Ghana","Panama","Colombia","Uzbekistan"}
    for i, line in enumerate(lines):
        if line in TEAMS and i+1 < len(lines) and lines[i+1] in TEAMS:
            return line, lines[i+1]
    return "", ""


def scrape_match(page, fixture):
    url  = fixture["url"]
    name = fixture["name"]
    print(f"  Scraping: {name}")
    print(f"  URL: {url}")

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookies(page)

    all_text = ""

    # Click Goals tab — gets Total Goals O/U, 1st Half Goals, Correct Score
    if click_tab(page, "Goals"):
        print(f"    ✓ Goals tab")
        scroll_page(page, 15)
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Click Half tab — gets 1st Half Result, HT/FT
    if click_tab(page, "Half"):
        print(f"    ✓ Half tab")
        scroll_page(page, 10)
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Click All Markets tab — gets BTTS, Double Chance, Match Winner
    if click_tab(page, "All Markets"):
        print(f"    ✓ All Markets tab")
        scroll_page(page, 20)
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    if not all_text:
        # Fallback — just grab whatever is on the page
        scroll_page(page, 15)
        all_text = page.locator("body").inner_text(timeout=15000)

    # Save debug
    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(all_text, encoding="utf-8")

    home, away = detect_teams(all_text)
    if not home:
        # Fallback from fixture name
        parts = name.split(" v ")
        home = parts[0].strip() if len(parts) == 2 else ""
        away = parts[1].strip() if len(parts) == 2 else ""

    markets = parse_all_markets(all_text, home, away) if home else []

    # Dedupe markets by normalized name
    seen_mkts = set()
    unique = []
    for m in markets:
        k = m["normalized_market"]
        if k not in seen_mkts:
            seen_mkts.add(k)
            unique.append(m)

    print(f"  ✓ {home} v {away} — {len(unique)} markets: {[m['market'] for m in unique]}")

    return {
        "match":      f"{home} v {away}" if home else name,
        "home_team":  home,
        "away_team":  away,
        "url":        url,
        "markets":    unique,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("888Sport World Cup Props Scraper")
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
        "bookmaker":    "888Sport",
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