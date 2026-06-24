#!/usr/bin/env python3
"""
audit_betvictor_player_stats_v10.py

Read-only validator for:
    football/data/
    betvictor_player_stats_exact_fast_test_v10_overlay_fix.json

It checks:
- duplicate player + threshold combinations;
- conflicting prices;
- malformed selections;
- threshold distribution;
- missing lower thresholds;
- gaps inside player ladders;
- odds that fail to increase as the requested threshold rises;
- comparison with the existing production exact-stat JSON when the same
  fixture and market are present.

It writes only:
    football/data/betvictor_player_stats_v10_audit.json

No scraper or production odds JSON is modified.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "football" / "data"

TEST_PATH = (
    DATA_DIR
    / "betvictor_player_stats_exact_fast_test_v10_overlay_fix.json"
)
PRODUCTION_PATH = (
    DATA_DIR
    / "betvictor_player_stats_exact.json"
)
OUT_PATH = (
    DATA_DIR
    / "betvictor_player_stats_v10_audit.json"
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
        fraction = Fraction(text)
        return 1.0 + float(fraction)
    except Exception:
        return None


def threshold_number(value: Any) -> int | None:
    match = THRESHOLD_RE.fullmatch(
        clean(value)
    )

    if not match:
        return None

    return int(match.group(1))


def market_key(market: dict[str, Any]) -> str:
    return normalize(
        market.get("normalized_market")
        or market.get("market")
    )


def index_production(
    path: Path,
) -> dict[tuple[str, str], dict[tuple[str, int], str]]:
    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return {}

    output = {}

    for match in data.get("matches", []):
        match_name = normalize(
            match.get("match")
        )

        for market in match.get("markets", []):
            key = market_key(market)

            if key not in {
                "player_shots_on_target",
                "player_shots",
                "player_fouls_committed",
            }:
                continue

            rows = {}

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
                    rows[(player, threshold)] = odds

            output[(match_name, key)] = rows

    return output


def audit_market(
    match_name: str,
    market: dict[str, Any],
    production_index: dict[
        tuple[str, str],
        dict[tuple[str, int], str],
    ],
) -> dict[str, Any]:
    key = market_key(market)
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
    duplicate_keys = []
    invalid_odds = []

    for selection in selections:
        player_raw = clean(
            selection.get("player")
        )
        player = normalize(player_raw)
        threshold = threshold_number(
            selection.get("threshold")
        )
        odds_raw = clean(
            selection.get("odds")
        ).upper()
        decimal = decimal_odds(odds_raw)

        if (
            not player
            or threshold is None
            or not odds_raw
        ):
            malformed.append(selection)
            continue

        if decimal is None:
            invalid_odds.append(selection)

        row = {
            "player": player_raw,
            "player_key": player,
            "threshold": threshold,
            "threshold_label": f"{threshold}+",
            "odds": odds_raw,
            "decimal_odds": decimal,
        }

        grouped[(player, threshold)].append(
            row
        )
        ladders[player].append(row)

    for key_tuple, rows in grouped.items():
        if len(rows) > 1:
            duplicate_keys.append(
                {
                    "player_key": key_tuple[0],
                    "threshold":
                        f"{key_tuple[1]}+",
                    "rows": rows,
                }
            )

    threshold_counts = Counter()
    ladder_gaps = []
    missing_lower_threshold = []
    odds_order_violations = []
    same_price_across_thresholds = []
    player_summaries = []

    for player, rows in ladders.items():
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
        expected = set(
            range(minimum, maximum + 1)
        )
        missing_inside = sorted(
            expected - set(thresholds)
        )

        if missing_inside:
            ladder_gaps.append(
                {
                    "player": rows[0]["player"],
                    "thresholds": thresholds,
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

            # A harder threshold must not be shorter than an easier one.
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
                same_price_across_thresholds.append(
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
                        "odds":
                            current["odds"],
                    }
                )

        player_summaries.append(
            {
                "player": rows[0]["player"],
                "thresholds": [
                    row["threshold_label"]
                    for row in rows
                ],
                "odds": [
                    row["odds"]
                    for row in rows
                ],
            }
        )

    player_summaries.sort(
        key=lambda row: (
            -len(row["thresholds"]),
            normalize(row["player"]),
        )
    )

    production_rows = production_index.get(
        (
            normalize(match_name),
            key,
        ),
        {},
    )

    overlap_count = 0
    matching_price_count = 0
    production_price_mismatches = []

    for player_threshold, rows in grouped.items():
        if player_threshold not in production_rows:
            continue

        overlap_count += 1
        current_odds = rows[0]["odds"]
        production_odds = production_rows[
            player_threshold
        ]

        if current_odds == production_odds:
            matching_price_count += 1
        else:
            production_price_mismatches.append(
                {
                    "player": rows[0]["player"],
                    "threshold":
                        rows[0]["threshold_label"],
                    "test_odds": current_odds,
                    "production_odds":
                        production_odds,
                }
            )

    selection_audit = market.get(
        "selection_audit",
        {},
    )

    critical_issues = (
        len(malformed)
        + len(invalid_odds)
        + len(duplicate_keys)
        + len(odds_order_violations)
    )

    warnings = (
        len(ladder_gaps)
        + len(missing_lower_threshold)
        + len(same_price_across_thresholds)
    )

    return {
        "match": match_name,
        "market": market.get("market"),
        "normalized_market": key,
        "reported_selection_count":
            market.get("selection_count"),
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
                    value
                    for _, value in grouped
                ),
                default=0,
            )}+"
        ),
        "selection_audit_from_scraper":
            selection_audit,
        "malformed_count": len(malformed),
        "invalid_odds_count":
            len(invalid_odds),
        "duplicate_player_threshold_count":
            len(duplicate_keys),
        "ladder_gap_count":
            len(ladder_gaps),
        "missing_lower_threshold_count":
            len(missing_lower_threshold),
        "odds_order_violation_count":
            len(odds_order_violations),
        "same_price_adjacent_threshold_count":
            len(same_price_across_thresholds),
        "production_overlap_count":
            overlap_count,
        "production_matching_price_count":
            matching_price_count,
        "production_price_mismatch_count":
            len(production_price_mismatches),
        "critical_issue_count":
            critical_issues,
        "warning_count": warnings,
        "verdict": (
            "PASS"
            if critical_issues == 0
            else "FAIL"
        ),
        "details": {
            "malformed": malformed,
            "invalid_odds": invalid_odds,
            "duplicates": duplicate_keys,
            "ladder_gaps": ladder_gaps,
            "missing_lower_threshold":
                missing_lower_threshold,
            "odds_order_violations":
                odds_order_violations,
            "same_price_across_thresholds":
                same_price_across_thresholds,
            "production_price_mismatches":
                production_price_mismatches,
            "sample_longest_ladders":
                player_summaries[:12],
        },
    }


def main() -> None:
    if not TEST_PATH.exists():
        raise SystemExit(
            f"Missing test file:\n{TEST_PATH}"
        )

    data = json.loads(
        TEST_PATH.read_text(encoding="utf-8")
    )
    production_index = index_production(
        PRODUCTION_PATH
    )

    audits = []

    print(
        "BETVICTOR PLAYER STATS V10 AUDIT"
    )
    print("=" * 76)
    print(f"Source: {TEST_PATH}")
    print(
        "Production comparison available: "
        f"{bool(production_index)}"
    )

    for match in data.get("matches", []):
        match_name = clean(
            match.get("match")
        )
        print(f"\n{match_name}")

        for market in match.get(
            "markets",
            [],
        ):
            audit = audit_market(
                match_name,
                market,
                production_index,
            )
            audits.append(audit)

            print(
                f"  {audit['market']:<28} "
                f"selections={audit['actual_selection_count']:<4} "
                f"players={audit['player_count']:<3} "
                f"duplicates="
                f"{audit['duplicate_player_threshold_count']:<2} "
                f"odds_order_errors="
                f"{audit['odds_order_violation_count']:<2} "
                f"gaps={audit['ladder_gap_count']:<2} "
                f"missing_1+="
                f"{audit['missing_lower_threshold_count']:<2} "
                f"{audit['verdict']}"
            )
            print(
                "    thresholds: "
                + json.dumps(
                    audit["threshold_counts"],
                    ensure_ascii=False,
                )
            )

            if audit[
                "production_overlap_count"
            ]:
                print(
                    "    production overlap: "
                    f"{audit['production_matching_price_count']}/"
                    f"{audit['production_overlap_count']} "
                    "same prices"
                )

    total_critical = sum(
        audit["critical_issue_count"]
        for audit in audits
    )
    total_warnings = sum(
        audit["warning_count"]
        for audit in audits
    )

    output = {
        "source": str(TEST_PATH),
        "production_comparison_source": (
            str(PRODUCTION_PATH)
            if PRODUCTION_PATH.exists()
            else None
        ),
        "market_count": len(audits),
        "markets_passed": sum(
            audit["verdict"] == "PASS"
            for audit in audits
        ),
        "critical_issue_count":
            total_critical,
        "warning_count": total_warnings,
        "overall_verdict": (
            "PASS"
            if total_critical == 0
            else "FAIL"
        ),
        "markets": audits,
    }

    temp_path = OUT_PATH.with_suffix(
        OUT_PATH.suffix + ".tmp"
    )
    temp_path.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temp_path.replace(OUT_PATH)

    print("\n" + "=" * 76)
    print(
        f"Overall verdict: "
        f"{output['overall_verdict']}"
    )
    print(
        f"Markets passed: "
        f"{output['markets_passed']}/"
        f"{output['market_count']}"
    )
    print(
        f"Critical issues: "
        f"{total_critical}"
    )
    print(
        f"Warnings: {total_warnings}"
    )
    print(f"Saved audit: {OUT_PATH}")
    print("Production files modified: NO")


if __name__ == "__main__":
    main()
