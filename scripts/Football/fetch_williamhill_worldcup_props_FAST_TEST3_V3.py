#!/usr/bin/env python3
"""
fetch_williamhill_worldcup_props_FAST_TEST3.py

William Hill World Cup props scraper — FAST TEST3 V2 candidate.

MAX_MATCHES = 3. This candidate never overwrites production output.

Built from the existing William Hill props scraper, but adds Player tab capture
and broad parsers for:
  - Anytime Goalscorer
  - Player Shots On Target
  - Player Shots
  - Player Assists
  - Player Cards
  - Player Tackles
  - Player Fouls Committed
  - Player Fouls Won
  - Match Shots On Target
  - Match Shots
  - Team Shots On Target
  - Team Shots
  - Total Corners
  - Total Cards

Also keeps the existing match markets:
  - Match Betting
  - Both Teams To Score
  - Total Goals Over / Under
  - 1st Half Goals Over / Under
  - Result & BTTS
  - Half Time Result
  - Double Chance

Output:
  football/data/williamhill_worldcup_props_FAST_TEST3_V3.json

Debug:
  football/debug/williamhill_worldcup_props_FAST_TEST3/<match>.txt
  football/debug/williamhill_worldcup_props_FAST_TEST3/<match>_hits.txt
"""

import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH  = ROOT / "football" / "data" / "williamhill_worldcup_props_FAST_TEST3_V3.json"
DEBUG_DIR = ROOT / "football" / "debug" / "williamhill_worldcup_props_FAST_TEST3_V3"
MONEYLINES_PATH = ROOT / "football" / "data" / "williamhill_worldcup_moneylines.json"

# Existing production outputs are read-only URL caches. This TEST3 candidate
# never writes to or replaces them. Reusing exact fixture URLs avoids repeatedly
# crawling the William Hill competition page.
EVENT_URL_CACHE_PATHS = [
    ROOT / "football" / "data" / "williamhill_worldcup_props.json",
    ROOT / "football" / "data" / "williamhill_worldcup_match_stats.json",
    ROOT / "football" / "data" / "williamhill_worldcup_cards_corners.json",
]

COMPETITION_URL = "https://sports.williamhill.com/betting/en-gb/football/competitions/OB_TY52321/world-cup-2026/matches"

MAX_MATCHES = 3
HEADLESS = False

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
THRESHOLD_RE = re.compile(r"^(?:\d+\+|Over\s+\d+(?:\.\d+)?|Under\s+\d+(?:\.\d+)?|\d+(?:\.\d+)?)$", re.I)

WORLD_CUP_TEAMS = {
    "Mexico","South Africa","South Korea","Czech Republic","Czechia",
    "Canada","Bosnia & Herzegovina","Bosnia and Herzegovina","Bosnia",
    "USA","Paraguay","Qatar","Switzerland","Brazil","Morocco","Haiti",
    "Scotland","Australia","Turkey","Turkiye","Türkiye","Germany",
    "Curacao","Curaçao","Netherlands","Japan","Ivory Coast","Ecuador",
    "Sweden","Tunisia","Spain","Cape Verde","Cape Verde Islands","Belgium",
    "Egypt","Saudi Arabia","Uruguay","Iran","New Zealand","France",
    "Senegal","Iraq","Norway","Argentina","Algeria","Austria","Jordan",
    "Portugal","DR Congo","Congo DR","England","Croatia","Ghana",
    "Panama","Colombia","Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
    "Cape Verde Islands": "Cape Verde",
    "Congo DR": "DR Congo",
}

TEAM_SEARCH_ALIASES = {
    "DR Congo": ["DR Congo", "Congo DR", "Democratic Republic Of Congo", "Democratic Republic of Congo"],
    "Bosnia": ["Bosnia", "Bosnia & Herzegovina", "Bosnia and Herzegovina"],
    "Türkiye": ["Türkiye", "Turkey", "Turkiye"],
    "Czechia": ["Czechia", "Czech Republic"],
    "Curacao": ["Curacao", "Curaçao"],
    "Cape Verde": ["Cape Verde", "Cape Verde Islands"],
    "USA": ["USA", "United States", "United States Of America", "United States of America"],
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    return TEAM_ALIASES.get(clean(s), clean(s))


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_threshold(s):
    return bool(THRESHOLD_RE.match(clean(s)))


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def slugify(s):
    return normalize(s).replace("_", "-")


def sel(name, odds, extra=None):
    obj = {
        "selection": clean(name),
        "normalized_selection": normalize(name),
        "odds": clean(odds).upper(),
    }
    if extra:
        obj.update(extra)
    return obj


def mkt(name, selections):
    """Deduplicate by the actual betting selection, not by captured tab.

    William Hill repeats many player markets under Popular, Players and Goals.
    The old key included odds, so the same player/threshold captured twice could
    survive when one tab briefly showed a different price. For player markets,
    player + prop type + threshold/line is the canonical selection identity.
    """
    seen, out = set(), []
    for s in selections:
        player = clean(s.get("player", ""))
        if player:
            key = (
                "player",
                normalize(player),
                clean(s.get("prop_type", "")),
                clean(s.get("threshold") or s.get("line") or ""),
                clean(s.get("side", "")),
            )
        else:
            key = (
                "standard",
                normalize(s.get("selection", "")),
                clean(s.get("side", "")),
                clean(s.get("line", "")),
                clean(s.get("prop_type", "")),
            )

        if key in seen:
            continue
        seen.add(key)
        out.append(s)

    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(out),
        "selections": out,
    }


def lines_from_text(text):
    return [clean(l) for l in text.splitlines() if clean(l)]


def threshold_to_line(th):
    th = clean(th)
    m = re.match(r"^(\d+)\+$", th)
    if m:
        return str(float(int(m.group(1)) - 0.5)).rstrip("0").rstrip(".")
    m = re.match(r"^Over\s+(\d+(?:\.\d+)?)$", th, re.I)
    if m:
        return m.group(1)
    m = re.match(r"^(\d+(?:\.\d+)?)$", th)
    if m:
        return m.group(1)
    return th


def threshold_label(th):
    th = clean(th)
    m = re.match(r"^(\d+)\+$", th)
    if m:
        return f"{m.group(1)}+"
    m = re.match(r"^Over\s+(\d+(?:\.\d+)?)$", th, re.I)
    if m:
        # Over 1.5 ~= 2+
        try:
            return f"{int(float(m.group(1)) + 0.5)}+"
        except Exception:
            return f"Over {m.group(1)}"
    return th


# ── Match market parsers ─────────────────────────────────────────────────────

def parse_match_result(lines, home, away):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Match Result"), -1)
    if idx == -1:
        idx = next((i for i, l in enumerate(lines) if clean(l) in {home, "Draw", away}), -1)
        if idx == -1:
            return mkt("Match Betting", selections)

    block = lines[idx:idx + 30]
    valid = {home, "Draw", away}
    for i, line in enumerate(block):
        label = clean(line)
        if label in valid and i + 1 < len(block) and is_odds(block[i + 1]):
            side = "home" if label == home else ("draw" if label == "Draw" else "away")
            selections.append(sel(label, block[i + 1], {"side": side}))
        if len(selections) >= 3:
            break

    return mkt("Match Betting", selections[:3])


