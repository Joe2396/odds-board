#!/usr/bin/env python3
"""
fetch_williamhill_worldcup_props_FAST_TEST3_V16_PLAYERS_SHOTS_TACKLES.py

William Hill World Cup props scraper — FAST TEST3 V16 candidate — V15 plus exact Players-tab Shots and Tackles.

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
  football/data/williamhill_worldcup_props_FAST_TEST3_V16_PLAYERS_SHOTS_TACKLES.json

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

OUT_PATH  = ROOT / "football" / "data" / "williamhill_worldcup_props_FAST_TEST3_V16_PLAYERS_SHOTS_TACKLES.json"
DEBUG_DIR = ROOT / "football" / "debug" / "williamhill_worldcup_props_FAST_TEST3_V16_PLAYERS_SHOTS_TACKLES"
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



COUNT_WORD_VALUES = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

COUNT_TOKEN_PATTERN = r"(?:\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten)"

# William Hill renders its player-stat ladders as full selection labels rather
# than a conventional 1+/2+/3+ grid. The same structure is used for shots,
# shots on target, tackles, fouls committed and fouls won, for example:
#   Iqraam Rayners At Least 1 Shot On Target
#   Iqraam Rayners Over 1 Shot On Target
#   Player Name Over 2 Tackles
#   Player Name Over 1 Foul
# These patterns deliberately capture the final stat phrase separately so that
# the market heading decides whether a row belongs to shots, tackles, fouls, etc.
INLINE_PLAYER_STAT_ROW_PATTERNS = [
    re.compile(
        rf"^(?P<player>.+?)\s+At\s+Least\s+(?P<count>{COUNT_TOKEN_PATTERN})\s+(?P<stat>.+)$",
        re.I,
    ),
    re.compile(
        rf"^(?P<player>.+?)\s+Over\s+(?P<count>{COUNT_TOKEN_PATTERN})\s+(?P<stat>.+)$",
        re.I,
    ),
    re.compile(
        rf"^(?P<player>.+?)\s+(?P<count>\d+)\+\s+(?P<stat>.+)$",
        re.I,
    ),
    re.compile(
        rf"^(?P<player>.+?)\s+(?:To\s+Have\s+|To\s+Make\s+|To\s+Commit\s+|To\s+Win\s+)?"
        rf"(?P<count>{COUNT_TOKEN_PATTERN})\s+Or\s+More\s+(?P<stat>.+)$",
        re.I,
    ),
]

LADDER_PLAYER_MARKETS = {
    "player_shots_on_target",
    "player_shots",
    "player_tackles",
    "player_fouls_committed",
    "player_fouls_won",
}


def count_token_value(token):
    token = clean(token).lower()
    if token in COUNT_WORD_VALUES:
        return float(COUNT_WORD_VALUES[token])
    try:
        return float(token)
    except (TypeError, ValueError):
        return None


def format_half_line(value):
    return f"{float(value):.1f}".rstrip("0").rstrip(".")


def canonical_count_threshold(mode, raw_count):
    """Convert William Hill integer wording into the shared site ladder.

    Examples for every player-stat ladder:
      At Least 1 -> threshold 1+, line 0.5
      Over 1     -> threshold 2+, line 1.5
      Over 2     -> threshold 3+, line 2.5
      Over 3     -> threshold 4+, line 3.5
    """
    value = count_token_value(raw_count)
    if value is None or value < 0:
        return "", ""

    if mode == "over":
        required = int(value) + 1
    else:
        required = max(1, int(value))

    return f"{required}+", format_half_line(required - 0.5)


def classify_player_stat_phrase(stat_phrase):
    """Return all logical market keys compatible with a WH stat suffix."""
    n = normalize(stat_phrase)
    keys = set()

    if "shot" in n:
        if "target" in n:
            keys.add("player_shots_on_target")
        else:
            keys.add("player_shots")

    if "tackle" in n:
        keys.add("player_tackles")

    if "assist" in n:
        keys.add("player_assists")

    if "card" in n or "booking" in n:
        keys.add("player_cards")

    # Fouls won can be worded as Foul Won, Fouls Won, Time(s) Fouled,
    # To Be Fouled, or Foul(s) Drawn. Keep it separate from committed fouls.
    won_markers = (
        "foul_won", "fouls_won", "time_fouled", "times_fouled",
        "be_fouled", "fouled", "foul_drawn", "fouls_drawn",
    )
    if any(marker in n for marker in won_markers):
        keys.add("player_fouls_won")
    elif "foul" in n:
        keys.add("player_fouls_committed")

    return keys


def match_inline_player_stat_row(label, expected_key=None):
    label = clean(label)
    for index, pattern in enumerate(INLINE_PLAYER_STAT_ROW_PATTERNS):
        match = pattern.fullmatch(label)
        if not match:
            continue

        stat = clean(match.group("stat"))
        compatible_keys = classify_player_stat_phrase(stat)
        if not compatible_keys:
            continue
        if expected_key and expected_key not in compatible_keys:
            continue

        mode = "over" if index == 1 else "at_least"
        return {
            "player": clean(match.group("player")),
            "raw_count": clean(match.group("count")),
            "stat": stat,
            "mode": mode,
            "compatible_keys": compatible_keys,
        }
    return None


def is_inline_player_stat_selection_label(label):
    return match_inline_player_stat_row(label) is not None


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
    if is_inline_player_stat_selection_label(s):
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
            if (
                j > idx + 2
                and is_probably_heading(tok)
                and not is_inline_player_stat_selection_label(tok)
            ):
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



def parse_inline_player_stat_rows(block, key, market_name, prop_type):
    """Parse and canonicalise WH full-label player-stat ladder rows.

    This is shared by shots, shots on target, tackles, fouls committed and
    fouls won. The market heading supplies ``key`` and therefore prevents an
    SOT row being stored as a shot, or a foul-won row as a committed foul.
    """
    selections = []

    for i, raw_label in enumerate(block):
        parsed = match_inline_player_stat_row(raw_label, expected_key=key)
        if not parsed:
            continue

        player = parsed["player"]
        if not looks_like_player_name(player):
            continue

        threshold, line = canonical_count_threshold(parsed["mode"], parsed["raw_count"])
        if not threshold or not line:
            continue

        odds = ""
        for j in range(i + 1, min(i + 4, len(block))):
            token = clean(block[j])
            if is_odds(token):
                odds = token
                break
            if is_inline_player_stat_selection_label(token):
                break

        if not odds:
            continue

        selections.append(sel(
            f"{player} {threshold}",
            odds,
            {
                "player": player,
                "prop_type": prop_type,
                "threshold": threshold,
                "line": line,
                "source_selection": clean(raw_label),
                "source_threshold": (
                    f"Over {parsed['raw_count']}"
                    if parsed["mode"] == "over"
                    else f"At Least {parsed['raw_count']}"
                ),
                "source_stat_phrase": parsed["stat"],
                "source_bookmaker_format": "williamhill_integer_over",
            },
        ))

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
        if key in LADDER_PLAYER_MARKETS:
            # Primary WH layout: each selection is a full row label such as
            # "Over 1 Tackle" or "At Least 1 Foul". Convert every stat market
            # to the common 1+/2+/3+/4+ ladder used by the site.
            all_sels.extend(parse_inline_player_stat_rows(
                block, key, market_name, prop_type
            ))

            # Retain support for a conventional grid if WH changes the layout
            # for a fixture. Do not use the old simple-player fallback here:
            # it mistakes full selection labels for player names and inflates
            # counts into the hundreds.
            all_sels.extend(parse_ladder_player_odds(
                block, market_name, prop_type
            ))
        elif key in {"player_assists", "player_cards"}:
            # WH usually offers these as one-price rows, but the same full-label
            # format can also appear (for example At Least 1 Assist/Card).
            # Support both without allowing the complete row label to become
            # the player name.
            all_sels.extend(parse_inline_player_stat_rows(
                block, key, market_name, prop_type
            ))
            all_sels.extend(parse_simple_player_odds(
                block, market_name, prop_type, default_threshold, default_line
            ))
        else:
            all_sels.extend(parse_simple_player_odds(
                block, market_name, prop_type, default_threshold, default_line
            ))

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


def parse_global_inline_player_stat_markets(lines):
    """Parse WH player-stat rows across the complete captured page text.

    William Hill repeats player markets under several tabs and sometimes nests
    rows beneath controls that make heading-based text blocks unreliable. The
    selection label itself contains everything needed, for example:

      Iqraam Rayners At Least 1 Shot On Target
      Iqraam Rayners Over 1 Shot On Target
      Player Name Over 2 Tackles
      Player Name At Least 1 Foul
      Player Name Over 1 Time Fouled

    The parser scans every captured line, classifies the final stat phrase,
    takes the following price, and deduplicates by player + prop + threshold.
    """
    target_keys = {
        "player_shots_on_target",
        "player_shots",
        "player_tackles",
        "player_fouls_committed",
        "player_fouls_won",
    }
    buckets = {key: [] for key in target_keys}
    source_counts = {key: 0 for key in target_keys}

    for i, raw_label in enumerate(lines):
        parsed = match_inline_player_stat_row(raw_label)
        if not parsed:
            continue

        compatible = [key for key in parsed["compatible_keys"] if key in target_keys]
        if len(compatible) != 1:
            continue

        key = compatible[0]
        player = parsed["player"]
        if not looks_like_player_name(player):
            continue

        threshold, line = canonical_count_threshold(parsed["mode"], parsed["raw_count"])
        if not threshold or not line:
            continue

        odds = ""
        for j in range(i + 1, min(i + 5, len(lines))):
            token = clean(lines[j])
            if is_odds(token):
                odds = token
                break
            if match_inline_player_stat_row(token):
                break
            if j > i + 1 and is_probably_heading(token):
                break

        if not odds:
            continue

        market_name, prop_type, _, _ = MARKET_META[key]
        buckets[key].append(sel(
            f"{player} {threshold}",
            odds,
            {
                "player": player,
                "prop_type": prop_type,
                "threshold": threshold,
                "line": line,
                "source_selection": clean(raw_label),
                "source_threshold": (
                    f"Over {parsed['raw_count']}"
                    if parsed["mode"] == "over"
                    else f"At Least {parsed['raw_count']}"
                ),
                "source_stat_phrase": parsed["stat"],
                "source_bookmaker_format": "williamhill_integer_over",
            },
        ))
        source_counts[key] += 1

    markets = []
    for key in [
        "player_shots_on_target",
        "player_shots",
        "player_tackles",
        "player_fouls_committed",
        "player_fouls_won",
    ]:
        market_name, _, _, _ = MARKET_META[key]
        market = mkt(market_name, buckets[key])
        if market["selection_count"] > 0:
            markets.append(market)

    return markets, source_counts



# Exact William Hill accordion headings for the count-ladder markets. Parsing is
# scoped to the heading block because WH can use similar row wording in both
# "Player Fouls" and "Player Fouls Won". The left/default visible price column
# is Impact Sub; this candidate never clicks Enhanced Win or the price-mode tabs.
SCOPED_LADDER_HEADINGS = {
    "player_shots_on_target": [
        "Player Shots On Target", "Player Shots on Target",
        "Total Player Shots On Target", "Total Player Shots on Target",
    ],
    "player_shots": [
        "Total Player Shots", "Player Shots",
    ],
    "player_tackles": [
        "Total Player Tackles", "Player Total Tackles", "Player Tackles",
    ],
    "player_fouls_committed": [
        "Player Fouls", "Player Fouls Committed", "Player Total Fouls",
    ],
    "player_fouls_won": [
        "Player Fouls Won", "Player To Be Fouled", "Player To Win A Foul",
    ],
}

SCOPED_HEADING_TO_KEY = {
    normalize(heading): key
    for key, headings in SCOPED_LADDER_HEADINGS.items()
    for heading in headings
}

SCOPED_BOUNDARY_HEADINGS = set(SCOPED_HEADING_TO_KEY)
SCOPED_BOUNDARY_HEADINGS.update(normalize(x) for x in [
    "Scorer Markets", "Player To Score", "Anytime Goalscorer",
    "Player Assists", "Player To Assist", "Player Shown A Card",
    "Player Cards", "Player To Be Carded", "Player To Be Sent Off",
    "Player Shot In Both Halves", "Match Result", "Both Teams To Score",
    "Double Chance", "Total Match Over/Under Goals", "1st Half Betting",
    "Responsible Gambling", "Safer Gambling",
])


def _contextual_inline_row(label, expected_key):
    """Parse one WH row, letting its exact accordion heading settle ambiguity."""
    parsed = match_inline_player_stat_row(label)
    if not parsed:
        return None

    compatible = parsed.get("compatible_keys", set())
    if expected_key in compatible:
        return parsed

    stat_n = normalize(parsed.get("stat", ""))

    # Some WH rows beneath Player Fouls Won still shorten the suffix to Foul(s).
    # The exact accordion heading is therefore the authoritative distinction.
    if expected_key in {"player_fouls_committed", "player_fouls_won"} and "foul" in stat_n:
        parsed = dict(parsed)
        parsed["compatible_keys"] = {expected_key}
        return parsed

    return None


def _scoped_blocks(lines, expected_key):
    heading_norms = {normalize(x) for x in SCOPED_LADDER_HEADINGS[expected_key]}
    blocks = []

    for idx, line in enumerate(lines):
        if normalize(line) not in heading_norms:
            continue

        block = []
        for j in range(idx + 1, min(idx + 700, len(lines))):
            token = clean(lines[j])
            token_n = normalize(token)

            if token.startswith("=== TAB "):
                break
            if j > idx + 1 and token_n in SCOPED_BOUNDARY_HEADINGS:
                break
            if token in {"Responsible Gambling", "Safer Gambling"}:
                break
            block.append(token)

        blocks.append(block)

    return blocks


def parse_scoped_player_stat_markets(lines):
    """Parse only rows inside the exact WH accordion for each player stat.

    The first visible odds token following a row is used. With WH's default
    left-hand mode this is the Impact Sub price. Enhanced Win is never clicked.
    """
    markets = []
    raw_counts = {}

    for key in [
        "player_shots_on_target",
        "player_shots",
        "player_tackles",
        "player_fouls_committed",
        "player_fouls_won",
    ]:
        selections = []
        raw_count = 0

        for block in _scoped_blocks(lines, key):
            i = 0
            while i < len(block):
                raw_label = clean(block[i])
                parsed = _contextual_inline_row(raw_label, key)
                if not parsed:
                    i += 1
                    continue

                player = clean(parsed.get("player", ""))
                if not looks_like_player_name(player):
                    i += 1
                    continue

                threshold, line = canonical_count_threshold(
                    parsed.get("mode", "at_least"),
                    parsed.get("raw_count", ""),
                )
                if not threshold or not line:
                    i += 1
                    continue

                odds = ""
                for j in range(i + 1, min(i + 6, len(block))):
                    token = clean(block[j])
                    if is_odds(token):
                        odds = token
                        break
                    if _contextual_inline_row(token, key):
                        break
                    if normalize(token) in SCOPED_BOUNDARY_HEADINGS:
                        break

                if odds:
                    market_name, prop_type, _, _ = MARKET_META[key]
                    selections.append(sel(
                        f"{player} {threshold}",
                        odds,
                        {
                            "player": player,
                            "prop_type": prop_type,
                            "threshold": threshold,
                            "line": line,
                            "source_selection": raw_label,
                            "source_threshold": (
                                f"Over {parsed['raw_count']}"
                                if parsed.get("mode") == "over"
                                else f"At Least {parsed['raw_count']}"
                            ),
                            "source_stat_phrase": parsed.get("stat", ""),
                            "source_bookmaker_format": "williamhill_integer_over",
                            "source_price_mode": "impact_sub_default_visible",
                        },
                    ))
                    raw_count += 1

                i += 1

        market_name, _, _, _ = MARKET_META[key]
        market = mkt(market_name, selections)
        raw_counts[key] = raw_count
        if market["selection_count"] > 0:
            markets.append(market)

    return markets, raw_counts

def parse_player_props(lines):
    """Parse player markets while keeping each market independent."""
    out, seen = [], set()

    # Primary parser: exact accordion-scoped rows. This prevents Player Fouls
    # and Player Fouls Won bleeding into one another and keeps the default
    # visible Impact Sub prices without clicking either price-mode control.
    scoped_markets, _ = parse_scoped_player_stat_markets(lines)
    for market in scoped_markets:
        out.append(market)
        seen.add(market["normalized_market"])

    # Assists and cards can be plain player + one-price rows.
    for key in ["player_assists", "player_cards"]:
        try:
            market = parse_player_market(lines, key)
            if market["selection_count"] > 0 and market["normalized_market"] not in seen:
                out.append(market)
                seen.add(market["normalized_market"])
        except Exception as exc:
            print(f"    player parser error ({key}): {exc}")

    # Use a full-page fallback only when the exact scoped parser found zero
    # rows for an entire market. Scoped data always wins.
    global_fallback_markets, _ = parse_global_inline_player_stat_markets(lines)
    global_fallback_by_name = {
        market["normalized_market"]: market for market in global_fallback_markets
    }

    for key in [
        "player_shots_on_target",
        "player_shots",
        "player_tackles",
        "player_fouls_committed",
        "player_fouls_won",
    ]:
        market_name, _, _, _ = MARKET_META[key]
        normalized_name = normalize(market_name)
        if normalized_name in seen:
            continue
        try:
            fallback = global_fallback_by_name.get(normalized_name)
            if fallback and fallback["selection_count"] > 0:
                out.append(fallback)
                seen.add(fallback["normalized_market"])
                continue

            fallback = parse_player_market(lines, key)
            if fallback["selection_count"] > 0:
                out.append(fallback)
                seen.add(fallback["normalized_market"])
        except Exception as exc:
            print(f"    player fallback parser error ({key}): {exc}")

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



EXACT_LADDER_EXPANSION_TARGETS = [
    ("Player Shots On Target", "player_shots_on_target"),
    ("Player Shots on Target", "player_shots_on_target"),
    ("Total Player Shots", "player_shots"),
    ("Total Player Tackles", "player_tackles"),
    ("Player Fouls", "player_fouls_committed"),
    ("Player Fouls Won", "player_fouls_won"),
]


def _scoped_count_for_heading_text(text, key):
    try:
        markets, counts = parse_scoped_player_stat_markets(lines_from_text(text))
        return int(counts.get(key, 0) or 0)
    except Exception:
        return 0


def click_exact_heading_right_edge(page, heading):
    """Click the accordion's right edge, avoiding its price-mode controls."""
    js = r"""
        (heading) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const target = norm(heading);
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 10 && r.height > 8 && r.bottom > 0 &&
                       r.top < window.innerHeight && st.display !== 'none' &&
                       st.visibility !== 'hidden';
            };

            const nodes = Array.from(document.querySelectorAll('div, span, button, [role=button], h2, h3, p'))
                .filter(visible)
                .filter(el => norm(el.innerText || el.textContent || '') === target);

            const candidates = [];
            for (const el of nodes) {
                let row = el;
                for (let d = 0; d < 8 && row && row !== document.body; d++, row = row.parentElement) {
                    if (!visible(row)) continue;
                    const r = row.getBoundingClientRect();
                    const txt = norm(row.innerText || row.textContent || '');
                    if (r.width >= 650 && r.height >= 28 && r.height <= 100 && txt.includes(target)) {
                        candidates.push({
                            x: Math.max(8, Math.min(r.right - 26, window.innerWidth - 8)),
                            y: Math.max(8, Math.min(r.top + r.height / 2, window.innerHeight - 8)),
                            area: r.width * r.height,
                        });
                        break;
                    }
                }
            }
            candidates.sort((a, b) => a.area - b.area);
            return candidates[0] || null;
        }
    """
    try:
        point = page.evaluate(js, heading)
        if not point:
            return False
        page.mouse.click(float(point["x"]), float(point["y"]))
        page.wait_for_timeout(700)
        return True
    except Exception:
        return False


