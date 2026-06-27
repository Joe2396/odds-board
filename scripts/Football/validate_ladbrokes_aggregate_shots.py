#!/usr/bin/env python3
"""
validate_ladbrokes_aggregate_shots.py

Validates aggregate Ladbrokes shots markets in:
  football/data/ladbrokes_worldcup_props.json

Checks:
  - aggregate Shots / Shots On Target markets are structurally valid
  - every stored line has both Over and Under
  - no duplicate selections
  - reports how many of the six target markets each fixture has

Does not modify any file.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = (
    ROOT
    / "football"
    / "data"
    / "ladbrokes_worldcup_props.json"
)

AGGREGATE_SUFFIXES = (
    "shots_over_under",
    "shots_on_target_over_under",
)

TOTAL_KEYS = {
    "total_shots_over_under",
    "total_shots_on_target_over_under",
}


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def normalized(value):
    value = clean(value).lower()
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        value,
    ).strip("_")


def is_aggregate_market(market):
    key = clean(
        market.get("normalized_market", "")
    )

    if not key:
        key = normalized(
            market.get("market", "")
        )

    return any(
        key.endswith(suffix)
        for suffix in AGGREGATE_SUFFIXES
    )


def selection_side(selection):
    side = clean(
        selection.get("side", "")
    ).lower()

    if side in {"over", "under"}:
        return side

    name = clean(
        selection.get("selection", "")
        or selection.get("name", "")
    )

    match = re.search(
        r"\b(Over|Under)\b",
        name,
        re.I,
    )
    return (
        match.group(1).lower()
        if match
        else ""
    )


def selection_line(selection):
    line = clean(
        selection.get("line", "")
    )

    if line:
        return line

    name = clean(
        selection.get("selection", "")
        or selection.get("name", "")
    )

    match = re.search(
        r"\b(?:Over|Under)\s+"
        r"(\d+(?:\.\d+)?)\b",
        name,
        re.I,
    )
    return (
        match.group(1)
        if match
        else ""
    )


def selection_identity(selection):
    return (
        clean(
            selection.get("selection", "")
            or selection.get("name", "")
        ).lower(),
        selection_side(selection),
        selection_line(selection),
    )


def main():
    if not JSON_PATH.exists():
        raise FileNotFoundError(
            f"Missing {JSON_PATH}"
        )

    data = json.loads(
        JSON_PATH.read_text(
            encoding="utf-8"
        )
    )
    matches = data.get("matches", [])

    print("=" * 72)
    print("Ladbrokes Aggregate Shots Validator")
    print("=" * 72)
    print(f"File: {JSON_PATH}")
    print(f"Matches: {len(matches)}")
    print("")

    total_markets = 0
    complete_six = 0
    partial = 0
    unavailable = 0
    invalid_markets = 0
    duplicate_count = 0

    for match in matches:
        match_name = clean(
            match.get("match", "Unknown fixture")
        )
        markets = [
            market
            for market in match.get("markets", [])
            if is_aggregate_market(market)
        ]

        total_markets += len(markets)

        if len(markets) == 6:
            complete_six += 1
        elif markets:
            partial += 1
        else:
            unavailable += 1

        issues = []

        for market in markets:
            market_name = clean(
                market.get("market", "")
            )
            selections = market.get(
                "selections",
                [],
            )

            seen = set()
            lines = defaultdict(set)

            for selection in selections:
                identity = selection_identity(
                    selection
                )

                if identity in seen:
                    duplicate_count += 1
                    issues.append(
                        f"{market_name}: duplicate "
                        f"{identity}"
                    )
                seen.add(identity)

                side = selection_side(selection)
                line = selection_line(selection)

                if not side or not line:
                    issues.append(
                        f"{market_name}: could not parse "
                        f"side/line from "
                        f"{clean(selection)}"
                    )
                    continue

                lines[line].add(side)

            if not selections:
                issues.append(
                    f"{market_name}: empty market"
                )

            for line, sides in sorted(
                lines.items()
            ):
                if sides != {"over", "under"}:
                    issues.append(
                        f"{market_name} line {line}: "
                        f"missing pair; found "
                        f"{sorted(sides)}"
                    )

        if issues:
            invalid_markets += 1
            status = "INVALID"
        elif len(markets) == 6:
            status = "COMPLETE"
        elif markets:
            status = "PARTIAL"
        else:
            status = "UNAVAILABLE"

        print(
            f"{status:<11} "
            f"{match_name:<38} "
            f"{len(markets)}/6 markets"
        )

        for issue in issues:
            print(f"    - {issue}")

    print("")
    print("=" * 72)
    print(f"Aggregate markets stored: {total_markets}")
    print(f"Fixtures with all six: {complete_six}")
    print(f"Fixtures with partial markets: {partial}")
    print(f"Fixtures unavailable: {unavailable}")
    print(f"Fixtures with validation issues: {invalid_markets}")
    print(f"Duplicate selections: {duplicate_count}")
    print("=" * 72)

    if invalid_markets or duplicate_count:
        print("RESULT: FAIL")
        sys.exit(1)

    print("RESULT: PASS")
    print(
        "Every stored aggregate shots line "
        "contains both Over and Under."
    )


if __name__ == "__main__":
    main()