def parse_total_goals(lines, section_header, market_name):
    selections = []
    idx = next((i for i, l in enumerate(lines) if section_header.lower() in clean(l).lower()), -1)
    if idx == -1:
        return mkt(market_name, selections)

    block = lines[idx:idx + 70]
    i = 0
    while i < len(block):
        label = clean(block[i])

        over_match = re.match(r"^Over\s+(\d+(?:\.\d+)?)$", label, re.I)
        under_match = re.match(r"^Under\s+(\d+(?:\.\d+)?)$", label, re.I)

        if over_match and i + 1 < len(block) and is_odds(block[i + 1]):
            line = over_match.group(1)
            selections.append(sel(f"Over {line}", block[i + 1], {"side": "over", "line": line}))
            i += 2
            continue

        if under_match and i + 1 < len(block) and is_odds(block[i + 1]):
            line = under_match.group(1)
            selections.append(sel(f"Under {line}", block[i + 1], {"side": "under", "line": line}))
            i += 2
            continue

        if i > 8 and label in {"Both Teams To Score", "Match Result", "Double Chance", "1st Half Betting"}:
            break

        i += 1

    return mkt(market_name, selections)


def parse_btts(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Both Teams To Score"), -1)
    if idx == -1:
        return mkt("Both Teams To Score", selections)

    block = lines[idx:idx + 16]
    for i, line in enumerate(block):
        label = clean(line)
        if label in {"Yes", "No"} and i + 1 < len(block) and is_odds(block[i + 1]):
            selections.append(sel(f"Both Teams To Score - {label}", block[i + 1], {"side": label.lower()}))

    return mkt("Both Teams To Score", selections)


def parse_btts_result(lines, home, away):
    selections = []
    idx = next((i for i, l in enumerate(lines) if "Match Result and Both Teams To Score" in clean(l)), -1)
    if idx == -1:
        return mkt("Result & Both Teams To Score", selections)

    block = lines[idx:idx + 25]
    valid = {home, "Draw", away}
    for i, line in enumerate(block):
        label = clean(line)
        if label in valid and i + 1 < len(block) and is_odds(block[i + 1]):
            selections.append(sel(f"{label} & Both Teams To Score", block[i + 1]))

    return mkt("Result & Both Teams To Score", selections)


def parse_half_time_result(lines, home, away):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "1st Half Betting"), -1)
    if idx == -1:
        return mkt("Half Time Result", selections)

    block = lines[idx:idx + 20]
    valid = {home, "Draw", away}
    for i, line in enumerate(block):
        label = clean(line)
        if label in valid and i + 1 < len(block) and is_odds(block[i + 1]):
            selections.append(sel(label, block[i + 1]))
        if len(selections) >= 3:
            break

    return mkt("Half Time Result", selections[:3])


def parse_double_chance(lines, home, away):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Double Chance"), -1)
    if idx == -1:
        return mkt("Double Chance", selections)

    block = lines[idx:idx + 25]

    for i, line in enumerate(block):
        label = clean(line)

        if " Or " in label and i + 1 < len(block) and is_odds(block[i + 1]):
            low = label.lower()
            if home.lower() in low and "draw" in low:
                mapped = "Home or Draw"
            elif away.lower() in low and "draw" in low:
                mapped = "Away or Draw"
            elif home.lower() in low and away.lower() in low:
                mapped = "Home or Away"
            else:
                mapped = label
            selections.append(sel(mapped, block[i + 1]))

    return mkt("Double Chance", selections)


# ── Player market parsers ────────────────────────────────────────────────────

PLAYER_MARKET_KEYWORDS = {
    "anytime_goalscorer": [
        "Anytime Goalscorer", "Player To Score", "Player To Score At Any Time",
    ],
    "player_shots_on_target": [
        "Player Shots On Target", "Shots On Target", "Player To Have A Shot On Target",
        "Player To Have 1 Or More Shots On Target", "Player To Have One Or More Shots On Target",
        "Player Total Shots On Target", "Total Player Shots On Target",
    ],
    "player_shots": [
        "Player Shots", "Total Player Shots", "Player Total Shots", "Shots At Goal",
    ],
    "player_assists": [
        "Player Assists", "Player To Assist", "To Assist",
    ],
    "player_cards": [
        "Player Cards", "Player Shown A Card", "Player To Be Carded", "To Be Carded",
        "Player Carded", "Shown A Card",
    ],
    "player_tackles": [
        "Player Tackles", "Player Total Tackles", "Total Player Tackles",
        "Player To Make A Tackle", "Player To Make 1 Or More Tackles",
        "Player To Commit A Tackle", "Tackles",
    ],
    "player_fouls_committed": [
        "Player Fouls Committed", "Player Total Fouls Committed",
        "Total Player Fouls Committed", "Player To Commit A Foul",
        "Player To Commit 1 Or More Fouls", "Fouls Committed",
    ],
    "player_fouls_won": [
        "Player Fouls Won", "Player To Be Fouled", "Player To Win A Foul",
        "Player Fouled", "Fouls Won", "To Be Fouled",
    ],
}

MARKET_META = {
    "anytime_goalscorer": ("Anytime Goalscorer", "anytime_scorer", "To Score", "0.5"),
    "player_shots_on_target": ("Player Shots On Target", "shots_on_target", None, None),
    "player_shots": ("Player Shots", "shots", None, None),
    "player_assists": ("Player Assists", "assists", "1+", "0.5"),
    "player_cards": ("Player Cards", "player_card", "To Be Carded", "0.5"),
    "player_tackles": ("Player Tackles", "tackles", None, None),
    "player_fouls_committed": ("Player Fouls Committed", "fouls_committed", None, None),
    "player_fouls_won": ("Player Fouls Won", "fouls_won", None, None),
}

STOP_HEADINGS = {
    "Popular", "Goals", "Half", "Player", "Player Stats", "Bet Builder", "Corners", "Cards",
    "Match Result", "Both Teams To Score", "Double Chance", "Correct Score",
    "Total Match Over/Under Goals", "1st Half Betting", "1st Half", "Total Corners",
    "Player First Goalscorer", "First Goalscorer", "Last Goalscorer", "Player To Be Sent Off",
    "First Player To Be Carded", "Player To Score Or Assist",
}


def is_probably_heading(s):
    s = clean(s)
    if not s:
        return False

    if s in STOP_HEADINGS:
        return True

    low = s.lower()
    heading_terms = [
        "goalscorer", "player shots", "shots on target", "player assists",
        "player cards", "shown a card", "to assist", "to score", "first player",
        "tackles", "fouls", "fouled", "to be fouled",
        "match shots", "team shots", "total shots", "shots at goal",
        "match cards", "total cards", "cards over", "corners over",
        "match result", "both teams", "double chance", "over/under", "corners",
    ]
    return any(t in low for t in heading_terms) and len(s) < 70


