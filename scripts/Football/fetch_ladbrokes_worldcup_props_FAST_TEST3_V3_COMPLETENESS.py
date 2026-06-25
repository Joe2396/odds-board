#!/usr/bin/env python3
"""
fetch_ladbrokes_worldcup_props_FAST_TEST3_V3_COMPLETENESS.py

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
OUT_PATH  = ROOT / "football" / "data" / "ladbrokes_worldcup_props_fast_test_v3_completeness.json"
DEBUG_DIR = ROOT / "football" / "debug" / "ladbrokes_worldcup_props_fast_test_v3_completeness"

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
    Parse the standard 90-minute Double Chance triplet.

    Ladbrokes may render an unexpanded heading before the expanded market.
    Inspect every occurrence and keep the first complete, valid triplet.
    """
    label_map = {
        "1X": (
            "home_draw",
            f"{home or 'Home'} or Draw",
        ),
        "X2": (
            "away_draw",
            f"{away or 'Away'} or Draw",
        ),
        "12": (
            "home_away",
            f"{home or 'Home'} or {away or 'Away'}",
        ),
    }

    def decimal(price):
        price = clean(price).upper()

        if price in {
            "EVS",
            "EVENS",
            "EVEN",
        }:
            return 2.0

        if "/" not in price:
            return None

        try:
            numerator, denominator = price.split(
                "/",
                1,
            )
            return (
                float(numerator)
                / float(denominator)
            ) + 1.0
        except Exception:
            return None

    occurrence_indexes = [
        index
        for index, line in enumerate(lines)
        if clean(line) == "Double Chance"
    ]

    for index in occurrence_indexes:
        block = lines[index:index + 45]

        ordered_labels = []

        for line in block:
            label = clean(line)

            if (
                label in label_map
                and label not in ordered_labels
            ):
                ordered_labels.append(label)

        if set(ordered_labels) != {
            "1X",
            "X2",
            "12",
        }:
            continue

        odds = []
        ninety_index = next(
            (
                row_index
                for row_index, line in enumerate(block)
                if clean(line) == "90 Mins"
            ),
            -1,
        )

        if ninety_index >= 0:
            odds = [
                clean(line)
                for line in block[
                    ninety_index + 1:
                    ninety_index + 12
                ]
                if is_odds(line)
            ][:3]

        if len(odds) != 3:
            last_label_index = max(
                row_index
                for row_index, line in enumerate(block)
                if clean(line) in label_map
            )
            odds = [
                clean(line)
                for line in block[
                    last_label_index + 1:
                    last_label_index + 15
                ]
                if is_odds(line)
            ][:3]

        if len(odds) != 3:
            direct = {}

            for row_index, line in enumerate(block):
                label = clean(line)

                if (
                    label in label_map
                    and row_index + 1 < len(block)
                    and is_odds(
                        block[row_index + 1]
                    )
                ):
                    direct[label] = clean(
                        block[row_index + 1]
                    )

            if set(direct) == {
                "1X",
                "X2",
                "12",
            }:
                odds = [
                    direct[label]
                    for label in ordered_labels
                ]

        if len(odds) != 3:
            continue

        decimals = [
            decimal(price)
            for price in odds
        ]

        if any(
            not value or value <= 1
            for value in decimals
        ):
            continue

        self_arb_sum = 0.5 * sum(
            1.0 / value
            for value in decimals
        )

        if not 0.97 <= self_arb_sum <= 1.25:
            print(
                "    Rejecting invalid Ladbrokes "
                "Double Chance triplet: "
                f"{odds} "
                f"(self sum {self_arb_sum:.3f})"
            )
            continue

        selections = []

        for label, price in zip(
            ordered_labels,
            odds,
        ):
            side, display = label_map[label]
            selections.append(
                sel(
                    display,
                    price,
                    {
                        "side": side,
                        "base_market":
                            "double_chance",
                        "period": "full_time",
                    },
                )
            )

        return mkt(
            "Double Chance",
            selections,
        )

    return mkt("Double Chance", [])



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

