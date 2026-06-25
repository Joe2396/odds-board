#!/usr/bin/env python3
"""
Inspect the existing V4 core-props debug files for the three remaining issues:

- Match Betting
- Anytime Goalscorer
- Total Cards Over/Under

This is read-only and does not rerun BetVictor or modify any JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "football" / "data"
DEBUG_ROOT = (
    ROOT
    / "football"
    / "debug"
    / "betvictor_worldcup_props_fast_test_v4_parse_fix"
)
RESULT_PATH = (
    DATA_DIR
    / "betvictor_worldcup_props_fast_test_v4_parse_fix.json"
)

ODDS_RE = re.compile(
    r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$",
    re.I,
)


def clean(value: object) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def slugify(value: object) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value or "").lower(),
    ).strip("-")


def load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []

    return [
        clean(line)
        for line in path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        if clean(line)
    ]


def print_windows(
    lines: list[str],
    patterns: Iterable[str],
    before: int = 5,
    after: int = 18,
    max_windows: int = 8,
) -> None:
    compiled = [
        re.compile(pattern, re.I)
        for pattern in patterns
    ]
    matches = []

    for index, line in enumerate(lines):
        if any(
            pattern.search(line)
            for pattern in compiled
        ):
            matches.append(index)

    if not matches:
        print("    No matching lines found.")
        return

    windows = []
    last_end = -1

    for index in matches:
        start = max(0, index - before)
        end = min(
            len(lines),
            index + after + 1,
        )

        if start <= last_end:
            continue

        windows.append((start, end))
        last_end = end

        if len(windows) >= max_windows:
            break

    for window_number, (start, end) in enumerate(
        windows,
        start=1,
    ):
        print(
            f"    --- window {window_number} "
            f"(lines {start + 1}-{end}) ---"
        )

        for index in range(start, end):
            marker = ">>" if index in matches else "  "
            print(
                f"    {marker} {index + 1:04d}: "
                f"{lines[index]}"
            )


def print_three_way_candidates(
    lines: list[str],
    home: str,
    away: str,
) -> None:
    labels = {
        "1",
        "x",
        "2",
        "home",
        "draw",
        "away",
        clean(home).lower(),
        clean(away).lower(),
    }

    candidates = []

    for index, line in enumerate(lines):
        lower = line.lower()

        if lower not in labels:
            continue

        nearby = lines[
            index:min(index + 6, len(lines))
        ]
        odds = [
            item
            for item in nearby
            if ODDS_RE.fullmatch(item)
        ]

        if odds:
            candidates.append(
                (
                    index,
                    nearby,
                )
            )

    if not candidates:
        print(
            "    No obvious 1/X/2 or "
            "Home/Draw/Away candidates."
        )
        return

    print(
        "    Potential Match Betting "
        "label/odds sequences:"
    )

    for index, nearby in candidates[:15]:
        print(
            f"      line {index + 1}: "
            + " | ".join(nearby)
        )


def main() -> None:
    if not RESULT_PATH.exists():
        raise SystemExit(
            f"Missing V4 result JSON:\n"
            f"{RESULT_PATH}"
        )

    if not DEBUG_ROOT.exists():
        raise SystemExit(
            f"Missing V4 debug directory:\n"
            f"{DEBUG_ROOT}"
        )

    data = json.loads(
        RESULT_PATH.read_text(
            encoding="utf-8"
        )
    )

    print(
        "BETVICTOR CORE V4 — "
        "MISSING MARKET INSPECTOR"
    )
    print("=" * 84)
    print(f"Debug root: {DEBUG_ROOT}")
    print(
        "This script is read-only and "
        "does not open BetVictor."
    )

    for match in data.get("matches", []):
        match_name = clean(
            match.get("match")
        )
        home = clean(
            match.get("home_team")
            or match.get("home")
        )
        away = clean(
            match.get("away_team")
            or match.get("away")
        )
        fixture_dir = (
            DEBUG_ROOT
            / slugify(match_name)
        )

        popular_lines = load_lines(
            fixture_dir / "popular.txt"
        )
        goals_lines = load_lines(
            fixture_dir / "goals.txt"
        )
        cards_lines = load_lines(
            fixture_dir / "cards.txt"
        )

        print("\n" + "=" * 84)
        print(match_name)
        print(
            f"  popular={len(popular_lines)} lines | "
            f"goals={len(goals_lines)} lines | "
            f"cards={len(cards_lines)} lines"
        )

        print("\n  MATCH BETTING WINDOWS")
        print_windows(
            popular_lines,
            [
                r"match betting",
                r"match result",
                r"match odds",
                r"1x2",
                rf"^{re.escape(home)}$",
                rf"^{re.escape(away)}$",
                r"^home$",
                r"^draw$",
                r"^away$",
                r"^1$",
                r"^x$",
                r"^2$",
            ],
            before=5,
            after=15,
            max_windows=7,
        )
        print_three_way_candidates(
            popular_lines,
            home,
            away,
        )

        print("\n  GOALSCORER WINDOWS")
        print_windows(
            goals_lines,
            [
                r"goal.*scorer",
                r"scorer",
                r"player.*score",
                r"to score",
                r"anytime",
                r"first",
                r"last",
            ],
            before=5,
            after=22,
            max_windows=10,
        )

        print("\n  TOTAL CARDS WINDOWS")
        print_windows(
            cards_lines,
            [
                r"total.*cards",
                r"cards.*total",
                r"card.*over",
                r"over.*card",
                r"90.*min.*card",
                r"booking",
            ],
            before=5,
            after=26,
            max_windows=8,
        )

    print("\n" + "=" * 84)
    print(
        "Inspection complete. "
        "Production files modified: NO"
    )


if __name__ == "__main__":
    main()
