#!/usr/bin/env python3
"""
fix_williamhill_player_shot_lines.py

Post-process fix for William Hill player Shots / Shots On Target thresholds.

Why:
  William Hill labels these markets as "Over 1", "Over 2", etc.
  For count markets:
    Over 1 = 2+
    Over 2 = 3+
    Over 3 = 4+

The scraper currently stores those as 1+, 2+, 3+ because it normalizes by
display column. This script safely shifts ONLY William Hill player shots/SOT
markets by +1 threshold.

Input/Output:
  football/data/williamhill_worldcup_props.json

Backup:
  football/data/williamhill_worldcup_props.before_wh_shot_line_fix.json

Run after:
  python scripts/Football/fetch_williamhill_worldcup_props.py

Before:
  python scripts/Football/fetch_williamhill_worldcup_match_stats.py
  python scripts/Football/merge_williamhill_match_stats.py
  python scripts/Football/generate_worldcup_page.py
"""

import json
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.json"
BACKUP_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.before_wh_shot_line_fix.json"

TARGET_MARKETS = {
    "player_shots_on_target",
    "player_shots",
}

TARGET_PROP_TYPES = {
    "shots_on_target",
    "shots",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def shifted_line_for_threshold(n):
    # 2+ = line 1.5, 3+ = line 2.5, etc. This matches the site grouping.
    return str(float(n) - 0.5).rstrip("0").rstrip(".")


def replace_trailing_threshold(selection, old_label, new_label):
    selection = clean(selection)
    old_label = clean(old_label)
    new_label = clean(new_label)

    # Most selections look like: "Harry Kane 1+"
    if selection.endswith(old_label):
        return clean(selection[: -len(old_label)] + new_label)

    # Fallback: replace last occurrence only.
    idx = selection.rfind(old_label)
    if idx != -1:
        return clean(selection[:idx] + new_label + selection[idx + len(old_label):])

    return clean(f"{selection} {new_label}")


def shift_selection_threshold(sel):
    if sel.get("williamhill_line_shifted"):
        return False

    threshold = clean(sel.get("threshold", ""))
    m = re.match(r"^(\d+)\+$", threshold)
    if not m:
        return False

    old_n = int(m.group(1))
    new_n = old_n + 1

    old_label = f"{old_n}+"
    new_label = f"{new_n}+"

    sel["original_threshold"] = threshold
    sel["original_line"] = clean(sel.get("line", ""))

    sel["threshold"] = new_label
    sel["line"] = shifted_line_for_threshold(new_n)
    sel["selection"] = replace_trailing_threshold(sel.get("selection", ""), old_label, new_label)
    sel["normalized_selection"] = normalize(sel["selection"])

    sel["williamhill_line_shifted"] = True
    sel["williamhill_line_shift_reason"] = "William Hill Over N player shots/SOT markets mean N+1 count threshold"

    return True


def main():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing file: {PROPS_PATH}")

    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))

    bookmaker = clean(data.get("bookmaker", ""))
    if bookmaker and normalize(bookmaker) not in {"williamhill", "william_hill"}:
        raise SystemExit(f"Refusing to patch non-WilliamHill file: bookmaker={bookmaker!r}")

    shutil.copy2(PROPS_PATH, BACKUP_PATH)

    shifted = 0
    touched_markets = 0
    touched_matches = 0

    for match in data.get("matches", []):
        match_shifted = 0

        for market in match.get("markets", []):
            market_name = clean(market.get("market", ""))
            market_key = market.get("normalized_market") or normalize(market_name)

            if market_key not in TARGET_MARKETS:
                continue

            market_shifted = 0

            for selection in market.get("selections", []):
                prop_type = clean(selection.get("prop_type", ""))
                if prop_type and prop_type not in TARGET_PROP_TYPES:
                    continue

                if shift_selection_threshold(selection):
                    shifted += 1
                    market_shifted += 1
                    match_shifted += 1

            if market_shifted:
                touched_markets += 1
                market["selection_count"] = len(market.get("selections", []))
                market["williamhill_player_shot_lines_fixed"] = True

        if match_shifted:
            touched_matches += 1

    data["williamhill_player_shot_lines_fixed_at"] = datetime.now(timezone.utc).isoformat()
    data["williamhill_player_shot_lines_shift_rule"] = "Player Shots and Player Shots On Target thresholds shifted +1: 1+->2+, 2+->3+, 3+->4+, etc."
    data["generated_at"] = datetime.now(timezone.utc).isoformat()

    PROPS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print("William Hill player shot/SOT line fix complete")
    print(f"Backup: {BACKUP_PATH}")
    print(f"Matches touched: {touched_matches}")
    print(f"Markets touched: {touched_markets}")
    print(f"Selections shifted: {shifted}")
    print(f"Output: {PROPS_PATH}")


if __name__ == "__main__":
    main()
