#!/usr/bin/env python3
"""
merge_betvictor_player_tackles.py

Safely replaces BetVictor Player Tackles with the latest exact DOM-row scrape.

Important behaviour:
- removes every old/stale BetVictor player_tackles market first;
- adds back only the exact markets present in betvictor_player_tackles.json;
- prevents finished/unavailable fixtures from retaining the old broken or
  incomplete tackle table;
- creates a backup before modifying the main BetVictor props JSON.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
TACKLES_PATH = ROOT / "football" / "data" / "betvictor_player_tackles.json"
BACKUP_PATH = (
    ROOT
    / "football"
    / "data"
    / "betvictor_worldcup_props.before_player_tackles_merge.json"
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def is_player_tackles(market):
    key = normalize(
        market.get("normalized_market")
        or market.get("market")
    )
    return key == "player_tackles"


def main():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing: {PROPS_PATH}")

    if not TACKLES_PATH.exists():
        raise SystemExit(f"Missing: {TACKLES_PATH}")

    props = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    tackles = json.loads(TACKLES_PATH.read_text(encoding="utf-8"))

    BACKUP_PATH.write_text(
        json.dumps(props, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    exact_by_match = {}

    for match in tackles.get("matches", []):
        markets = match.get("markets", [])
        if not markets:
            continue

        exact_market = next(
            (
                market
                for market in markets
                if is_player_tackles(market)
            ),
            None,
        )

        if exact_market:
            exact_by_match[normalize(match.get("match"))] = exact_market

    stale_markets_removed = 0
    matches_with_stale_removed = 0
    matches_updated = 0
    selections_merged = 0
    unmatched_exact = set(exact_by_match)

    for match in props.get("matches", []):
        old_markets = match.get("markets", [])
        kept_markets = [
            market
            for market in old_markets
            if not is_player_tackles(market)
        ]

        removed_here = len(old_markets) - len(kept_markets)

        if removed_here:
            stale_markets_removed += removed_here
            matches_with_stale_removed += 1

        match_key = normalize(match.get("match"))
        exact_market = exact_by_match.get(match_key)

        if exact_market:
            kept_markets.append(exact_market)
            matches_updated += 1
            selections_merged += exact_market.get(
                "selection_count",
                len(exact_market.get("selections", [])),
            )
            unmatched_exact.discard(match_key)

        match["markets"] = kept_markets
        match["market_count"] = len(kept_markets)

    now = datetime.now(timezone.utc).isoformat()
    props["generated_at"] = now
    props["betvictor_player_tackles_merged_at"] = now

    PROPS_PATH.write_text(
        json.dumps(props, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Merged exact BetVictor tackles into: {PROPS_PATH}")
    print(f"Backup: {BACKUP_PATH}")
    print(f"Old/stale tackle markets removed: {stale_markets_removed}")
    print(f"Matches cleaned: {matches_with_stale_removed}")
    print(f"Matches receiving exact tackles: {matches_updated}")
    print(f"Exact tackle selections merged: {selections_merged}")

    if unmatched_exact:
        print("WARNING — exact tackle fixtures missing from main props JSON:")
        for key in sorted(unmatched_exact):
            print(f"  {key}")


if __name__ == "__main__":
    main()
