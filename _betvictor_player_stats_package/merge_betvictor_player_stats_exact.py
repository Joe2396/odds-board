#!/usr/bin/env python3
"""
merge_betvictor_player_stats_exact.py

Cleanly replaces BetVictor's old broken:
- player_shots_on_target
- player_shots
- player_fouls / player_fouls_committed

with the exact DOM-row markets from betvictor_player_stats_exact.json.

A backup is created before modifying the main props JSON.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
EXACT_PATH = ROOT / "football" / "data" / "betvictor_player_stats_exact.json"
BACKUP_PATH = (
    ROOT
    / "football"
    / "data"
    / "betvictor_worldcup_props.before_exact_player_stats_merge.json"
)

REPLACE_KEYS = {
    "player_shots_on_target",
    "player_shots",
    "player_fouls",
    "player_fouls_committed",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def market_key(market):
    return normalize(
        market.get("normalized_market")
        or market.get("market")
    )


def main():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing: {PROPS_PATH}")
    if not EXACT_PATH.exists():
        raise SystemExit(f"Missing: {EXACT_PATH}")

    props = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    exact = json.loads(EXACT_PATH.read_text(encoding="utf-8"))

    BACKUP_PATH.write_text(
        json.dumps(props, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    exact_by_match = {
        normalize(match.get("match")): [
            market
            for market in match.get("markets", [])
            if market_key(market) in {
                "player_shots_on_target",
                "player_shots",
                "player_fouls_committed",
            }
        ]
        for match in exact.get("matches", [])
    }

    removed = 0
    matches_updated = 0
    markets_added = 0
    selections_added = 0

    for match in props.get("matches", []):
        old_markets = match.get("markets", [])
        kept = [
            market
            for market in old_markets
            if market_key(market) not in REPLACE_KEYS
        ]

        removed += len(old_markets) - len(kept)

        new_markets = exact_by_match.get(normalize(match.get("match")), [])

        if new_markets:
            kept.extend(new_markets)
            matches_updated += 1
            markets_added += len(new_markets)
            selections_added += sum(
                market.get(
                    "selection_count",
                    len(market.get("selections", [])),
                )
                for market in new_markets
            )

        match["markets"] = kept
        match["market_count"] = len(kept)

    now = datetime.now(timezone.utc).isoformat()
    props["generated_at"] = now
    props["betvictor_exact_player_stats_merged_at"] = now

    PROPS_PATH.write_text(
        json.dumps(props, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Merged exact BetVictor player stats into: {PROPS_PATH}")
    print(f"Backup: {BACKUP_PATH}")
    print(f"Old broken markets removed: {removed}")
    print(f"Matches updated: {matches_updated}")
    print(f"Exact markets added: {markets_added}")
    print(f"Exact selections added: {selections_added}")


if __name__ == "__main__":
    main()