def looks_like_player_name(s):
    s = clean(s)
    if not s or len(s) < 3 or len(s) > 55:
        return False
    if is_odds(s) or is_threshold(s):
        return False
    if s in {"BB", "See more", "Show more", "View more", "Add to Betslip", "Save to Betslip and build a Multiple"}:
        return False
    if s.startswith("Impact Sub") or s.startswith("If your player") or s.startswith("Applies to"):
        return False
    if " v " in s.lower() or " vs " in s.lower():
        return False
    if "Betting Odds" in s:
        return False
    if s in WORLD_CUP_TEAMS:
        return False
    if s.upper() == s and len(s) > 8:
        return False
    if is_probably_heading(s):
        return False

    low = s.lower()
    blocked_terms = {
        "yes", "no", "draw", "home", "away", "market suspended",
        "starting price", "cash out", "bet builder", "popular", "goals",
        "players", "player stats", "all markets", "more markets",
    }
    if low in blocked_terms:
        return False
    if any(term in low for term in [
        "click to", "add to", "terms apply", "enhanced odds", "price boost",
        "over/under", "both teams", "match result", "double chance",
    ]):
        return False
    if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", s):
        return False
    return True


def heading_matches_any(line, keywords):
    """Match market headings precisely enough to prevent overlapping markets.

    In particular, ``Player Shots`` must not match ``Player Shots On Target``.
    William Hill sometimes appends bracketed rules such as ``(Incl. Extra Time)``,
    so those suffixes are allowed while arbitrary substring matches are not.
    """
    line_n = normalize(line)
    for keyword in keywords:
        key_n = normalize(keyword)
        if not key_n:
            continue
        if line_n == key_n:
            return True
        if line_n.startswith(key_n + "_incl_"):
            return True
        if line_n.startswith(key_n + "_including_"):
            return True
        if line_n.startswith(key_n + "_90_minutes"):
            return True
    return False


def find_blocks(lines, keywords, max_len=360):
    idxs = [i for i, line in enumerate(lines) if heading_matches_any(line, keywords)]
    blocks = []
    signatures = set()

    for idx in idxs:
        block = []
        for j in range(idx + 1, min(idx + max_len, len(lines))):
            tok = clean(lines[j])
            if not tok:
                continue

            # A new market heading ends this block, including another occurrence
            # of the same market on a duplicated tab section.
            if j > idx + 2 and is_probably_heading(tok):
                break

            if tok in {"Responsible Gambling", "Safer Gambling", "Help", "Contact Us"}:
                break

            block.append(tok)

        if sum(1 for x in block if is_odds(x)) <= 0:
            continue

        signature = tuple(block[:80])
        if signature in signatures:
            continue
        signatures.add(signature)
        blocks.append(block)

    blocks.sort(key=lambda b: sum(1 for x in b if is_odds(x)), reverse=True)
    return blocks[:3]


def parse_simple_player_odds(block, market_name, prop_type, default_threshold, default_line):
    selections = []
    i = 0

    while i < len(block):
        player = clean(block[i])

        if looks_like_player_name(player):
            odds = None
            for j in range(i + 1, min(i + 5, len(block))):
                if is_odds(block[j]):
                    odds = block[j]
                    break
                if j > i + 1 and looks_like_player_name(block[j]):
                    break

            if odds:
                label = default_threshold or "1+"
                selections.append(sel(
                    f"{player} {label}",
                    odds,
                    {
                        "player": player,
                        "prop_type": prop_type,
                        "threshold": label,
                        "line": default_line or threshold_to_line(label),
                    }
                ))
                i += 2
                continue

        i += 1

    return selections


def parse_ladder_player_odds(block, market_name, prop_type):
    selections = []
    current_headers = []

    i = 0
    while i < len(block):
        tok = clean(block[i])

        # Header row can be 1+, 2+, 3+, 4+
        if is_threshold(tok):
            headers = []
            j = i
            while j < len(block) and is_threshold(block[j]) and len(headers) < 8:
                headers.append(clean(block[j]))
                j += 1

            if headers:
                current_headers = headers
                i = j
                continue

        if looks_like_player_name(tok):
            player = tok

            # Case A: player followed by thresholds then odds.
            thresholds = []
            odds = []
            j = i + 1
            while j < min(i + 20, len(block)):
                x = clean(block[j])
                if looks_like_player_name(x):
                    break
                if is_threshold(x):
                    thresholds.append(x)
                elif is_odds(x):
                    odds.append(x)
                j += 1

            if thresholds and odds:
                n = min(len(thresholds), len(odds))
                for th, odd in zip(thresholds[:n], odds[:n]):
                    lab = threshold_label(th)
                    selections.append(sel(
                        f"{player} {lab}",
                        odd,
                        {
                            "player": player,
                            "prop_type": prop_type,
                            "threshold": lab,
                            "line": threshold_to_line(lab),
                        }
                    ))
                i = j
                continue

            # Case B: thresholds appeared before player, player followed by odds only.
            if current_headers and odds:
                n = min(len(current_headers), len(odds))
                for th, odd in zip(current_headers[:n], odds[:n]):
                    lab = threshold_label(th)
                    selections.append(sel(
                        f"{player} {lab}",
                        odd,
                        {
                            "player": player,
                            "prop_type": prop_type,
                            "threshold": lab,
                            "line": threshold_to_line(lab),
                        }
                    ))
                i = j
                continue

        i += 1

    return selections


def parse_player_market(lines, key):
    market_name, prop_type, default_threshold, default_line = MARKET_META[key]
    blocks = find_blocks(lines, PLAYER_MARKET_KEYWORDS[key])

    all_sels = []
    for block in blocks:
        if key in {"player_shots", "player_shots_on_target", "player_tackles", "player_fouls_committed", "player_fouls_won"}:
            all_sels.extend(parse_ladder_player_odds(block, market_name, prop_type))
            # Some sites still show one-heading-per-threshold; catch simple pairs too.
            all_sels.extend(parse_simple_player_odds(block, market_name, prop_type, "1+", "0.5"))
        else:
            all_sels.extend(parse_simple_player_odds(block, market_name, prop_type, default_threshold, default_line))

    return mkt(market_name, all_sels)


SCORER_GRID_HEADERS = {
    "first", "anytime", "2 or more", "hat-trick", "hat trick", "last",
    "first and last", "first or last",
}


