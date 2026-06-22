#!/usr/bin/env python3
"""
fetch_ladbrokes_worldcup_props.py

Markets:
  Match:  Match Betting, BTTS, Double Chance, Half Time Result,
          Total Goals O/U, 1st Half Goals O/U,
          Total Shots On Target O/U, Total Shots O/U,
          Total Corners O/U, Total Cards O/U,
          Team Corners O/U (home/away)
  Player: First/Anytime Goalscorer,
          Shots On Target, Shots, Player Cards,
          Player Fouls, Player Assists, Player Tackles
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT      = Path(__file__).resolve().parents[2]
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
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Match Betting"), -1)
    if idx == -1: return mkt("Match Betting", [])
    block = lines[idx:idx+20]
    for i, line in enumerate(block):
        if clean(line) == "90 Mins" and i+3 < len(block):
            if is_odds(block[i+1]) and is_odds(block[i+2]) and is_odds(block[i+3]):
                return mkt("Match Betting", [
                    sel(home,   block[i+1], {"side":"home"}),
                    sel("Draw", block[i+2], {"side":"draw"}),
                    sel(away,   block[i+3], {"side":"away"}),
                ])
        if clean(line) == home and i+2 < len(block):
            if clean(block[i+1]) == "Draw" and clean(block[i+2]) == away:
                for j in range(i+3, min(i+8, len(block))):
                    if clean(block[j]) == "90 Mins" and j+3 < len(block):
                        if is_odds(block[j+1]) and is_odds(block[j+2]) and is_odds(block[j+3]):
                            return mkt("Match Betting", [
                                sel(home,   block[j+1], {"side":"home"}),
                                sel("Draw", block[j+2], {"side":"draw"}),
                                sel(away,   block[j+3], {"side":"away"}),
                            ])
    return mkt("Match Betting", [])


def parse_btts(lines):
    # Try multiple patterns for BTTS
    for i, l in enumerate(lines):
        if clean(l) != "Both Teams To Score":
            continue
        block = lines[i:i+20]
        # Pattern 1: "90 Mins" then two odds
        for j, line in enumerate(block):
            if clean(line) == "90 Mins" and j+2 < len(block):
                if is_odds(block[j+1]) and is_odds(block[j+2]):
                    return mkt("Both Teams To Score", [
                        sel("Both Teams To Score - Yes", block[j+1], {"side":"yes"}),
                        sel("Both Teams To Score - No",  block[j+2], {"side":"no"}),
                    ])
        # Pattern 2: odds appear within 5 lines (half tab format)
        odds_found = [clean(lines[k]) for k in range(i+1, min(i+6, len(lines))) if is_odds(clean(lines[k]))]
        if len(odds_found) >= 2:
            return mkt("Both Teams To Score", [
                sel("Both Teams To Score - Yes", odds_found[0], {"side":"yes"}),
                sel("Both Teams To Score - No",  odds_found[1], {"side":"no"}),
            ])
    return mkt("Both Teams To Score", [])


def parse_ou_goals(lines, market_name="Total Goals Over / Under", max_line=5.5):
    best_idx = -1
    for i, l in enumerate(lines):
        if clean(l) == "Over/Under Total Goals":
            block_check = [clean(lines[j]) for j in range(i, min(i+8, len(lines)))]
            if "90 Mins" in block_check:
                best_idx = i
    if best_idx == -1: return mkt(market_name, [])
    block = lines[best_idx:best_idx+40]
    sels = []
    collecting = False
    i = 0
    while i < len(block):
        label = clean(block[i])
        # Skip these always
        if label in {"Over/Under Total Goals","Show Stats","Match","Over","Under",
                     "1st Half","2nd Half","Show All","SUSP"}:
            if label == "90 Mins": collecting = True
            i += 1; continue
        if label == "90 Mins":
            collecting = True; i += 1; continue
        if label in {"Show Less","Match Betting And Total Goals"} and collecting:
            break
        # Stop if we hit a non-numeric non-odds line after collecting starts
        if collecting and not re.match(r'^\d+\.?\d*$', label) and not is_odds(label):
            if len(sels) > 0:  # only break if we already have some data
                break
            i += 1; continue
        if collecting and re.match(r'^\d+\.?\d*$', label):
            try:
                if float(label) > max_line:
                    i += 1; continue
            except: pass
            if i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
                sels.append(sel(f"Over {label}",  block[i+1], {"side":"over",  "line":label}))
                sels.append(sel(f"Under {label}", block[i+2], {"side":"under", "line":label}))
                i += 3; continue
        i += 1
    return mkt(market_name, sels)


def parse_ou_generic(lines, heading, market_name, max_line=None):
    # Use last occurrence
    best_idx = -1
    for i, l in enumerate(lines):
        if clean(l) == heading:
            best_idx = i
    if best_idx == -1: return mkt(market_name, [])
    block = lines[best_idx:best_idx+60]
    skip = {"Over","Under","Show All","Show Less","Show Stats",
            "90 Mins","1st Half","2nd Half","Match"}
    sels = []
    i = 0
    while i < len(block):
        label = clean(block[i])
        if label in skip or label in WORLD_CUP_TEAMS or label == heading:
            i += 1; continue
        if not re.match(r'^\d', label) and len(label) > 3:
            i += 1; continue
        if re.match(r'^\d+\.?\d*$', label):
            if max_line:
                try:
                    if float(label) > max_line:
                        i += 1; continue
                except: pass
            if i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
                sels.append(sel(f"Over {label}",  block[i+1], {"side":"over",  "line":label}))
                sels.append(sel(f"Under {label}", block[i+2], {"side":"under", "line":label}))
                i += 3; continue
        i += 1
    return mkt(market_name, sels)


def parse_double_chance(lines, home="", away=""):
    """
    Parse only the standard 90-minute Double Chance triplet.

    This version does not rely on each label being immediately followed by its
    price. Ladbrokes commonly renders all labels first, followed by a 90 Mins
    row containing the three prices.
    """
    selections = []

    idx = next(
        (i for i, line in enumerate(lines) if clean(line) == "Double Chance"),
        -1,
    )
    if idx == -1:
        return mkt("Double Chance", selections)

    block = lines[idx:idx + 35]
    label_map = {
        "1X": ("home_draw", f"{home or 'Home'} or Draw"),
        "X2": ("away_draw", f"{away or 'Away'} or Draw"),
        "12": ("home_away", f"{home or 'Home'} or {away or 'Away'}"),
    }

    ordered_labels = []
    for line in block:
        label = clean(line)
        if label in label_map and label not in ordered_labels:
            ordered_labels.append(label)

    if set(ordered_labels) != {"1X", "X2", "12"}:
        return mkt("Double Chance", selections)

    odds = []

    # Preferred Ladbrokes layout: "90 Mins" followed by three prices.
    ninety_idx = next(
        (i for i, line in enumerate(block) if clean(line) == "90 Mins"),
        -1,
    )
    if ninety_idx >= 0:
        odds = [
            clean(line)
            for line in block[ninety_idx + 1:ninety_idx + 10]
            if is_odds(line)
        ][:3]

    # Fallback: first three prices after all labels.
    if len(odds) != 3:
        last_label_idx = max(
            i for i, line in enumerate(block)
            if clean(line) in label_map
        )
        odds = [
            clean(line)
            for line in block[last_label_idx + 1:last_label_idx + 12]
            if is_odds(line)
        ][:3]

    # Final fallback: a true alternating label/price layout.
    if len(odds) != 3:
        direct = {}
        for i, line in enumerate(block):
            label = clean(line)
            if (
                label in label_map
                and i + 1 < len(block)
                and is_odds(block[i + 1])
            ):
                direct[label] = clean(block[i + 1])

        if set(direct) == {"1X", "X2", "12"}:
            odds = [direct[label] for label in ordered_labels]

    if len(odds) != 3:
        return mkt("Double Chance", selections)

    def decimal(price):
        price = clean(price).upper()
        if price in {"EVS", "EVENS", "EVEN"}:
            return 2.0
        if "/" not in price:
            return None
        try:
            num, den = price.split("/", 1)
            return (float(num) / float(den)) + 1.0
        except Exception:
            return None

    decimals = [decimal(price) for price in odds]
    if any(not value or value <= 1 for value in decimals):
        return mkt("Double Chance", selections)

    # A complete Double Chance triplet should be close to 1 after accounting
    # for the overlapping outcomes. A much smaller value means wrong prices.
    self_arb_sum = 0.5 * sum(1.0 / value for value in decimals)
    if not 0.97 <= self_arb_sum <= 1.25:
        print(
            f"    Rejecting invalid Ladbrokes Double Chance triplet: "
            f"{odds} (self sum {self_arb_sum:.3f})"
        )
        return mkt("Double Chance", selections)

    for label, price in zip(ordered_labels, odds):
        side, display = label_map[label]
        selections.append(
            sel(
                display,
                price,
                {
                    "side": side,
                    "base_market": "double_chance",
                    "period": "full_time",
                },
            )
        )

    return mkt("Double Chance", selections)

def parse_total_shots_ou(lines):
    """Over/Under Total Shots On Target and Total Shots."""
    markets = []
    for heading, mkt_name, max_l in [
        ("Over/Under Total Shots On Target", "Total Shots On Target Over / Under", 20.5),
        ("Over/Under Total Shots", "Total Shots Over / Under", 40.5),
    ]:
        m = parse_ou_generic(lines, heading, mkt_name, max_l)
        if m["selections"]: markets.append(m)
    return markets


def parse_team_corners(lines, home, away):
    """Team-specific corners O/U — e.g. Qatar/Switzerland Total Corners."""
    markets = []
    for team in [home, away]:
        heading = f"Over/Under Total Corners {team}"
        # Find first occurrence that has actual number lines nearby
        best_idx = -1
        for i, l in enumerate(lines):
            if clean(l) == heading:
                block_check = [clean(lines[j]) for j in range(i+1, min(i+15, len(lines)))]
                if any(re.match(r"^\d+\.?\d*$", x) for x in block_check):
                    best_idx = i
                    break  # use first good occurrence
        if best_idx == -1: continue
        block = lines[best_idx:best_idx+40]
        skip = {"Over","Under","Show All","Show Less","Show Stats",
                "90 Mins","1st Half","2nd Half","Match", heading}
        sels = []
        i = 0
        while i < len(block):
            label = clean(block[i])
            if label in skip or label in WORLD_CUP_TEAMS:
                i += 1; continue
            if not re.match(r"^\d", label) and len(label) > 3:
                i += 1; continue
            if re.match(r"^\d+\.?\d*$", label):
                try:
                    if float(label) > 12.5: i += 1; continue
                except: pass
                if i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
                    sels.append(sel(f"{team} Over {label}",  block[i+1],
                                   {"side":"over","line":label,"team":team}))
                    sels.append(sel(f"{team} Under {label}", block[i+2],
                                   {"side":"under","line":label,"team":team}))
                    i += 3; continue
            i += 1
        if sels:
            markets.append(mkt(f"{team} Corners Over / Under", sels))
    return markets


def parse_team_shots(lines, home, away):
    """Team-specific shots O/U — Brazil Total Shots / Morocco Total Shots."""
    markets = []
    for team in [home, away]:
        for heading, suffix, max_l in [
            (f"Over/Under Total Shots On Target", f"{team} Shots On Target Over / Under", 15.5),
            (f"Over/Under Total Shots",           f"{team} Shots Over / Under",            35.5),
        ]:
            # Find occurrence where team name appears nearby as a tab
            best_idx = -1
            for i, l in enumerate(lines):
                if clean(l) == heading:
                    block_check = [clean(lines[j]) for j in range(i, min(i+20, len(lines)))]
                    if team in block_check:
                        best_idx = i
            if best_idx == -1: continue
            block = lines[best_idx:best_idx+60]
            # Find the team tab and collect numbers after it
            team_idx = next((j for j,l in enumerate(block) if clean(l) == team), -1)
            if team_idx == -1: continue
            sels = []
            j = team_idx + 1
            while j < len(block):
                label = clean(block[j])
                if label in {"Match", home, away, "Over", "Under",
                             "Show All", "Show Less", "Total Shots On Target",
                             "Total Shots", heading}: j += 1; continue
                if not re.match(r'^\d+\.?\d*$', label) and not is_odds(label):
                    if sels: break
                    j += 1; continue
                if re.match(r'^\d+\.?\d*$', label):
                    try:
                        if float(label) > max_l: j += 1; continue
                    except: pass
                    if j+2 < len(block) and is_odds(block[j+1]) and is_odds(block[j+2]):
                        sels.append(sel(f"{team} Over {label}", block[j+1],
                                       {"side":"over","line":label,"team":team}))
                        sels.append(sel(f"{team} Under {label}", block[j+2],
                                       {"side":"under","line":label,"team":team}))
                        j += 3; continue
                j += 1
            if sels:
                markets.append(mkt(suffix, sels))
    return markets


def parse_match_shots_ou(lines):
    """Match-level Total Shots On Target and Total Shots O/U."""
    markets = []
    for heading, mkt_name, max_l in [
        ("Over/Under Total Shots On Target", "Total Shots On Target Over / Under", 20.5),
        ("Over/Under Total Shots",           "Total Shots Over / Under",            40.5),
    ]:
        best_idx = -1
        for i, l in enumerate(lines):
            if clean(l) == heading:
                block_check = [clean(lines[j]) for j in range(i, min(i+8, len(lines)))]
                if "Match" in block_check or any(is_odds(x) for x in block_check):
                    best_idx = i
        if best_idx == -1: continue
        block = lines[best_idx:best_idx+50]
        sels = []
        collecting = False
        i = 0
        while i < len(block):
            label = clean(block[i])
            if label in {heading, "Show Stats", "Over", "Under", "Total Shots On Target",
                         "Total Shots", "Show All", "Show Less"}:
                i += 1; continue
            if label == "Match":
                collecting = True; i += 1; continue
            if collecting and label in {"Brazil","Morocco","Haiti","Scotland",
                                        "Qatar","Switzerland","Australia","Turkey",
                                        "Türkiye","Germany","Curacao","Netherlands",
                                        "Japan","France","Senegal","Argentina","Algeria"}:
                break  # hit team tab, stop match-level collection
            if collecting and re.match(r'^\d+\.?\d*$', label):
                try:
                    if float(label) > max_l: i += 1; continue
                except: pass
                if i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
                    sels.append(sel(f"Over {label}",  block[i+1], {"side":"over",  "line":label}))
                    sels.append(sel(f"Under {label}", block[i+2], {"side":"under", "line":label}))
                    i += 3; continue
            i += 1
        if sels:
            markets.append(mkt(mkt_name, sels))
    return markets


def parse_half_time_result(lines, home, away):
    idx = next((i for i,l in enumerate(lines) if clean(l) in {
        "Half Time Or Full Time Result","Half Time Result","1st Half Betting","Half-Time Result"
    }), -1)
    if idx == -1: return mkt("Half Time Result", [])
    block = lines[idx:idx+15]
    sels = []
    for i, line in enumerate(block):
        label = clean(line)
        if label in {home,"Draw",away} and i+1 < len(block) and is_odds(block[i+1]):
            sels.append(sel(label, block[i+1]))
    return mkt("Half Time Result", sels)


def parse_goalscorers(lines):
    idx = next((i for i,l in enumerate(lines) if clean(l) in {
        "Popular Goalscorer Markets","Goalscorer","Goalscorers","Player To Score"
    }), -1)
    if idx == -1: return mkt("Player to Score", [])
    skip = {"Popular Goalscorer Markets","Goalscorer","Goalscorers","Player To Score",
            "Show All","Show Less","No Goalscorer","Show Stats","First Team Goalscorer",
            "Other Goalscorer Markets","Player To Score First & Result",
            "Player To Score And Their Team To Win"} | WORLD_CUP_TEAMS
    block = lines[idx:idx+200]
    sels = []
    i = 0
    while i < len(block):
        player = clean(block[i])
        if not player or player in skip or is_odds(player) or len(player) > 50:
            if player in {"First Team Goalscorer","Other Goalscorer Markets",
                         "Player To Score First & Result","Player To Score And Their Team To Win"}:
                break
            i += 1; continue
        if i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
            sels.append(sel(f"{player} First Goalscorer",   block[i+1], {"player":player,"prop_type":"first_goalscorer"}))
            sels.append(sel(f"{player} Anytime Goalscorer", block[i+2], {"player":player,"prop_type":"anytime_goalscorer"}))
            i += 3
            if i < len(block) and is_odds(block[i]): i += 1
        else:
            i += 1
    return mkt("Player to Score", sels)


def parse_player_tackles(lines):
    """
    Player Total Tackles — separate accordion, not a filter button.
    Format:
        Player Total Tackles
        Show Stats
        Brazil / Morocco  (team tabs — skip)
        PLAYERS  1+  2+  3+  4+  (headers — skip)
        Casemiro
        Brazil        (team name — skip)
        -             (no price — skip)
        1/12
        3/10
        4/5
    """
    idx = next((i for i,l in enumerate(lines) if clean(l) == "Player Total Tackles"), -1)
    if idx == -1: return mkt("Player Tackles", [])
    block = lines[idx:idx+400]
    sels = []
    seen = {}
    i = 0
    while i < len(block):
        player = clean(block[i])
        if (not player or player in WORLD_CUP_TEAMS or is_odds(player)
                or len(player) > 50
                or player in {"Player Total Tackles","PLAYERS","Show Stats",
                              "Show All","Show Less","1+","2+","3+","4+","-"}
                or re.match(r"^\d", player)):
            i += 1; continue
        # skip team name on next line
        j = i + 1
        if j < len(block) and clean(block[j]) in WORLD_CUP_TEAMS:
            j += 1
        # collect up to 4 odds, skipping "-"
        odds_found = []
        thresholds = ["1+","2+","3+","4+"]
        while j < len(block) and len(odds_found) < 4:
            tok = clean(block[j])
            if tok == "-":
                odds_found.append(None)
            elif is_odds(tok):
                odds_found.append(tok)
            elif tok and tok not in WORLD_CUP_TEAMS and not tok.startswith("Player"):
                break
            j += 1
        if any(o for o in odds_found if o):
            pk = player.lower()
            seen.setdefault(pk, {"name": player, "odds": {}})
            for k, o in enumerate(odds_found):
                if o:
                    seen[pk]["odds"].setdefault(thresholds[k], o)
            i = j
        else:
            i += 1
    for pd in seen.values():
        for threshold, odds in pd["odds"].items():
            line = str(float(threshold.replace("+","")) - 0.5)
            sels.append(sel(
                f"{pd['name']} Over {line} Tackles",
                odds,
                {"player": pd["name"], "prop_type": "tackles", "line": line}
            ))
    return mkt("Player Tackles", sels)


def parse_player_stat(lines, market_name, prop_type, threshold_label):
    """Handles single column (Carded) and multi-column (Fouls 1+/2+/3+, SoT, Shots)."""
    idx = next((i for i,l in enumerate(lines) if clean(l) == "PLAYERS"), -1)
    if idx == -1: idx = 0

    # Detect multi-threshold headers (1+, 2+, 3+) near PLAYERS header
    header_block = lines[idx:idx+10]
    thresholds = [clean(l) for l in header_block if re.match(r"^\d+\+$", clean(l))]
    if not thresholds:
        thresholds = ["1+"]

    lines_map = {"1+": "0.5", "2+": "1.5", "3+": "2.5", "4+": "3.5"}
    block = lines[idx:idx+400]
    sels = []
    i = 0
    skip = {"PLAYERS","Show All","Show Less","Show Stats",
            "SoT","Carded","Fouls","Scorer","Shots","Assists","1+","2+","3+","4+"}
    while i < len(block):
        player = clean(block[i])
        if (not player or player in WORLD_CUP_TEAMS or is_odds(player)
                or len(player) > 50 or player in skip
                or re.match(r"^\d", player)):
            i += 1; continue
        j = i + 1
        if j < len(block) and clean(block[j]) in WORLD_CUP_TEAMS:
            j += 1
        odds_found = []
        while j < len(block) and len(odds_found) < len(thresholds):
            tok = clean(block[j])
            if is_odds(tok):
                odds_found.append(tok)
            elif tok == "-":
                odds_found.append(None)
            elif tok and tok not in skip and tok not in WORLD_CUP_TEAMS:
                break
            j += 1
        if odds_found:
            for k, o in enumerate(odds_found):
                if o and k < len(thresholds):
                    line = lines_map.get(thresholds[k], "0.5")
                    sels.append(sel(
                        f"{player} Over {line} {market_name}",
                        o,
                        {"player": player, "prop_type": prop_type, "line": line}
                    ))
            i = j
        else:
            i += 1
    return mkt(market_name, sels)


# ── Browser helpers ────────────────────────────────────────────────────────────

def accept_cookies(page):
    for label in ["Accept All","Accept all","I Accept","Accept","Agree","Allow all","Got it"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except: pass

def scroll_page(page, steps=12):
    for _ in range(steps):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(300)

def get_body(page):
    try:
        return page.locator("body").inner_text(timeout=15000)
    except:
        return ""

def expand_show_all(page):
    try:
        btn = page.get_by_text("Show All", exact=True)
        if btn.count():
            btn.first.click(timeout=3000)
            page.wait_for_timeout(1000)
    except: pass

def click_filter(page, name):
    try:
        loc = page.get_by_text(name, exact=True)
        if loc.count():
            loc.first.click(timeout=3000)
            page.wait_for_timeout(1500)
            return True
    except: pass
    return False

def get_match_links(page):
    print(f"Opening: {COMPETITION_URL}")
    page.goto(COMPETITION_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)
    accept_cookies(page)
    for _ in range(20):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(400)
    links = page.evaluate("""
        () => [...new Set(
            Array.from(document.querySelectorAll('a[href*="/sports/event/football/international/world-cup-2026/"]'))
                .map(a => a.href)
                .filter(h => {
                    const path = h.split('/world-cup-2026/')[1] || '';
                    return path.includes('-v-') && !h.includes('outright') && !h.includes('top-goalscorer');
                })
        )]
    """)
    fixtures = []
    seen = set()
    for url in links:
        base = url.split("?")[0]
        if not base.endswith("/main-markets"):
            base = base.rstrip("/") + "/main-markets"
        if base in seen: continue
        seen.add(base)
        parts = base.split("/world-cup-2026/")[-1].split("/")
        slug = parts[0] if parts else ""
        name = slug.replace("-v-"," v ").replace("-"," ").title()
        fixtures.append({"url": base, "name": name})
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
    url  = fixture["url"]
    base = url.replace("/main-markets","")
    name = fixture["name"]
    print(f"  [{name}]")

    all_text = ""

    # Main tab
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookies(page)
    try:
        page.wait_for_function("() => document.body.innerText.includes('Match Betting')", timeout=10000)
    except: pass
    scroll_page(page, 10)
    # Click accordions to expand them
    for heading in ["Both Teams To Score", "Double Chance"]:
        try:
            loc = page.locator(f"text='{heading}'").first
            if loc.count():
                loc.scroll_into_view_if_needed(timeout=2000)
                page.wait_for_timeout(300)
                loc.click(timeout=2000)
                page.wait_for_timeout(1000)
        except: pass
    scroll_page(page, 10)
    expand_show_all(page)
    scroll_page(page, 5)
    all_text += "\n" + get_body(page)
    print(f"    main ok")



    # Goals tab
    page.goto(f"{base}/goals", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    try:
        page.wait_for_function("() => document.body.innerText.includes('Total Goals')", timeout=8000)
    except: pass
    try:
        page.get_by_text("1st Half", exact=True).first.click(timeout=3000)
        page.wait_for_timeout(1500)
    except: pass
    try:
        page.get_by_text("Show All", exact=True).first.click(timeout=3000)
        page.wait_for_timeout(1000)
    except: pass
    scroll_page(page, 10)
    all_text += "\n" + get_body(page)
    print(f"    goals ok")

    # Goalscorer tab
    page.goto(f"{base}/goalscorer", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    expand_show_all(page)
    scroll_page(page, 10)
    all_text += "\n" + get_body(page)
    print(f"    goalscorer ok")

    # Half tab
    page.goto(f"{base}/half", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(7000)
    try:
        page.wait_for_function("() => document.body.innerText.includes('Both Teams To Score')", timeout=8000)
    except: pass
    scroll_page(page, 8)
    all_text += "\n" + get_body(page)
    print(f"    half ok")

    # Corners and Cards tab
    page.goto(f"{base}/corners-and-cards", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    scroll_page(page, 10)
    all_text += "\n" + get_body(page)
    print(f"    corners-and-cards ok")

    # Debug
    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(all_text, encoding="utf-8")

    home, away = detect_teams(all_text)
    if not home:
        slug_part = url.split("/world-cup-2026/")[-1].split("/")[0]
        if "-v-" in slug_part:
            h, a = slug_part.split("-v-", 1)
            home = h.replace("-"," ").title()
            away = a.replace("-"," ").title()

    lines = [clean(l) for l in all_text.splitlines() if clean(l)]

    markets = []
    for parser, args in [
        (parse_match_betting,  (lines, home, away)),
        (parse_btts,           (lines,)),
        (parse_double_chance,  (lines, home, away)),
        (parse_goalscorers,    (lines,)),
        (parse_half_time_result, (lines, home, away)),
    ]:
        try:
            m = parser(*args)
            if m["selections"]: markets.append(m)
        except Exception as e:
            print(f"    Parser error ({parser.__name__}): {e}")

    # Total Goals O/U
    try:
        m = parse_ou_goals(lines, "Total Goals Over / Under", max_line=5.5)
        if m["selections"]: markets.append(m)
    except Exception as e:
        print(f"    Parser error (total_goals): {e}")

    # 1st half goals
    try:
        m = parse_ou_goals(lines, "1st Half Goals Over / Under", max_line=2.5)
        if m["selections"]: markets.append(m)
    except Exception as e:
        print(f"    Parser error (1st_half_goals): {e}")

    for heading, mkt_name, max_line in [
        ("Over/Under Total Corners", "Total Corners Over / Under", 15.5),
        ("Over/Under Total Cards",   "Total Cards Over / Under",  4.5),
    ]:
        try:
            m = parse_ou_generic(lines, heading, mkt_name, max_line)
            if m["selections"]: markets.append(m)
        except Exception as e:
            print(f"    Parser error ({mkt_name}): {e}")



    # Team corners O/U
    try:
        for m in parse_team_corners(lines, home, away):
            markets.append(m)
    except Exception as e:
        print(f"    Parser error (team_corners): {e}")

    # Player Stats tab — click each filter
    try:
        page.goto(f"{base}/player-stats", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        accept_cookies(page)

        filters = [
            ("SoT",     "Shots On Target", "shots_on_target", "Over 0.5 Shots On Target"),
            ("Shots",   "Shots",           "shots",           "Over 0.5 Shots"),
            ("Carded",  "Player Cards",    "player_card",     "To Be Carded"),
            ("Fouls",   "Player Fouls",    "fouls",           "Over 0.5 Fouls"),
            ("Assists", "Player Assists",  "assists",         "Over 0.5 Assists"),
        ]

        for filter_name, mkt_name, prop_type, threshold_label in filters:
            if not click_filter(page, filter_name):
                print(f"    player/{filter_name}: not found")
                continue
            expand_show_all(page)
            scroll_page(page, 10)
            tab_text = get_body(page)
            tab_lines = [clean(l) for l in tab_text.splitlines() if clean(l)]
            m = parse_player_stat(tab_lines, mkt_name, prop_type, threshold_label)
            if m["selections"]:
                markets.append(m)
                print(f"    player/{filter_name}: {m['selection_count']}")
            else:
                print(f"    player/{filter_name}: 0")

        # Player Total Tackles — separate section, not a filter button
        try:
            tab_text = get_body(page)
            tab_lines = [clean(l) for l in tab_text.splitlines() if clean(l)]
            m = parse_player_tackles(tab_lines)
            if m["selections"]:
                markets.append(m)
                print(f"    player/Tackles: {m['selection_count']}")
            else:
                print(f"    player/Tackles: 0")
        except Exception as e:
            print(f"    player/Tackles error: {e}")

        print(f"    player-stats ok")
    except Exception as e:
        print(f"    player-stats error: {e}")

    # Dedupe
    seen, unique = set(), []
    for m in markets:
        k = m["normalized_market"]
        if k not in seen: seen.add(k); unique.append(m)

    print(f"  ✓ {home} v {away} — {len(unique)} markets")
    return {"match": f"{home} v {away}" if home else name,
            "home_team": home, "away_team": away, "url": url, "markets": unique}


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
                print(f"  ERROR: {e}")
                results.append({"match": fixture["name"], "home_team": "", "away_team": "",
                                "url": fixture["url"], "markets": []})

        browser.close()

    output = {
        "sport": "football", "competition": "FIFA World Cup",
        "bookmaker": "Ladbrokes", "market_type": "props",
        "source_url": COMPETITION_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results), "matches": results,
    }
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ Saved → {OUT_PATH}")
    print("\n── Summary ──────────────────────────────────────────────")
    for r in results:
        print(f"  {r['match']:<40} {len(r['markets'])} markets")
        for m in r["markets"]:
            print(f"      - {m['market']} ({m['selection_count']})")
    print("─" * 60)


if __name__ == "__main__":
    main()