def verify_and_open_exact_ladders(page):
    """Open any target ladder that the generic fast pass failed to expose."""
    results = []
    attempted_keys = set()

    for heading, key in EXACT_LADDER_EXPANSION_TARGETS:
        if key in attempted_keys:
            continue

        try:
            current = page.locator("body").inner_text(timeout=12000)
        except Exception:
            current = ""

        # Try every heading alias present on the page until rows appear.
        if _scoped_count_for_heading_text(current, key) > 0:
            results.append((key, "already_open"))
            attempted_keys.add(key)
            continue

        aliases = [h for h, k in EXACT_LADDER_EXPANSION_TARGETS if k == key]
        opened = False
        for alias in aliases:
            if normalize(alias) not in normalize(current):
                continue
            if not click_exact_heading_right_edge(page, alias):
                continue
            click_all_see_more(page, max_clicks=4)
            try:
                after = page.locator("body").inner_text(timeout=12000)
            except Exception:
                after = ""
            if _scoped_count_for_heading_text(after, key) > 0:
                results.append((key, "opened"))
                opened = True
                break

        if not opened:
            results.append((key, "no_rows"))
        attempted_keys.add(key)

    return results

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
    ladder_status = verify_and_open_exact_ladders(page)
    click_all_see_more(page, max_clicks=12)
    return clicked, present, ladder_status


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
    "Player Shots On Target": 140,
    "Player Shots": 180,
    "Player Tackles": 180,
    "Player Fouls Committed": 180,
    "Player Fouls Won": 180,
}



CANONICAL_LADDER_MARKET_NAMES = {
    "Player Shots On Target",
    "Player Shots",
    "Player Tackles",
    "Player Fouls Committed",
    "Player Fouls Won",
}


def canonical_player_stat_mapping_warnings(markets):
    warnings = []
    for market in markets:
        if market.get("market") not in CANONICAL_LADDER_MARKET_NAMES:
            continue

        for selection in market.get("selections", []):
            player = clean(selection.get("player", ""))
            threshold = clean(selection.get("threshold", ""))
            line = clean(selection.get("line", ""))

            match = re.fullmatch(r"(\d+)\+", threshold)
            if not match:
                warnings.append(
                    f"{market['market']}: non-canonical threshold {threshold!r} "
                    f"for {player or selection.get('selection', '')}"
                )
                continue

            expected_line = format_half_line(int(match.group(1)) - 0.5)
            if line != expected_line:
                warnings.append(
                    f"{market['market']}: {player} {threshold} has line "
                    f"{line!r}; expected {expected_line}"
                )

            if re.search(r"\b(?:at least|over)\s+\d+", player, re.I):
                warnings.append(
                    f"{market['market']}: raw William Hill label leaked "
                    f"into player field: {player!r}"
                )
    return warnings


def print_canonical_player_stat_samples(markets):
    for market_name in [
        "Player Shots On Target",
        "Player Shots",
        "Player Tackles",
        "Player Fouls Committed",
        "Player Fouls Won",
    ]:
        market = next((m for m in markets if m.get("market") == market_name), None)
        if not market:
            continue

        grouped = {}
        for selection in market.get("selections", []):
            player = clean(selection.get("player", ""))
            threshold = clean(selection.get("threshold", ""))
            if not player or not re.fullmatch(r"\d+\+", threshold):
                continue
            grouped.setdefault(player, []).append(selection)

        if not grouped:
            continue

        player, rows = max(
            grouped.items(),
            key=lambda item: (len(item[1]), item[0]),
        )
        rows.sort(key=lambda row: int(clean(row.get("threshold", "0+")).rstrip("+")))
        ladder = ", ".join(
            f"{row.get('threshold')} @ {row.get('odds')} [line {row.get('line')}]"
            for row in rows[:6]
        )
        print(f"    canonical sample {market_name}: {player} | {ladder}")


def player_market_warnings(markets):
    warnings = canonical_player_stat_mapping_warnings(markets)
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



# ── V9 DOM-geometry player-stat extraction ───────────────────────────────────
# William Hill does not wrap every accordion in a clean market-specific parent.
# Instead of flattening body text, V9 identifies the exact accordion heading,
# defines its vertical section up to the next market heading, and pairs each
# visible row label with the visible odds token on the same horizontal row.
# The script never clicks Impact Sub or Enhanced Win; it reads the current
# default visible panel, which is Impact Sub on these markets.

