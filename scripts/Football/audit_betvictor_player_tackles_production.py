#!/usr/bin/env python3
"""
audit_betvictor_player_tackles_production.py

Read-only production audit for BetVictor Player Tackles.

Checks the staging scrape:
    football/data/betvictor_player_tackles.json

Checks the merged output:
    football/data/betvictor_worldcup_props.json

Writes:
    football/data/betvictor_player_tackles_audit.json
    football/data/betvictor_player_tackles_manual_spot_check.csv

It does not modify either production odds JSON.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "football" / "data"

TACKLES_PATH = (
    DATA_DIR / "betvictor_player_tackles.json"
)
MERGED_PATH = (
    DATA_DIR / "betvictor_worldcup_props.json"
)
AUDIT_PATH = (
    DATA_DIR / "betvictor_player_tackles_audit.json"
)
SPOT_CHECK_PATH = (
    DATA_DIR
    / "betvictor_player_tackles_manual_spot_check.csv"
)

ODDS_RE = re.compile(
    r"^(?:\d+/\d+|EVS|EVENS|EVEN)$",
    re.I,
)
THRESHOLD_RE = re.compile(r"^(\d+)\+$")


def clean(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def normalize(value: Any) -> str:
    value = unicodedata.normalize(
        "NFKD",
        clean(value),
    )
    value = "".join(
        character
        for character in value
        if not unicodedata.combining(character)
    )
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        value.lower(),
    ).strip("_")


def decimal_odds(value: Any) -> float | None:
    text = clean(value).upper()

    if text in {"EVS", "EVENS", "EVEN"}:
        return 2.0

    if not ODDS_RE.fullmatch(text):
        return None

    try:
        return 1.0 + float(Fraction(text))
    except Exception:
        return None


def threshold_number(value: Any) -> int | None:
    match = THRESHOLD_RE.fullmatch(
        clean(value)
    )

    if not match:
        return None

    return int(match.group(1))


def is_tackles_market(
    market: dict[str, Any],
) -> bool:
    return normalize(
        market.get("normalized_market")
        or market.get("market")
    ) == "player_tackles"


def canonical_selection_map(
    market: dict[str, Any],
) -> dict[tuple[str, int], str]:
    output = {}

    for selection in market.get(
        "selections",
        [],
    ):
        player = normalize(
            selection.get("player")
        )
        threshold = threshold_number(
            selection.get("threshold")
        )
        odds = clean(
            selection.get("odds")
        ).upper()

        if (
            player
            and threshold is not None
            and odds
        ):
            output[(player, threshold)] = odds

    return output


def merged_tackles_index(
    path: Path,
) -> dict[
    str,
    dict[str, Any],
]:
    if not path.exists():
        return {}

    data = json.loads(
        path.read_text(encoding="utf-8")
    )
    output = {}

    for match in data.get("matches", []):
        market = next(
            (
                item
                for item in match.get(
                    "markets",
                    [],
                )
                if is_tackles_market(item)
            ),
            None,
        )

        if market:
            output[
                normalize(match.get("match"))
            ] = market

    return output


def choose_spot_checks(
    match_name: str,
    source_url: str,
    ladders: dict[
        str,
        list[dict[str, Any]],
    ],
) -> list[dict[str, Any]]:
    """
    Choose a compact representative set:
    - one low threshold;
    - one middle threshold;
    - one highest threshold;
    - spread across different players when possible.
    """
    candidates = []

    for rows in ladders.values():
        rows = sorted(
            rows,
            key=lambda row: row["threshold"],
        )

        if not rows:
            continue

        candidates.append(rows[0])

        if len(rows) >= 3:
            candidates.append(
                rows[len(rows) // 2]
            )

        if len(rows) >= 2:
            candidates.append(rows[-1])

    # Prefer diverse threshold/player combinations.
    candidates.sort(
        key=lambda row: (
            row["threshold"],
            normalize(row["player"]),
        )
    )

    selected = []
    used_players = set()

    for row in candidates:
        player_key = normalize(row["player"])

        if (
            player_key in used_players
            and len(selected) < 4
        ):
            continue

        selected.append(
            {
                "match": match_name,
                "player": row["player"],
                "threshold":
                    row["threshold_label"],
                "odds": row["odds"],
                "decimal_odds":
                    row["decimal_odds"],
                "source_url": source_url,
            }
        )
        used_players.add(player_key)

        if len(selected) >= 5:
            break

    return selected


def audit_market(
    match_name: str,
    source_url: str,
    market: dict[str, Any],
    merged_market: dict[str, Any] | None,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
]:
    selections = market.get(
        "selections",
        [],
    )

    grouped: dict[
        tuple[str, int],
        list[dict[str, Any]],
    ] = defaultdict(list)
    ladders: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    malformed = []
    invalid_odds = []

    for selection in selections:
        player_raw = clean(
            selection.get("player")
        )
        player = normalize(player_raw)
        threshold = threshold_number(
            selection.get("threshold")
        )
        odds = clean(
            selection.get("odds")
        ).upper()
        decimal = decimal_odds(odds)

        if (
            not player
            or threshold is None
            or not odds
        ):
            malformed.append(selection)
            continue

        if decimal is None:
            invalid_odds.append(selection)

        row = {
            "player": player_raw,
            "player_key": player,
            "threshold": threshold,
            "threshold_label":
                f"{threshold}+",
            "odds": odds,
            "decimal_odds": decimal,
        }

        grouped[(player, threshold)].append(
            row
        )
        ladders[player].append(row)

    duplicates = []

    for key, rows in grouped.items():
        if len(rows) > 1:
            duplicates.append(
                {
                    "player_key": key[0],
                    "threshold": f"{key[1]}+",
                    "rows": rows,
                }
            )

    threshold_counts = Counter()
    ladder_gaps = []
    missing_lower_threshold = []
    odds_order_violations = []
    equal_adjacent_prices = []

    for rows in ladders.values():
        rows.sort(
            key=lambda row: row["threshold"]
        )
        thresholds = [
            row["threshold"]
            for row in rows
        ]

        for threshold in thresholds:
            threshold_counts[
                f"{threshold}+"
            ] += 1

        minimum = min(thresholds)
        maximum = max(thresholds)
        missing_inside = sorted(
            set(range(minimum, maximum + 1))
            - set(thresholds)
        )

        if missing_inside:
            ladder_gaps.append(
                {
                    "player": rows[0]["player"],
                    "thresholds": [
                        f"{value}+"
                        for value in thresholds
                    ],
                    "missing_inside": [
                        f"{value}+"
                        for value in missing_inside
                    ],
                }
            )

        if minimum > 1:
            missing_lower_threshold.append(
                {
                    "player": rows[0]["player"],
                    "lowest_available":
                        f"{minimum}+",
                }
            )

        for previous, current in zip(
            rows,
            rows[1:],
        ):
            previous_price = previous[
                "decimal_odds"
            ]
            current_price = current[
                "decimal_odds"
            ]

            if (
                previous_price is None
                or current_price is None
            ):
                continue

            # A harder tackle threshold must not be shorter.
            if current_price < previous_price:
                odds_order_violations.append(
                    {
                        "player":
                            current["player"],
                        "lower_threshold":
                            previous[
                                "threshold_label"
                            ],
                        "lower_odds":
                            previous["odds"],
                        "higher_threshold":
                            current[
                                "threshold_label"
                            ],
                        "higher_odds":
                            current["odds"],
                    }
                )
            elif current_price == previous_price:
                equal_adjacent_prices.append(
                    {
                        "player":
                            current["player"],
                        "lower_threshold":
                            previous[
                                "threshold_label"
                            ],
                        "higher_threshold":
                            current[
                                "threshold_label"
                            ],
                        "odds": current["odds"],
                    }
                )

    scraper_audit = market.get(
        "selection_audit",
        {},
    )
    scraper_conflicts = scraper_audit.get(
        "conflict_count",
        0,
    )

    reported_count = market.get(
        "selection_count"
    )
    count_mismatch = (
        reported_count is not None
        and reported_count != len(selections)
    )

    scraper_count_mismatch = (
        scraper_audit.get("selection_count")
        is not None
        and scraper_audit.get(
            "selection_count"
        )
        != len(selections)
    )

    staging_map = canonical_selection_map(
        market
    )

    merge_status = "NOT_MERGED"
    merged_missing = []
    merged_extra = []
    merged_price_mismatches = []

    if merged_market is not None:
        merged_map = canonical_selection_map(
            merged_market
        )

        staging_keys = set(staging_map)
        merged_keys = set(merged_map)

        merged_missing = sorted(
            staging_keys - merged_keys
        )
        merged_extra = sorted(
            merged_keys - staging_keys
        )

        for key in sorted(
            staging_keys & merged_keys
        ):
            if staging_map[key] != merged_map[key]:
                merged_price_mismatches.append(
                    {
                        "player_key": key[0],
                        "threshold":
                            f"{key[1]}+",
                        "staging_odds":
                            staging_map[key],
                        "merged_odds":
                            merged_map[key],
                    }
                )

        if (
            not merged_missing
            and not merged_extra
            and not merged_price_mismatches
        ):
            merge_status = "PASS"
        else:
            merge_status = "FAIL"

    critical_count = sum(
        [
            len(malformed),
            len(invalid_odds),
            len(duplicates),
            len(odds_order_violations),
            int(count_mismatch),
            int(scraper_count_mismatch),
            int(scraper_conflicts),
        ]
    )

    structure_verdict = (
        "PASS"
        if critical_count == 0
        else "FAIL"
    )

    spot_checks = choose_spot_checks(
        match_name,
        source_url,
        ladders,
    )

    audit = {
        "match": match_name,
        "market":
            market.get("market"),
        "reported_selection_count":
            reported_count,
        "actual_selection_count":
            len(selections),
        "unique_player_threshold_count":
            len(grouped),
        "player_count": len(ladders),
        "threshold_counts": dict(
            sorted(
                threshold_counts.items(),
                key=lambda item: int(
                    item[0].rstrip("+")
                ),
            )
        ),
        "maximum_threshold": (
            f"{max(
                (
                    threshold
                    for _, threshold in grouped
                ),
                default=0,
            )}+"
        ),
        "structure_verdict":
            structure_verdict,
        "critical_issue_count":
            critical_count,
        "warning_count": (
            len(ladder_gaps)
            + len(missing_lower_threshold)
            + len(equal_adjacent_prices)
        ),
        "merge_status": merge_status,
        "merge_missing_count":
            len(merged_missing),
        "merge_extra_count":
            len(merged_extra),
        "merge_price_mismatch_count":
            len(merged_price_mismatches),
        "checks": {
            "malformed_count":
                len(malformed),
            "invalid_odds_count":
                len(invalid_odds),
            "duplicate_count":
                len(duplicates),
            "ladder_gap_count":
                len(ladder_gaps),
            "missing_lower_threshold_count":
                len(missing_lower_threshold),
            "odds_order_violation_count":
                len(odds_order_violations),
            "equal_adjacent_price_count":
                len(equal_adjacent_prices),
            "reported_count_mismatch":
                count_mismatch,
            "scraper_count_mismatch":
                scraper_count_mismatch,
            "scraper_conflict_count":
                scraper_conflicts,
        },
        "details": {
            "malformed": malformed,
            "invalid_odds": invalid_odds,
            "duplicates": duplicates,
            "ladder_gaps": ladder_gaps,
            "missing_lower_threshold":
                missing_lower_threshold,
            "odds_order_violations":
                odds_order_violations,
            "equal_adjacent_prices":
                equal_adjacent_prices,
            "merge_missing": [
                {
                    "player_key": key[0],
                    "threshold":
                        f"{key[1]}+",
                }
                for key in merged_missing
            ],
            "merge_extra": [
                {
                    "player_key": key[0],
                    "threshold":
                        f"{key[1]}+",
                }
                for key in merged_extra
            ],
            "merge_price_mismatches":
                merged_price_mismatches,
        },
    }

    return audit, spot_checks


def main() -> None:
    if not TACKLES_PATH.exists():
        raise SystemExit(
            f"Missing production tackle file:\n"
            f"{TACKLES_PATH}"
        )

    tackles = json.loads(
        TACKLES_PATH.read_text(
            encoding="utf-8"
        )
    )
    merged_index = merged_tackles_index(
        MERGED_PATH
    )

    audits = []
    spot_checks = []

    print(
        "BETVICTOR PLAYER TACKLES — "
        "PRODUCTION AUDIT"
    )
    print("=" * 88)
    print(f"Staging source: {TACKLES_PATH}")
    print(
        "Merged props available: "
        f"{MERGED_PATH.exists()}"
    )

    for match in tackles.get(
        "matches",
        [],
    ):
        match_name = clean(
            match.get("match")
        )
        match_key = normalize(match_name)
        source_url = clean(
            match.get("source_url")
        )

        market = next(
            (
                item
                for item in match.get(
                    "markets",
                    [],
                )
                if is_tackles_market(item)
            ),
            None,
        )

        if market is None:
            audit = {
                "match": match_name,
                "structure_verdict": "FAIL",
                "critical_issue_count": 1,
                "warning_count": 0,
                "merge_status":
                    "NOT_MERGED",
                "error":
                    "Player Tackles market missing",
            }
            audits.append(audit)
            print(
                f"\n{match_name}: "
                "MISSING PLAYER TACKLES"
            )
            continue

        audit, selected = audit_market(
            match_name,
            source_url,
            market,
            merged_index.get(match_key),
        )
        audits.append(audit)
        spot_checks.extend(selected)

        print(f"\n{match_name}")
        print(
            "  "
            f"selections="
            f"{audit['actual_selection_count']} "
            f"players={audit['player_count']} "
            f"duplicates="
            f"{audit['checks']['duplicate_count']} "
            f"odds_order_errors="
            f"{audit['checks']['odds_order_violation_count']} "
            f"gaps="
            f"{audit['checks']['ladder_gap_count']} "
            f"scraper_conflicts="
            f"{audit['checks']['scraper_conflict_count']} "
            f"structure="
            f"{audit['structure_verdict']} "
            f"merge={audit['merge_status']}"
        )
        print(
            "  thresholds: "
            + json.dumps(
                audit["threshold_counts"],
                ensure_ascii=False,
            )
        )

    structure_failed = [
        audit
        for audit in audits
        if audit.get(
            "structure_verdict"
        ) != "PASS"
    ]
    merge_failed = [
        audit
        for audit in audits
        if audit.get(
            "merge_status"
        ) == "FAIL"
    ]
    not_merged = [
        audit
        for audit in audits
        if audit.get(
            "merge_status"
        ) == "NOT_MERGED"
    ]

    structure_verdict = (
        "PASS"
        if not structure_failed
        else "FAIL"
    )
    merge_verdict = (
        "PASS"
        if not merge_failed
        and not not_merged
        and audits
        else (
            "NOT_CURRENT"
            if not merge_failed
            else "FAIL"
        )
    )

    output = {
        "staging_source":
            str(TACKLES_PATH),
        "merged_source":
            str(MERGED_PATH),
        "fixture_count": len(audits),
        "structure_verdict":
            structure_verdict,
        "merge_verdict":
            merge_verdict,
        "fixtures_structure_passed":
            len(audits)
            - len(structure_failed),
        "fixtures_merge_passed": sum(
            audit.get("merge_status")
            == "PASS"
            for audit in audits
        ),
        "critical_issue_count": sum(
            audit.get(
                "critical_issue_count",
                0,
            )
            for audit in audits
        ),
        "warning_count": sum(
            audit.get(
                "warning_count",
                0,
            )
            for audit in audits
        ),
        "manual_spot_check_count":
            len(spot_checks),
        "fixtures": audits,
    }

    temp_path = AUDIT_PATH.with_suffix(
        AUDIT_PATH.suffix + ".tmp"
    )
    temp_path.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temp_path.replace(AUDIT_PATH)

    with SPOT_CHECK_PATH.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "match",
                "player",
                "threshold",
                "odds",
                "decimal_odds",
                "source_url",
                "manual_result",
                "notes",
            ],
        )
        writer.writeheader()

        for row in spot_checks:
            writer.writerow(
                {
                    **row,
                    "manual_result": "",
                    "notes": "",
                }
            )

    print("\n" + "=" * 88)
    print(
        f"Structure verdict: "
        f"{structure_verdict}"
    )
    print(
        f"Merge verdict: "
        f"{merge_verdict}"
    )
    print(
        "Critical issues: "
        f"{output['critical_issue_count']}"
    )
    print(
        f"Warnings: "
        f"{output['warning_count']}"
    )
    print(f"Saved audit: {AUDIT_PATH}")
    print(
        "Saved manual spot checks: "
        f"{SPOT_CHECK_PATH}"
    )
    print("Production odds JSON modified: NO")


if __name__ == "__main__":
    main()
