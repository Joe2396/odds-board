#!/usr/bin/env python3

import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "boylesports_worldcup_props.json"
STATS_PATH = ROOT / "football" / "data" / "boylesports_stats_props.json"

OUT_PATH = ROOT / "football" / "data" / "boylesports_worldcup_props_complete.json"


def main():

    with open(PROPS_PATH, "r", encoding="utf-8") as f:
        props_data = json.load(f)

    with open(STATS_PATH, "r", encoding="utf-8") as f:
        stats_data = json.load(f)

    stats_lookup = {}

    for match in stats_data.get("matches", []):
        stats_lookup[match["match"]] = match.get("markets", {})

    merged_matches = []

    for match in props_data.get("matches", []):

        match_name = match.get("match", "")

        markets = dict(match.get("markets", {}))

        stats_markets = stats_lookup.get(match_name, {})

        for market_name, market_data in stats_markets.items():
            markets[market_name] = market_data

        merged_match = dict(match)
        merged_match["markets"] = markets

        merged_matches.append(merged_match)

    output = {
        "bookmaker": "BoyleSports",
        "competition": "World Cup 2026",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(merged_matches),
        "matches": merged_matches,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print()
    print(f"✅ Saved -> {OUT_PATH}")
    print(f"✅ Matches -> {len(merged_matches)}")


if __name__ == "__main__":
    main()








































