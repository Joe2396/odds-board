#!/usr/bin/env python3
"""
merge_unibet_shots_cards.py

Merges the corrected Unibet player market file:

  football/data/unibet_worldcup_shots_cards.json

into the main Unibet props file:

  football/data/unibet_worldcup_props.json

It replaces ONLY these markets:
  - Player Shots
  - Player Shots On Target
  - Player Cards
  - Player Assists

Everything else in unibet_worldcup_props.json is kept unchanged.
A backup is written before overwrite.
"""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MAIN_PATH = ROOT / "football" / "data" / "unibet_worldcup_props.json"
FIX_PATH = ROOT / "football" / "data" / "unibet_worldcup_shots_cards.json"

REPLACE_MARKETS = {
    "Player Shots",
    "Player Shots On Target",
    "Player Cards",
    "Player Assists",
}


def load_json(path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def market_key(market):
    return market.get("market", "").strip()


def main():
    main_data = load_json(MAIN_PATH)
    fix_data = load_json(FIX_PATH)

    backup_path = MAIN_PATH.with_suffix(
        MAIN_PATH.suffix + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    backup_path.write_text(json.dumps(main_data, indent=2, ensure_ascii=False), encoding="utf-8")

    fix_by_match = {
        m.get("match", "").strip(): m
        for m in fix_data.get("matches", [])
        if m.get("match")
    }

    updated_matches = 0
    replaced_total = 0

    for match in main_data.get("matches", []):
        name = match.get("match", "").strip()
        fix_match = fix_by_match.get(name)
        if not fix_match:
            continue

        fixed_markets = {
            market_key(m): m
            for m in fix_match.get("markets", [])
            if market_key(m) in REPLACE_MARKETS
        }

        if not fixed_markets:
            continue

        kept = [
            m for m in match.get("markets", [])
            if market_key(m) not in REPLACE_MARKETS
        ]

        # Keep stable ordering: old markets first, corrected player markets at the end.
        for wanted in ["Player Shots On Target", "Player Shots", "Player Cards", "Player Assists"]:
            if wanted in fixed_markets:
                kept.append(fixed_markets[wanted])
                replaced_total += 1

        match["markets"] = kept
        match["market_count"] = len(kept)
        updated_matches += 1

    main_data["matches_with_markets"] = len(
        [m for m in main_data.get("matches", []) if m.get("market_count", 0) > 0]
    )

    MAIN_PATH.write_text(json.dumps(main_data, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Merged corrected Unibet player markets.")
    print(f"Backup written: {backup_path}")
    print(f"Matches updated: {updated_matches}")
    print(f"Markets replaced: {replaced_total}")
    print(f"Wrote: {MAIN_PATH}")


if __name__ == "__main__":
    main()
