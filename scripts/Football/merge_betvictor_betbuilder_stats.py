#!/usr/bin/env python3
"""
merge_betvictor_betbuilder_stats.py

Merges football/data/betvictor_worldcup_betbuilder_stats.json
into football/data/betvictor_worldcup_props.json.

Replaces any existing markets with the same normalized_market.
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
STATS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_betbuilder_stats.json"
BACKUP_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.before_betbuilder_merge.json"


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def norm(s):
    return re.sub(r"[^a-z0-9]+", "_", clean(s).lower().replace("&", "and")).strip("_")


def match_key(m):
    home = clean(m.get("home_team", ""))
    away = clean(m.get("away_team", ""))
    match = clean(m.get("match", ""))
    if home and away:
        return tuple(sorted([norm(home), norm(away)]))
    if " v " in match:
        a, b = match.split(" v ", 1)
        return tuple(sorted([norm(a), norm(b)]))
    return (norm(match),)


def main():
    props = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))

    if not BACKUP_PATH.exists():
        BACKUP_PATH.write_text(json.dumps(props, indent=2, ensure_ascii=False), encoding="utf-8")

    props_matches = props.get("matches", [])
    by_key = {match_key(m): m for m in props_matches}

    merged_matches = 0
    merged_markets = 0

    for sm in stats.get("matches", []):
        if sm.get("market_count", 0) <= 0:
            continue

        key = match_key(sm)
        pm = by_key.get(key)

        if not pm:
            props_matches.append({
                "match": sm.get("match"),
                "home_team": sm.get("home_team"),
                "away_team": sm.get("away_team"),
                "source_url": sm.get("source_url"),
                "market_count": 0,
                "markets": [],
            })
            pm = props_matches[-1]
            by_key[key] = pm

        existing = {m.get("normalized_market"): m for m in pm.get("markets", [])}
        for market in sm.get("markets", []):
            existing[market.get("normalized_market")] = market
            merged_markets += 1

        pm["markets"] = list(existing.values())
        pm["market_count"] = len(pm["markets"])
        merged_matches += 1

    props["matches"] = props_matches
    props["match_count"] = len(props_matches)
    props["matches_with_markets"] = len([m for m in props_matches if m.get("market_count", 0) > 0])
    props["betbuilder_stats_merged_at"] = datetime.now(timezone.utc).isoformat()

    PROPS_PATH.write_text(json.dumps(props, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Merged BetVictor Bet Builder stats into: {PROPS_PATH}")
    print(f"Backup: {BACKUP_PATH}")
    print(f"Matches updated: {merged_matches}")
    print(f"Markets merged/replaced: {merged_markets}")


if __name__ == "__main__":
    main()
