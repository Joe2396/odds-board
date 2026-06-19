#!/usr/bin/env python3
"""
merge_williamhill_match_stats_REPLACE.py

Replaces William Hill stat markets in williamhill_worldcup_props.json with the
fresh markets from williamhill_worldcup_match_stats.json.

Why replace instead of append/merge:
  If an earlier scrape put bad Total Corners / Total Cards rows into the props
  file, a normal merge leaves those bad rows in place. This script removes the
  WH stat markets first, then inserts the fresh version.

Input:
  football/data/williamhill_worldcup_props.json
  football/data/williamhill_worldcup_match_stats.json

Output:
  football/data/williamhill_worldcup_props.json

Backup:
  football/data/williamhill_worldcup_props.before_wh_stats_replace_merge.json
"""

import json
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.json"
STATS_PATH = ROOT / "football" / "data" / "williamhill_worldcup_match_stats.json"
BACKUP_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.before_wh_stats_replace_merge.json"

REPLACE_MARKETS = {
    "match_shots",
    "match_shots_on_target",
    "total_corners",
    "total_corners_over_under",
    "total_cards",
    "total_cards_over_under",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


TEAM_ALIASES = {
    "bosnia_and_herzegovina": "bosnia",
    "bosnia_herzegovina": "bosnia",
    "czech_republic": "czechia",
    "turkey": "turkiye",
    "türkiye": "turkiye",
    "curaçao": "curacao",
    "congo_dr": "dr_congo",
    "democratic_republic_of_congo": "dr_congo",
    "cape_verde_islands": "cape_verde",
    "united_states": "usa",
    "united_states_of_america": "usa",
}


def norm_team(s):
    n = normalize(s)
    return TEAM_ALIASES.get(n, n)


def match_key(match_obj):
    home = norm_team(match_obj.get("home_team", ""))
    away = norm_team(match_obj.get("away_team", ""))

    if home and away:
        return f"{home}_v_{away}"

    match = clean(match_obj.get("match", ""))
    if " v " in match:
        a, b = match.split(" v ", 1)
        return f"{norm_team(a)}_v_{norm_team(b)}"

    return normalize(match)


def market_key(m):
    return m.get("normalized_market") or normalize(m.get("market", ""))


def is_team_stat_market(m):
    key = market_key(m)
    prop_types = {clean(s.get("prop_type", "")) for s in m.get("selections", [])}

    if key in REPLACE_MARKETS:
        return True

    if prop_types & {"shots", "shots_on_target", "corners", "cards"}:
        # Team shots/SOT markets are named like "Ghana Shots", "Panama Shots On Target".
        name = clean(m.get("market", "")).lower()
        if "shot" in name or "corner" in name or "card" in name:
            return True

    return False


def main():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing main props file: {PROPS_PATH}")
    if not STATS_PATH.exists():
        raise SystemExit(f"Missing match stats file: {STATS_PATH}")

    props = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))

    shutil.copy2(PROPS_PATH, BACKUP_PATH)

    props_matches = props.setdefault("matches", [])
    stats_matches = stats.get("matches", [])

    props_by_key = {match_key(m): m for m in props_matches}

    removed = 0
    added = 0
    added_matches = 0

    for sm in stats_matches:
        key = match_key(sm)
        if not key:
            continue

        pm = props_by_key.get(key)
        if not pm:
            pm = {
                "match": sm.get("match", ""),
                "home_team": sm.get("home_team", ""),
                "away_team": sm.get("away_team", ""),
                "url": sm.get("url", ""),
                "markets": [],
            }
            props_matches.append(pm)
            props_by_key[key] = pm
            added_matches += 1

        old_markets = pm.get("markets", [])
        kept = []
        for m in old_markets:
            if is_team_stat_market(m):
                removed += 1
            else:
                kept.append(m)

        for incoming in sm.get("markets", []):
            incoming["normalized_market"] = incoming.get("normalized_market") or normalize(incoming.get("market", ""))
            incoming["selection_count"] = len(incoming.get("selections", []))
            kept.append(incoming)
            added += 1

        pm["markets"] = kept
        pm["market_count"] = len(kept)

    props["match_count"] = len(props_matches)
    props["matches_with_markets"] = len([m for m in props_matches if len(m.get("markets", [])) > 0])
    props["generated_at"] = datetime.now(timezone.utc).isoformat()
    props["merged_williamhill_match_stats_at"] = datetime.now(timezone.utc).isoformat()
    props["merged_williamhill_match_stats_mode"] = "replace_stat_markets"

    PROPS_PATH.write_text(json.dumps(props, indent=2, ensure_ascii=False), encoding="utf-8")

    print("William Hill match stats REPLACE merge complete")
    print(f"Backup: {BACKUP_PATH}")
    print(f"Added matches: {added_matches}")
    print(f"Removed old stat markets: {removed}")
    print(f"Added fresh stat markets: {added}")
    print(f"Output: {PROPS_PATH}")


if __name__ == "__main__":
    main()
