#!/usr/bin/env python3
"""
fetch_ladbrokes_shots_props.py

Separate scraper for Ladbrokes shots markets:
  - Over/Under Total Shots On Target (Match, Home, Away)
  - Over/Under Total Shots (Match, Home, Away)

Merges output into ladbrokes_worldcup_props.json
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT      = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "ladbrokes_worldcup_props.json"
DEBUG_DIR  = ROOT / "football" / "debug" / "ladbrokes_shots"

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

def clean(s):
    return re.sub(r"\s+"," ",str(s or "")).strip()

def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))

def normalize(s):
    s = clean(s).lower().replace("&","and").replace("?","")
    return re.sub(r"[^a-z0-9]+","_",s).strip("_")

def sel(name, odds, extra=None):
    obj = {"selection":clean(name),"normalized_selection":normalize(name),"odds":clean(odds).upper()}
    if extra: obj.update(extra)
    return obj

def mkt(name, selections):
    return {"market":name,"normalized_market":normalize(name),"selection_count":len(selections),"selections":selections}


def parse_shots_ou(lines, market_name, max_line=40.0):
    """
    Parse O/U lines from a block.
    Handles format:
      [Match/Team tabs]
      Total Shots On Target / Total Shots
      Over  Under
      7.5
      8/13
      23/20
      8.5
      11/10
      4/6
    """
    skip = {"Over","Under","Show All","Show Less","Show Stats","Match",
            "Total Shots On Target","Total Shots","Total Fouls",
            "Total Shots On Target Over / Under","Total Shots Over / Under"}
    sels = []
    i = 0
    while i < len(lines):
        label = clean(lines[i])
        if label in skip or label in WORLD_CUP_TEAMS:
            i += 1; continue
        if not re.match(r"^\d", label) and len(label) > 5 and sels:
            break
        if re.match(r"^\d+\.?\d*$", label):
            try:
                if float(label) > max_line: i += 1; continue
            except: pass
            odds = []
            j = i + 1
            while j < len(lines) and len(odds) < 2:
                tok = clean(lines[j])
                if is_odds(tok):
                    odds.append(tok)
                elif re.match(r"^\d+\.?\d*$", tok):
                    break
                j += 1
            if len(odds) == 2:
                sels.append(sel(f"Over {label}",  odds[0], {"side":"over",  "line":label}))
                sels.append(sel(f"Under {label}", odds[1], {"side":"under", "line":label}))
                i = j
                continue
        i += 1
    return mkt(market_name, sels)


def accept_cookies(page):
    for label in ["Accept All","Accept all","I Accept","Accept","Agree","Allow all","Got it"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except: pass

def scroll_page(page, steps=8):
    for _ in range(steps):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(300)

def get_body(page):
    try:
        return page.locator("body").inner_text(timeout=15000)
    except:
        return ""

def click_accordion(page, heading):
    """Click accordion by finding element via JS and using mouse coordinates."""
    try:
        # Get the bounding rect via JS - works even on non-visible elements
        result = page.evaluate(f"""() => {{
            // Find all text nodes containing exactly this heading
            const heading = '{heading}';
            const all = Array.from(document.querySelectorAll('h2, h3, h4, span, div, p, button, a'));
            // Find element whose trimmed text matches exactly
            const el = all.find(e => {{
                const txt = (e.innerText || e.textContent || '').trim();
                return txt === heading;
            }});
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            // Scroll element into view
            el.scrollIntoView({{behavior: 'instant', block: 'center'}});
            const rect2 = el.getBoundingClientRect();
            return {{x: rect2.left + rect2.width/2, y: rect2.top + rect2.height/2, 
                     visible: el.offsetParent !== null, tag: el.tagName, 
                     cls: el.className.substring(0,50)}};
        }}""")
        
        if not result:
            return "not_found_in_dom"
        
        page.wait_for_timeout(300)
        x, y = result['x'], result['y']
        page.mouse.click(x, y)
        page.wait_for_timeout(2000)
        return f"js_rect_click at ({x:.0f},{y:.0f}) tag={result.get('tag')} visible={result.get('visible')}"
    except Exception as e:
        return f"error: {e}"

def click_tab(page, tab_name):
    """Click a sub-tab (Match, Brazil, Morocco etc)."""
    try:
        result = page.evaluate(f"""() => {{
            const name = '{tab_name}';
            const els = Array.from(document.querySelectorAll('button, a, [role="tab"], [role="button"]'));
            const el = els.find(e => e.innerText && e.innerText.trim() === name);
            if (el) {{ el.click(); return 'clicked'; }}
            return 'not_found';
        }}""")
        return result
    except:
        return "error"


def scrape_match_shots(page, match_url, home, away, match_name):
    """
    Scrape shots/SOT markets using /all-markets URL.
    On /all-markets the SOT and Shots accordions are already expanded
    and all tab data is in the page text — no clicking needed.
    Format from console:
      Over/Under Total Shots On Target
      Match\nBrazil\nMorocco
      Total Shots On Target\nOver\nUnder
      4.5\n3/5\n6/5
    """
    markets = []
    all_url = match_url.replace("/main-markets", "/all-markets")

    page.goto(all_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    accept_cookies(page)
    scroll_page(page, 20)

    text = get_body(page)

    # Write debug
    slug = re.sub(r"[^a-z0-9]+", "-", match_name.lower()).strip("-")
    (DEBUG_DIR / f"{slug}_shots.txt").write_text(text, encoding="utf-8")

    lines = [clean(l) for l in text.splitlines() if clean(l)]

    # Parse match-level and team-level shots/SOT
    for heading, base_name, max_l in [
        ("Over/Under Total Shots On Target", "Shots On Target", 20.0),
        ("Over/Under Total Shots",           "Shots",           40.0),
    ]:
        # Navigate fresh for each heading so page state is clean
        page.goto(all_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        accept_cookies(page)
        scroll_page(page, 6)
        page.keyboard.press("Control+Home")
        page.wait_for_timeout(500)
        # Click accordion and wait for it to open
        result = click_accordion(page, heading)
        print(f"    click {heading}: {result}")
        page.wait_for_timeout(2000)

        # Read Match tab (default after opening)
        text = get_body(page)
        lines_fresh = [clean(l) for l in text.splitlines() if clean(l)]

        # Find heading in fresh text
        idx = -1
        for i, l in enumerate(lines_fresh):
            if clean(l) == heading:
                # Check if expanded (tabs should follow)
                block_check = [clean(lines_fresh[j]) for j in range(i+1, min(i+8, len(lines_fresh)))]
                if "Match" in block_check or home in block_check:
                    idx = i
                    break

        if idx == -1:
            print(f"    {heading}: accordion did not open")
            continue

        block = lines_fresh[idx:idx+80]
        print(f"    {heading}: opened, block[1:8]={block[1:8]}")

        # Find where "Match" tab starts — that's default view
        match_idx = next((j for j,l in enumerate(block) if clean(l) == "Match"), -1)
        if match_idx == -1:
            print(f"    {heading}: no Match tab found")
            continue

        # Parse match-level data (from Match tab onwards)
        m = parse_shots_ou(block[match_idx:], f"Total {base_name} Over / Under", max_l)
        if m["selections"]:
            markets.append(m)
            print(f"    match {base_name}: {m['selection_count']} selections")
        else:
            print(f"    match {base_name}: 0 selections")

        # Now click each team tab
        for team in [home, away]:
            result2 = click_tab(page, team)
            print(f"    {team} tab: {result2}")
            page.wait_for_timeout(1500)
            text2 = get_body(page)
            lines2 = [clean(l) for l in text2.splitlines() if clean(l)]
            idx2 = next((i for i,l in enumerate(lines2) if clean(l) == heading), -1)
            if idx2 == -1: continue
            block2 = lines2[idx2:idx2+40]
            m2 = parse_shots_ou(block2, f"{team} {base_name} Over / Under", max_l)
            if m2["selections"]:
                markets.append(m2)
                print(f"    {team} {base_name}: {m2['selection_count']} selections")
            else:
                print(f"    {team} {base_name}: 0 selections")

    return markets


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing props
    if not PROPS_PATH.exists():
        print(f"ERROR: {PROPS_PATH} not found — run fetch_ladbrokes_worldcup_props.py first")
        return

    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    matches = data.get("matches", [])
    print(f"Loaded {len(matches)} matches from existing props")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        for i, match in enumerate(matches):
            home = match.get("home_team","")
            away = match.get("away_team","")
            url  = match.get("url","").replace("/main-markets","") + "/main-markets"
            name = match.get("match","")
            if not home or not away or not url:
                continue

            print(f"\n[{i+1}/{len(matches)}] {name}")
            try:
                new_markets = scrape_match_shots(page, url, home, away, name)
                if new_markets:
                    # Merge into existing markets (avoid dupes by normalized_market key)
                    existing_keys = {m["normalized_market"] for m in match.get("markets",[])}
                    added = 0
                    for m in new_markets:
                        if m["normalized_market"] not in existing_keys:
                            match["markets"].append(m)
                            existing_keys.add(m["normalized_market"])
                            added += 1
                    match["market_count"] = len(match["markets"])
                    print(f"  Added {added} new markets → total {match['market_count']}")
                else:
                    print(f"  No new markets found")
            except Exception as e:
                print(f"  ERROR: {e}")

        browser.close()

    # Save updated props
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    PROPS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Saved → {PROPS_PATH}")

    print("\n── Summary ──────────────────────────────────────────────")
    for m in matches:
        shots_mkts = [mk for mk in m.get("markets",[]) if "shot" in mk["market"].lower()]
        if shots_mkts:
            print(f"  {m['match']:<40} {[mk['market'] for mk in shots_mkts]}")
    print("─" * 60)


if __name__ == "__main__":
    main()