DOM_STAT_TARGETS = {
    "player_shots_on_target": [
        "Player Shots On Target", "Player Shots on Target",
        "Total Player Shots On Target", "Total Player Shots on Target",
    ],
    "player_shots": ["Total Player Shots", "Player Shots"],
    "player_tackles": ["Total Player Tackles", "Player Total Tackles", "Player Tackles"],
    "player_fouls_committed": ["Player Fouls", "Player Fouls Committed", "Player Total Fouls"],
    "player_fouls_won": ["Player Fouls Won", "Player To Be Fouled", "Player To Win A Foul"],
}

DOM_BOUNDARY_HEADINGS = sorted(set(
    [heading for aliases in DOM_STAT_TARGETS.values() for heading in aliases]
    + FAST_PLAYER_HEADINGS
    + [
        "Scorer Markets", "Player First Goalscorer", "First Goalscorer",
        "Player Shot In Both Halves", "Player To Be Sent Off",
        "Player Shown A Card", "Player To Score Or Assist",
        "Player Assists", "Player Cards", "Popular", "Goals",
        "Match Result", "Both Teams To Score", "Double Chance",
        "Total Match Over/Under Goals", "1st Half Betting",
    ]
))

DOM_GEOMETRY_JS = r"""
({targets, boundaryHeadings, tabLabel}) => {
    const clean = s => (s || '').replace(/\s+/g, ' ').trim();
    const norm = s => clean(s).toLowerCase();
    const oddsRe = /^(?:\d+\/\d+|EVS|EVENS|EVEN|Evens)$/i;
    const countRowRe = /\b(?:At Least|Over)\s+\d+(?:\.\d+)?\b/i;

    const styleVisible = el => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 &&
               st.display !== 'none' && st.visibility !== 'hidden' &&
               st.opacity !== '0';
    };

    const absRect = el => {
        const r = el.getBoundingClientRect();
        return {
            left: r.left + window.scrollX,
            right: r.right + window.scrollX,
            top: r.top + window.scrollY,
            bottom: r.bottom + window.scrollY,
            width: r.width,
            height: r.height,
            cx: r.left + window.scrollX + r.width / 2,
            cy: r.top + window.scrollY + r.height / 2,
        };
    };

    const exactNodes = text => Array.from(document.querySelectorAll(
        'h1,h2,h3,h4,h5,h6,div,span,p,button,[role=button],[role=tab]'
    )).filter(el => styleVisible(el) && norm(el.innerText || el.textContent || '') === norm(text));

    const headerRowFor = text => {
        const candidates = [];
        for (const node of exactNodes(text)) {
            let cur = node;
            for (let depth = 0; depth < 9 && cur && cur !== document.body; depth++, cur = cur.parentElement) {
                if (!styleVisible(cur)) continue;
                const r = absRect(cur);
                const t = clean(cur.innerText || cur.textContent || '');
                if (
                    r.width >= 550 && r.height >= 24 && r.height <= 110 &&
                    norm(t).includes(norm(text))
                ) {
                    candidates.push({node, row: cur, rect: r, area: r.width * r.height, text: t});
                    break;
                }
            }
        }
        candidates.sort((a,b) => a.area - b.area || a.rect.top - b.rect.top);
        return candidates[0] || null;
    };

    const headers = [];
    for (const heading of boundaryHeadings) {
        const h = headerRowFor(heading);
        if (!h) continue;
        if (headers.some(x => Math.abs(x.rect.top - h.rect.top) < 4)) continue;
        headers.push({heading, rect: h.rect});
    }
    headers.sort((a,b) => a.rect.top - b.rect.top);

    const leafTextElements = Array.from(document.querySelectorAll('div,span,p,button,[role=button]'))
        .filter(styleVisible)
        .filter(el => {
            const t = clean(el.innerText || el.textContent || '');
            if (!t || t.includes('\n') || t.length > 190) return false;
            return !Array.from(el.children || []).some(ch => clean(ch.innerText || ch.textContent || '') === t);
        });

    const oddsLeaves = leafTextElements
        .map(el => ({el, text: clean(el.innerText || el.textContent || ''), rect: absRect(el)}))
        .filter(x => oddsRe.test(x.text));

    const matchesKey = (label, key) => {
        const l = norm(label);
        if (!countRowRe.test(label)) return false;
        if (key === 'player_shots_on_target') return /shots? on target/.test(l);
        if (key === 'player_shots') return /\bshots?\b/.test(l) && !/on target/.test(l);
        if (key === 'player_tackles') return /\btackles?\b/.test(l);
        if (key === 'player_fouls_committed') return /\bfouls?\b/.test(l) && !/(fouls? won|times? fouled|to be fouled)/.test(l);
        if (key === 'player_fouls_won') return /\bfouls?\b/.test(l);
        return false;
    };

    const output = {};
    const diagnostics = {};

    for (const [key, aliases] of Object.entries(targets)) {
        let chosen = null;
        for (const alias of aliases) {
            const h = headerRowFor(alias);
            if (!h) continue;
            if (!chosen || h.rect.top < chosen.rect.top) chosen = {alias, ...h};
        }
        if (!chosen) {
            output[key] = [];
            diagnostics[key] = {status: 'heading_not_found'};
            continue;
        }

        const next = headers.find(h => h.rect.top > chosen.rect.bottom + 3);
        const sectionTop = chosen.rect.bottom;
        const sectionBottom = next ? next.rect.top : document.documentElement.scrollHeight + 20;

        const labelCandidates = leafTextElements
            .map(el => ({el, label: clean(el.innerText || el.textContent || ''), rect: absRect(el)}))
            .filter(x => x.rect.cy > sectionTop && x.rect.cy < sectionBottom)
            .filter(x => matchesKey(x.label, key));

        // Deduplicate nested/duplicate text nodes by label and vertical position.
        const uniqueLabels = [];
        for (const row of labelCandidates.sort((a,b) => a.rect.top - b.rect.top || a.rect.width - b.rect.width)) {
            if (uniqueLabels.some(x => x.label === row.label && Math.abs(x.rect.cy - row.rect.cy) < 4)) continue;
            uniqueLabels.push(row);
        }

        const rows = [];
        for (const row of uniqueLabels) {
            const sameLine = oddsLeaves
                .filter(o => o.rect.cy > sectionTop && o.rect.cy < sectionBottom)
                .filter(o => o.rect.left > row.rect.left + Math.min(120, row.rect.width * 0.35))
                .filter(o => Math.abs(o.rect.cy - row.rect.cy) <= Math.max(22, row.rect.height * 0.75))
                .sort((a,b) => {
                    const dy = Math.abs(a.rect.cy - row.rect.cy) - Math.abs(b.rect.cy - row.rect.cy);
                    if (Math.abs(dy) > 0.5) return dy;
                    return b.rect.left - a.rect.left;
                });
            if (!sameLine.length) continue;
            rows.push({
                key,
                label: row.label,
                odds: sameLine[0].text,
                heading: chosen.alias,
                tab: tabLabel,
                y: Math.round(row.rect.cy),
            });
        }

        output[key] = rows;
        diagnostics[key] = {
            status: 'ok',
            heading: chosen.alias,
            section_top: Math.round(sectionTop),
            section_bottom: Math.round(sectionBottom),
            next_heading: next ? next.heading : '',
            label_candidates: uniqueLabels.length,
            paired_rows: rows.length,
        };
    }

    return {rows: output, diagnostics, headers};
}
"""


def extract_dom_player_stat_rows(page, tab_label):
    try:
        result = page.evaluate(DOM_GEOMETRY_JS, {
            "targets": DOM_STAT_TARGETS,
            "boundaryHeadings": DOM_BOUNDARY_HEADINGS,
            "tabLabel": tab_label,
        }) or {}
    except Exception as exc:
        return {key: [] for key in DOM_STAT_TARGETS}, {"error": str(exc)}

    rows = result.get("rows", {}) or {}
    diagnostics = result.get("diagnostics", {}) or {}
    return {key: rows.get(key, []) or [] for key in DOM_STAT_TARGETS}, diagnostics


def merge_dom_row_buckets(target, incoming):
    for key in DOM_STAT_TARGETS:
        target.setdefault(key, [])
        target[key].extend(incoming.get(key, []) or [])


def build_dom_player_stat_markets(row_buckets):
    markets = []
    parsed_counts = {}

    for key in [
        "player_shots_on_target", "player_shots", "player_tackles",
        "player_fouls_committed", "player_fouls_won",
    ]:
        rows = list(row_buckets.get(key, []) or [])
        # Dedicated Player/Players tab is authoritative over duplicate rows from
        # Popular or Goals. Within equal priority, keep the first visible price.
        rows.sort(key=lambda row: (
            0 if normalize(row.get("tab", "")) in {"player", "players", "player_stats"} else 1,
            int(row.get("y", 0) or 0),
        ))

        semantic = {}
        for row in rows:
            parsed = _contextual_inline_row(clean(row.get("label", "")), key)
            if not parsed:
                continue
            player = clean(parsed.get("player", ""))
            if not looks_like_player_name(player):
                continue
            threshold, line = canonical_count_threshold(
                parsed.get("mode", "at_least"), parsed.get("raw_count", "")
            )
            odds = clean(row.get("odds", ""))
            if not threshold or not line or not is_odds(odds):
                continue

            semantic_key = (normalize(player), threshold)
            if semantic_key in semantic:
                continue

            market_name, prop_type, _, _ = MARKET_META[key]
            semantic[semantic_key] = sel(
                f"{player} {threshold}",
                odds,
                {
                    "player": player,
                    "prop_type": prop_type,
                    "threshold": threshold,
                    "line": line,
                    "source_selection": clean(row.get("label", "")),
                    "source_threshold": (
                        f"Over {parsed['raw_count']}"
                        if parsed.get("mode") == "over"
                        else f"At Least {parsed['raw_count']}"
                    ),
                    "source_stat_phrase": parsed.get("stat", ""),
                    "source_bookmaker_format": "williamhill_integer_over",
                    "source_price_mode": "impact_sub_default_visible",
                    "source_dom_heading": clean(row.get("heading", "")),
                    "source_tab": clean(row.get("tab", "")),
                },
            )

        market_name, _, _, _ = MARKET_META[key]
        market = mkt(market_name, list(semantic.values()))
        parsed_counts[key] = market["selection_count"]
        if market["selection_count"] > 0:
            markets.append(market)

    return markets, parsed_counts


def replace_count_ladder_markets(markets, dom_markets):
    protected_names = {
        normalize(MARKET_META[key][0])
        for key in DOM_STAT_TARGETS
    }
    kept = [m for m in markets if m.get("normalized_market") not in protected_names]
    return kept + dom_markets


def identical_market_fingerprint(markets, first_name, second_name):
    by_name = {m.get("market"): m for m in markets}
    def fp(name):
        market = by_name.get(name, {})
        return {
            (
                normalize(s.get("player", "")),
                clean(s.get("threshold") or s.get("line") or ""),
                clean(s.get("odds", "")).upper(),
            )
            for s in market.get("selections", [])
        }
    a, b = fp(first_name), fp(second_name)
    return bool(a and b and a == b)



# ── V10 correctness-first isolated capture ───────────────────────────────────
# William Hill reuses similar row wording across multiple accordions and keeps
# Impact Sub / Enhanced Win controls beside the same market. V10 avoids trying
# to infer section boundaries from one giant page dump. Each count-ladder market
# is loaded on a fresh event page, the exact accordion is opened, and only that
# isolated capture is parsed. This is intentionally slower while TEST3 validates
# correctness; navigation can be optimised after the data is proven.

ISOLATED_STAT_SPECS = [
    ("player_shots_on_target", ["Player Shots On Target", "Player Shots on Target"]),
    ("player_shots", ["Total Player Shots", "Player Shots"]),
    ("player_tackles", ["Total Player Tackles", "Player Tackles"]),
    ("player_fouls_committed", ["Player Fouls"]),
    ("player_fouls_won", ["Player Fouls Won"]),
]