def mark_market_card(
    page,
    headings,
    marker,
):
    """
    Mark the smallest visible Ladbrokes card containing one of the headings.
    """
    if isinstance(headings, str):
        headings = [headings]

    try:
        return bool(
            page.evaluate(
                r"""
                ({headings, marker}) => {
                    const clean = value =>
                        (value || "")
                            .replace(/\s+/g, " ")
                            .trim();

                    const visible = element => {
                        const rect =
                            element.getBoundingClientRect();
                        const style =
                            getComputedStyle(element);

                        return (
                            rect.width > 0
                            && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                        );
                    };

                    const candidates = [];

                    for (const heading of headings) {
                        for (
                            const element
                            of document.querySelectorAll(
                                "h1, h2, h3, h4, h5, button, "
                                + "[role='button'], span, div, p"
                            )
                        ) {
                            if (
                                !visible(element)
                                || clean(element.innerText)
                                    !== heading
                            ) {
                                continue;
                            }

                            let node = element;

                            for (
                                let depth = 0;
                                node && depth < 10;
                                depth += 1,
                                node = node.parentElement
                            ) {
                                const rect =
                                    node.getBoundingClientRect();
                                const nodeText =
                                    clean(node.innerText);

                                if (
                                    rect.width >= 350
                                    && rect.width <= 1500
                                    && rect.height >= 70
                                    && rect.height <= 1800
                                    && nodeText.includes(heading)
                                ) {
                                    candidates.push({
                                        node,
                                        area:
                                            rect.width
                                            * rect.height,
                                    });
                                }
                            }
                        }
                    }

                    candidates.sort(
                        (a, b) => a.area - b.area
                    );

                    const best = candidates[0];

                    if (!best) {
                        return false;
                    }

                    document.querySelectorAll(
                        `[data-btb-market-card="${marker}"]`
                    ).forEach(
                        element =>
                            element.removeAttribute(
                                "data-btb-market-card"
                            )
                    );

                    best.node.setAttribute(
                        "data-btb-market-card",
                        marker
                    );

                    return true;
                }
                """,
                {
                    "headings": headings,
                    "marker": marker,
                },
            )
        )
    except Exception:
        return False


def market_card_text(page, marker):
    try:
        locator = page.locator(
            f'[data-btb-market-card="{marker}"]'
        )

        if not locator.count():
            return ""

        return locator.first.inner_text(
            timeout=8000
        )
    except Exception:
        return ""