def parse_anytime_goalscorer_grid(text):
    """Parse only the Anytime column from William Hill's scorer grid.

    William Hill renders several prices on each player row:
      First | Anytime | 2 or More | Hat-trick | Last | First AND Last | First OR Last

    The old generic parser treated every price in that row as a separate
    Anytime selection. This parser locates the grid header and keeps only the
    price under the Anytime column.
    """
    lines = lines_from_text(text)
    selections = []

    for idx, token in enumerate(lines):
        if clean(token).lower() != "name":
            continue

        # Read the scorer-grid column headers immediately after Name.
        headers = []
        cursor = idx + 1
        while cursor < min(idx + 18, len(lines)):
            low = clean(lines[cursor]).lower()
            if low in SCORER_GRID_HEADERS:
                headers.append(low.replace("hat trick", "hat-trick"))
                cursor += 1
                continue
            # Ignore harmless UI labels before the first recognised header.
            if not headers and low in {"impact sub", "enhanced win"}:
                cursor += 1
                continue
            break

        if "anytime" not in headers or len(headers) < 2:
            continue

        anytime_col = headers.index("anytime")
        column_count = len(headers)
        i = cursor

        while i < len(lines):
            tok = clean(lines[i])
            low = tok.lower()

            # Stop at the next major section or another scorer table header.
            if low == "name" or low in {
                "player shots", "player shots on target", "player assists",
                "player cards", "player tackles", "player fouls committed",
                "player fouls won", "both teams to score", "double chance",
                "match result", "responsible gambling", "safer gambling",
            }:
                break

            if not looks_like_player_name(tok):
                i += 1
                continue

            # A valid row is a player followed by the grid's run of odds.
            odds = []
            j = i + 1
            while j < min(i + column_count + 5, len(lines)):
                nxt = clean(lines[j])
                if is_odds(nxt):
                    odds.append(nxt)
                    j += 1
                    continue
                if odds or looks_like_player_name(nxt) or nxt.lower() == "name":
                    break
                j += 1

            if len(odds) > anytime_col:
                odd = odds[anytime_col]
                selections.append(sel(
                    f"{tok} To Score",
                    odd,
                    {
                        "player": tok,
                        "prop_type": "anytime_scorer",
                        "threshold": "To Score",
                        "line": "0.5",
                    },
                ))
                i = max(j, i + 1)
                continue

            i += 1

    return mkt("Anytime Goalscorer", selections)


def parse_player_props(lines):
    out = []
    # Anytime Goalscorer is intentionally excluded here. It is parsed from the
    # scorer grid by parse_anytime_goalscorer_grid(), which selects only the
    # dedicated Anytime column.
    for key in [
        "player_shots_on_target",
        "player_shots",
        "player_assists",
        "player_cards",
        "player_tackles",
        "player_fouls_committed",
        "player_fouls_won",
    ]:
        try:
            m = parse_player_market(lines, key)
            if m["selection_count"] > 0:
                out.append(m)
        except Exception as e:
            print(f"    player parser error ({key}): {e}")

    return out



# ── Match / team stats market parsers ─────────────────────────────────────────

def line_matches_heading(line, heading):
    ln = normalize(line)
    hn = normalize(heading)
    if not ln or not hn:
        return False
    return ln == hn or ln.startswith(hn)


def find_stat_blocks(lines, headings, max_len=130):
    """Find blocks after non-player stat headings.

    Designed for William Hill text where headings are followed by rows like:
      Over 8.5
      5/6
      Under 8.5
      5/6
    or threshold ladders like:
      10+
      4/6
    """
    blocks = []

    for idx, line in enumerate(lines):
        line_c = clean(line)
        low = line_c.lower()

        # Prevent match/team parser stealing player markets.
        if "player" in low:
            continue

        matched = any(line_matches_heading(line_c, h) for h in headings)
        if not matched:
            continue

        block = []
        for j in range(idx + 1, min(idx + max_len, len(lines))):
            tok = clean(lines[j])
            if not tok:
                continue

            tok_low = tok.lower()

            # Stop when another obvious heading starts.
            if j > idx + 2 and is_probably_heading(tok):
                # But don't stop on a line that is another threshold/odds row.
                if not is_odds(tok) and not is_threshold(tok):
                    break

            if tok in {"Responsible Gambling", "Safer Gambling", "Help", "Contact Us"}:
                break

            # Avoid pulling player names into match/team stat markets.
            if "player" in tok_low and not is_odds(tok):
                break

            block.append(tok)

        if sum(1 for x in block if is_odds(x)) > 0:
            blocks.append(block)

    # Prefer blocks with most odds.
    blocks.sort(key=lambda b: sum(1 for x in b if is_odds(x)), reverse=True)
    return blocks[:2]


def parse_ou_and_threshold_block(block, market_name, prop_type):
    selections = []
    i = 0

    while i < len(block):
        label = clean(block[i])

        # Standard William Hill format: Over X then odds, Under X then odds.
        over_match = re.match(r"^Over\s+(\d+(?:\.\d+)?)$", label, re.I)
        under_match = re.match(r"^Under\s+(\d+(?:\.\d+)?)$", label, re.I)

        if over_match and i + 1 < len(block) and is_odds(block[i + 1]):
            line = over_match.group(1)
            selections.append(sel(f"Over {line}", block[i + 1], {
                "side": "over",
                "line": line,
                "prop_type": prop_type,
            }))
            i += 2
            continue

        if under_match and i + 1 < len(block) and is_odds(block[i + 1]):
            line = under_match.group(1)
            selections.append(sel(f"Under {line}", block[i + 1], {
                "side": "under",
                "line": line,
                "prop_type": prop_type,
            }))
            i += 2
            continue

        # Threshold ladder fallback: 10+ then odds.
        if re.match(r"^\d+\+$", label) and i + 1 < len(block) and is_odds(block[i + 1]):
            selections.append(sel(label, block[i + 1], {
                "threshold": label,
                "line": threshold_to_line(label),
                "prop_type": prop_type,
            }))
            i += 2
            continue

        # Numeric line followed by two odds fallback:
        # 8.5, 5/6, 5/6 => Over 8.5 / Under 8.5
        if re.match(r"^\d+(?:\.\d+)?$", label) and i + 2 < len(block):
            if is_odds(block[i + 1]) and is_odds(block[i + 2]):
                selections.append(sel(f"Over {label}", block[i + 1], {
                    "side": "over",
                    "line": label,
                    "prop_type": prop_type,
                }))
                selections.append(sel(f"Under {label}", block[i + 2], {
                    "side": "under",
                    "line": label,
                    "prop_type": prop_type,
                }))
                i += 3
                continue

        i += 1

    return selections


def parse_stat_market(lines, market_name, headings, prop_type):
    all_sels = []
    for block in find_stat_blocks(lines, headings):
        all_sels.extend(parse_ou_and_threshold_block(block, market_name, prop_type))

    return mkt(market_name, all_sels)