SCORER_MARKET_NAMES = {
    "first_goalscorer": "First Goalscorer",
    "anytime_scorer": "Anytime Goalscorer",
    "scorer_2_plus": "To Score 2+",
}


def fresh_event_page(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=70000)
    page.wait_for_timeout(4200)
    accept_cookies(page)
    try:
        page.evaluate("window.scrollTo(0,0); document.scrollingElement.scrollTop=0")
    except Exception:
        pass


def heading_button_state(page, heading):
    """Return exact accordion state and a safe right-edge click point."""
    js = r"""
        (heading) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const target = norm(heading);
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 8 && r.height > 8 && st.display !== 'none' &&
                       st.visibility !== 'hidden';
            };
            const nodes = Array.from(document.querySelectorAll('button,[role=button],[aria-expanded],div,span,h2,h3,p'))
                .filter(visible)
                .filter(el => norm(el.innerText || el.textContent || '') === target);
            const found = [];
            for (const el of nodes) {
                let row = el;
                for (let d=0; d<10 && row && row!==document.body; d++, row=row.parentElement) {
                    if (!visible(row)) continue;
                    const r = row.getBoundingClientRect();
                    const txt = norm(row.innerText || row.textContent || '');
                    if (r.width < 500 || r.height < 25 || r.height > 110 || !txt.includes(target)) continue;
                    let expanded = row.getAttribute('aria-expanded');
                    if (expanded === null) {
                        const ae = row.querySelector('[aria-expanded]');
                        if (ae) expanded = ae.getAttribute('aria-expanded');
                    }
                    found.push({
                        heading: heading,
                        expanded: expanded,
                        x: Math.max(8, Math.min(r.right - 28, window.innerWidth - 8)),
                        y: Math.max(8, Math.min(r.top + r.height/2, window.innerHeight - 8)),
                        docY: r.top + window.scrollY,
                        area: r.width * r.height
                    });
                    break;
                }
            }
            found.sort((a,b)=>a.docY-b.docY || a.area-b.area);
            return found[0] || null;
        }
    """
    try:
        return page.evaluate(js, heading)
    except Exception:
        return None


def exact_heading_exists(page, heading):
    try:
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        return False
    target = normalize(heading)
    return any(normalize(line) == target for line in lines_from_text(body))


def set_accordion_open(page, aliases, should_open):
    """Open/collapse one exact accordion without touching price-mode buttons."""
    for heading in aliases:
        if not exact_heading_exists(page, heading):
            continue
        state = heading_button_state(page, heading)
        if not state:
            continue
        expanded = state.get("expanded")
        is_open = expanded == "true" if expanded in {"true", "false"} else None
        if is_open is should_open:
            return heading, "already_open" if should_open else "already_closed"
        # When William Hill omits aria-expanded, never click while trying to
        # collapse another market: doing so could open a closed accordion.
        if is_open is None and not should_open:
            return heading, "unknown_left_untouched"
        try:
            page.evaluate("y => window.scrollTo(0, Math.max(0, y - 260))", float(state["docY"]))
            page.wait_for_timeout(350)
            state = heading_button_state(page, heading) or state
            page.mouse.click(float(state["x"]), float(state["y"]))
            page.wait_for_timeout(900)
            return heading, "opened" if should_open else "closed"
        except Exception:
            continue
    return "", "not_found"


def collapse_other_stat_accordions(page, keep_key):
    for key, aliases in ISOLATED_STAT_SPECS:
        if key == keep_key:
            continue
        set_accordion_open(page, aliases, False)


def isolated_stat_phrase_ok(key, phrase):
    n = normalize(phrase)
    if key == "player_shots_on_target":
        return "shot" in n and "target" in n
    if key == "player_shots":
        return "shot" in n and "target" not in n
    if key == "player_tackles":
        return "tackle" in n
    if key in {"player_fouls_committed", "player_fouls_won"}:
        # The exact accordion supplies the meaning. WH sometimes shortens both
        # sets of row labels to plain "Foul(s)".
        return "foul" in n or "fouled" in n
    return False


def parse_isolated_stat_capture(text, key):
    market_name, prop_type, _, _ = MARKET_META[key]
    lines = lines_from_text(text)
    selections = []
    for i, raw_label in enumerate(lines):
        parsed = None
        for index, pattern in enumerate(INLINE_PLAYER_STAT_ROW_PATTERNS):
            match = pattern.fullmatch(clean(raw_label))
            if not match:
                continue
            phrase = clean(match.group("stat"))
            if not isolated_stat_phrase_ok(key, phrase):
                continue
            parsed = {
                "player": clean(match.group("player")),
                "raw_count": clean(match.group("count")),
                "stat": phrase,
                "mode": "over" if index == 1 else "at_least",
            }
            break
        if not parsed or not looks_like_player_name(parsed["player"]):
            continue
        odd = ""
        for j in range(i + 1, min(i + 5, len(lines))):
            token = clean(lines[j])
            if is_odds(token):
                odd = token
                break
            if any(p.fullmatch(token) for p in INLINE_PLAYER_STAT_ROW_PATTERNS):
                break
        if not odd:
            continue
        threshold, line = canonical_count_threshold(parsed["mode"], parsed["raw_count"])
        if not threshold:
            continue
        selections.append(sel(
            f"{parsed['player']} {threshold}", odd,
            {
                "player": parsed["player"],
                "prop_type": prop_type,
                "threshold": threshold,
                "line": line,
                "source_selection": clean(raw_label),
                "source_stat_phrase": parsed["stat"],
                "source_price_mode": "impact_sub_default",
                "source_capture": "isolated_accordion",
            },
        ))
    return mkt(market_name, selections)


def capture_one_isolated_stat(page, url, key, aliases):
    fresh_event_page(page, url)
    tab = try_tab_aliases(page, ["Player", "Players", "Player Stats"])
    if not tab:
        return mkt(MARKET_META[key][0], []), {"status": "no_player_tab"}, ""
    collapse_other_stat_accordions(page, key)
    heading, state = set_accordion_open(page, aliases, True)
    if not heading:
        return mkt(MARKET_META[key][0], []), {"status": state}, ""
    # Expand all visible row pagers while this exact market is the only target
    # accordion intentionally open. Never click Impact Sub or Enhanced Win.
    click_all_see_more(page, max_clicks=16)
    scroll_page(page, 5)
    text = page.locator("body").inner_text(timeout=22000)
    market = parse_isolated_stat_capture(text, key)
    return market, {
        "status": state,
        "heading": heading,
        "tab": tab,
        "selection_count": market["selection_count"],
    }, text


def parse_scorer_grid_three_markets(text):
    """Read First, Anytime and 2 Or More from the visible WH scorer grid."""
    lines = lines_from_text(text)
    buckets = {key: [] for key in SCORER_MARKET_NAMES}
    canonical_headers = {
        "first": "first_goalscorer",
        "anytime": "anytime_scorer",
        "2 or more": "scorer_2_plus",
    }
    stop_words = {
        "player shots", "player shots on target", "total player shots",
        "player shown a card", "player fouls", "player fouls won",
        "total player tackles", "responsible gambling", "safer gambling",
    }
    for idx, token in enumerate(lines):
        if clean(token).lower() != "name":
            continue
        headers = []
        cursor = idx + 1
        while cursor < min(idx + 18, len(lines)):
            low = clean(lines[cursor]).lower().replace("hat trick", "hat-trick")
            if low in SCORER_GRID_HEADERS:
                headers.append(low)
                cursor += 1
                continue
            if not headers and low in {"impact sub", "enhanced win"}:
                cursor += 1
                continue
            break
        wanted = {h: canonical_headers[h] for h in headers if h in canonical_headers}
        if not wanted:
            continue
        i = cursor
        while i < len(lines):
            player = clean(lines[i])
            low = player.lower()
            if low == "name" or low in stop_words:
                break
            if not looks_like_player_name(player):
                i += 1
                continue
            odds = []
            j = i + 1
            while j < min(i + len(headers) + 6, len(lines)):
                nxt = clean(lines[j])
                if is_odds(nxt):
                    odds.append(nxt)
                    j += 1
                    continue
                if odds or looks_like_player_name(nxt) or nxt.lower() == "name":
                    break
                j += 1
            if len(odds) >= len(headers):
                for col, header in enumerate(headers):
                    market_key = canonical_headers.get(header)
                    if not market_key or col >= len(odds):
                        continue
                    if market_key == "first_goalscorer":
                        label, prop_type, threshold, line = f"{player} First Goalscorer", "first_goalscorer", "First", "0.5"
                    elif market_key == "anytime_scorer":
                        label, prop_type, threshold, line = f"{player} Anytime Goalscorer", "anytime_scorer", "To Score", "0.5"
                    else:
                        label, prop_type, threshold, line = f"{player} To Score 2+", "scorer_2_plus", "2+", "1.5"
                    buckets[market_key].append(sel(label, odds[col], {
                        "player": player,
                        "prop_type": prop_type,
                        "threshold": threshold,
                        "line": line,
                        "source_price_mode": "impact_sub_default",
                        "source_grid_column": header,
                    }))
                i = max(j, i + 1)
                continue
            i += 1
    markets = []
    for key, name in SCORER_MARKET_NAMES.items():
        market = mkt(name, buckets[key])
        market["normalized_market"] = key
        if market["selection_count"]:
            markets.append(market)
    return markets


def click_scorer_team(page, team):
    js = r"""
        (team) => {
            const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLowerCase();
            const target=norm(team);
            const visible=el=>{const r=el.getBoundingClientRect();const st=getComputedStyle(el);return r.width>80&&r.height>18&&r.bottom>0&&r.top<window.innerHeight&&st.display!=='none'&&st.visibility!=='hidden';};
            const cands=[];
            for (const el of document.querySelectorAll('button,[role=button],[role=tab],a,div,span')) {
                if (!visible(el) || norm(el.innerText||el.textContent||'')!==target) continue;
                const r=el.getBoundingClientRect();
                if (r.width<120 || r.width>1000 || r.height>110) continue;
                let anc=el; let score=0;
                for(let d=0;d<8&&anc;d++,anc=anc.parentElement){const t=norm(anc.innerText||anc.textContent||'');if(t.includes('scorer markets')){score+=100;break;}}
                score += Math.min(r.width,900)/10;
                cands.push({x:r.left+r.width/2,y:r.top+r.height/2,score});
            }
            cands.sort((a,b)=>b.score-a.score);
            return cands[0]||null;
        }
    """
    try:
        point = page.evaluate(js, team)
        if not point:
            return False
        page.mouse.click(float(point["x"]), float(point["y"]))
        page.wait_for_timeout(1100)
        return True
    except Exception:
        return False


def capture_scorer_markets(page, url, home, away):
    fresh_event_page(page, url)
    if not click_tab(page, "Goals"):
        return [], {"status": "no_goals_tab"}, ""
    # Open Scorer Markets when it is collapsed; do not touch price-mode controls.
    set_accordion_open(page, ["Scorer Markets"], True)
    combined = {key: [] for key in SCORER_MARKET_NAMES}
    dumps = []
    team_results = []
    for team in [home, away]:
        clicked = click_scorer_team(page, team)
        click_all_see_more(page, max_clicks=12)
        text = page.locator("body").inner_text(timeout=22000)
        dumps.append(f"=== SCORER TEAM {team} clicked={clicked} ===\n{text}")
        parsed = parse_scorer_grid_three_markets(text)
        team_results.append({"team": team, "clicked": clicked, "counts": {m["normalized_market"]: m["selection_count"] for m in parsed}})
        for market in parsed:
            combined[market["normalized_market"]].extend(market["selections"])
    markets = []
    for key, name in SCORER_MARKET_NAMES.items():
        market = mkt(name, combined[key])
        market["normalized_market"] = key
        if market["selection_count"]:
            markets.append(market)
    return markets, {"status": "ok", "teams": team_results}, "\n\n".join(dumps)


def replace_named_markets(markets, replacements, protected_normalized):
    kept = [m for m in markets if normalize(m.get("normalized_market") or m.get("market")) not in protected_normalized]
    return kept + [m for m in replacements if m.get("selection_count", 0) > 0]



