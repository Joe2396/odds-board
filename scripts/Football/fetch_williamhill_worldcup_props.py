#!/usr/bin/env python3
"""
fetch_williamhill_worldcup_props.py

Scrapes World Cup props from William Hill using Playwright (headless=False).
Navigates to each match page and scrapes Popular + Goals + Half tabs.

Markets captured:
- Match Result (90 Minutes)
- Both Teams To Score
- Total Match Over/Under Goals
- 1st Half Over/Under Goals
- Match Result and Both Teams To Score
- 1st Half Betting (Half Time Result)
- Double Chance

Usage:
    pip install playwright
    playwright install chromium
    python fetch_williamhill_worldcup_props.py
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH  = ROOT / "football" / "data" / "williamhill_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "williamhill_worldcup_props"

COMPETITION_URL = "https://sports.williamhill.com/betting/en-gb/football/competitions/OB_TY52321/world-cup-2026/matches"
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

def parse_match_result(lines, home, away):
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Match Result"), -1)
    if idx == -1:
        # Try just finding the odds directly after home/draw/away labels
        idx = next((i for i,l in enumerate(lines) if clean(l) in {home, "Draw", away}), -1)
        if idx == -1:
            return mkt("Match Betting", selections)

    block = lines[idx:idx+20]
    valid = {home, "Draw", away}
    for i, line in enumerate(block):
        label = clean(line)
        if label in valid and i+1 < len(block) and is_odds(block[i+1]):
            side = "home" if label==home else ("draw" if label=="Draw" else "away")
            selections.append(sel(label, block[i+1], {"side":side}))
    return mkt("Match Betting", selections)


def parse_total_goals(lines, section_header, market_name):
    """Over/Under goals — format: 'Over X.X' label then odds side by side."""
    selections = []
    idx = next((i for i,l in enumerate(lines) if section_header.lower() in clean(l).lower()), -1)
    if idx == -1:
        return mkt(market_name, selections)

    block = lines[idx:idx+50]
    i = 0
    while i < len(block):
        label = clean(block[i])
        # WH format: "Over 1.5" then odds, then "Under 1.5" then odds
        over_match  = re.match(r'^Over (\d+\.?\d*)$', label)
        under_match = re.match(r'^Under (\d+\.?\d*)$', label)
        if over_match and i+1 < len(block) and is_odds(block[i+1]):
            threshold = over_match.group(1)
            selections.append(sel(f"Over {threshold}", block[i+1], {"side":"over","line":threshold}))
            i += 2
        elif under_match and i+1 < len(block) and is_odds(block[i+1]):
            threshold = under_match.group(1)
            selections.append(sel(f"Under {threshold}", block[i+1], {"side":"under","line":threshold}))
            i += 2
        # Stop if we hit a new market section
        elif label.istitle() and len(label) > 8 and i > 5 and not is_odds(label):
            break
        else:
            i += 1

    return mkt(market_name, selections)


def parse_btts(lines):
    """Both Teams To Score — Yes / No."""
    selections = []
    idx = next((i for i,l in enumerate(lines)
                if clean(l) == "Both Teams To Score"), -1)
    if idx == -1:
        return mkt("Both Teams To Score", selections)

    block = lines[idx:idx+10]
    for i, line in enumerate(block):
        label = clean(line)
        if label in {"Yes","No"} and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(f"Both Teams To Score - {label}", block[i+1], {"side":label.lower()}))
    return mkt("Both Teams To Score", selections)


def parse_btts_result(lines, home, away):
    """Match Result and Both Teams To Score."""
    selections = []
    idx = next((i for i,l in enumerate(lines)
                if "Match Result and Both Teams To Score" in clean(l)), -1)
    if idx == -1:
        return mkt("Result & Both Teams To Score", selections)

    block = lines[idx:idx+15]
    valid = {home, "Draw", away}
    for i, line in enumerate(block):
        label = clean(line)
        if label in valid and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(f"{label} & Both Teams To Score", block[i+1]))
    return mkt("Result & Both Teams To Score", selections)


def parse_half_time_result(lines, home, away):
    """1st Half Betting — Home / Draw / Away."""
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) == "1st Half Betting"), -1)
    if idx == -1:
        return mkt("Half Time Result", selections)

    block = lines[idx:idx+15]
    valid = {home, "Draw", away}
    for i, line in enumerate(block):
        label = clean(line)
        if label in valid and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label, block[i+1]))
    return mkt("Half Time Result", selections)


def parse_double_chance(lines):
    """Double Chance."""
    selections = []
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Double Chance"), -1)
    if idx == -1:
        return mkt("Double Chance", selections)

    label_map = {
        "Mexico Or Draw":"Home or Draw","Draw Or Mexico":"Home or Draw",
        "South Africa Or Draw":"Away or Draw","Draw Or South Africa":"Away or Draw",
        "Mexico Or South Africa":"Home or Away","South Africa Or Mexico":"Home or Away",
    }
    block = lines[idx:idx+15]
    for i, line in enumerate(block):
        label = clean(line)
        # WH uses team names like "Mexico Or Draw"
        mapped = label_map.get(label, label)
        if "Or" in label and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(mapped, block[i+1]))
    return mkt("Double Chance", selections)


def parse_all(text, home, away):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    markets = []

    for parser, args in [
        (parse_match_result,   (lines, home, away)),
        (parse_btts,           (lines,)),
        (parse_total_goals,    (lines, "Total Match Over/Under Goals", "Total Goals Over / Under")),
        (parse_total_goals,    (lines, "1st Half", "1st Half Goals Over / Under")),
        (parse_btts_result,    (lines, home, away)),
        (parse_half_time_result,(lines, home, away)),
        (parse_double_chance,  (lines,)),
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
        if k not in seen:
            seen.add(k); unique.append(m)
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


def scroll_page(page, steps=12):
    for _ in range(steps):
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(300)


def get_match_links(page):
    print(f"Opening: {COMPETITION_URL}")
    page.goto(COMPETITION_URL, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(10000)
    accept_cookies(page)

    # Scroll slowly to trigger lazy loading
    for _ in range(25):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(500)

    page.keyboard.press("Control+Home")
    page.wait_for_timeout(2000)

    # Now extract from fully rendered DOM
    links = page.evaluate("""
        () => {
            const results = [];
            // Get all anchor tags
            document.querySelectorAll('a').forEach(a => {
                const href = a.href || '';
                if (href.includes('OB_EV') && href.includes('/football/')) {
                    results.push(href);
                }
            });
            // Also check data attributes and onclick handlers
            document.querySelectorAll('[data-event-id], [data-ob-id], [data-id]').forEach(el => {
                const id = el.dataset.eventId || el.dataset.obId || el.dataset.id;
                if (id && id.includes('EV')) results.push(id);
            });
            return [...new Set(results)];
        }
    """)

    print(f"  DOM links: {links[:5]}")

    # If still empty — try clicking the first match name and grab the URL
    if not links:
        print("  Trying click approach...")
        fixtures = []
        seen = set()

        # Get team names from page text
        text = page.locator("body").inner_text(timeout=15000)
        lines = [clean(l) for l in text.splitlines() if clean(l)]

        match_pairs = []
        for i, line in enumerate(lines):
            if line in WORLD_CUP_TEAMS and i+1 < len(lines) and lines[i+1] in WORLD_CUP_TEAMS:
                match_pairs.append((line, lines[i+1]))

        print(f"  Found {len(match_pairs)} match pairs in text")

        for home, away in match_pairs[:MAX_MATCHES]:
            try:
                # Click on home team name
                page.get_by_text(home, exact=True).first.click(timeout=5000)
                page.wait_for_url("**/OB_EV**", timeout=8000)
                url = page.url.split("?")[0]
                if url not in seen and "OB_EV" in url:
                    seen.add(url)
                    fixtures.append({"url": url, "name": f"{home} v {away}"})
                    print(f"  ✓ {home} v {away}: {url}")
                page.go_back()
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"  ⚠ {home}: {e}")
                try:
                    page.goto(COMPETITION_URL, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                except:
                    pass

        return fixtures[:MAX_MATCHES]

    # Process found links
    fixtures = []
    seen = set()
    for url in links:
        base = url.split("?")[0]
        if base in seen: continue
        seen.add(base)
        slug = base.split("/")[-1]
        name = slug.replace("-vs-", " v ").replace("-", " ").title()
        fixtures.append({"url": base, "name": name})

    print(f"Found {len(fixtures)} fixtures")
    return fixtures[:MAX_MATCHES]


def detect_teams(text):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    # WH shows "Mexico v South Africa" in the breadcrumb
    for line in lines[:20]:
        m = re.match(r'^(.+?)\s+v\s+(.+?)$', line, re.I)
        if m:
            h, a = m.group(1).strip(), m.group(2).strip()
            if h in WORLD_CUP_TEAMS and a in WORLD_CUP_TEAMS:
                return h, a
    # Fallback: two consecutive team names
    for i, line in enumerate(lines):
        if line in WORLD_CUP_TEAMS and i+1 < len(lines) and lines[i+1] in WORLD_CUP_TEAMS:
            return line, lines[i+1]
    return "", ""


def scrape_match(page, fixture):
    url  = fixture["url"]
    name = fixture["name"]
    print(f"  Scraping: {name}")

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookies(page)

    all_text = ""

    # Popular tab (already active by default)
    scroll_page(page, 15)
    all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Goals tab
    if click_tab(page, "Goals"):
        print(f"    ✓ Goals tab")
        scroll_page(page, 10)
        # Click 1st Half sub-tab
        try:
            page.get_by_text("1st Half", exact=True).first.click(timeout=3000)
            page.wait_for_timeout(1500)
            scroll_page(page, 8)
        except Exception:
            pass
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Half tab
    if click_tab(page, "Half"):
        print(f"    ✓ Half tab")
        scroll_page(page, 10)
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(all_text, encoding="utf-8")

    home, away = detect_teams(all_text)
    if not home:
        parts = name.split(" v ")
        home = parts[0].strip() if len(parts)==2 else ""
        away = parts[1].strip() if len(parts)==2 else ""

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
    print("William Hill World Cup Props Scraper")
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
        "bookmaker":    "WilliamHill",
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