def parse_match_and_team_stats(lines, home, away):
    """Parse match/team shots, SOT, corners, and cards."""
    markets = []

    static_specs = [
        (
            "Match Shots On Target",
            [
                "Match Shots On Target",
                "Total Match Shots On Target",
                "Total Shots On Target",
                "Shots On Target Over/Under",
                "Match Shots On Target Over/Under",
                "Total Shots On Target Over/Under",
            ],
            "match_shots_on_target",
        ),
        (
            "Match Shots",
            [
                "Match Shots",
                "Total Match Shots",
                "Total Shots",
                "Shots Over/Under",
                "Match Shots Over/Under",
                "Total Shots Over/Under",
            ],
            "match_shots",
        ),
        (
            "Total Corners",
            [
                "Total Corners",
                "Match Corners",
                "Total Match Corners",
                "Corners Over/Under",
                "Total Corners Over/Under",
                "Match Corners Over/Under",
            ],
            "corners",
        ),
        (
            "Total Cards",
            [
                "Total Cards",
                "Match Cards",
                "Total Match Cards",
                "Cards Over/Under",
                "Total Cards Over/Under",
                "Match Cards Over/Under",
                "Total Booking Points",
                "Booking Points",
            ],
            "cards",
        ),
    ]

    for market_name, headings, prop_type in static_specs:
        try:
            m = parse_stat_market(lines, market_name, headings, prop_type)
            if m["selection_count"] > 0:
                markets.append(m)
        except Exception as e:
            print(f"    stat parser error ({market_name}): {e}")

    for team, side in [(home, "home"), (away, "away")]:
        team_specs = [
            (
                f"{team} Shots On Target",
                [
                    f"{team} Shots On Target",
                    f"{team} Total Shots On Target",
                    f"Total {team} Shots On Target",
                    f"{team} Team Shots On Target",
                    f"{team} Shots On Target Over/Under",
                ],
                "team_shots_on_target",
            ),
            (
                f"{team} Shots",
                [
                    f"{team} Shots",
                    f"{team} Total Shots",
                    f"Total {team} Shots",
                    f"{team} Team Shots",
                    f"{team} Shots Over/Under",
                ],
                "team_shots",
            ),
        ]

        for market_name, headings, prop_type in team_specs:
            try:
                m = parse_stat_market(lines, market_name, headings, prop_type)
                if m["selection_count"] > 0:
                    for s in m["selections"]:
                        s["team"] = team
                        s["side"] = side
                    markets.append(m)
            except Exception as e:
                print(f"    stat parser error ({market_name}): {e}")

    return markets


def parse_all(text, home, away):
    lines = lines_from_text(text)
    markets = []

    for parser, args in [
        (parse_match_result, (lines, home, away)),
        (parse_btts, (lines,)),
        (parse_total_goals, (lines, "Total Match Over/Under Goals", "Total Goals Over / Under")),
        (parse_total_goals, (lines, "1st Half", "1st Half Goals Over / Under")),
        (parse_btts_result, (lines, home, away)),
        (parse_half_time_result, (lines, home, away)),
        (parse_double_chance, (lines, home, away)),
    ]:
        try:
            m = parser(*args)
            if m["selection_count"] > 0:
                markets.append(m)
        except Exception as e:
            print(f"    parser error ({parser.__name__}): {e}")

    markets.extend(parse_match_and_team_stats(lines, home, away))

    scorer_market = parse_anytime_goalscorer_grid(text)
    if scorer_market["selection_count"] > 0:
        markets.append(scorer_market)

    markets.extend(parse_player_props(lines))

    seen, unique = set(), []
    for m in markets:
        k = m["normalized_market"]
        if k not in seen:
            seen.add(k)
            unique.append(m)

    return unique


# ── Browser helpers ──────────────────────────────────────────────────────────

def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "Got it", "OK"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(900)
                return
        except Exception:
            pass


def click_tab(page, tab_name):
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    page.wait_for_timeout(350)

    for role in ["link", "button", "tab"]:
        try:
            loc = page.get_by_role(role, name=re.compile(f"^{re.escape(tab_name)}$", re.I))
            if loc.count():
                loc.first.click(timeout=4000)
                page.wait_for_timeout(2200)
                return True
        except Exception:
            pass

    try:
        loc = page.get_by_text(tab_name, exact=True)
        for i in range(min(loc.count(), 10)):
            try:
                item = loc.nth(i)
                item.scroll_into_view_if_needed(timeout=1500)
                box = item.bounding_box()
                if not box or box["width"] <= 4 or box["height"] <= 4 or box["width"] > 260:
                    continue
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.wait_for_timeout(2200)
                return True
            except Exception:
                pass
    except Exception:
        pass

    return False


def scroll_page(page, steps=10):
    for _ in range(steps):
        try:
            page.mouse.wheel(0, 650)
        except Exception:
            pass
        page.wait_for_timeout(250)


def click_all_see_more(page, max_clicks=30):
    for _ in range(max_clicks):
        clicked = False
        for label in ["Show More", "Show more", "See more", "View more"]:
            try:
                loc = page.get_by_text(label, exact=True)
                if loc.count() > 0:
                    item = loc.first
                    item.scroll_into_view_if_needed(timeout=1200)
                    item.click(timeout=1200)
                    page.wait_for_timeout(350)
                    clicked = True
                    break
            except Exception:
                pass
        if not clicked:
            break


def click_heading(page, text):
    patterns = [
        re.compile(f"^{re.escape(text)}$", re.I),
        re.compile(re.escape(text), re.I),
    ]

    for pat in patterns:
        try:
            loc = page.get_by_text(pat)
            count = min(loc.count(), 12)
            for i in range(count):
                try:
                    item = loc.nth(i)
                    item.scroll_into_view_if_needed(timeout=1600)
                    page.wait_for_timeout(150)
                    box = item.bounding_box()
                    if not box or box["height"] <= 4:
                        continue

                    # Click in the same row but more to the right to hit accordion area.
                    x = min(max(box["x"] + 350, box["x"] + box["width"] / 2), 1250)
                    y = box["y"] + box["height"] / 2
                    page.mouse.click(x, y)
                    page.wait_for_timeout(650)
                    return True
                except Exception:
                    pass
        except Exception:
            pass

    return False


def expand_player_markets(page, home="", away=""):
    targets = [
        "Player To Score",
        "Anytime Goalscorer",
        "Player Shots On Target",
        "Shots On Target",
        "Player To Have A Shot On Target",
        "Player To Have 1 Or More Shots On Target",
        "Player Shots",
        "Player Assists",
        "Player To Assist",
        "Player Cards",
        "Player Shown A Card",
        "Player To Be Carded",
        "Player Tackles",
        "Player Total Tackles",
        "Total Player Tackles",
        "Player To Make A Tackle",
        "Player Fouls",
        "Player Fouls Committed",
        "Player Total Fouls",
        "Player To Commit A Foul",
        "Player Fouls Won",
        "Player To Be Fouled",
        "Player To Win A Foul",

        # Match/team stat markets.
        "Match Shots On Target",
        "Total Match Shots On Target",
        "Total Shots On Target",
        "Match Shots",
        "Total Match Shots",
        "Total Shots",
        "Total Corners",
        "Match Corners",
        "Total Match Corners",
        "Total Cards",
        "Match Cards",
        "Total Match Cards",
        "Cards Over/Under",
        "Corners Over/Under",
    ]

    for team in [home, away]:
        team = clean(team)
        if not team:
            continue
        targets.extend([
            f"{team} Shots On Target",
            f"{team} Total Shots On Target",
            f"Total {team} Shots On Target",
            f"{team} Shots",
            f"{team} Total Shots",
            f"Total {team} Shots",
        ])

    # Dedupe but preserve order.
    deduped = []
    seen = set()
    for t in targets:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(t)

    scroll_page(page, 4)

    for target in deduped:
        ok = click_heading(page, target)
        print(f"      {'clicked' if ok else 'missed '} {target}")
        click_all_see_more(page, max_clicks=4)

    click_all_see_more(page, max_clicks=40)