def v16_capture_players_tab_shots_tackles(page):
    """Capture only Total Player Shots and Total Player Tackles from Players.

    V15 correctly uses the top-level Impact Sub tab for scorer markets, SOT,
    fouls, cards and assists. William Hill exposes Total Player Shots and
    Total Player Tackles only on the separate Players tab, so V16 makes one
    additional tab switch and opens exactly those two accordions.

    No broad heading matching is used and no other Players markets are clicked.
    """
    tab = try_tab_aliases(page, ["Players", "Player", "Player Stats"])
    if not tab:
        return [], {
            "status": "no_players_tab",
            "opened": {},
            "selection_counts": {},
            "excluded_headings_clicked": 0,
        }, ""

    targets = {
        "player_shots": ["Total Player Shots"],
        "player_tackles": ["Total Player Tackles"],
    }

    opened = {}
    for key, aliases in targets.items():
        heading, state = v11_open_first_exact(page, aliases)
        opened[key] = {
            "heading": heading,
            "state": state,
        }

    # Only Show More controls exposed by the two exact opened accordions are
    # expanded. No unrelated heading is clicked.
    click_all_see_more(page, max_clicks=20)
    scroll_page(page, 5)

    text = page.locator("body").inner_text(timeout=22000)

    markets = []
    for key in targets:
        market = parse_isolated_stat_capture(text, key)
        if market.get("selection_count", 0):
            # Keep source metadata clear: these two markets come from Players,
            # not the top-level Impact Sub tab.
            for selection in market.get("selections", []):
                selection["source_top_tab"] = "Players"
                selection["source_price_mode"] = "players_tab_default"
            markets.append(market)

    counts = {
        normalize(m.get("normalized_market") or m.get("market")):
            m.get("selection_count", 0)
        for m in markets
    }

    return markets, {
        "status": "ok",
        "tab": tab,
        "opened": opened,
        "selection_counts": counts,
        "excluded_headings_clicked": 0,
    }, text


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

    match_started = time.perf_counter()
    base_chunks = []
    captured_tabs = []

    # One broad capture for core match markets, cards/assists and debug context.
    fresh_event_page(page, url)
    if hint_home and hint_away and not page_has_fixture(page, hint_home, hint_away):
        raise RuntimeError(f"Cached URL did not load expected fixture: {name}")
    clicked, present, _ = expand_relevant_player_markets_fast(page)
    base_chunks.append("=== TAB Popular/Default ===\n" + page.locator("body").inner_text(timeout=20000))
    captured_tabs.append("Popular/Default")
    print(f"    ✓ Popular/Default ({clicked} relevant headings clicked; {len(present)} found)")

    player_tab = try_tab_aliases(page, ["Player", "Players", "Player Stats"])
    if player_tab:
        clicked, present, _ = expand_relevant_player_markets_fast(page)
        click_all_see_more(page, max_clicks=12)
        base_chunks.append(f"=== TAB {player_tab} ===\n" + page.locator("body").inner_text(timeout=22000))
        captured_tabs.append(player_tab)
        print(f"    ✓ {player_tab} base capture ({clicked} relevant headings clicked; {len(present)} found)")
    else:
        print("    - no Player/Players/Player Stats tab")

    base_text = "\n\n".join(base_chunks)
    home, away = detect_teams(base_text, name)
    home = home or hint_home
    away = away or hint_away
    markets = parse_all(base_text, home, away) if home and away else []

    # Correctness-first: reload and isolate every count-ladder market.
    isolated_markets = []
    isolated_debug = []
    isolated_diag = {}
    for key, aliases in ISOLATED_STAT_SPECS:
        market, diag, text = capture_one_isolated_stat(page, url, key, aliases)
        isolated_diag[key] = diag
        if text:
            isolated_debug.append(f"=== ISOLATED {MARKET_META[key][0]} ===\n{text}")
        if market["selection_count"]:
            isolated_markets.append(market)
        print(f"    isolated {MARKET_META[key][0]}: {market['selection_count']} selections ({diag.get('status')})")

    protected_stats = {normalize(MARKET_META[key][0]) for key, _ in ISOLATED_STAT_SPECS}
    protected_stats |= {"player_shots_on_target", "player_shots", "player_tackles", "player_fouls_committed", "player_fouls_won"}
    markets = replace_named_markets(markets, isolated_markets, protected_stats)

    # Scorer grid: explicitly capture both team tabs and all three site-supported
    # scorer columns (First, Anytime and 2 Or More).
    scorer_markets, scorer_diag, scorer_text = capture_scorer_markets(page, url, home, away)
    protected_scorers = {"first_goalscorer", "anytime_scorer", "anytime_goalscorer", "scorer_2_plus", "to_score_2"}
    markets = replace_named_markets(markets, scorer_markets, protected_scorers)
    print("    scorer markets: " + ", ".join(f"{m['market']}={m['selection_count']}" for m in scorer_markets) if scorer_markets else "    scorer markets: none")

    all_text = base_text + "\n\n" + "\n\n".join(isolated_debug) + ("\n\n" + scorer_text if scorer_text else "")
    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(all_text, encoding="utf-8")
    save_hits(debug_file, all_text)
    diag_path = DEBUG_DIR / f"{slugify(name)}_isolated_diagnostics.json"
    diag_path.write_text(json.dumps({"stats": isolated_diag, "scorers": scorer_diag}, indent=2, ensure_ascii=False), encoding="utf-8")

    validation_warnings = player_market_warnings(markets)
    if identical_market_fingerprint(markets, "Player Fouls Committed", "Player Fouls Won"):
        validation_warnings.append("Fouls Committed and Fouls Won are still identical after isolated capture")
    by_norm = {m.get("normalized_market"): m for m in markets}
    for required in ["first_goalscorer", "anytime_scorer", "scorer_2_plus"]:
        if required not in by_norm:
            validation_warnings.append(f"Missing scorer market: {required}")

    player_keys = {
        "first_goalscorer", "anytime_scorer", "scorer_2_plus",
        "player_shots_on_target", "player_shots", "player_assists", "player_cards",
        "player_tackles", "player_fouls_committed", "player_fouls_won",
    }
    player_market_count = sum(1 for m in markets if normalize(m.get("normalized_market") or m.get("market")) in player_keys)
    player_selection_count = sum(m.get("selection_count", 0) for m in markets if normalize(m.get("normalized_market") or m.get("market")) in player_keys)

    elapsed_seconds = round(time.perf_counter() - match_started, 1)
    print(f"  ✓ {home} v {away} — {len(markets)} markets in {elapsed_seconds}s")
    print(f"    player coverage: {player_market_count} markets / {player_selection_count} selections")
    for market in markets:
        print(f"      {market['market']:<30} {market['selection_count']} selections")
    print_canonical_player_stat_samples(markets)
    for warning in validation_warnings:
        print(f"    ! VALIDATION: {warning}")

    return {
        "match": f"{home} v {away}",
        "home_team": home,
        "away_team": away,
        "url": url,
        "url_source": fixture.get("url_source", ""),
        "captured_tabs": captured_tabs,
        "player_price_mode": "impact_sub_default_no_mode_clicks",
        "capture_strategy": "isolated_fresh_page_per_count_ladder_market",
        "diagnostics": str(diag_path),
        "market_count": len(markets),
        "player_market_count": player_market_count,
        "player_selection_count": player_selection_count,
        "elapsed_seconds": elapsed_seconds,
        "validation_warnings": validation_warnings,
        "markets": markets,
    }


# ── V11 exact-whitelist reset ────────────────────────────────────────────────
# V10 still used broad substring heading clicks during its base pass. That meant
# "Player To Score" could open "Player To Score A Header", while "Player Fouls"
# could hit "Player Foul Involvements" or "Player Fouls Won". V11 never uses a
# substring click for market accordions. Only the exact headings below are opened.

V11_EXACT_PLAYER_HEADINGS = {
    "player_shots_on_target": ["Player Shots On Target", "Player Shots on Target"],
    "player_shots": ["Total Player Shots", "Player Shots"],
    "player_tackles": ["Total Player Tackles", "Player Tackles"],
    "player_fouls_committed": ["Player Fouls"],
    "player_fouls_won": ["Player Fouls Won"],
}

V11_EXACT_OPTIONAL_HEADINGS = [
    ["Player Shown A Card", "Player Cards", "Player To Be Carded"],
    ["Player Assists", "Player To Assist"],
]

# Exact boundaries used to split the flattened William Hill page text. The two
# unwanted markets reported during testing are deliberately boundaries, never
# targets, so their rows cannot bleed into a wanted market.
V11_MARKET_BOUNDARIES = {
    normalize(x) for x in [
        "Scorer Markets", "Player To Score A Header", "To Score A Header",
        "Player Foul Involvements", "Foul Involvements",
        "Player To Score Or Assist", "Player Offsides", "Player Assists",
        "Player To Assist", "Player Shown A Card", "Player Cards",
        "Player To Be Carded", "Player Shots On Target", "Player Shots on Target",
        "Total Player Shots", "Player Shots", "Total Player Tackles",
        "Player Tackles", "Player Fouls", "Player Fouls Won",
        "Player Passes", "Player Crosses", "Player Clearances",
        "Player Interceptions", "Goalkeeper Saves", "Player Saves",
        "Match Result", "Both Teams To Score", "Double Chance",
        "Total Match Goals", "1st Half Betting", "Correct Score",
    ]
}

_V10_PARSE_ISOLATED = parse_isolated_stat_capture
_V10_CAPTURE_SCORERS = capture_scorer_markets


def v11_exact_lines(page):
    try:
        return {normalize(x) for x in lines_from_text(page.locator("body").inner_text(timeout=12000))}
    except Exception:
        return set()


def v11_open_first_exact(page, aliases):
    """Open only a line whose full text exactly equals one supplied alias."""
    present = v11_exact_lines(page)
    for heading in aliases:
        if normalize(heading) not in present:
            continue
        actual, state = set_accordion_open(page, [heading], True)
        if actual:
            return actual, state
    return "", "not_found"


def v11_extract_exact_blocks(text, aliases):
    lines = lines_from_text(text)
    aliases_n = {normalize(x) for x in aliases}
    blocks = []
    for idx, line in enumerate(lines):
        if normalize(line) not in aliases_n:
            continue
        end = len(lines)
        for j in range(idx + 1, len(lines)):
            n = normalize(lines[j])
            if n in V11_MARKET_BOUNDARIES and n not in aliases_n:
                end = j
                break
        block = lines[idx:end]
        if block:
            blocks.append(block)
    return blocks


def parse_isolated_stat_capture(text, key):
    """Parse only the exact wanted accordion block, never the whole Player tab."""
    aliases = V11_EXACT_PLAYER_HEADINGS.get(key, [])
    blocks = v11_extract_exact_blocks(text, aliases)
    if not blocks:
        return mkt(MARKET_META[key][0], [])
    combined = []
    for block in blocks:
        parsed = _V10_PARSE_ISOLATED("\n".join(block), key)
        combined.extend(parsed.get("selections", []))
    return mkt(MARKET_META[key][0], combined)


