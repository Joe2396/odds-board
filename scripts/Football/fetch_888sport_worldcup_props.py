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
MAX_MATCHES     = 3
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


# ── Player Props Parsers ────────────────────────────────────────────────────

# 888Sport threshold label mapping:
# "PLAYER TO HAVE ONE OR MORE SHOTS AT GOAL" = SOT 1+ (line 0.5)
# "OVER 1 SHOTS ON TARGET"                   = SOT 2+ (line 1.5)
# "OVER 2 SHOTS ON TARGET"                   = SOT 3+ (line 2.5)
# "OVER 3 SHOTS ON TARGET"                   = SOT 4+ (line 3.5)
# "PLAYER OVER 1 SHOT"                       = Shots 2+ (line 1.5)
# "PLAYER OVER 2 SHOTS"                      = Shots 3+ (line 2.5)
# "PLAYER OVER 3 SHOTS"                      = Shots 4+ (line 3.5)

PLAYER_PROP_HEADINGS = {
    # (heading_upper, market_name, prop_type, line, threshold_label)
    # NOTE: 888Sport "Over N" means N+1 threshold (e.g. "Over 1 Shots" = 2+ shots)
    # But "Player To Have One Or More Shots At Goal" = SOT 1+ (line 0.5)
    "PLAYER TO SCORE":                            ("Player to Score",              "anytime_scorer",    "0.5", "To Score"),
    "PLAYER TO HAVE ONE OR MORE SHOTS AT GOAL":   ("Shots On Target",              "shots_on_target",   "0.5", "1+"),
    "OVER 1 SHOTS ON TARGET":                     ("Shots On Target",              "shots_on_target",   "1.5", "2+"),
    "OVER 2 SHOTS ON TARGET":                     ("Shots On Target",              "shots_on_target",   "2.5", "3+"),
    "OVER 3 SHOTS ON TARGET":                     ("Shots On Target",              "shots_on_target",   "3.5", "4+"),
    "PLAYER OVER 1 SHOT":                         ("Shots",                        "shots",             "1.5", "2+"),
    "PLAYER OVER 2 SHOTS":                        ("Shots",                        "shots",             "2.5", "3+"),
    "PLAYER OVER 3 SHOTS":                        ("Shots",                        "shots",             "3.5", "4+"),
    "PLAYER OVER 4 SHOTS":                        ("Shots",                        "shots",             "4.5", "5+"),
    "PLAYER TO ASSIST":                           ("Player Assists",               "assists",           "0.5", "1+"),
    "PLAYER SHOWN A CARD":                        ("Player Cards",                 "player_card",       "0.5", "To Be Carded"),
}

# Stop words — uppercase headings that end a player block
PLAYER_SECTION_STOPS = {
    "PLAYER TO SCORE", "PLAYER FIRST GOALSCORER", "PLAYER TO ASSIST",
    "PLAYER SHOWN A CARD", "PLAYER TO BE SENT OFF", "PLAYER TO HAVE TWO OR MORE ASSISTS",
    "PLAYER TO HAVE ONE OR MORE SHOTS AT GOAL", "PLAYER OVER 1 SHOT", "PLAYER OVER 2 SHOTS",
    "PLAYER OVER 3 SHOTS", "PLAYER OVER 4 SHOTS", "PLAYER OVER 5 SHOTS", "PLAYER OVER 6 SHOTS",
    "OVER 1 SHOTS ON TARGET", "OVER 2 SHOTS ON TARGET", "OVER 3 SHOTS ON TARGET",
    "FIRST PLAYER TO BE CARDED", "PLAYER TO SCORE OR ASSIST",
    "TOTAL GOALS OVER/UNDER", "1ST HALF - TOTAL GOALS OVER/UNDER",
    "MATCH WINNER", "BOTH TEAMS TO SCORE", "DOUBLE CHANCE", "CORRECT SCORE",
    "CORNERS", "CARDS", "BET BUILDER", "HALF TIME",
    "1ST FRANCE GOALSCORER", "1ST SENEGAL GOALSCORER",
    "1ST HOME GOALSCORER", "1ST AWAY GOALSCORER",
    "PLAYER TO SCORE A HEADER", "PLAYER TO SCORE FROM OUTSIDE THE BOX",
}


