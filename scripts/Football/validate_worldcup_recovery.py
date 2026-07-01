#!/usr/bin/env python3
"""
Validate the focused World Cup site recovery before Git push.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "football" / "data"
SNAPSHOT = DATA / "midnite_worldcup_props_fixtures_prod15.json"
INDEX = ROOT / "football" / "world-cup" / "index.html"


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value: Any) -> str:
    text = (
        unicodedata.normalize("NFKD", clean(value))
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
        .replace("&", " and ")
    )
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def extract_teams(row: dict[str, Any]) -> tuple[str, str]:
    return (
        clean(row.get("home") or row.get("home_team")),
        clean(row.get("away") or row.get("away_team")),
    )


def json_matches(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("matches") or []
    return rows if isinstance(rows, list) else []


def main() -> None:
    snapshot_rows = json_matches(SNAPSHOT)
    allowed_slugs = {
        slugify(f"{home}-v-{away}")
        for row in snapshot_rows
        for home, away in [extract_teams(row)]
        if home and away
    }

    issues = []

    if len(allowed_slugs) != 7:
        issues.append(
            f"Expected 7 upcoming snapshot fixtures, found {len(allowed_slugs)}"
        )

    actual_dirs = {
        path.name
        for path in (ROOT / "football" / "world-cup").iterdir()
        if path.is_dir()
    }

    extras = sorted(actual_dirs - allowed_slugs)
    missing = sorted(allowed_slugs - actual_dirs)

    if extras:
        issues.append(
            "Stale generated match directories remain: "
            + ", ".join(extras[:10])
        )
    if missing:
        issues.append(
            "Upcoming generated match directories missing: "
            + ", ".join(missing[:10])
        )

    index_text = INDEX.read_text(
        encoding="utf-8",
        errors="replace",
    )

    for old_label in (
        "Thu 25 Jun 2026",
        "Fri 26 Jun 2026",
        "Ecuador v Germany",
        "Türkiye v USA",
        "Turkiye v USA",
    ):
        if old_label in index_text:
            issues.append(
                f"Old fixture still appears in World Cup index: {old_label}"
            )

    coverage = {}

    for bookmaker, filename, minimum in (
        (
            "LiveScoreBet",
            "livescorebet_worldcup_props.json",
            4,
        ),
        (
            "WilliamHill",
            "williamhill_worldcup_props.json",
            4,
        ),
    ):
        path = DATA / filename
        rows = json_matches(path)
        coverage[bookmaker] = len(rows)
        if len(rows) < minimum:
            issues.append(
                f"{bookmaker} props coverage only {len(rows)}; "
                f"expected at least {minimum}"
            )

    malformed = list(
        (ROOT / "football" / "world-cup").glob(
            "*/player-props/players/*-over-*"
        )
    )
    if malformed:
        issues.append(
            f"Malformed player directories remain: {len(malformed)}"
        )

    print("=" * 72)
    print("WORLD CUP RECOVERY VALIDATION")
    print("=" * 72)
    print(f"Upcoming snapshot fixtures: {len(allowed_slugs)}")
    print(f"Generated upcoming match directories: {len(actual_dirs)}")
    print(
        "LiveScoreBet props fixtures: "
        f"{coverage.get('LiveScoreBet', 0)}"
    )
    print(
        "William Hill props fixtures: "
        f"{coverage.get('WilliamHill', 0)}"
    )

    if issues:
        print("")
        print("VALIDATION: FAIL")
        for issue in issues:
            print(f"  - {issue}")
        raise SystemExit(1)

    print("")
    print("VALIDATION: PASS")


if __name__ == "__main__":
    main()
