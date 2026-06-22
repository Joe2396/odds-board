#!/usr/bin/env python3
"""
Permanent Ladbrokes Double Chance fix — robust version.

This version does not depend on the exact spacing or tuple formatting inside
parse_all(). It replaces only parse_double_chance(), adds analyzer validation,
and repairs the current JSON.

Run from the odds-board repository root:

    python fix_ladbrokes_double_chance_long_term_FIXED.py
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SCRAPER = ROOT / "scripts" / "Football" / "fetch_ladbrokes_worldcup_props.py"
ANALYZER = ROOT / "scripts" / "Football" / "analyze_football_arbitrage.py"
DATA = ROOT / "football" / "data" / "ladbrokes_worldcup_props.json"

SCRAPER_BACKUP = SCRAPER.with_name(
    "fetch_ladbrokes_worldcup_props.before_double_chance_fix.py"
)
ANALYZER_BACKUP = ANALYZER.with_name(
    "analyze_football_arbitrage.before_ladbrokes_dc_fix.py"
)
DATA_BACKUP = DATA.with_name(
    "ladbrokes_worldcup_props.before_double_chance_fix.json"
)

NEW_PARSE_DOUBLE_CHANCE = 'def parse_double_chance(lines, home="", away=""):\n    """\n    Parse only the standard 90-minute Double Chance triplet.\n\n    This version does not rely on each label being immediately followed by its\n    price. Ladbrokes commonly renders all labels first, followed by a 90 Mins\n    row containing the three prices.\n    """\n    selections = []\n\n    idx = next(\n        (i for i, line in enumerate(lines) if clean(line) == "Double Chance"),\n        -1,\n    )\n    if idx == -1:\n        return mkt("Double Chance", selections)\n\n    block = lines[idx:idx + 35]\n    label_map = {\n        "1X": ("home_draw", f"{home or \'Home\'} or Draw"),\n        "X2": ("away_draw", f"{away or \'Away\'} or Draw"),\n        "12": ("home_away", f"{home or \'Home\'} or {away or \'Away\'}"),\n    }\n\n    ordered_labels = []\n    for line in block:\n        label = clean(line)\n        if label in label_map and label not in ordered_labels:\n            ordered_labels.append(label)\n\n    if set(ordered_labels) != {"1X", "X2", "12"}:\n        return mkt("Double Chance", selections)\n\n    odds = []\n\n    # Preferred Ladbrokes layout: "90 Mins" followed by three prices.\n    ninety_idx = next(\n        (i for i, line in enumerate(block) if clean(line) == "90 Mins"),\n        -1,\n    )\n    if ninety_idx >= 0:\n        odds = [\n            clean(line)\n            for line in block[ninety_idx + 1:ninety_idx + 10]\n            if is_odds(line)\n        ][:3]\n\n    # Fallback: first three prices after all labels.\n    if len(odds) != 3:\n        last_label_idx = max(\n            i for i, line in enumerate(block)\n            if clean(line) in label_map\n        )\n        odds = [\n            clean(line)\n            for line in block[last_label_idx + 1:last_label_idx + 12]\n            if is_odds(line)\n        ][:3]\n\n    # Final fallback: a true alternating label/price layout.\n    if len(odds) != 3:\n        direct = {}\n        for i, line in enumerate(block):\n            label = clean(line)\n            if (\n                label in label_map\n                and i + 1 < len(block)\n                and is_odds(block[i + 1])\n            ):\n                direct[label] = clean(block[i + 1])\n\n        if set(direct) == {"1X", "X2", "12"}:\n            odds = [direct[label] for label in ordered_labels]\n\n    if len(odds) != 3:\n        return mkt("Double Chance", selections)\n\n    def decimal(price):\n        price = clean(price).upper()\n        if price in {"EVS", "EVENS", "EVEN"}:\n            return 2.0\n        if "/" not in price:\n            return None\n        try:\n            num, den = price.split("/", 1)\n            return (float(num) / float(den)) + 1.0\n        except Exception:\n            return None\n\n    decimals = [decimal(price) for price in odds]\n    if any(not value or value <= 1 for value in decimals):\n        return mkt("Double Chance", selections)\n\n    # A complete Double Chance triplet should be close to 1 after accounting\n    # for the overlapping outcomes. A much smaller value means wrong prices.\n    self_arb_sum = 0.5 * sum(1.0 / value for value in decimals)\n    if not 0.97 <= self_arb_sum <= 1.25:\n        print(\n            f"    Rejecting invalid Ladbrokes Double Chance triplet: "\n            f"{odds} (self sum {self_arb_sum:.3f})"\n        )\n        return mkt("Double Chance", selections)\n\n    for label, price in zip(ordered_labels, odds):\n        side, display = label_map[label]\n        selections.append(\n            sel(\n                display,\n                price,\n                {\n                    "side": side,\n                    "base_market": "double_chance",\n                    "period": "full_time",\n                },\n            )\n        )\n\n    return mkt("Double Chance", selections)\n'
NEW_GUARD_HELPER = 'def validate_double_chance_source_triplets(data, audit):\n    """\n    Remove a bookmaker\'s Double Chance offers for a fixture unless that source\n    supplied a complete and internally plausible triplet.\n    """\n    for fixture in data.values():\n        dc = fixture.get("double_chance") or {}\n        outcomes = ("home_draw", "away_draw", "home_away")\n\n        bookmakers = set()\n        for outcome in outcomes:\n            for offer in dc.get(outcome) or []:\n                bookmakers.add(offer.get("bookmaker"))\n\n        for bookmaker in sorted(bookmakers):\n            offers = {}\n\n            for outcome in outcomes:\n                candidates = [\n                    offer\n                    for offer in dc.get(outcome) or []\n                    if offer.get("bookmaker") == bookmaker\n                ]\n                if candidates:\n                    offers[outcome] = max(\n                        candidates,\n                        key=lambda offer: offer["decimal"],\n                    )\n\n            valid = len(offers) == 3\n            self_sum = None\n\n            if valid:\n                self_sum = 0.5 * sum(\n                    1.0 / offers[outcome]["decimal"]\n                    for outcome in outcomes\n                )\n                valid = 0.97 <= self_sum <= 1.25\n\n            if valid:\n                continue\n\n            removed = 0\n            for outcome in outcomes:\n                before = len(dc.get(outcome) or [])\n                dc[outcome] = [\n                    offer\n                    for offer in dc.get(outcome) or []\n                    if offer.get("bookmaker") != bookmaker\n                ]\n                removed += before - len(dc[outcome])\n\n            if removed:\n                counts = audit.setdefault(\n                    bookmaker,\n                    {"matches": 0, "offers": 0},\n                )\n                counts["double_chance_rejected"] = (\n                    counts.get("double_chance_rejected", 0) + removed\n                )\n                detail = (\n                    f"{self_sum:.3f}"\n                    if self_sum is not None\n                    else "incomplete"\n                )\n                print(\n                    f"  Double Chance safety: removed {removed} "\n                    f"{bookmaker} offer(s) for {fixture.get(\'match\')} "\n                    f"(self sum {detail})"\n                )\n'