def v11_parse_flexible_scorer_grid(text):
    """Flexible First/Anytime/2+ grid parser for William Hill's scorer table."""
    lines = lines_from_text(text)
    buckets = {key: [] for key in SCORER_MARKET_NAMES}

    def header_key(token):
        low = clean(token).lower().replace("hat trick", "hat-trick")
        if low == "first" or low.startswith("first goalscorer"):
            return "first_goalscorer"
        if "anytime" in low:
            return "anytime_scorer"
        if low in {"2 or more", "2+", "two or more"} or low.startswith("2 or more"):
            return "scorer_2_plus"
        if low in {"hat-trick", "last", "first and last", "first or last"}:
            return "ignore"
        return ""

    for idx, token in enumerate(lines):
        if clean(token).lower() not in {"name", "player"}:
            continue
        headers = []
        cursor = idx + 1
        while cursor < min(idx + 28, len(lines)):
            low = clean(lines[cursor]).lower()
            if low in {"impact sub", "enhanced win", "price", "odds"}:
                cursor += 1
                continue
            hk = header_key(lines[cursor])
            if hk:
                headers.append(hk)
                cursor += 1
                continue
            if headers:
                break
            cursor += 1
        if not headers or not any(h in headers for h in buckets):
            continue

        i = cursor
        while i < len(lines):
            player = clean(lines[i])
            low = player.lower()
            if normalize(player) in V11_MARKET_BOUNDARIES or low in {"name", "player"}:
                break
            if not looks_like_player_name(player):
                i += 1
                continue
            odds = []
            j = i + 1
            while j < min(i + len(headers) + 12, len(lines)):
                val = clean(lines[j])
                if is_odds(val):
                    odds.append(val)
                    j += 1
                    continue
                if odds or looks_like_player_name(val):
                    break
                j += 1
            if len(odds) >= len(headers):
                for col, hk in enumerate(headers):
                    if hk not in buckets or col >= len(odds):
                        continue
                    if hk == "first_goalscorer":
                        label, prop, threshold, line = f"{player} First Goalscorer", hk, "First", "0.5"
                    elif hk == "anytime_scorer":
                        label, prop, threshold, line = f"{player} Anytime Goalscorer", hk, "To Score", "0.5"
                    else:
                        label, prop, threshold, line = f"{player} To Score 2+", hk, "2+", "1.5"
                    buckets[hk].append(sel(label, odds[col], {
                        "player": player, "prop_type": prop, "threshold": threshold,
                        "line": line, "source_price_mode": "impact_sub_default",
                        "source_grid_column": hk,
                    }))
                i = max(i + 1, j)
                continue
            i += 1

    result = []
    for key, name in SCORER_MARKET_NAMES.items():
        market = mkt(name, buckets[key])
        market["normalized_market"] = key
        if market["selection_count"]:
            result.append(market)
    return result


def capture_scorer_markets(page, url, home, away):
    """Exact Scorer Markets only; never click To Score A Header."""
    markets, diag, text = _V10_CAPTURE_SCORERS(page, url, home, away)
    if markets:
        return markets, diag, text

    flexible = v11_parse_flexible_scorer_grid(text)
    if flexible:
        diag = dict(diag or {})
        diag["fallback"] = "v11_flexible_grid"
        return flexible, diag, text

    # Last safe fallback: recover only the known-good Anytime column. This still
    # never touches the header market and is better than returning no scorer data.
    anytime = parse_anytime_goalscorer_grid(text)
    if anytime.get("selection_count", 0):
        anytime["normalized_market"] = "anytime_scorer"
        diag = dict(diag or {})
        diag["fallback"] = "v3_anytime_column"
        return [anytime], diag, text
    return [], diag, text


def v11_capture_player_tab_once(page, url, home, away):
    """Open one Player tab and only the exact whitelist, once per fixture."""
    fresh_event_page(page, url)
    tab = try_tab_aliases(page, ["Player", "Players", "Player Stats"])
    if not tab:
        return [], {"status": "no_player_tab"}, ""

    opened = {}
    for key, aliases in V11_EXACT_PLAYER_HEADINGS.items():
        heading, state = v11_open_first_exact(page, aliases)
        opened[key] = {"heading": heading, "state": state}

    optional_opened = []
    for aliases in V11_EXACT_OPTIONAL_HEADINGS:
        heading, state = v11_open_first_exact(page, aliases)
        if heading:
            optional_opened.append({"heading": heading, "state": state})

    # One pager pass after the wanted accordions are open. No generic heading
    # click and no Player To Score / Foul Involvements expansion.
    click_all_see_more(page, max_clicks=12)
    scroll_page(page, 5)
    text = page.locator("body").inner_text(timeout=22000)

    markets = []
    for key in V11_EXACT_PLAYER_HEADINGS:
        market = parse_isolated_stat_capture(text, key)
        if market["selection_count"]:
            markets.append(market)

    # Reuse established card/assist parsers, but keep only those exact outputs.
    parsed = parse_all(text, home, away)
    allowed = {"player_cards", "player_assists"}
    for market in parsed:
        n = normalize(market.get("normalized_market") or market.get("market"))
        if n in allowed and market.get("selection_count", 0):
            markets.append(market)

    return markets, {
        "status": "ok", "tab": tab, "opened": opened,
        "optional_opened": optional_opened,
        "selection_counts": {m["normalized_market"]: m["selection_count"] for m in markets},
    }, text


def scrape_match(page, fixture):
    """V11 exact-whitelist workflow: no broad market clicks, one Player load."""
    url = fixture["url"]
    name = fixture["name"]
    print(f"  Scraping: {name}")
    print(f"  URL: {url}")
    print(f"  URL source: {fixture.get('url_source', 'unknown')}")

    hint_home = canonical_team(clean(fixture.get("home") or ""))
    hint_away = canonical_team(clean(fixture.get("away") or ""))
    if (not hint_home or not hint_away) and " v " in name:
        hint_home, hint_away = [canonical_team(clean(x)) for x in name.split(" v ", 1)]

    started = time.perf_counter()
    fresh_event_page(page, url)
    if hint_home and hint_away and not page_has_fixture(page, hint_home, hint_away):
        raise RuntimeError(f"Cached URL did not load expected fixture: {name}")

    # Popular/default: capture only what is already visible. Do not open any
    # player heading here.
    popular_text = page.locator("body").inner_text(timeout=20000)
    home, away = detect_teams(popular_text, name)
    home = home or hint_home
    away = away or hint_away
    markets = parse_all(popular_text, home, away) if home and away else []
    print("    ✓ Popular/Default (0 generic headings clicked)")

    player_markets, player_diag, player_text = v11_capture_player_tab_once(page, url, home, away)
    protected_player = {
        "player_shots_on_target", "player_shots", "player_tackles",
        "player_fouls_committed", "player_fouls_won", "player_cards", "player_assists",
    }
    markets = replace_named_markets(markets, player_markets, protected_player)
    print("    ✓ Players exact whitelist: " + ", ".join(
        f"{m['market']}={m['selection_count']}" for m in player_markets
    ) if player_markets else "    - Players exact whitelist returned no markets")

    scorer_markets, scorer_diag, scorer_text = capture_scorer_markets(page, url, home, away)
    protected_scorers = {"first_goalscorer", "anytime_scorer", "anytime_goalscorer", "scorer_2_plus", "to_score_2"}
    markets = replace_named_markets(markets, scorer_markets, protected_scorers)
    print("    scorer markets: " + ", ".join(
        f"{m['market']}={m['selection_count']}" for m in scorer_markets
    ) if scorer_markets else "    scorer markets: none")

    all_text = "=== POPULAR DEFAULT (NO CLICKS) ===\n" + popular_text
    if player_text:
        all_text += "\n\n=== PLAYER EXACT WHITELIST ===\n" + player_text
    if scorer_text:
        all_text += "\n\n=== SCORER MARKETS EXACT ===\n" + scorer_text

    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(all_text, encoding="utf-8")
    save_hits(debug_file, all_text)
    diag_path = DEBUG_DIR / f"{slugify(name)}_v11_diagnostics.json"
    diag_path.write_text(json.dumps({"player": player_diag, "scorers": scorer_diag}, indent=2, ensure_ascii=False), encoding="utf-8")

    warnings = player_market_warnings(markets)
    if scorer_diag.get("status") != "ok_both_team_panels":
        warnings.append(
            f"Away scorer team panel was not captured: {scorer_diag.get('status', 'unknown')}"
        )
    if identical_market_fingerprint(markets, "Player Fouls Committed", "Player Fouls Won"):
        warnings.append("Fouls Committed and Fouls Won are identical after exact-block parsing")

    player_keys = {
        "first_goalscorer", "anytime_scorer", "scorer_2_plus",
        "player_shots_on_target", "player_shots", "player_assists", "player_cards",
        "player_tackles", "player_fouls_committed", "player_fouls_won",
    }
    player_market_count = sum(1 for m in markets if normalize(m.get("normalized_market") or m.get("market")) in player_keys)
    player_selection_count = sum(m.get("selection_count", 0) for m in markets if normalize(m.get("normalized_market") or m.get("market")) in player_keys)
    elapsed = round(time.perf_counter() - started, 1)

    print(f"  ✓ {home} v {away} — {len(markets)} markets in {elapsed}s")
    print(f"    player coverage: {player_market_count} markets / {player_selection_count} selections")
    for market in markets:
        print(f"      {market['market']:<30} {market['selection_count']} selections")
    print_canonical_player_stat_samples(markets)
    for warning in warnings:
        print(f"    ! VALIDATION: {warning}")

    return {
        "match": f"{home} v {away}", "home_team": home, "away_team": away,
        "url": url, "url_source": fixture.get("url_source", ""),
        "captured_tabs": ["Popular/Default", player_diag.get("tab", ""), "Goals"],
        "player_price_mode": "impact_sub_default_no_mode_clicks",
        "capture_strategy": "v11_exact_whitelist_one_player_load",
        "diagnostics": str(diag_path), "market_count": len(markets),
        "player_market_count": player_market_count,
        "player_selection_count": player_selection_count,
        "elapsed_seconds": elapsed, "validation_warnings": warnings,
        "markets": markets,
    }


# ── V12 top-level Impact Sub tab workflow ───────────────────────────────────
# The William Hill event page has a real top market tab named "Impact Sub".
# This is different from the per-market Impact Sub / Enhanced Win toggle that
# broke V7. V12 clicks only the top tab strip once, then opens an exact market
# whitelist inside that tab. It never opens Player To Score A Header or Player
# Foul Involvements and never clicks a price-mode toggle.

V12_UNWANTED_HEADINGS = {
    normalize("Player To Score A Header"),
    normalize("To Score A Header"),
    normalize("Player Foul Involvements"),
    normalize("Foul Involvements"),
    normalize("Player To Score Or Assist"),
}


