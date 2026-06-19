#!/usr/bin/env python3
"""
fix_williamhill_embedded_player_shots.py

Post-process patch for William Hill player Shots / Shots On Target.

Why:
  William Hill embeds some player shot selections as full row labels, e.g.
    Jonathan David At Least 1 Shot On Target
    Jonathan David Over 1 Shot On Target
    Alphonso Davies Over 2 Shots On Target

The main scraper can capture the page text but may not convert these embedded
row labels into player markets. This script reads the William Hill debug text
files already saved by fetch_williamhill_worldcup_props.py and inserts/replaces:

  - Player Shots On Target
  - Player Shots

Input:
  football/data/williamhill_worldcup_props.json
  football/debug/williamhill_worldcup_props/<match>.txt

Output:
  football/data/williamhill_worldcup_props.json

Backup:
  football/data/williamhill_worldcup_props.before_wh_embedded_player_shots.json

Run AFTER:
  python scripts/Football/fetch_williamhill_worldcup_props.py
  python scripts/Football/fix_williamhill_player_shot_lines.py

Run BEFORE:
  python scripts/Football/generate_worldcup_page.py

Important:
  This writes final correct thresholds itself:
    At Least 1 Shot On Target = 1+
    Over 1 Shot On Target     = 2+
    Over 2 Shots On Target    = 3+
    Over 3 Shots On Target    = 4+
Do not run fix_williamhill_player_shot_lines.py again after this script.
"""

import json
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "williamhill_worldcup_props"
BACKUP_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.before_wh_embedded_player_shots.json"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)

# Player names can include accents, apostrophes, hyphens and dots.
PLAYER = r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.\- ]{1,70}?"

SOT_RE = re.compile(
    rf"^(?P<player>{PLAYER})\s+"
    rf"(?:(?P<atleast>At\s+Least)\s+(?P<atleast_n>\d+)|Over\s+(?P<over_n>\d+))\s+"
    rf"Shots?\s+On\s+Target$",
    re.I,
)

SHOTS_RE = re.compile(
    rf"^(?P<player>{PLAYER})\s+"
    rf"(?:(?P<atleast>At\s+Least)\s+(?P<atleast_n>\d+)|Over\s+(?P<over_n>\d+))\s+"
    rf"Shots?$",
    re.I,
)