def replace_function(source, name, replacement):
    match = re.search(rf"(?m)^def {re.escape(name)}\s*\(", source)
    if not match:
        raise RuntimeError(f"Could not find {name}()")

    next_def = re.search(r"(?m)^def \w+\s*\(", source[match.end():])
    end = len(source) if not next_def else match.end() + next_def.start()

    return source[:match.start()] + replacement.rstrip() + "\n\n" + source[end:]


def patch_scraper():
    original = SCRAPER.read_text(encoding="utf-8")
    patched = replace_function(
        original,
        "parse_double_chance",
        NEW_PARSE_DOUBLE_CHANCE,
    )

    ast.parse(patched)

    if not SCRAPER_BACKUP.exists():
        SCRAPER_BACKUP.write_text(original, encoding="utf-8")
    SCRAPER.write_text(patched, encoding="utf-8")

    print(f"Patched scraper: {SCRAPER}")
    print(f"Backup: {SCRAPER_BACKUP}")


def patch_analyzer():
    original = ANALYZER.read_text(encoding="utf-8")
    patched = original

    if "def validate_double_chance_source_triplets(" not in patched:
        marker = "def scan_named_prop_arbitrage(root):"
        idx = patched.find(marker)
        if idx < 0:
            raise RuntimeError("Could not find scan_named_prop_arbitrage()")
        patched = (
            patched[:idx]
            + NEW_GUARD_HELPER.rstrip()
            + "\n\n\n"
            + patched[idx:]
        )

    function_start = patched.find("def scan_named_prop_arbitrage(root):")
    arbs_marker = patched.find("\n    arbs = []", function_start)
    if arbs_marker < 0:
        raise RuntimeError("Could not find named-market arb list initialization")

    call = "\n    validate_double_chance_source_triplets(data, audit)\n"
    if "validate_double_chance_source_triplets(data, audit)" not in patched[
        function_start:arbs_marker
    ]:
        patched = patched[:arbs_marker] + call + patched[arbs_marker:]

    ast.parse(patched)

    if not ANALYZER_BACKUP.exists():
        ANALYZER_BACKUP.write_text(original, encoding="utf-8")
    ANALYZER.write_text(patched, encoding="utf-8")

    print(f"Patched analyzer: {ANALYZER}")
    print(f"Backup: {ANALYZER_BACKUP}")


