#!/usr/bin/env python3
"""
Permanent Paddy Power BTTS fix.

Run from the odds-board repository root:

    python fix_paddypower_btts_long_term_FIXED.py

The script:
- patches the Paddy Power scraper to keep only standard full-time BTTS;
- patches the football arb analyzer to reject exotic BTTS variants;
- repairs the current Paddy Power JSON immediately;
- creates backups before making changes.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PP_SCRIPT = ROOT / "scripts" / "Football" / "fetch_paddypower_worldcup_props.py"
ARB_SCRIPT = ROOT / "scripts" / "Football" / "analyze_football_arbitrage.py"
PP_JSON = ROOT / "football" / "data" / "paddypower_worldcup_props.json"

PP_BACKUP = PP_SCRIPT.with_name(
    "fetch_paddypower_worldcup_props.before_standard_btts_fix.py"
)
ARB_BACKUP = ARB_SCRIPT.with_name(
    "analyze_football_arbitrage.before_standard_btts_fix.py"
)
JSON_BACKUP = PP_JSON.with_name(
    "paddypower_worldcup_props.before_standard_btts_fix.json"
)

NEW_PP_PARSE_BTTS = 'def parse_btts(lines) -> dict:\n    """\n    Parse only the ordinary full-time Both Teams To Score Yes/No row.\n\n    Paddy Power also lists several different propositions in this section\n    (first half, both halves, no draw, both teams 2+ goals). Those are separate\n    markets and must not be merged into the standard BTTS market.\n    """\n    block = get_first_block(\n        lines,\n        ["Both Teams to Score Markets", "Both Teams To Score Markets"],\n        ["Result & Both to Score", "Match Odds", "1st Half Over/Under Goals"],\n    )\n\n    accepted_labels = {\n        "both teams to score?",\n        "both team to score?",\n        "both teams to score",\n        "both team to score",\n    }\n\n    for i, line in enumerate(block):\n        label = clean(line).strip().lower()\n\n        if label not in accepted_labels:\n            continue\n        if i + 2 >= len(block):\n            continue\n\n        yes_odds = clean(block[i + 1])\n        no_odds = clean(block[i + 2])\n\n        if not is_odds(yes_odds) or not is_odds(no_odds):\n            continue\n\n        selections = [\n            build_sel(\n                "Both Teams To Score - Yes",\n                yes_odds,\n                {\n                    "side": "yes",\n                    "base_market": "full_time_btts",\n                    "period": "full_time",\n                },\n            ),\n            build_sel(\n                "Both Teams To Score - No",\n                no_odds,\n                {\n                    "side": "no",\n                    "base_market": "full_time_btts",\n                    "period": "full_time",\n                },\n            ),\n        ]\n\n        return dedupe(build_market("Both Teams To Score", selections))\n\n    return build_market("Both Teams To Score", [])\n'

NEW_RESOLVE_BTTS = 'def resolve_btts_outcome(selection):\n    """\n    Accept only the ordinary full-time BTTS Yes/No selections.\n\n    Exotic BTTS variants are rejected even if a scraper accidentally placed\n    them inside a generic Both Teams To Score market.\n    """\n    name = normalize_key(\n        selection.get("normalized_selection")\n        or selection.get("selection")\n        or ""\n    )\n    side = normalize_key(selection.get("side") or "")\n    period = normalize_key(selection.get("period") or "")\n    base_market = normalize_key(selection.get("base_market") or "")\n\n    yes_names = {\n        "yes",\n        "btts_yes",\n        "both_team_to_score_yes",\n        "both_teams_to_score_yes",\n        "both_teams_to_score_full_time_yes",\n        "full_time_btts_yes",\n    }\n    no_names = {\n        "no",\n        "btts_no",\n        "both_team_to_score_no",\n        "both_teams_to_score_no",\n        "both_teams_to_score_full_time_no",\n        "full_time_btts_no",\n    }\n\n    if period and period not in {"full_time", "fulltime"}:\n        return None\n\n    if base_market and base_market not in {\n        "full_time_btts",\n        "both_teams_to_score",\n        "btts",\n    }:\n        return None\n\n    if name in yes_names and side in {"", "yes"}:\n        return "yes"\n    if name in no_names and side in {"", "no"}:\n        return "no"\n\n    return None\n'


def replace_function(source: str, function_name: str, replacement: str) -> str:
    match = re.search(
        rf"(?m)^def {re.escape(function_name)}\s*\(",
        source,
    )
    if not match:
        raise RuntimeError(f"Could not find function: {function_name}")

    start = match.start()
    next_def = re.search(r"(?m)^def \w+\s*\(", source[match.end():])
    end = len(source) if not next_def else match.end() + next_def.start()

    return source[:start] + replacement.rstrip() + "\n\n" + source[end:]


def patch_python_file(
    target: Path,
    backup: Path,
    function_name: str,
    replacement: str,
) -> None:
    if not target.exists():
        raise RuntimeError(f"Missing target: {target}")

    original = target.read_text(encoding="utf-8")
    patched = replace_function(
        original,
        function_name,
        replacement,
    )

    ast.parse(patched)

    if not backup.exists():
        backup.write_text(original, encoding="utf-8")

    target.write_text(patched, encoding="utf-8")

    print(f"Patched: {target}")
    print(f"Backup:  {backup}")


def normalized(value: str) -> str:
    value = str(value or "").lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def standard_btts_side(selection: dict) -> str | None:
    name = normalized(
        selection.get("normalized_selection")
        or selection.get("selection")
        or ""
    )
    side = normalized(selection.get("side") or "")

    yes_names = {
        "yes",
        "btts_yes",
        "both_team_to_score_yes",
        "both_teams_to_score_yes",
        "both_teams_to_score_full_time_yes",
        "full_time_btts_yes",
    }
    no_names = {
        "no",
        "btts_no",
        "both_team_to_score_no",
        "both_teams_to_score_no",
        "both_teams_to_score_full_time_no",
        "full_time_btts_no",
    }

    if name in yes_names and side in {"", "yes"}:
        return "yes"
    if name in no_names and side in {"", "no"}:
        return "no"
    return None


def repair_current_json() -> None:
    if not PP_JSON.exists():
        print(f"Current JSON not found, skipping repair: {PP_JSON}")
        return

    if not JSON_BACKUP.exists():
        shutil.copy2(PP_JSON, JSON_BACKUP)

    data = json.loads(PP_JSON.read_text(encoding="utf-8"))
    matches = data.get("matches") or []

    repaired = 0
    removed = 0

    for match in matches:
        markets = match.get("markets") or []
        if not isinstance(markets, list):
            continue

        new_markets = []

        for market in markets:
            market_key = normalized(
                market.get("normalized_market")
                or market.get("market")
                or ""
            )

            if market_key not in {
                "both_teams_to_score",
                "both_teams_to_score_markets",
                "btts",
            }:
                new_markets.append(market)
                continue

            kept_by_side = {}

            for selection in market.get("selections") or []:
                if not isinstance(selection, dict):
                    continue

                side = standard_btts_side(selection)
                if not side or side in kept_by_side:
                    continue

                fixed = dict(selection)
                fixed["selection"] = (
                    "Both Teams To Score - Yes"
                    if side == "yes"
                    else "Both Teams To Score - No"
                )
                fixed["normalized_selection"] = normalized(
                    fixed["selection"]
                )
                fixed["side"] = side
                fixed["base_market"] = "full_time_btts"
                fixed["period"] = "full_time"
                kept_by_side[side] = fixed

            if set(kept_by_side) == {"yes", "no"}:
                fixed_market = dict(market)
                fixed_market["market"] = "Both Teams To Score"
                fixed_market["normalized_market"] = "both_teams_to_score"
                fixed_market["selections"] = [
                    kept_by_side["yes"],
                    kept_by_side["no"],
                ]
                fixed_market["selection_count"] = 2
                new_markets.append(fixed_market)
                repaired += 1
            else:
                removed += 1

        match["markets"] = new_markets
        match["market_count"] = len(new_markets)

    PP_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Repaired standard BTTS markets: {repaired}")
    print(f"Removed unverified BTTS markets: {removed}")
    print(f"JSON backup: {JSON_BACKUP}")


def main() -> None:
    patch_python_file(
        PP_SCRIPT,
        PP_BACKUP,
        "parse_btts",
        NEW_PP_PARSE_BTTS,
    )
    patch_python_file(
        ARB_SCRIPT,
        ARB_BACKUP,
        "resolve_btts_outcome",
        NEW_RESOLVE_BTTS,
    )
    repair_current_json()

    print("")
    print("Paddy Power BTTS fix completed successfully.")
    print("No bookmaker scraper rerun is required for the current board.")
    print("")
    print("Next commands:")
    print(r"  python scripts\Football\analyze_football_arbitrage.py")
    print(r"  python scripts\build_arbitrage_all.py")


if __name__ == "__main__":
    main()
