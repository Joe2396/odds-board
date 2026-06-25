#!/usr/bin/env python3
"""
validate_worldcup_moneylines.py

Safety validator for BeatTheBooks World Cup moneyline data.

Purpose:
- Block only genuinely unsafe data: missing files, broken JSON, merge conflict junk,
  or bookmaker files with zero usable matches.
- Do NOT block just because a bookmaker has fewer fixtures than another bookmaker.
  That happens naturally when matches go live/finish or a book removes events.

Run from repo root:
  python validate_worldcup_moneylines.py
"""

import json
import re
import sys
from pathlib import Path

# WORLDCUP_VALIDATOR_LATE_TOURNAMENT_V1

ROOT = Path(__file__).resolve().parent

FILES = {
    "PaddyPower":  ROOT / "football" / "data" / "paddypower_worldcup_moneylines.json",
    "BoyleSports": ROOT / "football" / "data" / "boylesports_worldcup_moneylines.json",
    "BetVictor":   ROOT / "football" / "data" / "betvictor_worldcup_moneylines.json",
    "Unibet":      ROOT / "football" / "data" / "unibet_worldcup_moneylines.json",
    "LiveScoreBet":ROOT / "football" / "data" / "livescorebet_worldcup_moneylines.json",
    "WilliamHill": ROOT / "football" / "data" / "williamhill_worldcup_moneylines.json",
    "888Sport":    ROOT / "football" / "data" / "888sport_worldcup_moneylines.json",
    "Ladbrokes":   ROOT / "football" / "data" / "ladbrokes_worldcup_moneylines.json",
    "Midnite":     ROOT / "football" / "data" / "midnite_worldcup_moneylines.json",

    "Bwin":  ROOT / "football" / "data" / "bwin_worldcup_moneylines.json",}

MIN_GOOD_BOOKS = 5
MIN_TOTAL_UNIQUE_MATCHES = 30


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def norm_team(s):
    s = clean(s).lower().replace("&", "and")
    s = s.replace("bosnia and herzegovina", "bosnia")
    s = s.replace("czech republic", "czechia")
    s = s.replace("turkey", "turkiye").replace("türkiye", "turkiye")
    s = s.replace("curaçao", "curacao")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def split_match_name(name):
    name = clean(name)
    if " v " in name:
        h, a = name.split(" v ", 1)
        return h, a
    return "", ""


def get_matches(data):
    if isinstance(data, dict):
        rows = data.get("matches") or data.get("results") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    out = []
    for m in rows:
        if not isinstance(m, dict):
            continue

        home = (
            m.get("home_team")
            or m.get("home")
            or m.get("home_name")
            or ""
        )
        away = (
            m.get("away_team")
            or m.get("away")
            or m.get("away_name")
            or ""
        )

        if not home or not away:
            home, away = split_match_name(m.get("match") or m.get("name") or "")

        home = clean(home)
        away = clean(away)
        if not home or not away:
            continue

        odds = m.get("odds") or {}
        has_odds = False

        if isinstance(odds, dict):
            has_odds = bool(odds.get("home") or odds.get("draw") or odds.get("away"))

        # Midnite style
        if not has_odds:
            has_odds = bool(m.get("home_odds") or m.get("draw_odds") or m.get("away_odds"))

        if not has_odds:
            continue

        key = "__".join(sorted([norm_team(home), norm_team(away)]))
        out.append(key)

    return out


def main():
    print("Validating World Cup moneyline data...")

    hard_errors = []
    warnings = []
    good_books = 0
    all_keys = set()

    for book, path in FILES.items():
        if not path.exists():
            hard_errors.append(f"{book}: missing file {path}")
            continue

        text = path.read_text(encoding="utf-8", errors="replace")

        if any(marker in text for marker in ("<<<<<<<", "=======", ">>>>>>>")):
            hard_errors.append(f"{book}: merge conflict markers found")
            continue

        try:
            data = json.loads(text)
        except Exception as e:
            hard_errors.append(f"{book}: invalid JSON ({e})")
            continue

        matches = get_matches(data)
        count = len(matches)

        if count == 0:
            hard_errors.append(f"{book}: 0 usable moneyline matches")
            continue

        good_books += 1
        all_keys.update(matches)

        if count < 20:
            warnings.append(f"{book}: only {count} usable matches")
            print(f"{book}: WARN {count} usable matches")
        else:
            print(f"{book}: OK {count} usable matches")

    print(f"Unique fixtures across all books: {len(all_keys)}")
    print(f"Good bookmaker files: {good_books}/{len(FILES)}")

    if warnings:
        print()
        print("Warnings:")
        for w in warnings:
            print(" - " + w)

    if hard_errors:
        print()
        print("FAILED: unsafe moneyline data found:")
        for e in hard_errors:
            print(" - " + e)
        return 1

    if good_books < MIN_GOOD_BOOKS:
        print()
        print(f"FAILED: only {good_books} good bookmaker files, need at least {MIN_GOOD_BOOKS}.")
        return 1

    if len(all_keys) < MIN_TOTAL_UNIQUE_MATCHES:
        print()
        print(
            f"WARNING: only {len(all_keys)} unique fixtures across all books; "
            f"the historical warning threshold is {MIN_TOTAL_UNIQUE_MATCHES}. "
            "Continuing because the number of remaining fixtures naturally "
            "falls as the tournament progresses."
        )

    print()
    print("Validation passed: data is safe enough to build/push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