def decimal(price):
    price = str(price or "").strip().upper()
    if price in {"EVS", "EVENS", "EVEN"}:
        return 2.0
    if "/" not in price:
        return None
    try:
        num, den = price.split("/", 1)
        return (float(num) / float(den)) + 1.0
    except Exception:
        return None


def normalized(value):
    value = str(value or "").lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def repair_current_json():
    if not DATA.exists():
        print(f"Current Ladbrokes JSON not found: {DATA}")
        return

    if not DATA_BACKUP.exists():
        shutil.copy2(DATA, DATA_BACKUP)

    payload = json.loads(DATA.read_text(encoding="utf-8"))
    removed = 0
    kept = 0

    for match in payload.get("matches") or []:
        markets = match.get("markets") or []
        if not isinstance(markets, list):
            continue

        repaired_markets = []

        for market in markets:
            market_key = normalized(
                market.get("normalized_market")
                or market.get("market")
            )
            if market_key != "double_chance":
                repaired_markets.append(market)
                continue

            by_side = {}
            for selection in market.get("selections") or []:
                side = normalized(selection.get("side") or "")

                # Support old labels with no side metadata.
                if not side:
                    label = normalized(selection.get("selection") or "")
                    if label in {"home_or_draw", "1x"}:
                        side = "home_draw"
                    elif label in {"away_or_draw", "x2"}:
                        side = "away_draw"
                    elif label in {"home_or_away", "12"}:
                        side = "home_away"

                if side in {"home_draw", "away_draw", "home_away"}:
                    by_side[side] = selection

            valid = set(by_side) == {
                "home_draw",
                "away_draw",
                "home_away",
            }

            self_sum = None
            if valid:
                prices = [
                    decimal(by_side[side].get("odds"))
                    for side in (
                        "home_draw",
                        "away_draw",
                        "home_away",
                    )
                ]
                valid = all(prices)
                if valid:
                    self_sum = 0.5 * sum(1.0 / price for price in prices)
                    valid = 0.97 <= self_sum <= 1.25

            if valid:
                repaired_markets.append(market)
                kept += 1
            else:
                removed += 1
                detail = (
                    f" self sum={self_sum:.3f}"
                    if self_sum is not None
                    else ""
                )
                print(
                    f"Removed malformed Ladbrokes Double Chance: "
                    f"{match.get('match')}{detail}"
                )

        match["markets"] = repaired_markets
        if "market_count" in match:
            match["market_count"] = len(repaired_markets)

    DATA.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Current JSON Double Chance kept: {kept}")
    print(f"Current JSON Double Chance removed: {removed}")
    print(f"JSON backup: {DATA_BACKUP}")


def main():
    patch_scraper()
    patch_analyzer()
    repair_current_json()

    print("")
    print("Ladbrokes Double Chance long-term fix completed.")
    print("Rebuild with:")
    print(r"  python scripts\Football\analyze_football_arbitrage.py")
    print(r"  python scripts\build_arbitrage_all.py")


if __name__ == "__main__":
    main()
