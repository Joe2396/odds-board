#!/usr/bin/env python3
"""
merge_williamhill_cards_corners.py

Replaces only William Hill Total Corners / Total Cards markets in
williamhill_worldcup_props.json with the fresh output from the separate
cards/corners scraper.

Input:
  football/data/williamhill_worldcup_props.json
  football/data/williamhill_worldcup_cards_corners.json

Output:
  football/data/williamhill_worldcup_props.json

Backup:
  football/data/williamhill_worldcup_props.before_wh_cards_corners_merge.json
"""

import json
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.json"
CC_PATH = ROOT / "football" / "data" / "williamhill_worldcup_cards_corners.json"
BACKUP_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.before_wh_cards_corners_merge.json"

REPLACE_KEYS = {
    "total_corners",
    "total_corners_over_under",
    "match_corners",
    "match_over_under_corners",
    "total_cards",
    "total_cards_over_under",
    "match_cards",
    "match_over_under_cards",
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


def match_key(m):
    home = norm_team(m.get("home_team", ""))
    away = norm_team(m.get("away_team", ""))

    if home and away:
        return f"{home}_v_{away}"

    match = clean(m.get("match", ""))
    if " v " in match:
        a, b = match.split(" v ", 1)
        return f"{norm_team(a)}_v_{norm_team(b)}"

    return normalize(match)


def market_key(m):
    return m.get("normalized_market") or normalize(m.get("market", ""))


def is_cards_corners_market(m):
    k = market_key(m)
    if k in REPLACE_KEYS:
        return True

    name = normalize(m.get("market", ""))
    return ("corner" in name or "card" in name) and not ("player" in name)


def main():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing main props file: {PROPS_PATH}")

    if not CC_PATH.exists():
        raise SystemExit(f"Missing cards/corners file: {CC_PATH}")

    props = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    cc = json.loads(CC_PATH.read_text(encoding="utf-8"))

    shutil.copy2(PROPS_PATH, BACKUP_PATH)

    props_matches = props.setdefault("matches", [])
    by_key = {match_key(m): m for m in props_matches}

    removed = 0
    added = 0
    added_matches = 0

    for cm in cc.get("matches", []):
        key = match_key(cm)
        if not key:
            continue

        pm = by_key.get(key)
        if not pm:
            pm = {
                "match": cm.get("match", ""),
                "home_team": cm.get("home_team", ""),
                "away_team": cm.get("away_team", ""),
                "url": cm.get("url", ""),
                "markets": [],
            }
            props_matches.append(pm)
            by_key[key] = pm
            added_matches += 1

        old = pm.get("markets", [])
        kept = []
        for m in old:
            if is_cards_corners_market(m):
                removed += 1
            else:
                kept.append(m)

        for m in cm.get("markets", []):
            m["normalized_market"] = m.get("normalized_market") or normalize(m.get("market", ""))
            m["selection_count"] = len(m.get("selections", []))
            kept.append(m)
            added += 1

        pm["markets"] = kept
        pm["market_count"] = len(kept)

    props["match_count"] = len(props_matches)
    props["matches_with_markets"] = len([m for m in props_matches if m.get("markets")])
    props["generated_at"] = datetime.now(timezone.utc).isoformat()
    props["merged_williamhill_cards_corners_at"] = datetime.now(timezone.utc).isoformat()

    PROPS_PATH.write_text(json.dumps(props, indent=2, ensure_ascii=False), encoding="utf-8")

    print("William Hill cards/corners merge complete")
    print(f"Backup: {BACKUP_PATH}")
    print(f"Added matches: {added_matches}")
    print(f"Removed old cards/corners markets: {removed}")
    print(f"Added fresh cards/corners markets: {added}")
    print(f"Output: {PROPS_PATH}")


if __name__ == "__main__":
    main()
