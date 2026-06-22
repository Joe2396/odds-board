#!/usr/bin/env python3
"""
Patch scripts/build_arbitrage_all.py so the combined board renders:
- Over/Under
- BTTS
- Double Chance
- Half Time Result
- Moneyline

Run from the odds-board repository root:
    python patch_build_arbitrage_all_named_markets.py
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scripts" / "build_arbitrage_all.py"
BACKUP = TARGET.with_name("build_arbitrage_all.before_named_markets.py")

NEW_FUNCTION = 'def normalize_football():\n    data = load_json(FOOTBALL_ARB_PATH)\n    rows = data.get("arbitrage") or data.get("arbitrage_opportunities") or []\n    out = []\n\n    type_orders = {\n        "moneyline_1x2": ["home", "draw", "away"],\n        "props_ou": ["over", "under"],\n        "props_btts": ["yes", "no"],\n        "props_half_time_result": ["home", "draw", "away"],\n        "props_double_chance": [\n            "home_draw", "away_draw", "home_away"\n        ],\n    }\n\n    for row in rows:\n        selections = row.get("selections") or {}\n        row_type = row.get("type") or "moneyline_1x2"\n        order = type_orders.get(row_type, list(selections.keys()))\n        books = []\n\n        for key in order:\n            info = selections.get(key) or {}\n            if not info:\n                continue\n\n            label = info.get("selection_label") or ""\n\n            if not label:\n                if key == "home":\n                    label = row.get("home_team") or "Home"\n                elif key == "away":\n                    label = row.get("away_team") or "Away"\n                elif key == "draw":\n                    label = "Draw"\n                elif key == "over":\n                    label = f"Over {row.get(\'line\', \'\')}".strip()\n                elif key == "under":\n                    label = f"Under {row.get(\'line\', \'\')}".strip()\n                elif key == "yes":\n                    label = "Yes"\n                elif key == "no":\n                    label = "No"\n                elif key == "home_draw":\n                    label = "Home or Draw"\n                elif key == "away_draw":\n                    label = "Away or Draw"\n                elif key == "home_away":\n                    label = "Home or Away"\n                else:\n                    label = key.replace("_", " ").title()\n\n            books.append({\n                "selection": label,\n                "bookmaker": info.get("bookmaker") or "",\n                "odds": info.get("odds") or "",\n                "decimal_odds": info.get("decimal_odds") or info.get("decimal") or "",\n                "implied_probability": info.get("implied_probability") or "",\n            })\n\n        out.append({\n            "sport": "Football",\n            "competition": row.get("competition") or "FIFA World Cup",\n            "event": row.get("match") or "",\n            "market": row.get("market") or "Match Odds",\n            "type": row_type,\n            "date_label": row.get("date_label") or "",\n            "time": row.get("time") or "",\n            "profit_margin_percent": normalize_profit(row),\n            "arb_percent": row.get("arb_percent") or "",\n            "arb_sum": row.get("arb_sum") or "",\n            "bookmaker_count": row.get("bookmaker_count") or len({\n                book.get("bookmaker") for book in books if book.get("bookmaker")\n            }),\n            "bookmakers": books,\n            "source_file": "football/data/arbitrage.json",\n        })\n\n    return out, data\n'


def replace_function(source, name, replacement):
    match = re.search(rf"(?m)^def {re.escape(name)}\s*\(", source)
    if not match:
        raise RuntimeError(f"Could not find {name}()")

    next_def = re.search(r"(?m)^def \w+\s*\(", source[match.end():])
    end = len(source) if not next_def else match.end() + next_def.start()

    return source[:match.start()] + replacement.rstrip() + "\n\n" + source[end:]


def main():
    if not TARGET.exists():
        raise SystemExit(f"Target not found: {TARGET}")

    source = TARGET.read_text(encoding="utf-8")
    patched = replace_function(source, "normalize_football", NEW_FUNCTION)
    ast.parse(patched)

    if not BACKUP.exists():
        BACKUP.write_text(source, encoding="utf-8")

    TARGET.write_text(patched, encoding="utf-8")

    print(f"Updated: {TARGET}")
    print(f"Backup:  {BACKUP}")
    print("Syntax validation: OK")
    print("Combined board now renders all football arb selection types.")


if __name__ == "__main__":
    main()