def click_top_impact_sub_tab(page):
    """Click only the top navigation tab named Impact Sub.

    The page can also contain per-market Impact Sub controls. We identify the
    top tab by requiring it to sit in the short horizontal strip that also
    contains Popular, Goals, Players, Cards and Corners.
    """
    try:
        page.evaluate("window.scrollTo(0,0); document.scrollingElement.scrollTop=0")
    except Exception:
        pass
    page.wait_for_timeout(350)

    js = r"""
        () => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 8 && r.height > 8 && r.bottom > 0 &&
                       r.top < window.innerHeight && st.display !== 'none' &&
                       st.visibility !== 'hidden';
            };
            const nodes = Array.from(document.querySelectorAll(
                'button,a,[role=tab],[role=button],div,span'
            )).filter(visible).filter(el => norm(el.innerText || el.textContent || '') === 'impact sub');

            const cands = [];
            for (const el of nodes) {
                const click = el.closest('button,a,[role=tab],[role=button]') || el;
                const r = click.getBoundingClientRect();
                if (r.width < 35 || r.width > 340 || r.height < 18 || r.height > 100) continue;

                let strip = null;
                let cur = click.parentElement;
                for (let d = 0; d < 8 && cur; d++, cur = cur.parentElement) {
                    const cr = cur.getBoundingClientRect();
                    const txt = norm(cur.innerText || cur.textContent || '');
                    if (cr.height <= 150 && cr.width >= 700 &&
                        txt.includes('popular') && txt.includes('goals') &&
                        txt.includes('players') && txt.includes('cards') &&
                        txt.includes('corners')) {
                        strip = cr;
                        break;
                    }
                }
                if (!strip) continue;

                let score = 10000;
                if (r.top >= 120 && r.top <= 560) score += 1000;
                score -= Math.abs(r.top - 360);
                cands.push({
                    x: r.left + r.width / 2,
                    y: r.top + r.height / 2,
                    top: r.top,
                    score,
                    ariaSelected: click.getAttribute('aria-selected') || '',
                    cls: String(click.className || '')
                });
            }
            cands.sort((a,b) => b.score - a.score);
            return cands[0] || null;
        }
    """
    try:
        point = page.evaluate(js)
        if not point:
            return False, {"status": "top_tab_not_found"}
        page.mouse.click(float(point["x"]), float(point["y"]))
        page.wait_for_timeout(2600)
        body = page.locator("body").inner_text(timeout=15000)
        exact = {normalize(x) for x in lines_from_text(body)}
        verified = normalize("Scorer Markets") in exact or any(
            normalize(h) in exact
            for aliases in V11_EXACT_PLAYER_HEADINGS.values()
            for h in aliases
        )
        return bool(verified), {
            "status": "clicked_verified" if verified else "clicked_unverified",
            "point": point,
        }
    except Exception as exc:
        return False, {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def v12_exact_block_text(text, aliases):
    blocks = v11_extract_exact_blocks(text, aliases)
    return "\n".join("\n".join(block) for block in blocks)


def v13_visible_scorer_block_text(page):
    """Return the current visible Scorer Markets block from the Impact Sub tab."""
    try:
        full_text = page.locator("body").inner_text(timeout=22000)
    except Exception:
        return ""
    block_text = v12_exact_block_text(full_text, ["Scorer Markets"])
    return block_text or full_text


def v14_scorer_signature(markets):
    """Return a stable set of scorer player names for panel-change verification."""
    players = set()
    for market in markets or []:
        for selection in market.get("selections", []):
            player = clean(selection.get("player") or "")
            if player:
                players.add(player.lower())
    return frozenset(players)


def v14_poll_scorer_panel_change(page, before_signature, attempts=20):
    """Wait until the visible scorer player list differs from the home panel."""
    last_parsed, last_text = [], ""
    for _ in range(attempts):
        page.wait_for_timeout(250)
        last_parsed, last_text = v13_parse_current_scorer_grid(page)
        signature = v14_scorer_signature(last_parsed)
        if signature and signature != before_signature:
            return True, last_parsed, last_text, signature
    return False, last_parsed, last_text, v14_scorer_signature(last_parsed)


def v14_find_exact_heading_box(page, heading="Scorer Markets"):
    boxes = []
    try:
        loc = page.get_by_text(heading, exact=True)
        for i in range(min(loc.count(), 20)):
            item = loc.nth(i)
            try:
                if not item.is_visible():
                    continue
                box = item.bounding_box()
                if not box or box["width"] < 30 or box["height"] < 10:
                    continue
                boxes.append((box["width"] * box["height"], box))
            except Exception:
                pass
    except Exception:
        pass
    boxes.sort(key=lambda x: x[0])
    return boxes[0][1] if boxes else None


def v14_click_exact_away_text(page, away, heading_box):
    """Use Playwright's real click on the exact visible away-team text node."""
    candidates = []
    try:
        loc = page.get_by_text(away, exact=True)
        for i in range(min(loc.count(), 30)):
            item = loc.nth(i)
            try:
                if not item.is_visible():
                    continue
                box = item.bounding_box()
                if not box:
                    continue
                if heading_box:
                    min_y = heading_box["y"] + heading_box["height"] - 20
                    max_y = heading_box["y"] + heading_box["height"] + 260
                    if box["y"] < min_y or box["y"] > max_y:
                        continue
                # The away selector is the right-hand team box.
                centre_x = box["x"] + box["width"] / 2
                score = centre_x * 10 + box["width"]
                candidates.append((score, item, box, i))
            except Exception:
                pass
    except Exception:
        pass

    candidates.sort(key=lambda x: x[0], reverse=True)
    for _, item, box, idx in candidates:
        try:
            item.scroll_into_view_if_needed(timeout=1500)
            page.wait_for_timeout(150)
            item.click(force=True, timeout=2500)
            return True, {
                "method": "playwright_exact_text_force",
                "locator_index": idx,
                "box": box,
                "candidate_count": len(candidates),
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return False, {
        "method": "playwright_exact_text_force",
        "candidate_count": len(candidates),
        "error": locals().get("last_error", "no_candidate"),
    }


def v14_click_away_parent_box(page, home, away):
    """Fallback: click the right scorer-team box ancestor, not just its text."""
    js = r"""
        ({home, away}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const H = norm(home), A = norm(away);
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 5 && r.height > 5 && r.bottom > 0 &&
                       r.top < window.innerHeight && st.display !== 'none' &&
                       st.visibility !== 'hidden';
            };
            const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,div,span'))
                .filter(el => visible(el) && norm(el.innerText || el.textContent || '') === 'scorer markets')
                .sort((a,b) => {
                    const ar=a.getBoundingClientRect(), br=b.getBoundingClientRect();
                    return (ar.width*ar.height)-(br.width*br.height);
                });
            if (!headings.length) return {status:'heading_not_found'};
            const hr = headings[0].getBoundingClientRect();
            const nodes = Array.from(document.querySelectorAll('button,[role=button],[role=tab],a,div,span'))
                .filter(el => visible(el) && norm(el.innerText || el.textContent || '') === A);
            const cands = [];
            for (const el of nodes) {
                const er = el.getBoundingClientRect();
                if (er.top < hr.bottom - 25 || er.top > hr.bottom + 260) continue;
                let cur = el;
                for (let d=0; d<8 && cur && cur!==document.body; d++, cur=cur.parentElement) {
                    if (!visible(cur)) continue;
                    const r = cur.getBoundingClientRect();
                    const txt = norm(cur.innerText || cur.textContent || '');
                    if (!txt.includes(A) || txt.includes(H)) continue;
                    if (r.width < 180 || r.width > 1100 || r.height < 28 || r.height > 130) continue;
                    if (r.top < hr.bottom - 25 || r.top > hr.bottom + 260) continue;
                    cands.push({
                        x:r.left+r.width/2, y:r.top+r.height/2,
                        left:r.left, top:r.top, width:r.width, height:r.height,
                        score:(r.left+r.width/2)*10+r.width,
                        tag:cur.tagName, role:cur.getAttribute('role')||'',
                        cls:String(cur.className||'').slice(0,240)
                    });
                }
            }
            cands.sort((a,b)=>b.score-a.score);
            return cands.length ? {status:'candidate', candidate:cands[0], count:cands.length} : {status:'not_found'};
        }
    """
    try:
        result = page.evaluate(js, {"home": home, "away": away})
        if not result or result.get("status") != "candidate":
            return False, {"method": "away_parent_box", "result": result}
        point = result["candidate"]
        page.mouse.click(float(point["x"]), float(point["y"]))
        return True, {
            "method": "away_parent_box",
            "candidate_count": result.get("count", 0),
            "candidate": point,
        }
    except Exception as exc:
        return False, {"method": "away_parent_box", "error": f"{type(exc).__name__}: {exc}"}


def v14_click_right_half_of_team_row(page, home, away):
    """Final fallback: find the row containing both team labels and click its right half."""
    js = r"""
        ({home, away}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const H=norm(home), A=norm(away);
            const visible=el=>{if(!el)return false;const r=el.getBoundingClientRect();const st=getComputedStyle(el);return r.width>5&&r.height>5&&r.bottom>0&&r.top<window.innerHeight&&st.display!=='none'&&st.visibility!=='hidden';};
            const headings=Array.from(document.querySelectorAll('h1,h2,h3,h4,div,span')).filter(el=>visible(el)&&norm(el.innerText||el.textContent||'')==='scorer markets').sort((a,b)=>{const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();return ar.width*ar.height-br.width*br.height;});
            if(!headings.length)return {status:'heading_not_found'};
            const hr=headings[0].getBoundingClientRect();
            const rows=[];
            for(const el of document.querySelectorAll('div,section,nav,[role=tablist]')){
                if(!visible(el))continue;
                const r=el.getBoundingClientRect();
                const txt=norm(el.innerText||el.textContent||'');
                if(!txt.includes(H)||!txt.includes(A))continue;
                if(r.top<hr.bottom-25||r.top>hr.bottom+260)continue;
                if(r.width<600||r.height<35||r.height>150)continue;
                rows.push({x:r.left+r.width*.75,y:r.top+r.height/2,left:r.left,top:r.top,width:r.width,height:r.height,score:r.width-r.height*5});
            }
            rows.sort((a,b)=>b.score-a.score);
            return rows.length?{status:'candidate',candidate:rows[0],count:rows.length}:{status:'not_found'};
        }
    """
    try:
        result = page.evaluate(js, {"home": home, "away": away})
        if not result or result.get("status") != "candidate":
            return False, {"method": "right_half_team_row", "result": result}
        point = result["candidate"]
        page.mouse.click(float(point["x"]), float(point["y"]))
        return True, {
            "method": "right_half_team_row",
            "candidate_count": result.get("count", 0),
            "candidate": point,
        }
    except Exception as exc:
        return False, {"method": "right_half_team_row", "error": f"{type(exc).__name__}: {exc}"}



def scroll_heading_into_view(page, heading):
    """Scroll an exact visible market heading into the centre of the viewport.

    This helper only scrolls. It does not click or change a market.
    """
    js = r"""
        (heading) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const target = norm(heading);

            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 5 && r.height > 5 &&
                       st.display !== 'none' &&
                       st.visibility !== 'hidden';
            };

            const nodes = Array.from(
                document.querySelectorAll(
                    'h1,h2,h3,h4,h5,button,[role=button],[role=tab],div,span,p'
                )
            );

            const candidates = nodes
                .filter(el => visible(el))
                .map(el => {
                    const txt = norm(el.innerText || el.textContent || '');
                    const r = el.getBoundingClientRect();
                    return {
                        el,
                        txt,
                        area: r.width * r.height
                    };
                })
                .filter(x => x.txt === target)
                .sort((a, b) => a.area - b.area);

            if (!candidates.length) {
                return {found: false};
            }

            const el = candidates[0].el;
            try {
                el.scrollIntoView({behavior: 'instant', block: 'center', inline: 'nearest'});
            } catch (_) {
                el.scrollIntoView({block: 'center', inline: 'nearest'});
            }

            const r = el.getBoundingClientRect();
            return {
                found: true,
                text: (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim(),
                top: r.top,
                left: r.left,
                width: r.width,
                height: r.height
            };
        }
    """
    try:
        result = page.evaluate(js, heading)
        page.wait_for_timeout(250)
        return bool(result and result.get("found"))
    except Exception:
        return False


def v14_switch_to_away_scorer_panel(page, home, away, home_signature):
    """Try three increasingly broad click methods and require new player names."""
    set_accordion_open(page, ["Scorer Markets"], True)
    scroll_heading_into_view(page, "Scorer Markets")
    page.wait_for_timeout(300)
    heading_box = v14_find_exact_heading_box(page)
    attempts = []

    methods = [
        lambda: v14_click_exact_away_text(page, away, heading_box),
        lambda: v14_click_away_parent_box(page, home, away),
        lambda: v14_click_right_half_of_team_row(page, home, away),
    ]

    for method in methods:
        clicked, click_diag = method()
        attempts.append(click_diag)
        if not clicked:
            continue
        changed, parsed, text, signature = v14_poll_scorer_panel_change(page, home_signature)
        attempts[-1]["verified_grid_change"] = changed
        attempts[-1]["parsed_player_count"] = len(signature)
        if changed:
            return True, parsed, text, {
                "status": "away_panel_verified",
                "successful_method": click_diag.get("method", "unknown"),
                "attempts": attempts,
            }

    parsed, text = v13_parse_current_scorer_grid(page)
    return False, parsed, text, {
        "status": "away_panel_failed",
        "attempts": attempts,
        "final_player_count": len(v14_scorer_signature(parsed)),
    }

def v13_parse_current_scorer_grid(page):
    text = v13_visible_scorer_block_text(page)
    parsed = v11_parse_flexible_scorer_grid(text)
    if not parsed:
        parsed = parse_scorer_grid_three_markets(text)
    return parsed, text


def v12_capture_scorers_on_impact_tab(page, home, away):
    """Capture First, Anytime and 2+ from both Impact Sub scorer panels."""
    heading, state = v11_open_first_exact(page, ["Scorer Markets"])
    combined = {key: [] for key in SCORER_MARKET_NAMES}
    dumps = []
    team_results = []

    if not heading:
        return [], {
            "status": "scorer_markets_not_found",
            "heading_state": state,
        }, ""

    set_accordion_open(page, ["Scorer Markets"], True)
    click_all_see_more(page, max_clicks=8)
    page.wait_for_timeout(350)

    home_parsed, home_text = v13_parse_current_scorer_grid(page)
    home_signature = v14_scorer_signature(home_parsed)
    home_counts = {m["normalized_market"]: m["selection_count"] for m in home_parsed}
    team_results.append({
        "team": home,
        "panel": "default_left",
        "clicked": False,
        "status": "parsed_default_panel",
        "unique_players": len(home_signature),
        "counts": home_counts,
    })
    dumps.append(f"=== IMPACT SUB SCORER TEAM {home} default-left ===\n{home_text}")
    for market in home_parsed:
        key = normalize(market.get("normalized_market") or market.get("market"))
        if key in combined:
            for selection in market.get("selections", []):
                selection = dict(selection)
                selection["source_team_panel"] = home
                combined[key].append(selection)

    away_changed, away_parsed, away_text, away_diag = v14_switch_to_away_scorer_panel(
        page, home, away, home_signature
    )
    if away_changed:
        click_all_see_more(page, max_clicks=8)
        page.wait_for_timeout(250)
        # Re-read after any Show More expansion on the verified away panel.
        away_parsed, away_text = v13_parse_current_scorer_grid(page)

    away_signature = v14_scorer_signature(away_parsed) if away_changed else frozenset()
    away_counts = {
        m["normalized_market"]: m["selection_count"] for m in away_parsed
    } if away_changed else {}
    team_results.append({
        "team": away,
        "panel": "right",
        "clicked": away_changed,
        "status": away_diag.get("status", ""),
        "unique_players": len(away_signature),
        "click_diagnostics": away_diag,
        "counts": away_counts,
    })
    dumps.append(
        f"=== IMPACT SUB SCORER TEAM {away} changed={away_changed} "
        f"diag={away_diag} ===\n{away_text}"
    )

    if away_changed:
        for market in away_parsed:
            key = normalize(market.get("normalized_market") or market.get("market"))
            if key in combined:
                for selection in market.get("selections", []):
                    selection = dict(selection)
                    selection["source_team_panel"] = away
                    combined[key].append(selection)

    markets = []
    for key, name in SCORER_MARKET_NAMES.items():
        market = mkt(name, combined[key])
        market["normalized_market"] = key
        if market["selection_count"]:
            markets.append(market)

    home_total = sum(home_counts.values())
    away_total = sum(away_counts.values())
    status = "ok_both_team_panels" if away_changed and away_total else "away_team_panel_failed"

    print(
        f"    scorer panels: {home}={len(home_signature)} players, "
        f"{away}={len(away_signature)} players, status={status}"
    )
    if not away_changed:
        print(f"    ! scorer away-panel diagnostics: {away_diag}")

    return markets, {
        "status": status,
        "heading": heading,
        "heading_state": state,
        "home_total": home_total,
        "away_total": away_total,
        "home_unique_players": len(home_signature),
        "away_unique_players": len(away_signature),
        "teams": team_results,
    }, "\n\n".join(dumps)

def v12_parse_optional_exact_market(text, aliases, key):
    combined = []
    for block in v11_extract_exact_blocks(text, aliases):
        lines = lines_from_text("\n".join(block))
        try:
            market = parse_player_market(lines, key)
            combined.extend(market.get("selections", []))
        except Exception:
            pass
    return mkt(MARKET_META[key][0], combined)


def v12_capture_player_markets_on_impact_tab(page):
    """Open and parse only wanted player markets inside the Impact Sub tab."""
    opened = {}
    for key, aliases in V11_EXACT_PLAYER_HEADINGS.items():
        heading, state = v11_open_first_exact(page, aliases)
        opened[key] = {"heading": heading, "state": state}

    optional_specs = [
        ("player_cards", ["Player Shown A Card", "Player Cards", "Player To Be Carded"]),
        ("player_assists", ["Player Assists", "Player To Assist"]),
    ]
    optional_opened = {}
    for key, aliases in optional_specs:
        heading, state = v11_open_first_exact(page, aliases)
        optional_opened[key] = {"heading": heading, "state": state}

    # Only expanded whitelisted accordions expose Show More controls. No broad
    # heading click is used anywhere in V12.
    click_all_see_more(page, max_clicks=24)
    scroll_page(page, 4)
    text = page.locator("body").inner_text(timeout=26000)

    markets = []
    for key in V11_EXACT_PLAYER_HEADINGS:
        market = parse_isolated_stat_capture(text, key)
        if market.get("selection_count", 0):
            markets.append(market)

    for key, aliases in optional_specs:
        market = v12_parse_optional_exact_market(text, aliases, key)
        if market.get("selection_count", 0):
            markets.append(market)

    exact_lines = {normalize(x) for x in lines_from_text(text)}
    unwanted_present = sorted(x for x in V12_UNWANTED_HEADINGS if x in exact_lines)
    return markets, {
        "status": "ok",
        "opened": opened,
        "optional_opened": optional_opened,
        "unwanted_headings_present_but_not_clicked": unwanted_present,
        "selection_counts": {
            normalize(m.get("normalized_market") or m.get("market")): m.get("selection_count", 0)
            for m in markets
        },
    }, text


def scrape_match(page, fixture):
    """V12: one default capture, then one top-level Impact Sub tab capture."""
    url = fixture["url"]
    name = fixture["name"]
    print(f"  Scraping: {name}")
    print(f"  URL: {url}")
    print(f"  URL source: {fixture.get('url_source', 'unknown')}")

    hint_home = canonical_team(clean(fixture.get("home") or ""))
    hint_away = canonical_team(clean(fixture.get("away") or ""))
    if (not hint_home or not hint_away) and " v " in name:
        hint_home, hint_away = [canonical_team(clean(x)) for x in name.split(" v ", 1)]

    started = time.perf_counter()
    fresh_event_page(page, url)
    if hint_home and hint_away and not page_has_fixture(page, hint_home, hint_away):
        raise RuntimeError(f"Cached URL did not load expected fixture: {name}")

    # Keep the quick no-click default capture for core match markets only.
    popular_text = page.locator("body").inner_text(timeout=20000)
    home, away = detect_teams(popular_text, name)
    home = home or hint_home
    away = away or hint_away
    player_and_scorer_keys = {
        "first_goalscorer", "anytime_scorer", "anytime_goalscorer", "scorer_2_plus", "to_score_2",
        "player_shots_on_target", "player_shots", "player_tackles",
        "player_fouls_committed", "player_fouls_won", "player_cards", "player_assists",
    }
    markets = []
    if home and away:
        for market in parse_all(popular_text, home, away):
            key = normalize(market.get("normalized_market") or market.get("market"))
            if key not in player_and_scorer_keys and market.get("selection_count", 0):
                markets.append(market)
    print("    ✓ Popular/Default captured with 0 market clicks")

    tab_ok, tab_diag = click_top_impact_sub_tab(page)
    if not tab_ok:
        raise RuntimeError(f"Could not verify top-level Impact Sub tab: {tab_diag}")
    print("    ✓ Top-level Impact Sub tab selected")

    # Scorer grid first while it is near the top of the Impact Sub page.
    scorer_markets, scorer_diag, scorer_text = v12_capture_scorers_on_impact_tab(page, home, away)
    markets = replace_named_markets(
        markets, scorer_markets,
        {"first_goalscorer", "anytime_scorer", "anytime_goalscorer", "scorer_2_plus", "to_score_2"},
    )
    print("    scorer markets: " + ", ".join(
        f"{m['market']}={m['selection_count']}" for m in scorer_markets
    ) if scorer_markets else "    scorer markets: none")

    player_markets, player_diag, player_text = v12_capture_player_markets_on_impact_tab(page)
    markets = replace_named_markets(
        markets, player_markets,
        {"player_shots_on_target", "player_shots", "player_tackles",
         "player_fouls_committed", "player_fouls_won", "player_cards", "player_assists"},
    )
    print("    Impact Sub exact player whitelist: " + ", ".join(
        f"{m['market']}={m['selection_count']}" for m in player_markets
    ) if player_markets else "    Impact Sub exact player whitelist returned no markets")
    print("    excluded headings clicked: 0")

    # William Hill keeps these two wanted ladders on the separate Players tab.
    players_extra_markets, players_extra_diag, players_extra_text = (
        v16_capture_players_tab_shots_tackles(page)
    )
    markets = replace_named_markets(
        markets,
        players_extra_markets,
        {"player_shots", "player_tackles"},
    )
    if players_extra_markets:
        print("    Players exact add-on: " + ", ".join(
            f"{m['market']}={m['selection_count']}"
            for m in players_extra_markets
        ))
    else:
        print(
            "    Players exact add-on returned no Player Shots or Player Tackles "
            f"({players_extra_diag.get('status', 'unknown')})"
        )
    print("    Players excluded headings clicked: 0")

    all_text = "=== POPULAR DEFAULT (NO CLICKS) ===\n" + popular_text
    if scorer_text:
        all_text += "\n\n=== TOP IMPACT SUB — SCORER MARKETS ===\n" + scorer_text
    if player_text:
        all_text += "\n\n=== TOP IMPACT SUB — EXACT PLAYER WHITELIST ===\n" + player_text
    if players_extra_text:
        all_text += (
            "\n\n=== PLAYERS TAB — EXACT TOTAL PLAYER SHOTS + "
            "TOTAL PLAYER TACKLES ===\n" + players_extra_text
        )

    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(all_text, encoding="utf-8")
    save_hits(debug_file, all_text)
    diag_path = DEBUG_DIR / f"{slugify(name)}_v12_diagnostics.json"
    diag_path.write_text(json.dumps({
        "top_impact_sub_tab": tab_diag,
        "scorers": scorer_diag,
        "impact_sub_players": player_diag,
        "players_tab_shots_tackles": players_extra_diag,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    warnings = player_market_warnings(markets)
    if identical_market_fingerprint(markets, "Player Fouls Committed", "Player Fouls Won"):
        warnings.append("Fouls Committed and Fouls Won are identical on top Impact Sub tab")
    scorer_norms = {normalize(m.get("normalized_market") or m.get("market")) for m in markets}
    for required in ["first_goalscorer", "anytime_scorer", "scorer_2_plus"]:
        if required not in scorer_norms:
            warnings.append(f"Missing scorer market: {required}")

    for required, label in [
        ("player_shots", "Player Shots"),
        ("player_tackles", "Player Tackles"),
    ]:
        if required not in scorer_norms:
            warnings.append(f"Missing Players-tab market: {label}")

    player_keys = {
        "first_goalscorer", "anytime_scorer", "scorer_2_plus",
        "player_shots_on_target", "player_shots", "player_assists", "player_cards",
        "player_tackles", "player_fouls_committed", "player_fouls_won",
    }
    player_market_count = sum(
        1 for m in markets
        if normalize(m.get("normalized_market") or m.get("market")) in player_keys
    )
    player_selection_count = sum(
        m.get("selection_count", 0) for m in markets
        if normalize(m.get("normalized_market") or m.get("market")) in player_keys
    )
    elapsed = round(time.perf_counter() - started, 1)

    print(f"  ✓ {home} v {away} — {len(markets)} markets in {elapsed}s")
    print(f"    player coverage: {player_market_count} markets / {player_selection_count} selections")
    for market in markets:
        print(f"      {market['market']:<30} {market['selection_count']} selections")
    print_canonical_player_stat_samples(markets)
    for warning in warnings:
        print(f"    ! VALIDATION: {warning}")

    return {
        "match": f"{home} v {away}",
        "home_team": home,
        "away_team": away,
        "url": url,
        "url_source": fixture.get("url_source", ""),
        "captured_tabs": ["Popular/Default", "Impact Sub", "Players"],
        "player_price_mode": "top_level_impact_sub_tab",
        "capture_strategy": "v16_v15_impact_sub_plus_exact_players_shots_tackles",
        "diagnostics": str(diag_path),
        "market_count": len(markets),
        "player_market_count": player_market_count,
        "player_selection_count": player_selection_count,
        "elapsed_seconds": elapsed,
        "validation_warnings": warnings,
        "markets": markets,
    }

def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("William Hill World Cup Props Scraper — FAST TEST3 V16 PLAYERS SHOTS + TACKLES")
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
        "player_price_mode": "top_level_impact_sub_tab",
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