def parse_player_section(lines, heading_upper, market_name, prop_type, line, threshold_label):
    """
    Parse a player prop section from flattened text.
    Format:
      SECTION HEADING
      Player Name
      Odds
      Player Name
      Odds
      ...
      See more / next heading
    """
    # Find the occurrence of the heading that has actual player data following it.
    # 888Sport renders headings twice: first collapsed (just 'BB' follows),
    # then expanded (player names and odds follow). We want the expanded one.
    idx = -1
    for i, l in enumerate(lines):
        if clean(l).upper() == heading_upper:
            # Check if odds appear within the next 15 lines
            has_data = any(
                is_odds(clean(lines[j]))
                for j in range(i+1, min(i+15, len(lines)))
            )
            if has_data:
                idx = i
                break
    if idx == -1:
        return mkt(market_name, [])

    block = lines[idx+1 : idx+200]
    sels = []
    i = 0
    while i < len(block):
        player = clean(block[i])

        # Stop at next section heading
        if player.upper() in PLAYER_SECTION_STOPS:
            break
        # Stop at obvious non-player lines
        if not player or len(player) < 3:
            i += 1; continue
        if player.upper() == player and len(player) > 8:
            break  # all-caps long string = new section
        # Skip bet builder badges, info text, and other non-player lines
        if player in {"See more", "See More", "Show more", "Show More", "BB"}:
            i += 1; continue
        if player.startswith("Impact Sub"):
            i += 1; continue
        if player.startswith("If your player"):
            i += 1; continue
        if is_odds(player):
            i += 1; continue
        # Next line should be odds
        if i+1 < len(block) and is_odds(clean(block[i+1])):
            odds = clean(block[i+1])
            sels.append(sel(
                f"{player} {threshold_label}",
                odds,
                {"player": player, "prop_type": prop_type, "line": line}
            ))
            i += 2
        else:
            i += 1

    return mkt(f"{market_name}", sels)


def parse_player_props(lines):
    """Parse all player prop markets from Player tab text."""
    all_markets = []
    seen_mkt_line = set()  # (market_name, line)

    for heading_upper, (market_name, prop_type, line, threshold_label) in PLAYER_PROP_HEADINGS.items():
        key = (prop_type, line)
        if key in seen_mkt_line:
            continue
        try:
            m = parse_player_section(lines, heading_upper, market_name, prop_type, line, threshold_label)
            if m and m.get("selections"):
                seen_mkt_line.add(key)
                all_markets.append(m)
        except Exception:
            pass

    return all_markets


    label_map = {"1X":"Home or Draw","X2":"Away or Draw","12":"Home or Away"}
    block = lines[idx:idx+15]
    for i, line in enumerate(block):
        label = clean(line)
        if label in label_map and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label_map[label], block[i+1]))
    return mkt("Double Chance", selections)


# ── Player Props Parsers ────────────────────────────────────────────────────

# 888Sport threshold label mapping:
# "PLAYER TO HAVE ONE OR MORE SHOTS AT GOAL" = SOT 1+ (line 0.5)
# "OVER 1 SHOTS ON TARGET"                   = SOT 2+ (line 1.5)
# "OVER 2 SHOTS ON TARGET"                   = SOT 3+ (line 2.5)
# "OVER 3 SHOTS ON TARGET"                   = SOT 4+ (line 3.5)
# "PLAYER OVER 1 SHOT"                       = Shots 2+ (line 1.5)
# "PLAYER OVER 2 SHOTS"                      = Shots 3+ (line 2.5)
# "PLAYER OVER 3 SHOTS"                      = Shots 4+ (line 3.5)

PLAYER_PROP_HEADINGS = {
    # (heading_upper, market_name, prop_type, line, threshold_label)
    # NOTE: 888Sport "Over N" means N+1 threshold (e.g. "Over 1 Shots" = 2+ shots)
    # But "Player To Have One Or More Shots At Goal" = SOT 1+ (line 0.5)
    "PLAYER TO SCORE":                            ("Player to Score",              "anytime_scorer",    "0.5", "To Score"),
    "PLAYER TO HAVE ONE OR MORE SHOTS AT GOAL":   ("Shots On Target",              "shots_on_target",   "0.5", "1+"),
    "OVER 1 SHOTS ON TARGET":                     ("Shots On Target",              "shots_on_target",   "1.5", "2+"),
    "OVER 2 SHOTS ON TARGET":                     ("Shots On Target",              "shots_on_target",   "2.5", "3+"),
    "OVER 3 SHOTS ON TARGET":                     ("Shots On Target",              "shots_on_target",   "3.5", "4+"),
    "PLAYER OVER 1 SHOT":                         ("Shots",                        "shots",             "1.5", "2+"),
    "PLAYER OVER 2 SHOTS":                        ("Shots",                        "shots",             "2.5", "3+"),
    "PLAYER OVER 3 SHOTS":                        ("Shots",                        "shots",             "3.5", "4+"),
    "PLAYER OVER 4 SHOTS":                        ("Shots",                        "shots",             "4.5", "5+"),
    "PLAYER TO ASSIST":                           ("Player Assists",               "assists",           "0.5", "1+"),
    "PLAYER SHOWN A CARD":                        ("Player Cards",                 "player_card",       "0.5", "To Be Carded"),
}