BAD_PLAYER_PARTS = {
    "Home",
    "Away",
    "Team",
    "Match",
    "Total",
    "First Half",
    "Second Half",
    "1st Half",
    "2nd Half",
    "Show More",
    "View More",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def slugify(s):
    return normalize(s).replace("_", "-")


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def threshold_from_match(m):
    if m.group("atleast"):
        n = int(m.group("atleast_n"))
        return f"{n}+", str(float(n) - 0.5).rstrip("0").rstrip(".")

    # WH "Over 1 Shot On Target" means 2+.
    n = int(m.group("over_n")) + 1
    return f"{n}+", str(float(n) - 0.5).rstrip("0").rstrip(".")


def make_selection(player, threshold, line, odds, prop_type):
    return {
        "selection": f"{player} {threshold}",
        "normalized_selection": normalize(f"{player} {threshold}"),
        "odds": clean(odds).upper(),
        "player": player,
        "prop_type": prop_type,
        "threshold": threshold,
        "line": line,
        "williamhill_embedded_player_shot_fix": True,
    }


def make_market(name, normalized_market, selections):
    # stable sort by player then numeric threshold
    def sort_key(s):
        m = re.match(r"^(\d+)\+$", s.get("threshold", ""))
        n = int(m.group(1)) if m else 99
        return (normalize(s.get("player", "")), n)

    selections = sorted(selections, key=sort_key)

    return {
        "market": name,
        "normalized_market": normalized_market,
        "selection_count": len(selections),
        "selections": selections,
        "williamhill_embedded_player_shot_fix": True,
    }


def find_debug_file(match):
    candidates = [
        DEBUG_DIR / f"{slugify(match)}.txt",
        DEBUG_DIR / f"{slugify(match.replace('Bosnia and Herzegovina', 'Bosnia'))}.txt",
        DEBUG_DIR / f"{slugify(match.replace('Bosnia', 'Bosnia and Herzegovina'))}.txt",
    ]

    for p in candidates:
        if p.exists():
            return p

    # fuzzy fallback
    target = slugify(match)
    files = list(DEBUG_DIR.glob("*.txt"))
    for p in files:
        stem = p.stem
        if stem == target or target in stem or stem in target:
            return p

    return None


def parse_debug_file(path):
    lines = [clean(x) for x in path.read_text(encoding="utf-8", errors="ignore").splitlines() if clean(x)]

    sot = []
    shots = []
    seen = set()

    for i, line in enumerate(lines):
        for regex, prop_type, bucket in [
            (SOT_RE, "shots_on_target", sot),
            (SHOTS_RE, "shots", shots),
        ]:
            m = regex.match(line)
            if not m:
                continue

            player = clean(m.group("player"))

            if any(bad.lower() == player.lower() for bad in BAD_PLAYER_PARTS):
                continue

            # Avoid menu/market nonsense.
            if any(noise in player.lower() for noise in ["bet builder", "odds format", "help", "media"]):
                continue

            odds = None
            for j in range(i + 1, min(i + 6, len(lines))):
                if is_odds(lines[j]):
                    odds = lines[j]
                    break
                # Stop if another embedded shot row starts before odds.
                if j > i + 1 and (SOT_RE.match(lines[j]) or SHOTS_RE.match(lines[j])):
                    break

            if not odds:
                continue

            threshold, line_val = threshold_from_match(m)
            key = (prop_type, normalize(player), threshold, clean(odds).upper())

            if key in seen:
                continue
            seen.add(key)

            bucket.append(make_selection(player, threshold, line_val, odds, prop_type))
            break

    return sot, shots


def replace_market(match_obj, normalized_market, new_market):
    markets = match_obj.setdefault("markets", [])

    # Remove old WH shot market entirely to prevent bad shifted/partial rows.
    markets[:] = [
        m for m in markets
        if (m.get("normalized_market") or normalize(m.get("market", ""))) != normalized_market
    ]

    if new_market["selection_count"]:
        markets.append(new_market)

    match_obj["market_count"] = len(markets)


def main():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing file: {PROPS_PATH}")

    if not DEBUG_DIR.exists():
        raise SystemExit(f"Missing debug folder: {DEBUG_DIR}")

    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    shutil.copy2(PROPS_PATH, BACKUP_PATH)

    touched_matches = 0
    total_sot = 0
    total_shots = 0

    for match_obj in data.get("matches", []):
        match_name = clean(match_obj.get("match", ""))
        if not match_name:
            continue

        debug_file = find_debug_file(match_name)
        if not debug_file:
            continue

        sot, shots = parse_debug_file(debug_file)

        if not sot and not shots:
            continue

        if sot:
            replace_market(
                match_obj,
                "player_shots_on_target",
                make_market("Player Shots On Target", "player_shots_on_target", sot),
            )
            total_sot += len(sot)

        if shots:
            replace_market(
                match_obj,
                "player_shots",
                make_market("Player Shots", "player_shots", shots),
            )
            total_shots += len(shots)

        touched_matches += 1

        print(f"✓ {match_name}")
        if sot:
            print(f"  Player Shots On Target: {len(sot)} selections")
        if shots:
            print(f"  Player Shots:           {len(shots)} selections")

    data["williamhill_embedded_player_shots_fixed_at"] = datetime.now(timezone.utc).isoformat()
    data["williamhill_embedded_player_shots_rule"] = "Parsed embedded WH rows: At Least N = N+, Over N = N+1 for player shots/SOT"
    data["generated_at"] = datetime.now(timezone.utc).isoformat()

    PROPS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nWilliam Hill embedded player shot fix complete")
    print(f"Backup: {BACKUP_PATH}")
    print(f"Matches touched: {touched_matches}")
    print(f"Player SOT selections inserted: {total_sot}")
    print(f"Player Shots selections inserted: {total_shots}")
    print(f"Output: {PROPS_PATH}")


if __name__ == "__main__":
    main()
