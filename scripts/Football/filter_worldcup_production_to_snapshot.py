#!/usr/bin/env python3
"""
Keep World Cup production JSON aligned to the shared upcoming-15 snapshot.

The shared snapshot is created by:
    prepare_midnite_worldcup_props_fixtures.py

This script does not alter odds or markets. It removes completed/old fixtures
from top-level production JSON files by matching team pairs against that
snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "football" / "data"
SNAPSHOT_PATH = DATA_DIR / "midnite_worldcup_props_fixtures_prod15.json"

EXCLUDED_NAME_PARTS = (
    "test",
    "before",
    "audit",
    "backup",
    "debug",
    "profile",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def ascii_text(value: Any) -> str:
    return (
        unicodedata.normalize("NFKD", clean(value))
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def team_key(value: Any) -> str:
    text = ascii_text(value).casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()

    aliases = {
        "united states": "usa",
        "u s a": "usa",
        "us": "usa",
        "turkey": "turkiye",
        "turkiye": "turkiye",
        "bosnia and herzegovina": "bosnia",
        "bosnia herzegovina": "bosnia",
        "czech republic": "czechia",
        "cote d ivoire": "ivory coast",
        "democratic republic of congo": "dr congo",
        "congo dr": "dr congo",
        "korea republic": "south korea",
        "republic of korea": "south korea",
        "cabo verde": "cape verde",
    }
    return aliases.get(text, text)


def pair_key(home: Any, away: Any) -> str:
    teams = sorted((team_key(home), team_key(away)))
    if not all(teams):
        return ""
    return "__".join(teams)


def extract_teams(row: dict[str, Any]) -> tuple[str, str]:
    home = clean(row.get("home_team") or row.get("home"))
    away = clean(row.get("away_team") or row.get("away"))

    if home and away:
        return home, away

    label = clean(
        row.get("match")
        or row.get("name")
        or row.get("fixture")
    )

    for delimiter in (" v ", " vs ", " - "):
        if delimiter in label:
            left, right = label.split(delimiter, 1)
            return clean(left), clean(right)

    return "", ""


def load_allowed_pairs() -> tuple[set[str], list[dict[str, Any]]]:
    if not SNAPSHOT_PATH.exists():
        raise FileNotFoundError(
            f"Upcoming fixture snapshot missing: {SNAPSHOT_PATH}"
        )

    payload = json.loads(
        SNAPSHOT_PATH.read_text(encoding="utf-8")
    )
    matches = payload.get("matches") or []

    if not isinstance(matches, list) or not matches:
        raise RuntimeError(
            "Upcoming fixture snapshot has no matches"
        )

    allowed: set[str] = set()
    for row in matches:
        home, away = extract_teams(row)
        key = pair_key(home, away)
        if key:
            allowed.add(key)

    if len(allowed) < 5:
        raise RuntimeError(
            f"Snapshot produced only {len(allowed)} usable team pairs"
        )

    return allowed, matches


def is_production_file(path: Path) -> bool:
    low = path.name.casefold()
    if path.suffix.casefold() != ".json":
        return False
    if any(part in low for part in EXCLUDED_NAME_PARTS):
        return False
    return True


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{path.stem}_pending_",
        suffix=".json",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                ensure_ascii=False,
            )
            handle.flush()
            os.fsync(handle.fileno())

        json.loads(temp_path.read_text(encoding="utf-8"))
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def filter_file(path: Path, allowed: set[str]) -> tuple[int, int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0, 0

    if not isinstance(payload, dict):
        return 0, 0, 0

    matches = payload.get("matches")
    if not isinstance(matches, list):
        return 0, 0, 0

    kept = []
    removed = 0
    unkeyed = 0

    for row in matches:
        if not isinstance(row, dict):
            kept.append(row)
            unkeyed += 1
            continue

        home, away = extract_teams(row)
        key = pair_key(home, away)

        if not key:
            kept.append(row)
            unkeyed += 1
        elif key in allowed:
            kept.append(row)
        else:
            removed += 1

    if removed:
        payload["matches"] = kept
        for count_key in (
            "match_count",
            "selected_match_count",
            "matches_scraped",
        ):
            if count_key in payload:
                payload[count_key] = len(kept)

        atomic_write(path, payload)

    return len(matches), len(kept), unkeyed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        help="A filename inside football/data. Can be repeated.",
    )
    parser.add_argument(
        "--all-production",
        action="store_true",
        help="Filter all top-level production JSON files with a matches list.",
    )
    args = parser.parse_args()

    allowed, snapshot_matches = load_allowed_pairs()

    if args.file:
        paths = [DATA_DIR / name for name in args.file]
    elif args.all_production:
        paths = [
            path
            for path in sorted(DATA_DIR.glob("*.json"))
            if is_production_file(path)
        ]
    else:
        raise SystemExit(
            "Use --file <name> or --all-production"
        )

    print("=" * 72)
    print("WORLD CUP PRODUCTION SNAPSHOT FILTER")
    print("=" * 72)
    print(f"Upcoming snapshot fixtures: {len(snapshot_matches)}")
    print(f"Usable pair keys: {len(allowed)}")

    touched = 0
    total_removed = 0

    for path in paths:
        if not path.exists():
            print(f"SKIP missing: {path.name}")
            continue

        before, after, unkeyed = filter_file(path, allowed)
        if before == 0:
            continue

        removed = before - after
        if removed:
            touched += 1
            total_removed += removed
            print(
                f"FILTERED {path.name}: "
                f"{before} -> {after} "
                f"(removed {removed}, unkeyed kept {unkeyed})"
            )

    print("")
    print(f"Files changed: {touched}")
    print(f"Old fixture rows removed: {total_removed}")


if __name__ == "__main__":
    main()
