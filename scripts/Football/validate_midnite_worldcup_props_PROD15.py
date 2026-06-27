#!/usr/bin/env python3
"""
validate_midnite_worldcup_props_PROD15.py

Independent final validator for:
    football/data/midnite_worldcup_props.json

Validation rules:
- exactly 15 unique fixtures;
- every fixture has Match Result and a non-empty market payload;
- other main/player markets are availability-based;
- team stats are either all six valid ladders or none;
- copied Shots/SOT ladders fail;
- banned markets fail.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

PRODUCTION_PATH = (
    ROOT
    / "football"
    / "data"
    / "midnite_worldcup_props.json"
)

EXPECTED_MATCHES = 15

TEAM_STAT_MARKETS = (
    "total_shots_on_target",
    "home_shots_on_target",
    "away_shots_on_target",
    "total_shots",
    "home_shots",
    "away_shots",
)

OPTIONAL_MAIN_MARKETS = (
    "total_goals",
    "btts",
    "double_chance",
    "half_result_1h",
    "total_cards",
    "total_corners",
    "team_most_corners",
)

PLAYER_MARKETS = (
    "player_carded",
    "player_shots_on_target",
    "player_fouls_committed",
    "player_fouls_won",
    "player_to_score",
    "player_shots",
)

BANNED_TOKENS = (
    "htft",
    "half_time_full_time",
    "sent_off",
    "send_off",
    "carded_first",
    "carded_last",
    "first_goalscorer",
    "last_goalscorer",
)


def clean(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def valid_ladder(
    value: Any,
) -> bool:
    if (
        not isinstance(
            value,
            dict,
        )
        or not value
    ):
        return False

    return all(
        re.fullmatch(
            r"over_\d+",
            str(key),
        )
        and isinstance(
            odds,
            (int, float),
        )
        and odds > 1
        for key, odds in value.items()
    )


def main() -> None:
    print("=" * 72)
    print("VALIDATE MIDNITE WORLD CUP PROPS PROD15")
    print("=" * 72)

    if not PRODUCTION_PATH.exists():
        raise RuntimeError(
            f"Production file missing: {PRODUCTION_PATH}"
        )

    payload = json.loads(
        PRODUCTION_PATH.read_text(
            encoding="utf-8"
        )
    )
    matches = (
        payload.get("matches")
        or []
    )
    issues = []
    optional_notes = []
    seen = set()
    complete_stats = 0
    unavailable_stats = 0

    if len(matches) != EXPECTED_MATCHES:
        issues.append(
            f"Expected {EXPECTED_MATCHES} matches, "
            f"found {len(matches)}"
        )

    for index, match in enumerate(
        matches,
        start=1,
    ):
        label = (
            f"{clean(match.get('home'))} v "
            f"{clean(match.get('away'))}"
        )
        key = (
            clean(match.get("event_id"))
            or (
                clean(match.get("match_id"))
                + "|"
                + clean(match.get("home"))
                + "|"
                + clean(match.get("away"))
            )
        )

        if not key:
            issues.append(
                f"[{index}] {label}: no fixture key"
            )
        elif key in seen:
            issues.append(
                f"[{index}] {label}: duplicate fixture"
            )
        else:
            seen.add(key)

        markets = match.get("markets")

        if (
            not isinstance(
                markets,
                dict,
            )
            or not markets
        ):
            issues.append(
                f"[{index}] {label}: invalid/empty markets object"
            )
            continue

        if not markets.get(
            "match_result"
        ):
            issues.append(
                f"[{index}] {label}: Match Result missing"
            )

        missing_optional = [
            market_name
            for market_name in OPTIONAL_MAIN_MARKETS
            if not markets.get(
                market_name
            )
        ]

        if missing_optional:
            optional_notes.append(
                f"{label}: "
                + ", ".join(
                    missing_optional
                )
            )

        present_stats = [
            market_name
            for market_name in TEAM_STAT_MARKETS
            if valid_ladder(
                markets.get(
                    market_name
                )
            )
        ]

        if len(present_stats) == 6:
            complete_stats += 1
        elif len(present_stats) == 0:
            unavailable_stats += 1
        else:
            missing_stats = [
                market_name
                for market_name in TEAM_STAT_MARKETS
                if market_name not in present_stats
            ]
            issues.append(
                f"[{index}] {label}: partial team-stat set "
                f"({len(present_stats)}/6); missing: "
                + ", ".join(
                    missing_stats
                )
            )

        for sot_key, shots_key in (
            (
                "total_shots_on_target",
                "total_shots",
            ),
            (
                "home_shots_on_target",
                "home_shots",
            ),
            (
                "away_shots_on_target",
                "away_shots",
            ),
        ):
            if (
                markets.get(sot_key)
                and markets.get(sot_key)
                == markets.get(shots_key)
            ):
                issues.append(
                    f"[{index}] {label}: identical "
                    f"{sot_key}/{shots_key}"
                )

        for market_name in markets:
            low = str(
                market_name
            ).casefold()

            if any(
                token in low
                for token in BANNED_TOKENS
            ):
                issues.append(
                    f"[{index}] {label}: banned market "
                    f"{market_name}"
                )

    player_coverage = {
        market_name: sum(
            bool(
                match.get(
                    "markets",
                    {},
                ).get(
                    market_name
                )
            )
            for match in matches
        )
        for market_name in PLAYER_MARKETS
    }

    print(
        f"Matches: {len(matches)}/{EXPECTED_MATCHES}"
    )
    print(
        "Fixtures with all six team stats: "
        f"{complete_stats}/{EXPECTED_MATCHES}"
    )
    print(
        "Fixtures with team stats unavailable: "
        f"{unavailable_stats}/{EXPECTED_MATCHES}"
    )
    print(
        "Fixtures with partial team stats: "
        f"{len(matches) - complete_stats - unavailable_stats}/"
        f"{EXPECTED_MATCHES}"
    )

    print("Player-market coverage:")

    for market_name, count in (
        player_coverage.items()
    ):
        print(
            f"  {market_name}: "
            f"{count}/{EXPECTED_MATCHES}"
        )

    if optional_notes:
        print("")
        print(
            "Optional main markets not published:"
        )
        for note in optional_notes:
            print(f"  - {note}")

    if issues:
        print("")
        print("VALIDATION: FAIL")

        for issue in issues:
            print(f"  - {issue}")

        raise SystemExit(1)

    print("")
    print("VALIDATION: PASS")
    print(
        f"Validated: {PRODUCTION_PATH}"
    )


if __name__ == "__main__":
    main()