def click_market_card_label(
    page,
    marker,
    label,
):
    try:
        clicked = page.evaluate(
            r"""
            ({marker, label}) => {
                const clean = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const card = document.querySelector(
                    `[data-btb-market-card="${marker}"]`
                );

                if (!card) {
                    return false;
                }

                const candidates = Array.from(
                    card.querySelectorAll(
                        "button, a, [role='button'], "
                        + "[role='tab'], div, span"
                    )
                ).filter(
                    element => {
                        const rect =
                            element.getBoundingClientRect();
                        const style =
                            getComputedStyle(element);

                        return (
                            clean(element.innerText)
                                === label
                            && rect.width > 0
                            && rect.height > 0
                            && rect.width < 350
                            && rect.height < 120
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
            page.wait_for_timeout(700)

        return bool(clicked)
    except Exception:
        return False


def expand_show_all_in_market_card(
    page,
    marker,
):
    clicked_total = 0

    for _ in range(4):
        if not click_market_card_label(
            page,
            marker,
            "Show All",
        ):
            break

        clicked_total += 1
        page.wait_for_timeout(350)

    return clicked_total


def extract_structured_player_rows(
    page,
    marker,
):
    """
    Extract the smallest visible DOM row around each odds cell.

    Keeping '-' placeholders preserves the correct threshold column.
    """
    try:
        rows = page.evaluate(
            r"""
            marker => {
                const clean = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const oddsPattern =
                    /^(?:\d+\/\d+|EVS|EVENS|EVEN)$/i;

                const card = document.querySelector(
                    `[data-btb-ladbrokes-card="${marker}"]`
                );

                if (!card) {
                    return [];
                }

                const visible = element => {
                    const rect =
                        element.getBoundingClientRect();
                    const style =
                        getComputedStyle(element);

                    return (
                        rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                    );
                };

                const ownText = element =>
                    Array.from(element.childNodes)
                        .filter(
                            node =>
                                node.nodeType
                                === Node.TEXT_NODE
                        )
                        .map(
                            node =>
                                clean(node.textContent)
                        )
                        .filter(Boolean)
                        .join(" ");

                const oddsLeaves = Array.from(
                    card.querySelectorAll(
                        "button, span, div, p"
                    )
                ).filter(
                    element => {
                        if (!visible(element)) {
                            return false;
                        }

                        const text =
                            ownText(element)
                            || clean(element.innerText);

                        return (
                            oddsPattern.test(text)
                            || text === "-"
                        );
                    }
                );

                const rowNodes = new Set();

                for (const oddsElement of oddsLeaves) {
                    let node = oddsElement;
                    let best = null;

                    for (
                        let depth = 0;
                        node
                            && node !== card
                            && depth < 8;
                        depth += 1,
                        node = node.parentElement
                    ) {
                        const rect =
                            node.getBoundingClientRect();

                        if (
                            rect.width < 300
                            || rect.height < 25
                            || rect.height > 150
                        ) {
                            continue;
                        }

                        const lines = clean(
                            node.innerText
                        )
                            .split(/\n+/)
                            .map(clean)
                            .filter(Boolean);

                        const oddsCount = lines.filter(
                            line =>
                                oddsPattern.test(line)
                                || line === "-"
                        ).length;

                        const textCount =
                            lines.length - oddsCount;

                        if (
                            oddsCount >= 1
                            && oddsCount <= 4
                            && textCount >= 1
                        ) {
                            best = node;
                            break;
                        }
                    }

                    if (best) {
                        rowNodes.add(best);
                    }
                }

                const rows = [];

                for (const row of rowNodes) {
                    const rect =
                        row.getBoundingClientRect();

                    const lines = clean(
                        row.innerText
                    )
                        .split(/\n+/)
                        .map(clean)
                        .filter(Boolean);

                    const odds = lines.filter(
                        line =>
                            oddsPattern.test(line)
                            || line === "-"
                    );

                    const labels = lines.filter(
                        line =>
                            !oddsPattern.test(line)
                            && line !== "-"
                            && !/^\d+\+$/.test(line)
                    );

                    rows.push({
                        top: rect.top,
                        labels,
                        odds,
                        raw: lines,
                    });
                }

                rows.sort(
                    (a, b) => a.top - b.top
                );

                return rows;
            }
            """,
            marker,
        )

        return rows or []
    except Exception:
        return []


def market_from_structured_rows(
    rows,
    market_name,
    prop_type,
):
    ignored = {
        "PLAYERS",
        "Show Stats",
        "Show All",
        "Show Less",
        "SoT",
        "Carded",
        "Fouls",
        "Scorer",
        "Shots",
        "Assists",
        "Player Total Tackles",
        "Bet Builder Player Markets",
    }
    threshold_lines = [
        "0.5",
        "1.5",
        "2.5",
        "3.5",
    ]

    selections = []
    seen = set()

    for row in rows:
        labels = [
            clean(label)
            for label in row.get(
                "labels",
                [],
            )
            if clean(label)
        ]

        player = next(
            (
                label
                for label in labels
                if (
                    label not in ignored
                    and label not in WORLD_CUP_TEAMS
                    and not re.match(
                        r"^\d+\+$",
                        label,
                    )
                    and len(label) <= 60
                )
            ),
            "",
        )

        if not player:
            continue

        odds_values = [
            clean(value)
            for value in row.get(
                "odds",
                [],
            )
        ][:4]

        for column, price in enumerate(
            odds_values
        ):
            if price == "-" or not is_odds(price):
                continue

            line = threshold_lines[column]
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
    total_started = time.perf_counter()
    stage_timings = {}

    url  = fixture["url"]
    base = url.replace("/main-markets","")
    name = fixture["name"]
    print(f"  [{name}]")

    all_text = ""
    scoped_markets = []

    # Main tab
    stage_started = time.perf_counter()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
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
    main_text = get_body(page)
    all_text += "\n" + main_text

    if mark_market_card(
        page,
        "Double Chance",
        "double-chance",
    ):
        clicked_dc = click_market_card_label(
            page,
            "double-chance",
            "Double Chance",
        )
        page.wait_for_timeout(450)
        dc_text = market_card_text(
            page,
            "double-chance",
        )
        all_text += "\n" + dc_text
        print(
            "    Double Chance scoped: "
            f"clicked={clicked_dc} | "
            f"chars={len(dc_text)}"
        )

    stage_timings["main"] = time.perf_counter() - stage_started
    print(f"    main ok ({stage_timings['main']:.2f}s)")



    # Goals tab
    stage_started = time.perf_counter()
    page.goto(f"{base}/goals", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1800)
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
    stage_timings["goals"] = time.perf_counter() - stage_started
    print(f"    goals ok ({stage_timings['goals']:.2f}s)")

    # Goalscorer tab
    stage_started = time.perf_counter()
    page.goto(f"{base}/goalscorer", wait_until="domcontentloaded", timeout=30000)
    wait_for_any_text(
        page,
        ["Popular Goalscorer Markets", "Goalscorer", "Player To Score"],
        timeout=7000,
    )
    page.wait_for_timeout(500)
    goalscorer_scoped = mark_market_card(
        page,
        [
            "Popular Goalscorer Markets",
            "Goalscorer",
            "Goalscorers",
            "Player To Score",
        ],
        "goalscorer",
    )

    goalscorer_expanded = 0

    if goalscorer_scoped:
        goalscorer_expanded = (
            expand_show_all_in_market_card(
                page,
                "goalscorer",
            )
        )
    else:
        expand_show_all(page)

    scroll_page(page, 6)

    goalscorer_text = (
        market_card_text(
            page,
            "goalscorer",
        )
        if goalscorer_scoped
        else get_body(page)
    )

    all_text += "\n" + goalscorer_text
    print(
        "    goalscorer scoped: "
        f"{goalscorer_scoped} | "
        f"Show All clicks "
        f"{goalscorer_expanded}"
    )
    stage_timings["goalscorer"] = time.perf_counter() - stage_started
    print(f"    goalscorer ok ({stage_timings['goalscorer']:.2f}s)")

    # Half tab
    stage_started = time.perf_counter()
    page.goto(f"{base}/half", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2200)
    try:
        page.wait_for_function("() => document.body.innerText.includes('Both Teams To Score')", timeout=8000)
    except: pass
    scroll_page(page, 8)
    all_text += "\n" + get_body(page)
    stage_timings["half"] = time.perf_counter() - stage_started
    print(f"    half ok ({stage_timings['half']:.2f}s)")

    # Corners and Cards tab
    stage_started = time.perf_counter()
    page.goto(f"{base}/corners-and-cards", wait_until="domcontentloaded", timeout=30000)
    wait_for_any_text(
        page,
        ["Over/Under Total Corners", "Over/Under Total Cards", "Corners"],
        timeout=7000,
    )
    page.wait_for_timeout(500)
    scroll_page(page, 10)
    corners_page_text = get_body(page)
    all_text += "\n" + corners_page_text

    if mark_market_card(
        page,
        "Over/Under Total Corners",
        "total-corners",
    ):
        click_market_card_label(
            page,
            "total-corners",
            "Over/Under Total Corners",
        )
        expand_show_all_in_market_card(
            page,
            "total-corners",
        )

        for tab_label, market_name in (
            (
                "Match",
                "Total Corners Over / Under",
            ),
            (
                home,
                f"{home} Corners Over / Under",
            ),
            (
                away,
                f"{away} Corners Over / Under",
            ),
        ):
            clicked_tab = click_market_card_label(
                page,
                "total-corners",
                tab_label,
            )
            page.wait_for_timeout(350)
            card_body = market_card_text(
                page,
                "total-corners",
            )
            card_lines = [
                clean(line)
                for line in card_body.splitlines()
                if clean(line)
            ]
            recovered = parse_ou_generic(
                card_lines,
                "Over/Under Total Corners",
                market_name,
                15.5,
            )

            if recovered["selections"]:
                scoped_markets.append(recovered)

            print(
                f"    corners/{tab_label}: "
                f"clicked={clicked_tab} | "
                f"{recovered['selection_count']}"
            )

    if mark_market_card(
        page,
        "Over/Under Total Cards",
        "total-cards",
    ):
        click_market_card_label(
            page,
            "total-cards",
            "Over/Under Total Cards",
        )
        expand_show_all_in_market_card(
            page,
            "total-cards",
        )
        cards_body = market_card_text(
            page,
            "total-cards",
        )
        cards_lines = [
            clean(line)
            for line in cards_body.splitlines()
            if clean(line)
        ]
        recovered_cards = parse_ou_generic(
            cards_lines,
            "Over/Under Total Cards",
            "Total Cards Over / Under",
            8.5,
        )

        if recovered_cards["selections"]:
            scoped_markets.append(
                recovered_cards
            )

        print(
            "    cards scoped: "
            f"{recovered_cards['selection_count']}"
        )

    stage_timings["corners_cards"] = time.perf_counter() - stage_started
    print(
        f"    corners-and-cards ok "
        f"({stage_timings['corners_cards']:.2f}s)"
    )

    # Debug is intentionally disabled during the timing test.
    if SAVE_DEBUG_ARTIFACTS:
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

    # Player Stats page — scrape the two cards independently.
    stage_started = time.perf_counter()

    try:
        page.goto(
            f"{base}/player-stats",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        wait_for_any_text(
            page,
            [
                "Player Total Tackles",
                "Bet Builder Player Markets",
            ],
            timeout=10000,
        )
        page.wait_for_timeout(1400)
        accept_cookies(page)

        # Bring the actual player cards into the viewport before marking them.
        try:
            page.get_by_text(
                "Bet Builder Player Markets",
                exact=True,
            ).first.scroll_into_view_if_needed(
                timeout=3000
            )
            page.wait_for_timeout(500)
        except Exception:
            scroll_page(page, 4)

        marked = mark_player_stats_cards(page)
        print(
            "    player cards: "
            f"tackles={marked.get('tackles')} | "
            "player-markets="
            f"{marked.get('playerMarkets')}"
        )

        # Right-hand Bet Builder Player Markets card.
        filters = [
            (
                "SoT",
                "Shots On Target",
                "shots_on_target",
                "Over 0.5 Shots On Target",
            ),
            (
                "Shots",
                "Shots",
                "shots",
                "Over 0.5 Shots",
            ),
            (
                "Carded",
                "Player Cards",
                "player_card",
                "To Be Carded",
            ),
            (
                "Fouls",
                "Player Fouls",
                "fouls",
                "Over 0.5 Fouls",
            ),
            (
                "Assists",
                "Player Assists",
                "assists",
                "Over 0.5 Assists",
            ),
        ]

        if marked.get("playerMarkets"):
            for (
                filter_name,
                market_name,
                prop_type,
                threshold_label,
            ) in filters:
                if not click_card_label(
                    page,
                    "player-markets",
                    filter_name,
                ):
                    print(
                        f"    player/{filter_name}: "
                        "filter not found"
                    )
                    continue

                expanded = expand_show_all_in_card(
                    page,
                    "player-markets",
                )

                # Re-mark after tab/filter DOM updates.
                mark_player_stats_cards(page)
                rows = extract_structured_player_rows(
                    page,
                    "player-markets",
                )

                market = market_from_structured_rows(
                    rows,
                    market_name,
                    prop_type,
                )

                if market["selections"]:
                    markets.append(market)
                    print(
                        f"    player/{filter_name}: "
                        f"{market['selection_count']} "
                        f"from {len(rows)} rows "
                        f"(Show All clicks {expanded})"
                    )
                else:
                    print(
                        f"    player/{filter_name}: 0 "
                        f"from {len(rows)} rows "
                        f"(Show All clicks {expanded})"
                    )
        else:
            print(
                "    player markets card not found"
            )

        # Left-hand Player Total Tackles card.
        tackles_market = mkt(
            "Player Tackles",
            [],
        )

        if marked.get("tackles"):
            for team in (home, away):
                clicked_team = click_card_label(
                    page,
                    "tackles",
                    team,
                )

                expanded = expand_show_all_in_card(
                    page,
                    "tackles",
                )

                mark_player_stats_cards(page)
                tackle_rows = (
                    extract_structured_player_rows(
                        page,
                        "tackles",
                    )
                )

                team_market = (
                    market_from_structured_rows(
                        tackle_rows,
                        "Player Tackles",
                        "tackles",
                    )
                )

                merge_market_selections(
                    tackles_market,
                    team_market,
                )

                print(
                    f"    player/Tackles {team}: "
                    f"tab_clicked={clicked_team} | "
                    f"rows={len(tackle_rows)} | "
                    f"captured="
                    f"{team_market['selection_count']} | "
                    f"Show All clicks {expanded}"
                )

            if tackles_market["selections"]:
                markets.append(tackles_market)
                print(
                    "    player/Tackles total: "
                    f"{tackles_market['selection_count']}"
                )
            else:
                print(
                    "    player/Tackles total: 0"
                )
        else:
            print(
                "    tackles card not found"
            )

        if SAVE_DEBUG_ARTIFACTS:
            player_debug = (
                DEBUG_DIR
                / f"{slugify(name)}_player_stats.txt"
            )
            player_debug.write_text(
                get_body(page),
                encoding="utf-8",
            )

        print("    player-stats ok")

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

    markets.extend(scoped_markets)

    # Merge duplicate captures. Scoped recovery may contain more selections
    # than the original whole-page parser, so first-wins would lose data.
    unique_by_key = {}

    for market in markets:
        key = market["normalized_market"]

        if key not in unique_by_key:
            unique_by_key[key] = market
            continue

        merge_market_selections(
            unique_by_key[key],
            market,
        )

    unique = list(unique_by_key.values())

    expected_markets = {
        "match_betting",
        "both_teams_to_score",
        "double_chance",
        "player_to_score",
        "total_goals_over_under",
        "total_corners_over_under",
        "total_cards_over_under",
        "shots_on_target",
        "shots",
        "player_cards",
        "player_fouls",
        "player_assists",
        "player_tackles",
    }

    captured_keys = {
        market["normalized_market"]
        for market in unique
    }
    missing_markets = sorted(
        expected_markets - captured_keys
    )

    print(
        "    missing-market audit: "
        + (
            ", ".join(missing_markets)
            if missing_markets
            else "none"
        )
    )

    total_seconds = time.perf_counter() - total_started
    print(
        f"  ✓ {home} v {away} — {len(unique)} markets "
        f"in {total_seconds:.2f}s"
    )
    print(
        "    timing: "
        + " | ".join(
            f"{stage}={seconds:.2f}s"
            for stage, seconds in stage_timings.items()
        )
    )

    return {
        "match": f"{home} v {away}" if home else name,
        "home_team": home,
        "away_team": away,
        "url": url,
        "market_count": len(unique),
        "timing": {
            key: round(value, 3)
            for key, value in stage_timings.items()
        },
        "total_seconds": round(total_seconds, 3),
        "missing_markets": missing_markets,
        "markets": unique,
    }


def main():
    script_started = time.perf_counter()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Ladbrokes World Cup Props FAST TEST3 V3 COMPLETENESS")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
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
    print(
        f"Total elapsed: "
        f"{time.perf_counter() - script_started:.2f}s"
    )
    print(f"Output: {OUT_PATH}")
    print("Production Ladbrokes props JSON modified: NO")


if __name__ == "__main__":
    main()