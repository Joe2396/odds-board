#!/usr/bin/env python3
"""
test_betvictor_player_tackles.py

Read-only test parser for BetVictor Player Tackles.

Why this exists:
The current generic table parser scans too far ahead and can assign odds from
later player rows to the current player. That creates repeated fake columns,
for example the same 1+/2+/3+ prices for several different players.

This test parser only accepts BetVictor's exact embedded rows:
    Nahuel Molina 3+ Tackles
    17/20

It does NOT modify betvictor_worldcup_props.json.

Output:
    football/data/betvictor_player_tackles_TEST.json
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_worldcup_props"
OUT_PATH = ROOT / "football" / "data" / "betvictor_player_tackles_TEST.json"

MAX_MATCHES = 3
PRIORITY_MATCHES = ["Argentina v Austria"]

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN)$", re.I)
TACKLE_ROW_RE = re.compile(
    r"^(.+?)\s+(\d+)\+\s+Tackles?(?:\s+90\s*Mins)?$",
    re.I,
)

BAD_PLAYER_STARTS = (
    "match ",
    "player ",
    "to have ",
    "home ",
    "away ",
    "over ",
    "under ",
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def slugify(value):
    return normalize(value).replace("_", "-")


def is_odds(value):
    return bool(ODDS_RE.match(clean(value)))


def load_props():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing: {PROPS_PATH}")
    return json.loads(PROPS_PATH.read_text(encoding="utf-8"))


def choose_debug_file(match_name):
    folder = DEBUG_ROOT / slugify(match_name)
    candidates = [
        folder / "player.txt",
        folder / "ALL_GROUPS.txt",
        folder / "HITS.txt",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def next_row_odds(lines, start_index):
    """
    Look only a few non-empty lines ahead.
    Stop immediately if another tackle row begins before an odd appears.
    """
    checked = 0

    for index in range(start_index + 1, min(start_index + 8, len(lines))):
        token = clean(lines[index])
        if not token:
            continue

        if TACKLE_ROW_RE.match(token):
            return None

        checked += 1

        if is_odds(token):
            return token.upper()

        if checked >= 3:
            return None

    return None


def parse_tackles(text, home, away):
    lines = [clean(line) for line in text.splitlines() if clean(line)]
    found = {}

    blocked_names = {
        clean(home).lower(),
        clean(away).lower(),
        "argentina",
        "austria",
    }

    for index, row in enumerate(lines):
        match = TACKLE_ROW_RE.match(row)
        if not match:
            continue

        player = clean(match.group(1))
        threshold_number = int(match.group(2))
        threshold = f"{threshold_number}+"
        player_low = player.lower()

        if not player or len(player) < 3 or len(player) > 70:
            continue
        if player_low in blocked_names:
            continue
        if player_low.startswith(BAD_PLAYER_STARTS):
            continue
        if any(word in player_low for word in (" shots", " offsides", " corners")):
            continue

        odds = next_row_odds(lines, index)
        if not odds:
            continue

        key = (normalize(player), threshold)

        # Keep the first exact row found. Do not manufacture missing thresholds.
        if key not in found:
            found[key] = {
                "selection": f"{player} {threshold} Tackles",
                "normalized_selection": normalize(
                    f"{player} {threshold} Tackles"
                ),
                "odds": odds,
                "player": player,
                "threshold": threshold,
                "prop_type": "tackles",
            }

    selections = sorted(
        found.values(),
        key=lambda item: (
            normalize(item["player"]),
            int(item["threshold"].rstrip("+")),
        ),
    )

    return {
        "market": "Player Tackles",
        "normalized_market": "player_tackles",
        "selection_count": len(selections),
        "selections": selections,
    }


def select_matches(data):
    matches = data.get("matches", [])
    by_name = {clean(match.get("match")): match for match in matches}
    selected = []

    for name in PRIORITY_MATCHES:
        if name in by_name:
            selected.append(by_name[name])

    for match in matches:
        if len(selected) >= MAX_MATCHES:
            break
        if match not in selected:
            selected.append(match)

    return selected[:MAX_MATCHES]


def main():
    data = load_props()
    results = []

    print("BETVICTOR PLAYER TACKLES — SAFE TEST PARSER")
    print("=" * 72)

    for match_data in select_matches(data):
        match_name = clean(match_data.get("match"))
        home = clean(match_data.get("home_team"))
        away = clean(match_data.get("away_team"))
        debug_file = choose_debug_file(match_name)

        print(f"\n{match_name}")
        print(f"  Debug: {debug_file}")

        if not debug_file.exists():
            print("  MISSING DEBUG FILE")
            results.append(
                {
                    "match": match_name,
                    "home_team": home,
                    "away_team": away,
                    "debug_file": str(debug_file),
                    "market_count": 0,
                    "markets": [],
                    "error": "debug_file_missing",
                }
            )
            continue

        text = debug_file.read_text(encoding="utf-8", errors="replace")
        market = parse_tackles(text, home, away)

        print(f"  selections: {market['selection_count']}")
        for selection in market["selections"]:
            print(
                f"    {selection['player']:<28} "
                f"{selection['threshold']:<3} {selection['odds']}"
            )

        results.append(
            {
                "match": match_name,
                "home_team": home,
                "away_team": away,
                "debug_file": str(debug_file),
                "market_count": 1 if market["selection_count"] else 0,
                "markets": [market] if market["selection_count"] else [],
            }
        )

    output = {
        "bookmaker": "BetVictor",
        "market_type": "player_tackles_test",
        "max_matches": MAX_MATCHES,
        "match_count": len(results),
        "matches": results,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print(f"Saved read-only test output: {OUT_PATH}")
    print("The main BetVictor props JSON was NOT changed.")


if __name__ == "__main__":
    main()