def is_valid_kickoff_time(t):
    t = clean(t)
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if not m:
        return False
    hh = int(m.group(1))
    mm = int(m.group(2))
    return 0 <= hh <= 23 and 0 <= mm <= 59


def load_moneyline_targets():
    """Use fresh William Hill moneylines JSON as target fixture order.

    Skip live-clock rows like 61:02 because they are in-play clock values,
    not future kickoff times.
    """
    if not MONEYLINES_PATH.exists():
        return []

    try:
        data = json.loads(MONEYLINES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    targets = []
    seen = set()

    for m in data.get("matches", []):
        time_label = clean(m.get("time", ""))
        if not is_valid_kickoff_time(time_label):
            continue

        home = clean(m.get("home_team") or "")
        away = clean(m.get("away_team") or "")
        match = clean(m.get("match") or "")

        if not home or not away:
            if " v " in match:
                home, away = [clean(x) for x in match.split(" v ", 1)]

        if not home or not away:
            continue

        home = canonical_team(home)
        away = canonical_team(away)
        key = normalize(f"{home} v {away}")

        if key in seen:
            continue

        seen.add(key)
        targets.append({
            "home": home,
            "away": away,
            "name": f"{home} v {away}",
            "date_label": clean(m.get("date_label", "")),
            "time": time_label,
        })

    return targets


def team_search_terms(team):
    team = canonical_team(team)
    terms = [team]
    terms.extend(TEAM_SEARCH_ALIASES.get(team, []))

    for canonical, variants in TEAM_SEARCH_ALIASES.items():
        if team == canonical or team in variants:
            terms.append(canonical)
            terms.extend(variants)

    out = []
    seen = set()
    for t in terms:
        t = clean(t)
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def page_has_fixture(page, home, away):
    try:
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body = ""
    lo = clean(body).lower()
    return (
        any(t.lower() in lo for t in team_search_terms(home)) and
        any(t.lower() in lo for t in team_search_terms(away))
    )


def get_visible_fixture_click_candidates(page, home, away):
    """Return clickable boxes for visible rows/cards containing the exact teams.

    V8: supports William Hill display aliases, e.g. target "DR Congo" can appear
    on the page as "Congo DR", and target "Bosnia" can appear as
    "Bosnia & Herzegovina".
    """
    home_terms = team_search_terms(home)
    away_terms = team_search_terms(away)

    js = r"""
        ({homeTerms, awayTerms}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const H = homeTerms.map(norm).filter(Boolean);
            const A = awayTerms.map(norm).filter(Boolean);

            const hasAny = (txt, arr) => arr.some(v => txt.includes(v));
            const eqAny = (txt, arr) => arr.some(v => txt === v);

            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 4 && r.height > 4 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.visibility !== 'hidden' && st.display !== 'none';
            };

            const textOf = el => norm(el.innerText || el.textContent || '');

            const nodes = Array.from(document.querySelectorAll('a, button, [role=button], span, div, li, article, section'))
                .filter(visible);

            const candidates = [];

            for (const el of nodes) {
                const t = textOf(el);

                if (!eqAny(t, H)) continue;

                let row = el;
                for (let depth = 0; depth < 9 && row && row !== document.body; depth++, row = row.parentElement) {
                    if (!visible(row)) continue;

                    const rt = textOf(row);
                    if (!hasAny(rt, H) || !hasAny(rt, A)) continue;

                    const r = row.getBoundingClientRect();

                    if (r.height > 280 || r.width > 1450 || rt.length > 950) continue;

                    const er = el.getBoundingClientRect();

                    candidates.push({
                        x: Math.max(8, Math.min(er.left + er.width / 2, window.innerWidth - 8)),
                        y: Math.max(8, Math.min(er.top + er.height / 2, window.innerHeight - 8)),
                        row_x: Math.max(8, Math.min(r.left + Math.min(r.width * 0.30, 320), window.innerWidth - 8)),
                        row_y: Math.max(8, Math.min(r.top + r.height / 2, window.innerHeight - 8)),
                        score: (r.width * r.height) + (rt.length * 20),
                        text: rt.slice(0, 180)
                    });
                    break;
                }
            }

            candidates.sort((a, b) => a.score - b.score);
            return candidates.slice(0, 8);
        }
    """
    try:
        return page.evaluate(js, {"homeTerms": home_terms, "awayTerms": away_terms}) or []
    except Exception:
        return []


def try_click_candidate(page, cand, home, away, list_url, y):
    """Click one candidate, verify the event page, then return URL or empty."""
    click_points = [
        (cand.get("x"), cand.get("y")),
        (cand.get("row_x"), cand.get("row_y")),
    ]

    for x, y_click in click_points:
        if x is None or y_click is None:
            continue

        try:
            page.mouse.click(float(x), float(y_click))
            page.wait_for_timeout(1600)

            # Sometimes first click only focuses/expands; click again if no navigation.
            if "OB_EV" not in page.url:
                page.mouse.click(float(x), float(y_click))
                page.wait_for_url("**/OB_EV**", timeout=6500)

            page.wait_for_timeout(2200)

            if "OB_EV" in page.url and page_has_fixture(page, home, away):
                return page.url.split("?", 1)[0]

            if "OB_EV" in page.url:
                print(f"    rejected wrong page for {home} v {away}: {page.url}")

        except Exception:
            pass

        # Return to same list scroll position for next candidate.
        try:
            page.goto(list_url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(1200)
            accept_cookies(page)
            page.evaluate("(y) => { window.scrollTo(0, y); document.scrollingElement.scrollTop = y; }", y)
            page.wait_for_timeout(350)
        except Exception:
            pass

    return ""


def discover_event_url_for_target(page, target):
    """Scroll list and click the exact visible row for this target fixture."""
    home, away = target["home"], target["away"]
    list_url = COMPETITION_URL

    page.goto(list_url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5500)
    accept_cookies(page)

    try:
        page.evaluate("window.scrollTo(0, 0); document.scrollingElement.scrollTop = 0")
        page.wait_for_timeout(700)
    except Exception:
        pass

    for pass_no in range(1, 4):
        try:
            scroll_height = int(page.evaluate("document.scrollingElement.scrollHeight"))
            client_height = int(page.evaluate("document.scrollingElement.clientHeight"))
            max_y = max(scroll_height - client_height, 0)
        except Exception:
            max_y = 10000

        positions = list(range(0, max_y + 1, 140))
        if max_y not in positions:
            positions.append(max_y)

        for y in positions:
            try:
                page.evaluate("(y) => { window.scrollTo(0, y); document.scrollingElement.scrollTop = y; }", y)
            except Exception:
                page.mouse.wheel(0, 650)
            page.wait_for_timeout(320)

            cands = get_visible_fixture_click_candidates(page, home, away)
            if not cands:
                continue

            print(f"    visible candidates for {home} v {away} at y={y}: {len(cands)}")
            for cand in cands:
                url = try_click_candidate(page, cand, home, away, list_url, y)
                if url:
                    print(f"  ✓ found {home} v {away}: {url}")
                    return url

    print(f"  - could not discover event URL for {home} v {away}")
    return ""



def load_cached_event_urls():
    """Return exact-match fixture URLs from existing William Hill outputs.

    Cache files are read only. Only direct William Hill event URLs containing
    /OB_EV are accepted, and fixture names must match after normalization.
    """
    cached = {}

    for path in EVENT_URL_CACHE_PATHS:
        if not path.exists():
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  cache skipped ({path.name}): {exc}")
            continue

        rows = data.get("matches", data if isinstance(data, list) else [])
        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue

            name = clean(row.get("match") or row.get("name") or row.get("event_name") or "")
            home = clean(row.get("home_team") or row.get("home") or "")
            away = clean(row.get("away_team") or row.get("away") or "")

            if (not home or not away) and " v " in name:
                home, away = [clean(x) for x in name.split(" v ", 1)]

            if not home or not away:
                continue

            home = canonical_team(home)
            away = canonical_team(away)
            url = clean(
                row.get("url")
                or row.get("event_url")
                or row.get("match_url")
                or row.get("href")
                or ""
            )

            if "/OB_EV" not in url:
                continue

            cached.setdefault(normalize(f"{home} v {away}"), url.split("?", 1)[0])

    return cached


def get_match_links(page):
    print(f"Opening target list: {COMPETITION_URL}")

    targets = load_moneyline_targets()
    print(f"  valid moneyline targets loaded: {len(targets)}")

    if not targets:
        print("  No valid moneyline targets found. Run fetch_williamhill_worldcup_moneylines.py first.")
        return []

    cached_urls = load_cached_event_urls()
    print(f"  exact cached event URLs available: {len(cached_urls)}")

    fixtures = []
    seen_urls = set()

    for target in targets:
        if len(fixtures) >= MAX_MATCHES:
            break

        key = normalize(target["name"])
        url = cached_urls.get(key, "")

        if url:
            print(f"  ✓ cached {target['name']}: {url}")
        else:
            print(f"  - no cached URL for {target['name']}; using exact row discovery")
            url = discover_event_url_for_target(page, target)

        if not url or url in seen_urls:
            continue

        seen_urls.add(url)
        fixtures.append({
            "url": url,
            "name": target["name"],
            "home": target["home"],
            "away": target["away"],
            "url_source": "cache" if key in cached_urls else "row_discovery",
        })

    print(f"Found {len(fixtures)} TEST3 fixtures")
    return fixtures[:MAX_MATCHES]

def detect_teams(text, fallback_name=""):
    lines = lines_from_text(text)

    for line in lines[:80]:
        m = re.match(r"^(.+?)\s+v\s+(.+?)$", line, re.I)
        if m:
            h = canonical_team(m.group(1).strip())
            a = canonical_team(m.group(2).strip())
            if h in WORLD_CUP_TEAMS or a in WORLD_CUP_TEAMS:
                return h, a

    for i, line in enumerate(lines):
        if line in WORLD_CUP_TEAMS and i + 1 < len(lines) and lines[i + 1] in WORLD_CUP_TEAMS:
            return canonical_team(line), canonical_team(lines[i + 1])

    if " v " in fallback_name:
        h, a = fallback_name.split(" v ", 1)
        return canonical_team(h), canonical_team(a)

    return "", ""


def save_hits(debug_file, text):
    hit_file = debug_file.with_name(debug_file.stem + "_hits.txt")
    words = [
        "Player", "Shots", "Shot", "Target", "Assist", "Card",
        "Tackle", "Tackles", "Foul", "Fouls", "Fouled",
        "Corner", "Corners", "Card", "Cards", "Booking",
        "Match Shots", "Total Shots", "Team Shots",
        "Goalscorer", "To Score", "Both Teams", "Double Chance",
    ]
    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if any(w.lower() in line.lower() for w in words):
            hits.append(f"{i + 1}: {line}")
            for j in range(i + 1, min(i + 14, len(lines))):
                if clean(lines[j]):
                    hits.append(f"    {j + 1}: {lines[j]}")
            hits.append("")
    hit_file.write_text("\n".join(hits), encoding="utf-8")



FAST_PLAYER_HEADINGS = [
    "Player To Score",
    "Anytime Goalscorer",
    "Player Shots On Target",
    "Shots On Target",
    "Player To Have A Shot On Target",
    "Player To Have 1 Or More Shots On Target",
    "Player Shots",
    "Total Player Shots",
    "Player Assists",
    "Player To Assist",
    "Player Cards",
    "Player Shown A Card",
    "Player To Be Carded",
    "Player Tackles",
    "Player Total Tackles",
    "Total Player Tackles",
    "Player Fouls",
    "Player Fouls Committed",
    "Player Total Fouls",
    "Player Fouls Won",
    "Player To Be Fouled",
    "Player To Win A Foul",
]


def expand_relevant_player_markets_fast(page):
    """Expand only player-market headings that are actually present.

    The old scraper attempted dozens of headings on every tab, including
    cards/corners/match-stat markets handled by separate William Hill scripts.
    This version first reads the page and clicks only relevant headings found.
    """
    scroll_page(page, 5)

    try:
        body_text = page.locator("body").inner_text(timeout=12000)
    except Exception:
        body_text = ""

    low = body_text.lower()
    present = []
    seen = set()
    for heading in FAST_PLAYER_HEADINGS:
        key = heading.lower()
        if key in low and key not in seen:
            seen.add(key)
            present.append(heading)

    clicked = 0
    for heading in present:
        if click_heading(page, heading):
            clicked += 1
        click_all_see_more(page, max_clicks=2)

    click_all_see_more(page, max_clicks=12)
    return clicked, present


def try_tab_aliases(page, aliases):
    """Click the first available alias in a logical tab group."""
    for alias in aliases:
        if click_tab(page, alias):
            return alias
    return ""


PLAYER_COUNT_LIMITS = {
    "Anytime Goalscorer": 60,
    "Player Assists": 70,
    "Player Cards": 80,
    "Player Shots On Target": 260,
    "Player Shots": 300,
    "Player Tackles": 300,
    "Player Fouls Committed": 300,
    "Player Fouls Won": 300,
}


def player_market_warnings(markets):
    warnings = []
    for market in markets:
        name = market.get("market", "")
        count = int(market.get("selection_count", 0) or 0)
        limit = PLAYER_COUNT_LIMITS.get(name)
        if limit is not None and count > limit:
            warnings.append(f"{name}: suspiciously high selection count {count} > {limit}")

        semantic = set()
        dupes = 0
        for selection in market.get("selections", []):
            player = normalize(selection.get("player", ""))
            if not player:
                continue
            key = (
                player,
                selection.get("prop_type", ""),
                selection.get("threshold") or selection.get("line") or "",
            )
            if key in semantic:
                dupes += 1
            semantic.add(key)
        if dupes:
            warnings.append(f"{name}: {dupes} semantic duplicate selections remained")
    return warnings


def scrape_match(page, fixture):
    url = fixture["url"]
    name = fixture["name"]

    print(f"  Scraping: {name}")
    print(f"  URL: {url}")
    print(f"  URL source: {fixture.get('url_source', 'unknown')}")

    hint_home = canonical_team(clean(fixture.get("home") or ""))
    hint_away = canonical_team(clean(fixture.get("away") or ""))
    if (not hint_home or not hint_away) and " v " in name:
        hint_home, hint_away = [canonical_team(clean(x)) for x in name.split(" v ", 1)]

    page.goto(url, wait_until="domcontentloaded", timeout=70000)
    page.wait_for_timeout(4200)
    accept_cookies(page)

    # A cached URL is accepted only when the loaded event still contains both
    # expected teams. This prevents stale URLs from silently scraping a wrong game.
    if hint_home and hint_away and not page_has_fixture(page, hint_home, hint_away):
        print(f"    ! cached/resolved URL was stale for {name}; trying exact row discovery")
        fresh_url = discover_event_url_for_target(page, {
            "home": hint_home,
            "away": hint_away,
            "name": name,
            "date_label": "",
            "time": "",
        })
        if not fresh_url:
            raise RuntimeError(f"Could not refresh stale event URL for: {name}")
        url = fresh_url
        fixture["url"] = fresh_url
        fixture["url_source"] = "row_discovery_after_stale_cache"
        page.goto(fresh_url, wait_until="domcontentloaded", timeout=70000)
        page.wait_for_timeout(4200)
        accept_cookies(page)
        if not page_has_fixture(page, hint_home, hint_away):
            raise RuntimeError(f"Refreshed URL did not load expected fixture: {name}")

    match_started = time.perf_counter()
    chunks = []
    captured_tabs = []

    # Default/Popular contains core match markets and often some player markets.
    try:
        clicked, present = expand_relevant_player_markets_fast(page)
        scroll_page(page, 5)
        chunks.append("=== TAB Popular/Default ===\n" + page.locator("body").inner_text(timeout=18000))
        captured_tabs.append("Popular/Default")
        print(f"    ✓ Popular/Default ({clicked} relevant headings clicked; {len(present)} found)")
    except Exception as exc:
        print(f"    default capture error: {exc}")

    # Main player coverage: only one alias from this group should be necessary.
    player_tab = try_tab_aliases(page, ["Player", "Players", "Player Stats"])
    if player_tab:
        clicked, present = expand_relevant_player_markets_fast(page)
        scroll_page(page, 7)
        chunks.append(f"=== TAB {player_tab} ===\n" + page.locator("body").inner_text(timeout=20000))
        captured_tabs.append(player_tab)
        print(f"    ✓ {player_tab} ({clicked} relevant headings clicked; {len(present)} found)")
    else:
        print("    - no Player/Players/Player Stats tab")

    # Goals is retained because it is commonly the richest goalscorer source.
    if click_tab(page, "Goals"):
        clicked, present = expand_relevant_player_markets_fast(page)
        scroll_page(page, 6)
        chunks.append("=== TAB Goals ===\n" + page.locator("body").inner_text(timeout=20000))
        captured_tabs.append("Goals")
        print(f"    ✓ Goals ({clicked} relevant headings clicked; {len(present)} found)")
    else:
        print("    - Goals tab not found")

    # All/All Markets is a fallback only when no dedicated player tab exists.
    if not player_tab:
        all_tab = try_tab_aliases(page, ["All", "All Markets"])
        if all_tab:
            clicked, present = expand_relevant_player_markets_fast(page)
            scroll_page(page, 7)
            chunks.append(f"=== TAB {all_tab} ===\n" + page.locator("body").inner_text(timeout=20000))
            captured_tabs.append(all_tab)
            print(f"    ✓ {all_tab} fallback ({clicked} relevant headings clicked; {len(present)} found)")

    all_text = "\n\n".join(chunks)
    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(all_text, encoding="utf-8")
    save_hits(debug_file, all_text)

    home, away = detect_teams(all_text, name)
    markets = parse_all(all_text, home, away) if home and away else []
    validation_warnings = player_market_warnings(markets)

    player_market_names = {
        "Anytime Goalscorer",
        "Player Shots On Target",
        "Player Shots",
        "Player Assists",
        "Player Cards",
        "Player Tackles",
        "Player Fouls Committed",
        "Player Fouls Won",
    }
    player_market_count = sum(1 for market in markets if market.get("market") in player_market_names)
    player_selection_count = sum(
        market.get("selection_count", 0)
        for market in markets
        if market.get("market") in player_market_names
    )

    elapsed_seconds = round(time.perf_counter() - match_started, 1)
    print(f"  ✓ {home} v {away} — {len(markets)} markets in {elapsed_seconds}s")
    print(f"    player coverage: {player_market_count} markets / {player_selection_count} selections")
    for market in markets:
        print(f"      {market['market']:<30} {market['selection_count']} selections")
    for warning in validation_warnings:
        print(f"    ! VALIDATION: {warning}")

    return {
        "match": f"{home} v {away}" if home and away else name,
        "home_team": home,
        "away_team": away,
        "url": url,
        "url_source": fixture.get("url_source", ""),
        "captured_tabs": captured_tabs,
        "market_count": len(markets),
        "player_market_count": player_market_count,
        "player_selection_count": player_selection_count,
        "elapsed_seconds": elapsed_seconds,
        "validation_warnings": validation_warnings,
        "markets": markets,
    }

def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("William Hill World Cup Props Scraper — FAST TEST3 V2 candidate")
    print("TEST MODE: MAX_MATCHES = 3")
    print("=" * 60)
    run_started = time.perf_counter()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        fixtures = get_match_links(page)

        results = []
        for i, fixture in enumerate(fixtures, 1):
            print("\n" + "=" * 60)
            print(f"[{i}/{len(fixtures)}]")
            try:
                results.append(scrape_match(page, fixture))
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"  ⚠ Error: {type(e).__name__}: {e}")
                results.append({
                    "match": fixture["name"],
                    "home_team": "",
                    "away_team": "",
                    "url": fixture["url"],
                    "market_count": 0,
                    "markets": [],
                    "error": str(e),
                })

        browser.close()

    run_elapsed_seconds = round(time.perf_counter() - run_started, 1)
    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "WilliamHill",
        "source_url": COMPETITION_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches_with_markets": len([r for r in results if r.get("market_count", 0) > 0]),
        "total_player_markets": sum(r.get("player_market_count", 0) for r in results),
        "total_player_selections": sum(r.get("player_selection_count", 0) for r in results),
        "elapsed_seconds": run_elapsed_seconds,
        "matches": results,
    }

    tmp_path = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(OUT_PATH)

    print(f"\nSaved → {OUT_PATH}")
    print("\n── Summary ─────────────────────────────────────────────")
    for r in results:
        print(
            f"  {r['match']:<40} {r.get('market_count', 0):>2} markets | "
            f"{r.get('player_selection_count', 0):>3} player selections | "
            f"{r.get('elapsed_seconds', 0):>6}s"
        )
    print(f"Total runtime: {run_elapsed_seconds}s")
    print("─" * 60)


if __name__ == "__main__":
    main()
