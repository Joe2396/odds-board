#!/usr/bin/env python3
"""
fetch_ladbrokes_worldcup_props_FAST_TEST3_V4_COMPONENTS.py

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
import time
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT      = Path(__file__).resolve().parents[2]
OUT_PATH  = ROOT / "football" / "data" / "ladbrokes_worldcup_props_fast_test_v4_components.json"
DEBUG_DIR = ROOT / "football" / "debug" / "ladbrokes_worldcup_props_fast_test_v4_components"

COMPETITION_URL = "https://www.ladbrokes.com/en/sports/competitions/football/international/world-cup-2026"
MAX_MATCHES = 3
HEADLESS = False
SAVE_DEBUG_ARTIFACTS = False

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
                page.wait_for_timeout(350)
                return
        except: pass

def scroll_page(page, steps=12):
    """Trigger Ladbrokes lazy loading with larger, shorter scroll steps."""
    for _ in range(steps):
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(180)

def get_body(page):
    try:
        return page.locator("body").inner_text(timeout=15000)
    except:
        return ""


def wait_for_any_text(page, labels, timeout=8000):
    """Wait until any expected Ladbrokes label appears in body text."""
    try:
        page.wait_for_function(
            """
            labels => {
                const text = (document.body?.innerText || '').toLowerCase();
                return labels.some(label => text.includes(label.toLowerCase()));
            }
            """,
            labels,
            timeout=timeout,
        )
        return True
    except Exception:
        return False

def expand_show_all(page):
    try:
        btn = page.get_by_text("Show All", exact=True)
        if btn.count():
            btn.first.click(timeout=3000)
            page.wait_for_timeout(450)
    except: pass

def click_filter(page, name):
    try:
        loc = page.get_by_text(name, exact=True)
        if loc.count():
            loc.first.click(timeout=3000)
            page.wait_for_timeout(650)
            return True
    except: pass
    return False

def mark_player_stats_cards(page):
    """
    Mark the two independent cards on Ladbrokes' player-stats page:
      - Player Total Tackles
      - Bet Builder Player Markets

    The page contains a PLAYERS heading inside both cards, so parsing the
    entire body causes the player-market parser to start in the tackles card.
    """
    try:
        result = page.evaluate(
            r"""
            () => {
                const clean = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const visible = element => {
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);

                    return (
                        rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                    );
                };

                const exactElement = label => {
                    const candidates = Array.from(
                        document.querySelectorAll(
                            "h1, h2, h3, h4, h5, button, span, div, p"
                        )
                    ).filter(
                        element =>
                            visible(element)
                            && clean(element.innerText) === label
                    );

                    candidates.sort(
                        (a, b) => {
                            const ar = a.getBoundingClientRect();
                            const br = b.getBoundingClientRect();
                            return (
                                ar.width * ar.height
                                - br.width * br.height
                            );
                        }
                    );

                    return candidates[0] || null;
                };

                const climbToCard = (
                    start,
                    requiredLabels
                ) => {
                    let node = start;

                    for (
                        let depth = 0;
                        node && depth < 10;
                        depth += 1, node = node.parentElement
                    ) {
                        const text = clean(node.innerText);

                        if (
                            requiredLabels.every(
                                label => text.includes(label)
                            )
                            && node.getBoundingClientRect().width > 350
                        ) {
                            return node;
                        }
                    }

                    return null;
                };

                document.querySelectorAll(
                    "[data-btb-ladbrokes-card]"
                ).forEach(
                    element =>
                        element.removeAttribute(
                            "data-btb-ladbrokes-card"
                        )
                );

                const tacklesHeading = exactElement(
                    "Player Total Tackles"
                );
                const playerHeading = exactElement(
                    "Bet Builder Player Markets"
                );

                const tacklesCard = climbToCard(
                    tacklesHeading,
                    [
                        "Player Total Tackles",
                        "PLAYERS",
                        "1+",
                        "2+",
                        "3+",
                        "4+",
                    ]
                );

                const playerCard = climbToCard(
                    playerHeading,
                    [
                        "Bet Builder Player Markets",
                        "PLAYERS",
                        "SoT",
                        "Carded",
                        "Fouls",
                        "Shots",
                        "Assists",
                    ]
                );

                if (tacklesCard) {
                    tacklesCard.setAttribute(
                        "data-btb-ladbrokes-card",
                        "tackles"
                    );
                }

                if (playerCard) {
                    playerCard.setAttribute(
                        "data-btb-ladbrokes-card",
                        "player-markets"
                    );
                }

                return {
                    tackles: Boolean(tacklesCard),
                    playerMarkets: Boolean(playerCard),
                };
            }
            """
        )

        return result or {
            "tackles": False,
            "playerMarkets": False,
        }
    except Exception:
        return {
            "tackles": False,
            "playerMarkets": False,
        }


def card_text(page, marker):
    try:
        locator = page.locator(
            f'[data-btb-ladbrokes-card="{marker}"]'
        )

        if not locator.count():
            return ""

        return locator.first.inner_text(
            timeout=8000
        )
    except Exception:
        return ""


def refresh_player_cards_and_text(
    page,
    marker,
    previous_text="",
    timeout_ms=5000,
):
    """
    Ladbrokes often remounts a card after a filter/team click, removing our
    temporary data attribute. Re-mark it and wait for useful card text.
    """
    deadline = time.perf_counter() + (
        timeout_ms / 1000
    )
    latest = ""

    while time.perf_counter() < deadline:
        mark_player_stats_cards(page)
        latest = card_text(page, marker)

        if (
            latest
            and len(latest) >= 80
            and (
                not previous_text
                or latest != previous_text
            )
        ):
            return latest

        page.wait_for_timeout(250)

    mark_player_stats_cards(page)
    return card_text(page, marker)


def write_player_debug(
    fixture_name,
    label,
    content,
):
    """Small test-only card snapshot, not a full-page debug dump."""
    debug_name = (
        f"{slugify(fixture_name)}_"
        f"{slugify(label)}.txt"
    )
    (DEBUG_DIR / debug_name).write_text(
        content,
        encoding="utf-8",
    )


def click_card_label(page, marker, label):
    """
    Click an exact visible label inside one marked card only.
    This avoids accidentally clicking identically named controls elsewhere.
    """
    try:
        clicked = page.evaluate(
            r"""
            ({marker, label}) => {
                const clean = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const card = document.querySelector(
                    `[data-btb-ladbrokes-card="${marker}"]`
                );

                if (!card) {
                    return false;
                }

                const candidates = Array.from(
                    card.querySelectorAll(
                        "button, a, [role='button'], [role='tab'], div, span"
                    )
                ).filter(
                    element => {
                        const rect =
                            element.getBoundingClientRect();
                        const style =
                            getComputedStyle(element);

                        return (
                            clean(element.innerText) === label
                            && rect.width > 0
                            && rect.height > 0
                            && rect.width < 300
                            && rect.height < 100
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                        );
                    }
                );

                candidates.sort(
                    (a, b) => {
                        const ar =
                            a.getBoundingClientRect();
                        const br =
                            b.getBoundingClientRect();

                        return (
                            ar.width * ar.height
                            - br.width * br.height
                        );
                    }
                );

                const target = candidates[0];

                if (!target) {
                    return false;
                }

                target.scrollIntoView({
                    block: "center",
                    inline: "center",
                    behavior: "instant",
                });
                target.click();
                return true;
            }
            """,
            {
                "marker": marker,
                "label": label,
            },
        )

        if clicked:
            page.wait_for_timeout(650)

        return bool(clicked)
    except Exception:
        return False


def expand_show_all_in_card(page, marker):
    """
    Expand every visible Show All control within the selected card.
    Returns the number clicked.
    """
    clicked_total = 0

    for _ in range(3):
        try:
            clicked = page.evaluate(
                r"""
                marker => {
                    const clean = value =>
                        (value || "")
                            .replace(/\s+/g, " ")
                            .trim();

                    const card = document.querySelector(
                        `[data-btb-ladbrokes-card="${marker}"]`
                    );

                    if (!card) {
                        return false;
                    }

                    const candidates = Array.from(
                        card.querySelectorAll(
                            "button, a, [role='button'], div, span"
                        )
                    ).filter(
                        element => {
                            const rect =
                                element.getBoundingClientRect();
                            const style =
                                getComputedStyle(element);

                            return (
                                clean(element.innerText)
                                === "Show All"
                                && rect.width > 0
                                && rect.height > 0
                                && rect.width < 300
                                && rect.height < 100
                                && style.display !== "none"
                                && style.visibility !== "hidden"
                            );
                        }
                    );

                    candidates.sort(
                        (a, b) => {
                            const ar =
                                a.getBoundingClientRect();
                            const br =
                                b.getBoundingClientRect();

                            return (
                                ar.width * ar.height
                                - br.width * br.height
                            );
                        }
                    );

                    const target = candidates[0];

                    if (!target) {
                        return false;
                    }

                    target.scrollIntoView({
                        block: "center",
                        behavior: "instant",
                    });
                    target.click();
                    return true;
                }
                """,
                marker,
            )
        except Exception:
            clicked = False

        if not clicked:
            break

        clicked_total += 1
        page.wait_for_timeout(500)

    return clicked_total


def merge_market_selections(target, incoming):
    """Merge selections into one market without duplicate normalized names."""
    existing = {
        selection.get("normalized_selection")
        for selection in target.get("selections", [])
    }

    for selection in incoming.get("selections", []):
        key = selection.get(
            "normalized_selection"
        )

        if key in existing:
            continue

        target["selections"].append(selection)
        existing.add(key)

    target["selection_count"] = len(
        target["selections"]
    )


def teams_from_fixture_url(url, fallback_name=""):
    slug_part = (
        clean(url)
        .split("/world-cup-2026/")[-1]
        .split("/")[0]
    )

    if "-v-" in slug_part:
        home_slug, away_slug = slug_part.split(
            "-v-",
            1,
        )
        return (
            canonical_team(
                home_slug.replace("-", " ").title()
            ),
            canonical_team(
                away_slug.replace("-", " ").title()
            ),
        )

    match = re.match(
        r"^(.+?)\s+[Vv]\s+(.+?)$",
        clean(fallback_name),
    )

    if match:
        return (
            canonical_team(match.group(1)),
            canonical_team(match.group(2)),
        )

    return "", ""


def event_is_live(page):
    """Reject live/started events because Ladbrokes removes prematch props."""
    try:
        exact_live = page.get_by_text(
            "LIVE",
            exact=True,
        )

        if exact_live.count():
            return True
    except Exception:
        pass

    body = get_body(page)

    return bool(
        re.search(
            r"\b(?:1st|2nd)\s+Half\s*\|\s*\d{1,2}:\d{2}\b",
            body,
            re.I,
        )
        or re.search(
            r"\bHalf Time\b|\bFull Time\b",
            body,
            re.I,
        )
    )


def list_market_titles(page):
    try:
        return page.evaluate(
            r"""
            () => {
                const clean = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                return Array.from(
                    document.querySelectorAll(
                        'markets-group-component '
                        + '[data-crlat="containerHeader"]'
                    )
                )
                    .map(header => clean(header.innerText))
                    .filter(Boolean);
            }
            """
        )
    except Exception:
        return []


def expand_market_component(
    page,
    title,
    show_all=False,
):
    """
    Expand one exact markets-group-component and optionally click its Show All.
    """
    try:
        result = page.evaluate(
            r"""
            ({title, showAll}) => {
                const clean = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const wanted = clean(title).toLowerCase();

                const component = Array.from(
                    document.querySelectorAll(
                        "markets-group-component"
                    )
                ).find(item => {
                    const header = item.querySelector(
                        '[data-crlat="containerHeader"]'
                    );

                    return (
                        header
                        && clean(header.innerText)
                            .toLowerCase() === wanted
                    );
                });

                if (!component) {
                    return {
                        found: false,
                        clicked: false,
                        showAllClicks: 0,
                    };
                }

                const accordion =
                    component.querySelector("accordion");
                const header = component.querySelector(
                    '[data-crlat="containerHeader"]'
                );

                let clicked = false;

                if (
                    header
                    && (
                        !accordion
                        || !accordion.classList.contains(
                            "is-expanded"
                        )
                    )
                ) {
                    header.scrollIntoView({
                        block: "center",
                        behavior: "instant",
                    });
                    header.click();
                    clicked = true;
                }

                return {
                    found: true,
                    clicked,
                    showAllRequested: showAll,
                };
            }
            """,
            {
                "title": title,
                "showAll": show_all,
            },
        )
    except Exception:
        result = {
            "found": False,
            "clicked": False,
        }

    if not result.get("found"):
        return result

    page.wait_for_timeout(
        650 if result.get("clicked") else 250
    )

    show_all_clicks = 0

    if show_all:
        for _ in range(4):
            try:
                clicked_show_all = page.evaluate(
                    r"""
                    title => {
                        const clean = value =>
                            (value || "")
                                .replace(/\s+/g, " ")
                                .trim();

                        const wanted =
                            clean(title).toLowerCase();

                        const component = Array.from(
                            document.querySelectorAll(
                                "markets-group-component"
                            )
                        ).find(item => {
                            const header = item.querySelector(
                                '[data-crlat="containerHeader"]'
                            );

                            return (
                                header
                                && clean(header.innerText)
                                    .toLowerCase()
                                    === wanted
                            );
                        });

                        if (!component) {
                            return false;
                        }

                        const candidates = Array.from(
                            component.querySelectorAll(
                                '[data-crlat="showAllButton"], '
                                + 'button, a, [role="button"], '
                                + 'span, div'
                            )
                        ).filter(element => {
                            const rect =
                                element.getBoundingClientRect();
                            const style =
                                getComputedStyle(element);

                            return (
                                clean(element.innerText)
                                    === "Show All"
                                && rect.width > 0
                                && rect.height > 0
                                && rect.width < 350
                                && rect.height < 120
                                && style.display !== "none"
                                && style.visibility !== "hidden"
                            );
                        });

                        candidates.sort(
                            (a, b) => {
                                const ar =
                                    a.getBoundingClientRect();
                                const br =
                                    b.getBoundingClientRect();

                                return (
                                    ar.width * ar.height
                                    - br.width * br.height
                                );
                            }
                        );

                        const target = candidates[0];

                        if (!target) {
                            return false;
                        }

                        target.scrollIntoView({
                            block: "center",
                            behavior: "instant",
                        });
                        target.click();
                        return true;
                    }
                    """,
                    title,
                )
            except Exception:
                clicked_show_all = False

            if not clicked_show_all:
                break

            show_all_clicks += 1
            page.wait_for_timeout(550)

    result["showAllClicks"] = show_all_clicks
    return result


def click_market_switcher(
    page,
    title,
    label,
):
    try:
        clicked = page.evaluate(
            r"""
            ({title, label}) => {
                const clean = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const wantedTitle =
                    clean(title).toLowerCase();
                const wantedLabel =
                    clean(label).toLowerCase();

                const component = Array.from(
                    document.querySelectorAll(
                        "markets-group-component"
                    )
                ).find(item => {
                    const header = item.querySelector(
                        '[data-crlat="containerHeader"]'
                    );

                    return (
                        header
                        && clean(header.innerText)
                            .toLowerCase()
                            === wantedTitle
                    );
                });

                if (!component) {
                    return false;
                }

                const switcher = Array.from(
                    component.querySelectorAll(
                        '[data-crlat="buttonSwitch"]'
                    )
                ).find(item =>
                    clean(item.innerText).toLowerCase()
                    === wantedLabel
                );

                if (!switcher) {
                    return false;
                }

                switcher.scrollIntoView({
                    block: "center",
                    behavior: "instant",
                });
                switcher.click();
                return true;
            }
            """,
            {
                "title": title,
                "label": label,
            },
        )
    except Exception:
        clicked = False

    if clicked:
        page.wait_for_timeout(650)

    return bool(clicked)


def extract_market_component(page, title):
    """
    Read Ladbrokes' real outcome DOM from one markets-group-component.

    Supports:
      - standard .odds-card rows
      - player table .player-market-odds-item rows
      - Show All expanded rows
      - suspended/missing cells while preserving column position
    """
    try:
        return page.evaluate(
            r"""
            title => {
                const clean = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const wanted =
                    clean(title).toLowerCase();

                const component = Array.from(
                    document.querySelectorAll(
                        "markets-group-component"
                    )
                ).find(item => {
                    const header = item.querySelector(
                        '[data-crlat="containerHeader"]'
                    );

                    return (
                        header
                        && clean(header.innerText)
                            .toLowerCase() === wanted
                    );
                });

                if (!component) {
                    return null;
                }

                const headers = Array.from(
                    component.querySelectorAll(
                        '[data-crlat="oddsHeader"]'
                    )
                ).map(item => clean(item.innerText));

                const switchers = Array.from(
                    component.querySelectorAll(
                        '[data-crlat="buttonSwitch"]'
                    )
                ).map(item => clean(item.innerText));

                const standardRows = Array.from(
                    component.querySelectorAll(
                        ".odds-card"
                    )
                ).map(row => {
                    const nameElement =
                        row.querySelector(
                            '[data-crlat="oddsNames"]'
                        )
                        || row.querySelector(
                            ".odds-left"
                        );

                    const cells = Array.from(
                        row.querySelectorAll(
                            ".odds-btn-wrapper"
                        )
                    ).map(cell => {
                        const price = cell.querySelector(
                            '[data-crlat="oddsPrice"]'
                        );

                        if (price) {
                            return clean(price.innerText);
                        }

                        const raw = clean(cell.innerText);
                        return raw || "-";
                    });

                    return {
                        name: clean(
                            nameElement
                                ? nameElement.innerText
                                : ""
                        ),
                        cells,
                        raw: clean(row.innerText),
                    };
                });

                const names = Array.from(
                    component.querySelectorAll(
                        '[data-crlat="oddsNames"]'
                    )
                ).map(item => clean(item.innerText));

                const matrixRows = Array.from(
                    component.querySelectorAll(
                        ".player-market-odds-item"
                    )
                ).map((row, index) => ({
                    name: names[index] || "",
                    cells: Array.from(
                        row.querySelectorAll(
                            ".odds-btn-wrapper"
                        )
                    ).map(cell => {
                        const price = cell.querySelector(
                            '[data-crlat="oddsPrice"]'
                        );

                        if (price) {
                            return clean(price.innerText);
                        }

                        const raw = clean(cell.innerText);
                        return raw || "-";
                    }),
                    raw: clean(row.innerText),
                }));

                return {
                    title: clean(
                        component.querySelector(
                            '[data-crlat="containerHeader"]'
                        )?.innerText || title
                    ),
                    headers,
                    switchers,
                    rows:
                        matrixRows.length
                            ? matrixRows
                            : standardRows,
                    standardRows,
                    matrixRows,
                    text: clean(component.innerText),
                };
            }
            """,
            title,
        )
    except Exception:
        return None


def extract_marked_card(page, marker):
    """
    Same structured extractor for V2's marked Bet Builder/Tackles cards.
    """
    try:
        return page.evaluate(
            r"""
            marker => {
                const clean = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const root = document.querySelector(
                    `[data-btb-ladbrokes-card="${marker}"]`
                );

                if (!root) {
                    return null;
                }

                const headers = Array.from(
                    root.querySelectorAll(
                        '[data-crlat="oddsHeader"]'
                    )
                ).map(item => clean(item.innerText));

                const names = Array.from(
                    root.querySelectorAll(
                        '[data-crlat="oddsNames"]'
                    )
                ).map(item => clean(item.innerText));

                const matrixRows = Array.from(
                    root.querySelectorAll(
                        ".player-market-odds-item"
                    )
                ).map((row, index) => ({
                    name: names[index] || "",
                    cells: Array.from(
                        row.querySelectorAll(
                            ".odds-btn-wrapper"
                        )
                    ).map(cell => {
                        const price = cell.querySelector(
                            '[data-crlat="oddsPrice"]'
                        );

                        if (price) {
                            return clean(price.innerText);
                        }

                        const raw = clean(cell.innerText);
                        return raw || "-";
                    }),
                    raw: clean(row.innerText),
                }));

                const standardRows = Array.from(
                    root.querySelectorAll(
                        ".odds-card"
                    )
                ).map(row => {
                    const nameElement =
                        row.querySelector(
                            '[data-crlat="oddsNames"]'
                        )
                        || row.querySelector(
                            ".odds-left"
                        );

                    return {
                        name: clean(
                            nameElement
                                ? nameElement.innerText
                                : ""
                        ),
                        cells: Array.from(
                            row.querySelectorAll(
                                ".odds-btn-wrapper"
                            )
                        ).map(cell => {
                            const price = cell.querySelector(
                                '[data-crlat="oddsPrice"]'
                            );

                            if (price) {
                                return clean(price.innerText);
                            }

                            const raw =
                                clean(cell.innerText);
                            return raw || "-";
                        }),
                        raw: clean(row.innerText),
                    };
                });

                return {
                    title: marker,
                    headers,
                    switchers: Array.from(
                        root.querySelectorAll(
                            '[data-crlat="buttonSwitch"]'
                        )
                    ).map(item => clean(item.innerText)),
                    rows:
                        matrixRows.length
                            ? matrixRows
                            : standardRows,
                    standardRows,
                    matrixRows,
                    text: clean(root.innerText),
                };
            }
            """,
            marker,
        )
    except Exception:
        return None


def structured_rows(data):
    if not data:
        return []

    return [
        row
        for row in data.get("rows", [])
        if clean(row.get("name"))
    ]


def structured_headers(data):
    if not data:
        return []

    return [
        clean(header)
        for header in data.get("headers", [])
        if clean(header)
        and clean(header).upper()
            not in {"PLAYERS", "PLAYER"}
    ]


def parse_three_way_component(
    data,
    market_name,
    labels,
    row_label="90 Mins",
):
    rows = structured_rows(data)
    target = next(
        (
            row
            for row in rows
            if normalize(row.get("name"))
            == normalize(row_label)
        ),
        rows[0] if rows else None,
    )

    if not target:
        return mkt(market_name, [])

    prices = [
        clean(cell)
        for cell in target.get("cells", [])
    ]
    selections = []

    for index, label in enumerate(labels):
        if index >= len(prices):
            continue

        price = prices[index]

        if not is_odds(price):
            continue

        side = (
            "home"
            if index == 0
            else "draw"
            if index == 1
            else "away"
        )
        selections.append(
            sel(
                label,
                price,
                {
                    "side": side,
                    "period": "full_time",
                },
            )
        )

    return mkt(market_name, selections)


def parse_double_chance_component(
    data,
    home,
    away,
):
    selections = []

    for row in structured_rows(data):
        display = clean(row.get("name"))
        prices = row.get("cells", [])
        price = next(
            (
                clean(cell)
                for cell in prices
                if is_odds(cell)
            ),
            "",
        )

        if not display or not price:
            continue

        low = display.lower()

        if home.lower() in low and "draw" in low:
            side = "home_draw"
            canonical = f"{home} or Draw"
        elif away.lower() in low and "draw" in low:
            side = "away_draw"
            canonical = f"{away} or Draw"
        elif (
            home.lower() in low
            and away.lower() in low
        ):
            side = "home_away"
            canonical = f"{home} or {away}"
        else:
            continue

        selections.append(
            sel(
                canonical,
                price,
                {
                    "side": side,
                    "base_market": "double_chance",
                    "period": "full_time",
                },
            )
        )

    return mkt(
        "Double Chance",
        selections,
    )


def parse_ou_component(
    data,
    market_name,
    selection_prefix="",
    max_line=None,
):
    selections = []

    for row in structured_rows(data):
        line = clean(row.get("name"))

        if not re.fullmatch(
            r"\d+(?:\.\d+)?",
            line,
        ):
            continue

        if max_line is not None:
            try:
                if float(line) > max_line:
                    continue
            except Exception:
                continue

        cells = [
            clean(cell)
            for cell in row.get("cells", [])
        ]

        if len(cells) < 2:
            continue

        over_price = cells[0]
        under_price = cells[1]

        # Keep complete two-sided lines only; safer for comparison/arb.
        if not (
            is_odds(over_price)
            and is_odds(under_price)
        ):
            continue

        prefix = (
            f"{selection_prefix} "
            if selection_prefix
            else ""
        )

        extra = {
            "line": line,
        }

        if selection_prefix:
            extra["team"] = selection_prefix

        selections.append(
            sel(
                f"{prefix}Over {line}",
                over_price,
                {
                    **extra,
                    "side": "over",
                },
            )
        )
        selections.append(
            sel(
                f"{prefix}Under {line}",
                under_price,
                {
                    **extra,
                    "side": "under",
                },
            )
        )

    return mkt(market_name, selections)


def parse_goalscorer_component(data):
    headers = [
        header
        for header in structured_headers(data)
        if header.lower()
        not in {
            "player",
            "players",
        }
    ]

    lower_headers = [
        header.lower()
        for header in headers
    ]

    first_index = next(
        (
            index
            for index, header in enumerate(
                lower_headers
            )
            if "first" in header
            or "1st" in header
        ),
        None,
    )
    anytime_index = next(
        (
            index
            for index, header in enumerate(
                lower_headers
            )
            if "anytime" in header
        ),
        None,
    )

    # Prematch Ladbrokes normally provides First + Anytime in the first
    # two columns. This fallback is intentionally disabled for live "2nd".
    if (
        first_index is None
        and headers
        and not any(
            "2nd" in header
            for header in lower_headers
        )
    ):
        first_index = 0

    if anytime_index is None and len(headers) >= 2:
        anytime_index = 1

    selections = []

    for row in structured_rows(data):
        player = clean(row.get("name"))

        if (
            not player
            or player.lower()
            == "no goalscorer"
        ):
            continue

        cells = [
            clean(cell)
            for cell in row.get("cells", [])
        ]

        if (
            first_index is not None
            and first_index < len(cells)
            and is_odds(cells[first_index])
        ):
            selections.append(
                sel(
                    f"{player} First Goalscorer",
                    cells[first_index],
                    {
                        "player": player,
                        "prop_type":
                            "first_goalscorer",
                    },
                )
            )

        if (
            anytime_index is not None
            and anytime_index < len(cells)
            and is_odds(cells[anytime_index])
        ):
            selections.append(
                sel(
                    f"{player} Anytime Goalscorer",
                    cells[anytime_index],
                    {
                        "player": player,
                        "prop_type":
                            "anytime_goalscorer",
                    },
                )
            )

    return mkt(
        "Player to Score",
        selections,
    )


def parse_player_component(
    data,
    market_name,
    prop_type,
):
    headers = structured_headers(data)
    thresholds = [
        header
        for header in headers
        if re.fullmatch(
            r"\d+\+",
            header,
        )
    ]

    selections = []
    seen = set()

    for row in structured_rows(data):
        player = clean(row.get("name"))

        if not player:
            continue

        cells = [
            clean(cell)
            for cell in row.get("cells", [])
        ]

        if prop_type == "player_card":
            price = next(
                (
                    cell
                    for cell in cells
                    if is_odds(cell)
                ),
                "",
            )

            if not price:
                continue

            key = (
                normalize(player),
                "0.5",
            )

            if key in seen:
                continue

            seen.add(key)
            selections.append(
                sel(
                    f"{player} To Be Carded",
                    price,
                    {
                        "player": player,
                        "prop_type": prop_type,
                        "line": "0.5",
                    },
                )
            )
            continue

        if not thresholds:
            thresholds = [
                f"{index + 1}+"
                for index in range(
                    max(1, len(cells))
                )
            ]

        for index, threshold in enumerate(
            thresholds
        ):
            if index >= len(cells):
                break

            price = cells[index]

            if not is_odds(price):
                continue

            integer_line = int(
                threshold.replace("+", "")
            )
            line = str(
                float(integer_line) - 0.5
            )

            key = (
                normalize(player),
                line,
            )

            if key in seen:
                continue

            seen.add(key)
            selections.append(
                sel(
                    f"{player} Over {line} "
                    f"{market_name}",
                    price,
                    {
                        "player": player,
                        "prop_type": prop_type,
                        "line": line,
                    },
                )
            )

    return mkt(
        market_name,
        selections,
    )


def merge_markets(markets):
    merged = {}

    for market in markets:
        if not market.get("selections"):
            continue

        key = market["normalized_market"]

        if key not in merged:
            merged[key] = market
            continue

        merge_market_selections(
            merged[key],
            market,
        )

    return list(merged.values())


def get_match_links(page):
    print(f"Opening: {COMPETITION_URL}")
    page.goto(COMPETITION_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4500)
    accept_cookies(page)
    for _ in range(12):
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(220)
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
    return fixtures

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
    total_started = time.perf_counter()
    stage_timings = {}

    url = fixture["url"]
    base = url.replace("/main-markets", "")
    name = fixture["name"]
    home, away = teams_from_fixture_url(
        url,
        name,
    )

    print(f"  [{name}]")
    print(
        f"    fixture teams: "
        f"{home or 'unknown'} v "
        f"{away or 'unknown'}"
    )

    markets = []
    all_text = ""

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------
    stage_started = time.perf_counter()
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )
    page.wait_for_timeout(2500)
    accept_cookies(page)
    wait_for_any_text(
        page,
        ["Match Betting"],
        timeout=10000,
    )

    if event_is_live(page):
        print(
            "    SKIP: event is live/started; "
            "prematch props are no longer complete"
        )
        return None

    scroll_page(page, 8)

    for heading in (
        "Match Betting",
        "Both Teams To Score",
        "Double Chance",
    ):
        result = expand_market_component(
            page,
            heading,
            show_all=False,
        )
        print(
            f"    main/{heading}: "
            f"found={result.get('found')} | "
            f"clicked={result.get('clicked')}"
        )

    match_data = extract_market_component(
        page,
        "Match Betting",
    )
    match_market = parse_three_way_component(
        match_data,
        "Match Betting",
        [home, "Draw", away],
    )
    if match_market["selections"]:
        markets.append(match_market)

    dc_data = extract_market_component(
        page,
        "Double Chance",
    )
    dc_market = parse_double_chance_component(
        dc_data,
        home,
        away,
    )
    if dc_market["selections"]:
        markets.append(dc_market)

    main_text = get_body(page)
    all_text += "\n" + main_text

    # BTTS component varies; preserve proven text fallback too.
    main_lines = [
        clean(line)
        for line in main_text.splitlines()
        if clean(line)
    ]
    btts_market = parse_btts(main_lines)
    if btts_market["selections"]:
        markets.append(btts_market)

    stage_timings["main"] = (
        time.perf_counter() - stage_started
    )
    print(
        f"    main ok "
        f"({stage_timings['main']:.2f}s)"
    )

    # ------------------------------------------------------------------
    # Goals: match, first half, home and away
    # ------------------------------------------------------------------
    stage_started = time.perf_counter()
    page.goto(
        f"{base}/goals",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    wait_for_any_text(
        page,
        ["Over/Under Total Goals"],
        timeout=8000,
    )
    page.wait_for_timeout(700)
    scroll_page(page, 6)

    expand_market_component(
        page,
        "Over/Under Total Goals",
        show_all=True,
    )

    click_market_switcher(
        page,
        "Over/Under Total Goals",
        "90 mins",
    )
    total_goals_data = extract_market_component(
        page,
        "Over/Under Total Goals",
    )
    total_goals_market = parse_ou_component(
        total_goals_data,
        "Total Goals Over / Under",
        max_line=6.5,
    )
    if total_goals_market["selections"]:
        markets.append(total_goals_market)

    click_market_switcher(
        page,
        "Over/Under Total Goals",
        "1st Half",
    )
    first_half_data = extract_market_component(
        page,
        "Over/Under Total Goals",
    )
    first_half_market = parse_ou_component(
        first_half_data,
        "1st Half Goals Over / Under",
        max_line=3.5,
    )
    if first_half_market["selections"]:
        markets.append(first_half_market)

    for team in (home, away):
        title = f"Over/Under Goals {team}"
        result = expand_market_component(
            page,
            title,
            show_all=True,
        )
        data = extract_market_component(
            page,
            title,
        )
        team_market = parse_ou_component(
            data,
            f"{team} Goals Over / Under",
            selection_prefix=team,
            max_line=5.5,
        )
        if team_market["selections"]:
            markets.append(team_market)

        print(
            f"    goals/{team}: "
            f"found={result.get('found')} | "
            f"{team_market['selection_count']}"
        )

    goals_text = get_body(page)
    all_text += "\n" + goals_text

    stage_timings["goals"] = (
        time.perf_counter() - stage_started
    )
    print(
        f"    goals ok "
        f"({stage_timings['goals']:.2f}s)"
    )

    # ------------------------------------------------------------------
    # Goalscorer: both team tabs, full Show All
    # ------------------------------------------------------------------
    stage_started = time.perf_counter()
    page.goto(
        f"{base}/goalscorer",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    wait_for_any_text(
        page,
        [
            "Popular Goalscorer Markets",
            "Goalscorer",
            "Player To Score",
        ],
        timeout=8000,
    )
    page.wait_for_timeout(500)
    scroll_page(page, 5)

    goalscorer_title = next(
        (
            title
            for title in list_market_titles(page)
            if title.lower()
            in {
                "popular goalscorer markets",
                "goalscorer",
                "goalscorers",
                "player to score",
            }
        ),
        "",
    )

    goalscorer_market = mkt(
        "Player to Score",
        [],
    )

    if goalscorer_title:
        for team in (home, away):
            expand_market_component(
                page,
                goalscorer_title,
                show_all=False,
            )
            clicked_team = click_market_switcher(
                page,
                goalscorer_title,
                team,
            )
            expand_result = expand_market_component(
                page,
                goalscorer_title,
                show_all=True,
            )
            data = extract_market_component(
                page,
                goalscorer_title,
            )
            team_market = parse_goalscorer_component(
                data
            )
            merge_market_selections(
                goalscorer_market,
                team_market,
            )
            print(
                f"    goalscorer/{team}: "
                f"tab={clicked_team} | "
                f"Show All="
                f"{expand_result.get('showAllClicks', 0)} | "
                f"captured="
                f"{team_market['selection_count']}"
            )

    if goalscorer_market["selections"]:
        markets.append(goalscorer_market)

    scorer_text = get_body(page)
    all_text += "\n" + scorer_text

    stage_timings["goalscorer"] = (
        time.perf_counter() - stage_started
    )
    print(
        f"    goalscorer ok "
        f"({stage_timings['goalscorer']:.2f}s)"
    )

    # ------------------------------------------------------------------
    # Half
    # ------------------------------------------------------------------
    stage_started = time.perf_counter()
    page.goto(
        f"{base}/half",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_timeout(1600)
    scroll_page(page, 5)

    half_text = get_body(page)
    all_text += "\n" + half_text
    half_lines = [
        clean(line)
        for line in half_text.splitlines()
        if clean(line)
    ]

    half_result = parse_half_time_result(
        half_lines,
        home,
        away,
    )
    if half_result["selections"]:
        markets.append(half_result)

    # Half page is often the most reliable BTTS source.
    btts_half = parse_btts(half_lines)
    if btts_half["selections"]:
        markets.append(btts_half)

    stage_timings["half"] = (
        time.perf_counter() - stage_started
    )
    print(
        f"    half ok "
        f"({stage_timings['half']:.2f}s)"
    )

    # ------------------------------------------------------------------
    # Corners and cards: independent components, not tabs
    # ------------------------------------------------------------------
    stage_started = time.perf_counter()
    page.goto(
        f"{base}/corners-and-cards",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    wait_for_any_text(
        page,
        [
            "Over/Under Total Corners",
            "Over/Under Total Cards",
        ],
        timeout=8000,
    )
    page.wait_for_timeout(500)
    scroll_page(page, 7)

    titles = list_market_titles(page)

    most_corners_title = next(
        (
            title
            for title in titles
            if title.lower()
            == "team to have the most corners"
        ),
        "",
    )
    most_cards_title = next(
        (
            title
            for title in titles
            if "team to have the most total cards"
            in title.lower()
        ),
        "",
    )

    if most_corners_title:
        expand_market_component(
            page,
            most_corners_title,
        )
        data = extract_market_component(
            page,
            most_corners_title,
        )
        market = parse_three_way_component(
            data,
            "Team To Have The Most Corners",
            [home, "Draw", away],
        )
        if market["selections"]:
            markets.append(market)

    if most_cards_title:
        expand_market_component(
            page,
            most_cards_title,
        )
        data = extract_market_component(
            page,
            most_cards_title,
        )
        market = parse_three_way_component(
            data,
            "Team To Have The Most Cards",
            [home, "Draw", away],
        )
        if market["selections"]:
            markets.append(market)

    corner_specs = [
        (
            "Over/Under Total Corners",
            "Total Corners Over / Under",
            "",
            20.5,
        ),
        (
            f"Over/Under Total Corners {home}",
            f"{home} Corners Over / Under",
            home,
            15.5,
        ),
        (
            f"Over/Under Total Corners {away}",
            f"{away} Corners Over / Under",
            away,
            15.5,
        ),
    ]

    card_specs = [
        (
            "Over/Under Total Cards",
            "Total Cards Over / Under",
            "",
            12.5,
        ),
        (
            f"Over/Under Total Cards {home}",
            f"{home} Cards Over / Under",
            home,
            10.5,
        ),
        (
            f"Over/Under Total Cards {away}",
            f"{away} Cards Over / Under",
            away,
            10.5,
        ),
    ]

    for (
        title,
        market_name,
        prefix,
        max_line,
    ) in corner_specs + card_specs:
        result = expand_market_component(
            page,
            title,
            show_all=True,
        )
        data = extract_market_component(
            page,
            title,
        )
        market = parse_ou_component(
            data,
            market_name,
            selection_prefix=prefix,
            max_line=max_line,
        )
        if market["selections"]:
            markets.append(market)

        print(
            f"    component/{title}: "
            f"found={result.get('found')} | "
            f"clicked={result.get('clicked')} | "
            f"{market['selection_count']}"
        )

    corner_text = get_body(page)
    all_text += "\n" + corner_text

    stage_timings["corners_cards"] = (
        time.perf_counter() - stage_started
    )
    print(
        f"    corners-and-cards ok "
        f"({stage_timings['corners_cards']:.2f}s)"
    )

    # ------------------------------------------------------------------
    # Player stats: Bet Builder card + direct-component fallback
    # ------------------------------------------------------------------
    stage_started = time.perf_counter()

    try:
        page.goto(
            f"{base}/player-stats",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(1700)
        accept_cookies(page)
        scroll_page(page, 5)

        marked = mark_player_stats_cards(page)
        print(
            "    player cards: "
            f"tackles={marked.get('tackles')} | "
            f"player-markets="
            f"{marked.get('playerMarkets')}"
        )

        filters = [
            (
                "SoT",
                "Shots On Target",
                "shots_on_target",
            ),
            (
                "Shots",
                "Shots",
                "shots",
            ),
            (
                "Carded",
                "Player Cards",
                "player_card",
            ),
            (
                "Fouls",
                "Player Fouls",
                "fouls",
            ),
            (
                "Assists",
                "Player Assists",
                "assists",
            ),
        ]

        if marked.get("playerMarkets"):
            for (
                filter_name,
                market_name,
                prop_type,
            ) in filters:
                mark_player_stats_cards(page)

                clicked = click_card_label(
                    page,
                    "player-markets",
                    filter_name,
                )

                mark_player_stats_cards(page)
                expanded = expand_show_all_in_card(
                    page,
                    "player-markets",
                )

                mark_player_stats_cards(page)
                data = extract_marked_card(
                    page,
                    "player-markets",
                )
                market = parse_player_component(
                    data,
                    market_name,
                    prop_type,
                )

                if market["selections"]:
                    markets.append(market)

                print(
                    f"    player/{filter_name}: "
                    f"clicked={clicked} | "
                    f"Show All={expanded} | "
                    f"rows="
                    f"{len(structured_rows(data))} | "
                    f"{market['selection_count']}"
                )

        if marked.get("tackles"):
            tackles_market = mkt(
                "Player Tackles",
                [],
            )

            for team in (home, away):
                mark_player_stats_cards(page)
                clicked = click_card_label(
                    page,
                    "tackles",
                    team,
                )
                mark_player_stats_cards(page)
                expanded = expand_show_all_in_card(
                    page,
                    "tackles",
                )
                mark_player_stats_cards(page)
                data = extract_marked_card(
                    page,
                    "tackles",
                )
                team_market = parse_player_component(
                    data,
                    "Player Tackles",
                    "tackles",
                )
                merge_market_selections(
                    tackles_market,
                    team_market,
                )

                print(
                    f"    tackles/{team}: "
                    f"clicked={clicked} | "
                    f"Show All={expanded} | "
                    f"rows="
                    f"{len(structured_rows(data))} | "
                    f"{team_market['selection_count']}"
                )

            if tackles_market["selections"]:
                markets.append(tackles_market)

        # Direct component fallback/supplement.
        direct_patterns = [
            (
                "player total shots on target",
                "Shots On Target",
                "shots_on_target",
            ),
            (
                "player total shots",
                "Shots",
                "shots",
            ),
            (
                "player to be carded",
                "Player Cards",
                "player_card",
            ),
            (
                "player total fouls",
                "Player Fouls",
                "fouls",
            ),
            (
                "player fouls",
                "Player Fouls",
                "fouls",
            ),
            (
                "player total assists",
                "Player Assists",
                "assists",
            ),
            (
                "player to assist",
                "Player Assists",
                "assists",
            ),
            (
                "player total tackles",
                "Player Tackles",
                "tackles",
            ),
        ]

        direct_titles = list_market_titles(page)

        for (
            title_pattern,
            market_name,
            prop_type,
        ) in direct_patterns:
            title = next(
                (
                    candidate
                    for candidate in direct_titles
                    if candidate.lower()
                    == title_pattern
                ),
                "",
            )

            if not title:
                continue

            combined = mkt(
                market_name,
                [],
            )

            # Capture each team tab when available.
            data_initial = extract_market_component(
                page,
                title,
            )
            switches = (
                data_initial.get("switchers", [])
                if data_initial
                else []
            )
            team_switches = [
                team
                for team in (home, away)
                if any(
                    normalize(item)
                    == normalize(team)
                    for item in switches
                )
            ]

            capture_tabs = (
                team_switches
                if team_switches
                else [""]
            )

            for team in capture_tabs:
                expand_market_component(
                    page,
                    title,
                    show_all=False,
                )

                if team:
                    click_market_switcher(
                        page,
                        title,
                        team,
                    )

                expand_result = expand_market_component(
                    page,
                    title,
                    show_all=True,
                )
                data = extract_market_component(
                    page,
                    title,
                )
                market = parse_player_component(
                    data,
                    market_name,
                    prop_type,
                )
                merge_market_selections(
                    combined,
                    market,
                )

                print(
                    f"    direct/{title}"
                    f"{'/' + team if team else ''}: "
                    f"Show All="
                    f"{expand_result.get('showAllClicks', 0)} | "
                    f"rows="
                    f"{len(structured_rows(data))} | "
                    f"{market['selection_count']}"
                )

            if combined["selections"]:
                markets.append(combined)

        all_text += "\n" + get_body(page)

    except Exception as error:
        print(
            f"    player-stats error: {error}"
        )

    stage_timings["player_stats"] = (
        time.perf_counter() - stage_started
    )
    print(
        f"    player-stats total "
        f"({stage_timings['player_stats']:.2f}s)"
    )

    # ------------------------------------------------------------------
    # Safe fallbacks for markets not captured structurally.
    # ------------------------------------------------------------------
    lines = [
        clean(line)
        for line in all_text.splitlines()
        if clean(line)
    ]

    existing_keys = {
        market["normalized_market"]
        for market in markets
        if market.get("selections")
    }

    fallback_specs = [
        (
            "match_betting",
            parse_match_betting,
            (lines, home, away),
        ),
        (
            "both_teams_to_score",
            parse_btts,
            (lines,),
        ),
        (
            "double_chance",
            parse_double_chance,
            (lines, home, away),
        ),
        (
            "player_to_score",
            parse_goalscorers,
            (lines,),
        ),
        (
            "half_time_result",
            parse_half_time_result,
            (lines, home, away),
        ),
    ]

    for key, parser, args in fallback_specs:
        if key in existing_keys:
            continue

        try:
            fallback = parser(*args)
            if fallback["selections"]:
                markets.append(fallback)
        except Exception as error:
            print(
                f"    fallback/{parser.__name__}: "
                f"{error}"
            )

    unique = merge_markets(markets)

    expected = {
        "match_betting",
        "both_teams_to_score",
        "double_chance",
        "player_to_score",
        "total_goals_over_under",
        "total_corners_over_under",
        normalize(f"{home} Corners Over / Under"),
        normalize(f"{away} Corners Over / Under"),
        "total_cards_over_under",
        normalize(f"{home} Cards Over / Under"),
        normalize(f"{away} Cards Over / Under"),
        "shots_on_target",
        "shots",
        "player_cards",
        "player_fouls",
        "player_assists",
        "player_tackles",
    }

    captured = {
        market["normalized_market"]
        for market in unique
    }
    missing = sorted(
        expected - captured
    )

    print(
        "    complete-props audit: "
        + (
            ", ".join(missing)
            if missing
            else "none"
        )
    )

    total_seconds = (
        time.perf_counter() - total_started
    )
    print(
        f"  ✓ {home} v {away} — "
        f"{len(unique)} markets "
        f"in {total_seconds:.2f}s"
    )
    print(
        "    timing: "
        + " | ".join(
            f"{stage}={seconds:.2f}s"
            for stage, seconds
            in stage_timings.items()
        )
    )

    return {
        "match": (
            f"{home} v {away}"
            if home
            else name
        ),
        "home_team": home,
        "away_team": away,
        "url": url,
        "market_count": len(unique),
        "timing": {
            key: round(value, 3)
            for key, value
            in stage_timings.items()
        },
        "total_seconds": round(
            total_seconds,
            3,
        ),
        "missing_markets": missing,
        "markets": unique,
    }



def main():
    script_started = time.perf_counter()

    OUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 64)
    print(
        "Ladbrokes World Cup Props "
        "FAST TEST3 V4 COMPONENTS"
    )
    print("=" * 64)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS
        )
        page = browser.new_page(
            viewport={
                "width": 1700,
                "height": 1000,
            }
        )

        fixtures = get_match_links(page)
        results = []
        attempted = 0

        for fixture in fixtures:
            if len(results) >= MAX_MATCHES:
                break

            attempted += 1
            print(
                f"\n[usable {len(results) + 1}/"
                f"{MAX_MATCHES} | "
                f"candidate {attempted}/"
                f"{len(fixtures)}]"
            )

            try:
                result = scrape_match(
                    page,
                    fixture,
                )

                if result is None:
                    continue

                results.append(result)

            except Exception as error:
                print(
                    f"  ERROR: {error}"
                )

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "Ladbrokes",
        "market_type": "props",
        "source_url": COMPETITION_URL,
        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "match_count": len(results),
        "matches": results,
    }

    OUT_PATH.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"\n✅ Saved → {OUT_PATH}")
    print(
        "\n── Summary "
        "──────────────────────────────────────────────"
    )

    for result in results:
        print(
            f"  {result['match']:<40} "
            f"{len(result['markets'])} markets"
        )

        for market in result["markets"]:
            print(
                f"      - {market['market']} "
                f"({market['selection_count']})"
            )

        if result.get("missing_markets"):
            print(
                "      MISSING: "
                + ", ".join(
                    result["missing_markets"]
                )
            )

    print("─" * 64)
    print(
        f"Total elapsed: "
        f"{time.perf_counter() - script_started:.2f}s"
    )
    print(f"Output: {OUT_PATH}")
    print(
        "Production Ladbrokes props JSON "
        "modified: NO"
    )


if __name__ == "__main__":
    main()