# Stop words — uppercase headings that end a player block
PLAYER_SECTION_STOPS = {
    "PLAYER TO SCORE", "PLAYER FIRST GOALSCORER", "PLAYER TO ASSIST",
    "PLAYER SHOWN A CARD", "PLAYER TO BE SENT OFF", "PLAYER TO HAVE TWO OR MORE ASSISTS",
    "PLAYER TO HAVE ONE OR MORE SHOTS AT GOAL", "PLAYER OVER 1 SHOT", "PLAYER OVER 2 SHOTS",
    "PLAYER OVER 3 SHOTS", "PLAYER OVER 4 SHOTS", "PLAYER OVER 5 SHOTS", "PLAYER OVER 6 SHOTS",
    "OVER 1 SHOTS ON TARGET", "OVER 2 SHOTS ON TARGET", "OVER 3 SHOTS ON TARGET",
    "FIRST PLAYER TO BE CARDED", "PLAYER TO SCORE OR ASSIST",
    "TOTAL GOALS OVER/UNDER", "1ST HALF - TOTAL GOALS OVER/UNDER",
    "MATCH WINNER", "BOTH TEAMS TO SCORE", "DOUBLE CHANCE", "CORRECT SCORE",
    "CORNERS", "CARDS", "BET BUILDER", "HALF TIME",
    "1ST FRANCE GOALSCORER", "1ST SENEGAL GOALSCORER",
    "1ST HOME GOALSCORER", "1ST AWAY GOALSCORER",
    "PLAYER TO SCORE A HEADER", "PLAYER TO SCORE FROM OUTSIDE THE BOX",
}


def parse_player_section(lines, heading_upper, market_name, prop_type, line, threshold_label):
    """
    Parse a player prop section from flattened text.
    Format:
      SECTION HEADING
      Player Name
      Odds
      Player Name
      Odds
      ...
      See more / next heading
    """
    # Find the occurrence of the heading that has actual player data following it.
    # 888Sport renders headings twice: first collapsed (just 'BB' follows),
    # then expanded (player names and odds follow). We want the expanded one.
    idx = -1
    for i, l in enumerate(lines):
        if clean(l).upper() == heading_upper:
            # Check if odds appear within the next 15 lines
            has_data = any(
                is_odds(clean(lines[j]))
                for j in range(i+1, min(i+15, len(lines)))
            )
            if has_data:
                idx = i
                break
    if idx == -1:
        return mkt(market_name, [])

    block = lines[idx+1 : idx+200]
    sels = []
    i = 0
    while i < len(block):
        player = clean(block[i])

        # Stop at next section heading
        if player.upper() in PLAYER_SECTION_STOPS:
            break
        # Stop at obvious non-player lines
        if not player or len(player) < 3:
            i += 1; continue
        if player.upper() == player and len(player) > 8:
            break  # all-caps long string = new section
        # Skip bet builder badges, info text, and other non-player lines
        if player in {"See more", "See More", "Show more", "Show More", "BB"}:
            i += 1; continue
        if player.startswith("Impact Sub"):
            i += 1; continue
        if player.startswith("If your player"):
            i += 1; continue
        if is_odds(player):
            i += 1; continue
        # Next line should be odds
        if i+1 < len(block) and is_odds(clean(block[i+1])):
            odds = clean(block[i+1])
            sels.append(sel(
                f"{player} {threshold_label}",
                odds,
                {"player": player, "prop_type": prop_type, "line": line}
            ))
            i += 2
        else:
            i += 1

    return mkt(f"{market_name}", sels)


def parse_player_props(lines):
    """Parse all player prop markets from Player tab text."""
    all_markets = []
    seen_mkt_line = set()  # (market_name, line)

    for heading_upper, (market_name, prop_type, line, threshold_label) in PLAYER_PROP_HEADINGS.items():
        key = (prop_type, line)
        if key in seen_mkt_line:
            continue
        try:
            m = parse_player_section(lines, heading_upper, market_name, prop_type, line, threshold_label)
            if m and m.get("selections"):
                seen_mkt_line.add(key)
                all_markets.append(m)
        except Exception:
            pass

    return all_markets



