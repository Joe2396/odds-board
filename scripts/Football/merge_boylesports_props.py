#!/usr/bin/env python3

import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "boylesports_worldcup_props.json"
STATS_PATH = ROOT / "football" / "data" / "boylesports_stats_props.json"
OUT_PATH = ROOT / "football" / "data" / "boylesports_worldcup_props_complete.json"


def flatten_goalscorers(markets: dict) -> None:
    """
    Boyle goalscorers is nested:
      goalscorers -> selections -> first / anytime / two_plus / three_plus

    Generator expects a normal flat market:
      anytime_scorer -> selections: [{selection, odds}]
    """
    gs = markets.get("goalscorers")
    if not isinstance(gs, dict):
        return

    selections = gs.get("selections")
    if not isinstance(selections, dict):
        return

    anytime = selections.get("anytime") or []
    if not isinstance(anytime, list) or not anytime:
        return

    flat = []

    for item in anytime:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        price = str(item.get("price", "")).strip()

        if not name or not price:
            continue

        if name.lower() in {"no goalscorer", "own goal"}:
            continue

        flat.append({
            "selection": f"Anytime Goalscorer {name}",
            "odds": price,
            "player": name,
            "prop_type": "anytime_scorer",
        })

    if flat:
        markets["anytime_scorer"] = {
            "market": "Anytime Goalscorer",
            "label": "Anytime Goalscorer",
            "selections": flat,
        }


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

        # Flatten Boyle goalscorers into a generator-friendly market
        flatten_goalscorers(markets)

        # Add stats markets
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

    # Quick confirmation
    sample = next((m for m in merged_matches if m.get("match") == "Brazil v Morocco"), None)
    if sample:
        markets = sample.get("markets", {})
        ag = markets.get("anytime_scorer", {}).get("selections", [])
        print(f"✅ Brazil v Morocco anytime_scorer -> {len(ag)} selections")


if __name__ == "__main__":
    main()