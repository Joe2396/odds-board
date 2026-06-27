#!/usr/bin/env python3
"""
Remove stale World Cup match directories before regenerating the site.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = (
    ROOT
    / "football"
    / "data"
    / "midnite_worldcup_props_fixtures_prod15.json"
)
OUT_DIR = ROOT / "football" / "world-cup"


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


def teams(row: dict[str, Any]) -> tuple[str, str]:
    home = clean(row.get("home") or row.get("home_team"))
    away = clean(row.get("away") or row.get("away_team"))
    return home, away


def main() -> None:
    payload = json.loads(
        SNAPSHOT_PATH.read_text(encoding="utf-8")
    )
    matches = payload.get("matches") or []

    allowed = {
        slugify(f"{home}-v-{away}")
        for row in matches
        for home, away in [teams(row)]
        if home and away
    }

    if len(allowed) < 5:
        raise RuntimeError(
            f"Only {len(allowed)} allowed match directories resolved"
        )

    removed = []

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for path in OUT_DIR.iterdir():
        if not path.is_dir():
            continue
        if path.name not in allowed:
            shutil.rmtree(path)
            removed.append(path.name)

    malformed = []
    bad_pattern = re.compile(
        r"(^u-[0-9]|-(?:over|under)-[0-9]|"
        r"corners|win-or-draw|win-either-half|yes-and-|no-and-)",
        re.IGNORECASE,
    )

    for players_dir in OUT_DIR.glob(
        "*/player-props/players"
    ):
        if not players_dir.is_dir():
            continue
        for player_dir in players_dir.iterdir():
            if (
                player_dir.is_dir()
                and bad_pattern.search(player_dir.name)
            ):
                shutil.rmtree(player_dir)
                malformed.append(str(player_dir))

    print("=" * 72)
    print("WORLD CUP GENERATED OUTPUT CLEANUP")
    print("=" * 72)
    print(f"Allowed upcoming match directories: {len(allowed)}")
    print(f"Stale match directories removed: {len(removed)}")
    print(f"Malformed player directories removed: {len(malformed)}")


if __name__ == "__main__":
    main()