def parse_correct_score(lines):
    """Correct Score — stub, not needed for props EV/arb."""
    return mkt("Correct Score", [])


def parse_ht_ft(lines):
    """Half Time / Full Time — stub."""
    return mkt("Half Time / Full Time", [])


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

    parser_names = ["match_winner","total_goals","half_goals","correct_score","half_result","ht_ft","btts","double_chance"]
    for name, parser in zip(parser_names, parsers):
        try:
            m = parser()
            if m is None:
                print(f"    WARNING: {name} returned None")
                continue
            if m["selections"]:
                markets.append(m)
        except Exception as e:
            print(f"    Parser error ({name}): {e}")

    # Parse player props
    try:
        player_markets = parse_player_props(lines)
        markets += player_markets
    except Exception as e:
        print(f"    Player props error: {e}")

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


def expand_player_accordions(page):
    """
    Click collapsed player prop accordions using JS to find element coordinates,
    then page.mouse.click() to trigger React event handlers reliably.
    """
    target_headings = [
        "PLAYER TO HAVE ONE OR MORE SHOTS AT GOAL",
        "OVER 1 SHOTS ON TARGET",
        "OVER 2 SHOTS ON TARGET",
        "OVER 3 SHOTS ON TARGET",
        "PLAYER OVER 1 SHOT",
        "PLAYER OVER 2 SHOTS",
        "PLAYER OVER 3 SHOTS",
        "PLAYER OVER 4 SHOTS",
        "PLAYER TO ASSIST",
        "PLAYER SHOWN A CARD",
        "PLAYER TO SCORE OR ASSIST",
    ]
    for heading in target_headings:
        try:
            coords = page.evaluate(f"""() => {{
                const heading = {repr(heading)};
                // Find the innermost text node that matches the heading exactly
                const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let tn;
                while (tn = walk.nextNode()) {{
                    if (tn.textContent.trim() === heading) {{
                        // Found the text node - walk up to clickable container
                        let el = tn.parentElement;
                        for (let i = 0; i < 10; i++) {{
                            if (!el || el === document.body) break;
                            el.scrollIntoView({{behavior:'instant', block:'center'}});
                            const r = el.getBoundingClientRect();
                            // Look for header row: wide, short height, visible
                            if (r.width > 200 && r.height > 10 && r.height < 80 && r.top >= 0) {{
                                return {{x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height}};
                            }}
                            el = el.parentElement;
                        }}
                        break;
                    }}
                }}
                return null;
            }}""")
            if coords:
                page.mouse.click(coords['x'], coords['y'])
                page.wait_for_timeout(700)
                print(f"      clicked {heading[:30]} at ({coords['x']:.0f},{coords['y']:.0f}) w={coords.get('w',0):.0f}")
            else:
                print(f"      no coords for: {heading[:40]}")
        except Exception as e:
            print(f"      expand error ({heading[:30]}): {e}")

    # Click all "See more" buttons to load full player lists
    page.wait_for_timeout(500)
    for _ in range(25):
        try:
            sm = page.get_by_text("See more", exact=True)
            if sm.count() > 0:
                sm.first.scroll_into_view_if_needed(timeout=1000)
                sm.first.click(timeout=1000)
                page.wait_for_timeout(300)
            else:
                break
        except Exception:
            break


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

    # Click Goals tab
    if click_tab(page, "Goals"):
        print(f"    ✓ Goals tab")
        scroll_page(page, 15)
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Click Half tab
    if click_tab(page, "Half"):
        print(f"    ✓ Half tab")
        scroll_page(page, 10)
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Click All Markets tab
    if click_tab(page, "All Markets"):
        print(f"    ✓ All Markets tab")
        scroll_page(page, 20)
        all_text += "\n" + page.locator("body").inner_text(timeout=15000)

    # Click Player tab and expand all player prop accordions
    if click_tab(page, "Player"):
        print(f"    ✓ Player tab")
        page.wait_for_timeout(2000)
        scroll_page(page, 5)
        # Expand all collapsed accordions on player tab
        try:
            expand_player_accordions(page)
        except Exception as e:
            print(f"    accordion expand error: {e}")
        scroll_page(page, 20)
        player_text = page.locator("body").inner_text(timeout=15000)
        all_text += "\n" + player_text

    if not all_text:
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