#!/usr/bin/env python3
"""
merge_midnite_worldcup_props_PROD15.py

Merges the two Midnite production stages:

    football/data/midnite_worldcup_props_main_prod15.json
    football/data/midnite_worldcup_team_stats_prod15.json

Production rules:
- exactly 7 matching fixtures;
- Match Result must exist;
- other main/player markets are availability-based;
- team stats must be either all six markets or none;
- partial or copied Shots/SOT sets fail;
- existing production JSON is backed up;
- replacement is atomic.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

MAIN_PATH = (
    ROOT
    / "football"
    / "data"
    / "midnite_worldcup_props_main_prod15.json"
)

STATS_PATH = (
    ROOT
    / "football"
    / "data"
    / "midnite_worldcup_team_stats_prod15.json"
)

PRODUCTION_PATH = (
    ROOT
    / "football"
    / "data"
    / "midnite_worldcup_props.json"
)

BACKUP_DIR = (
    ROOT
    / "football"
    / "data"
    / "backups"
)

MAX_MATCHES = 7

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


def normalise_name(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        clean(value).casefold(),
    )


def fixture_label(
    match: dict[str, Any],
) -> str:
    return (
        f"{clean(match.get('home'))} v "
        f"{clean(match.get('away'))}"
    )


def match_keys(
    match: dict[str, Any],
) -> list[str]:
    keys: list[str] = []

    match_id = clean(
        match.get("match_id")
    )
    event_id = clean(
        match.get("event_id")
    )

    if match_id or event_id:
        keys.append(
            f"id:{match_id}|{event_id}"
        )

    home = normalise_name(
        match.get("home")
    )
    away = normalise_name(
        match.get("away")
    )

    if home and away:
        keys.append(
            f"teams:{home}|{away}"
        )

    return keys


def read_json(
    path: Path,
) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(
            f"Required stage file missing: {path}"
        )

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as error:
        raise RuntimeError(
            f"Could not parse {path}: {error}"
        ) from error

    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            f"Expected JSON object in {path}"
        )

    return payload


def decimal_odds(
    value: Any,
) -> float | None:
    if isinstance(
        value,
        (int, float),
    ):
        result = float(value)
        return (
            round(result, 4)
            if result > 1
            else None
        )

    text = clean(value).upper()

    if text in {
        "EVS",
        "EVENS",
    }:
        return 2.0

    try:
        result = float(text)
        if result > 1:
            return round(result, 4)
    except ValueError:
        pass

    match = re.fullmatch(
        r"(\d+)\s*/\s*(\d+)",
        text,
    )

    if not match:
        return None

    numerator = int(
        match.group(1)
    )
    denominator = int(
        match.group(2)
    )

    if denominator <= 0:
        return None

    result = float(
        Fraction(
            numerator,
            denominator,
        )
        + 1
    )

    return round(
        result,
        4,
    )


def normalise_ladder(
    value: Any,
) -> dict[str, float]:
    ladder: dict[str, float] = {}

    if not isinstance(
        value,
        dict,
    ):
        return ladder

    for raw_key, raw_odds in value.items():
        key_match = re.search(
            r"(\d+)",
            str(raw_key),
        )

        if not key_match:
            continue

        threshold = int(
            key_match.group(1)
        )
        odds = decimal_odds(
            raw_odds
        )

        if odds is None:
            continue

        ladder[
            f"over_{threshold}"
        ] = odds

    return dict(
        sorted(
            ladder.items(),
            key=lambda item:
                int(
                    item[0]
                    .split(
                        "_",
                        1,
                    )[1]
                ),
        )
    )


def rebuild_from_audit(
    audit_entry: Any,
) -> dict[str, float]:
    if not isinstance(
        audit_entry,
        dict,
    ):
        return {}

    row_groups = [
        audit_entry.get("rows"),
    ]
    raw = audit_entry.get("raw")

    if isinstance(
        raw,
        dict,
    ):
        row_groups.append(
            raw.get("rows")
        )

    ladder: dict[str, float] = {}

    for rows in row_groups:
        if not isinstance(
            rows,
            list,
        ):
            continue

        for row in rows:
            if not isinstance(
                row,
                dict,
            ):
                continue

            try:
                threshold = int(
                    row.get("threshold")
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            odds = decimal_odds(
                row.get(
                    "decimal_odds"
                )
            )

            if odds is None:
                odds = decimal_odds(
                    row.get(
                        "fractional_odds"
                    )
                )

            if odds is None:
                continue

            ladder[
                f"over_{threshold}"
            ] = odds

    return dict(
        sorted(
            ladder.items(),
            key=lambda item:
                int(
                    item[0]
                    .split(
                        "_",
                        1,
                    )[1]
                ),
        )
    )


def identical_shots_and_sot(
    markets: dict[str, Any],
) -> bool:
    return any(
        markets.get(sot_key)
        and markets.get(sot_key)
        == markets.get(shots_key)
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
        )
    )


def prepare_stats_markets(
    stats_match: dict[str, Any],
) -> tuple[
    dict[str, dict[str, float]],
    list[str],
]:
    source_markets = (
        stats_match.get("markets")
        if isinstance(
            stats_match.get("markets"),
            dict,
        )
        else {}
    )
    audit = (
        stats_match.get("audit")
        if isinstance(
            stats_match.get("audit"),
            dict,
        )
        else {}
    )

    prepared: dict[
        str,
        dict[str, float],
    ] = {}
    recovered: list[str] = []

    for market_name in TEAM_STAT_MARKETS:
        ladder = normalise_ladder(
            source_markets.get(
                market_name
            )
        )
        audit_ladder = rebuild_from_audit(
            audit.get(
                market_name
            )
        )

        if len(
            audit_ladder
        ) > len(ladder):
            ladder = audit_ladder
            recovered.append(
                market_name
            )

        if ladder:
            prepared[
                market_name
            ] = ladder

    return prepared, recovered


def derive_expected_count(
    payload: dict[str, Any],
    matches: list[dict[str, Any]],
    stage_name: str,
) -> int:
    raw = payload.get(
        "expected_match_count",
        payload.get(
            "selected_match_count",
            payload.get(
                "match_count",
                len(matches),
            ),
        ),
    )

    try:
        expected = int(raw)
    except (TypeError, ValueError):
        raise RuntimeError(
            f"{stage_name} has an invalid expected_match_count: {raw!r}"
        )

    if expected != len(matches):
        raise RuntimeError(
            f"{stage_name} count mismatch: metadata says {expected}, "
            f"but file contains {len(matches)} matches"
        )

    if not 1 <= expected <= MAX_MATCHES:
        raise RuntimeError(
            f"{stage_name} must contain between 1 and {MAX_MATCHES} "
            f"matches; found {expected}"
        )

    return expected


def validate_main_matches(
    matches: list[dict[str, Any]],
    expected_matches: int,
) -> tuple[
    list[str],
    list[str],
]:
    issues: list[str] = []
    availability_notes: list[str] = []
    seen: set[str] = set()

    if len(matches) != expected_matches:
        issues.append(
            f"Expected {expected_matches} main-stage matches, "
            f"found {len(matches)}"
        )

    for index, match in enumerate(
        matches,
        start=1,
    ):
        label = fixture_label(match)
        keys = match_keys(match)

        if not keys:
            issues.append(
                f"[{index}] {label}: no usable match key"
            )
        elif keys[0] in seen:
            issues.append(
                f"[{index}] {label}: duplicate fixture"
            )
        else:
            seen.add(keys[0])

        markets = match.get("markets")

        if (
            not isinstance(
                markets,
                dict,
            )
            or not markets
        ):
            issues.append(
                f"[{index}] {label}: no main/player markets"
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
            availability_notes.append(
                f"{label}: "
                + ", ".join(
                    missing_optional
                )
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
                    f"[{index}] {label}: banned market retained: "
                    f"{market_name}"
                )

    return issues, availability_notes


def main() -> None:
    print("=" * 72)
    print("MERGE MIDNITE WORLD CUP PROPS PROD15")
    print("=" * 72)

    main_payload = read_json(
        MAIN_PATH
    )
    stats_payload = read_json(
        STATS_PATH
    )

    main_matches = (
        main_payload.get("matches")
        or []
    )
    stats_matches = (
        stats_payload.get("matches")
        or []
    )

    try:
        main_expected = derive_expected_count(
            main_payload,
            main_matches,
            "Main props stage",
        )
        stats_expected = derive_expected_count(
            stats_payload,
            stats_matches,
            "Team-stats stage",
        )
    except RuntimeError as error:
        print(f"INPUT VALIDATION: FAIL\n  - {error}")
        raise SystemExit(1)

    expected_matches = main_expected

    issues, availability_notes = (
        validate_main_matches(
            main_matches,
            expected_matches,
        )
    )

    if stats_expected != expected_matches:
        issues.append(
            f"Stage count mismatch: main expects {expected_matches}, "
            f"team stats expects {stats_expected}"
        )

    main_snapshot = clean(
        main_payload.get("fixture_snapshot_created_at")
    )
    stats_snapshot = clean(
        stats_payload.get("fixture_snapshot_created_at")
    )
    if (
        main_snapshot
        and stats_snapshot
        and main_snapshot != stats_snapshot
    ):
        issues.append(
            "Main props and team-stats stages were built from "
            "different fixture snapshots"
        )

    if len(stats_matches) != expected_matches:
        issues.append(
            f"Expected {expected_matches} team-stats matches, "
            f"found {len(stats_matches)}"
        )

    stats_index: dict[
        str,
        dict[str, Any],
    ] = {}

    for stats_match in stats_matches:
        keys = match_keys(
            stats_match
        )

        if not keys:
            issues.append(
                f"{fixture_label(stats_match)}: "
                "team-stats match has no key"
            )
            continue

        for key in keys:
            if key in stats_index:
                issues.append(
                    f"Duplicate team-stats key: {key}"
                )
            else:
                stats_index[key] = (
                    stats_match
                )

    if issues:
        print("INPUT VALIDATION: FAIL")
        for issue in issues:
            print(f"  - {issue}")
        raise SystemExit(1)

    merged_matches = []
    unmatched = []
    complete_labels = []
    unavailable_labels = []
    recovered_labels = []
    partial_labels = []

    for main_match in main_matches:
        label = fixture_label(
            main_match
        )
        matched_stats = None

        for key in match_keys(
            main_match
        ):
            matched_stats = (
                stats_index.get(key)
            )
            if matched_stats:
                break

        if not matched_stats:
            unmatched.append(label)
            continue

        prepared_stats, recovered = (
            prepare_stats_markets(
                matched_stats
            )
        )

        if recovered:
            recovered_labels.append(
                f"{label}: "
                + ", ".join(recovered)
            )

        if not prepared_stats:
            unavailable_labels.append(
                label
            )
        elif len(prepared_stats) != 6:
            partial_labels.append(
                f"{label}: "
                f"{len(prepared_stats)}/6"
            )
        elif identical_shots_and_sot(
            prepared_stats
        ):
            partial_labels.append(
                f"{label}: copied/identical Shots and SOT ladders"
            )
        else:
            complete_labels.append(
                label
            )

        merged = deepcopy(
            main_match
        )
        markets = deepcopy(
            merged.get("markets")
            or {}
        )

        for market_name in TEAM_STAT_MARKETS:
            markets.pop(
                market_name,
                None,
            )

        if (
            len(prepared_stats) == 6
            and not identical_shots_and_sot(
                prepared_stats
            )
        ):
            for (
                market_name,
                ladder,
            ) in prepared_stats.items():
                markets[
                    market_name
                ] = deepcopy(ladder)

        merged["markets"] = markets
        merged["market_count"] = len(
            markets
        )

        for debug_key in (
            "filter_audit",
            "removed_duplicate_aggregate_markets",
            "removed_contaminated_markets",
            "audit",
        ):
            merged.pop(
                debug_key,
                None,
            )

        merged_matches.append(
            merged
        )

    if unmatched:
        print("MATCHING: FAIL")
        for label in unmatched:
            print(
                f"  - No team-stats record for {label}"
            )
        raise SystemExit(1)

    if partial_labels:
        print("TEAM-STATS VALIDATION: FAIL")
        for label in partial_labels:
            print(f"  - {label}")
        print(
            "Production JSON was not replaced. "
            "A fixture must have all six team-stat markets or none."
        )
        raise SystemExit(1)

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
            for match in merged_matches
        )
        for market_name in PLAYER_MARKETS
    }

    output = {
        "bookmaker": "Midnite",
        "competition":
            "FIFA World Cup 2026",
        "scraped_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "match_count":
            len(merged_matches),
        "sources": {
            "main_props_scraped_at":
                main_payload.get(
                    "scraped_at"
                ),
            "team_stats_scraped_at":
                stats_payload.get(
                    "scraped_at"
                ),
        },
        "validation": {
            "status": "PASS",
            "requested_max_matches":
                MAX_MATCHES,
            "expected_matches":
                expected_matches,
            "fixture_snapshot_created_at":
                main_snapshot or stats_snapshot,
            "matches_with_complete_team_stats":
                len(complete_labels),
            "matches_team_stats_unavailable":
                len(unavailable_labels),
            "team_stats_recovered_from_audit":
                len(recovered_labels),
            "team_stats_policy":
                "all six markets or none; partial sets fail",
            "player_market_coverage":
                player_coverage,
        },
        "matches": merged_matches,
    }

    PRODUCTION_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    backup_path = None

    if PRODUCTION_PATH.exists():
        stamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
        backup_path = (
            BACKUP_DIR
            / (
                "midnite_worldcup_props_"
                f"{stamp}.json"
            )
        )
        shutil.copy2(
            PRODUCTION_PATH,
            backup_path,
        )

    descriptor, temp_name = (
        tempfile.mkstemp(
            prefix=(
                "midnite_worldcup_props_"
                "pending_"
            ),
            suffix=".json",
            dir=str(
                PRODUCTION_PATH.parent
            ),
        )
    )
    temp_path = Path(
        temp_name
    )

    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                output,
                handle,
                indent=2,
                ensure_ascii=False,
            )
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        parsed = json.loads(
            temp_path.read_text(
                encoding="utf-8"
            )
        )

        if len(
            parsed.get(
                "matches",
                [],
            )
        ) != expected_matches:
            raise RuntimeError(
                "Temporary production file failed final count check"
            )

        os.replace(
            temp_path,
            PRODUCTION_PATH,
        )
    finally:
        temp_path.unlink(
            missing_ok=True
        )

    print("")
    print("Optional main markets not published:")

    if availability_notes:
        for note in availability_notes:
            print(f"  - {note}")
    else:
        print("  none")

    print("")
    print("Team-stat audit recovery:")

    if recovered_labels:
        for note in recovered_labels:
            print(f"  - {note}")
    else:
        print("  none")

    print("")
    print("VALIDATION: PASS")
    print(
        f"Production matches: "
        f"{len(merged_matches)}/{expected_matches}"
    )
    print(
        f"Complete six-market team stats: "
        f"{len(complete_labels)}/{expected_matches}"
    )
    print(
        f"Team stats unavailable: "
        f"{len(unavailable_labels)}/{expected_matches}"
    )
    print(
        "Partial team-stat sets published: 0"
    )

    for market_name, count in (
        player_coverage.items()
    ):
        print(
            f"{market_name}: "
            f"{count}/{expected_matches}"
        )

    if backup_path:
        print(f"Backup: {backup_path}")
    else:
        print(
            "Backup: none "
            "(no previous production file)"
        )

    print(
        "Production replaced atomically: "
        f"{PRODUCTION_PATH}"
    )


if __name__ == "__main__":
    main()
