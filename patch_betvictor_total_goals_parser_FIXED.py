#!/usr/bin/env python3
"""
Patch BetVictor Total Goals parsing so the scraper never invents or shifts
a missing 0.5 line when the bookmaker market starts at 1.5.

Run from the odds-board repository root:
    python patch_betvictor_total_goals_parser_FIXED.py
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scripts" / "Football" / "fetch_betvictor_worldcup_props.py"
BACKUP = TARGET.with_name("fetch_betvictor_worldcup_props.before_goal_line_fix.py")

PARSE_OVER_UNDER = 'def parse_over_under(lines, title, market_name):\n    block = find_block(lines, title, 120)\n\n    if not block:\n        idxs = [\n            i for i, x in enumerate(lines)\n            if clean(title).lower() in clean(x).lower()\n        ]\n        if idxs:\n            block = lines[idxs[0]:idxs[0] + 120]\n\n    out = []\n    seen = set()\n\n    def add(side, line, odds):\n        side = clean(side).lower()\n        line = clean(line)\n        odds = clean(odds)\n\n        if side not in {"over", "under"}:\n            return\n        if not re.fullmatch(r"\\d+(?:\\.\\d+)?", line):\n            return\n        if not is_odds(odds):\n            return\n\n        key = (side, line)\n        if key in seen:\n            return\n        seen.add(key)\n\n        out.append(\n            sel(\n                f"{side.title()} {line}",\n                odds,\n                side=side,\n                line=line,\n            )\n        )\n\n    # Parse explicit BetVictor rows first:\n    # O 1.5\n    # 1/6\n    # U 1.5\n    # 4/1\n    explicit_started = False\n    misses_after_start = 0\n    i = 0\n\n    while i < len(block):\n        token = clean(block[i])\n        explicit = re.fullmatch(\n            r"(O|U|Over|Under)\\s*(\\d+(?:\\.\\d+)?)",\n            token,\n            re.I,\n        )\n\n        if explicit and i + 1 < len(block) and is_odds(block[i + 1]):\n            side_token = explicit.group(1).lower()\n            side = "over" if side_token in {"o", "over"} else "under"\n            add(side, explicit.group(2), block[i + 1])\n            explicit_started = True\n            misses_after_start = 0\n            i += 2\n            continue\n\n        if explicit_started:\n            if token not in {"Show More", "Show Less", "Over", "Under"} and not is_odds(token):\n                misses_after_start += 1\n                if misses_after_start >= 2:\n                    break\n\n        i += 1\n\n    if out:\n        return market(market_name, out)\n\n    # Fallback for a genuine two-column layout.\n    first_line_idx = next(\n        (\n            i for i, token in enumerate(block)\n            if re.fullmatch(r"\\d+(?:\\.\\d+)?", clean(token))\n        ),\n        -1,\n    )\n    over_header_idx = next(\n        (i for i, token in enumerate(block) if clean(token).lower() == "over"),\n        -1,\n    )\n    under_header_idx = next(\n        (i for i, token in enumerate(block) if clean(token).lower() == "under"),\n        -1,\n    )\n\n    if (\n        first_line_idx >= 0\n        and over_header_idx >= 0\n        and under_header_idx >= 0\n        and over_header_idx < first_line_idx\n        and under_header_idx < first_line_idx\n    ):\n        i = first_line_idx\n        while i < len(block):\n            token = clean(block[i])\n\n            if not re.fullmatch(r"\\d+(?:\\.\\d+)?", token):\n                i += 1\n                continue\n\n            odds = []\n            j = i + 1\n            while j < min(i + 7, len(block)):\n                nxt = clean(block[j])\n\n                if re.fullmatch(r"\\d+(?:\\.\\d+)?", nxt):\n                    break\n                if is_odds(nxt):\n                    odds.append(nxt)\n                    if len(odds) == 2:\n                        break\n                j += 1\n\n            if len(odds) == 2:\n                add("over", token, odds[0])\n                add("under", token, odds[1])\n                i = j + 1\n            else:\n                i += 1\n\n        if out:\n            return market(market_name, out)\n\n    # Final fallback for separate Over and Under blocks.\n    mode = None\n    i = 0\n    while i < len(block):\n        token = clean(block[i])\n        lower = token.lower()\n\n        if lower == "over":\n            mode = "over"\n            i += 1\n            continue\n        if lower == "under":\n            mode = "under"\n            i += 1\n            continue\n\n        if (\n            mode\n            and re.fullmatch(r"\\d+(?:\\.\\d+)?", token)\n            and i + 1 < len(block)\n            and is_odds(block[i + 1])\n        ):\n            add(mode, token, block[i + 1])\n            i += 2\n            continue\n\n        i += 1\n\n    return market(market_name, out)\n'

PARSE_TOTAL_GOALS = 'def parse_total_goals(lines):\n    selections = []\n\n    idx = next(\n        (\n            i for i, line in enumerate(lines)\n            if "total goals over/under" in clean(line).lower()\n        ),\n        -1,\n    )\n    if idx == -1:\n        idx = next(\n            (i for i, line in enumerate(lines) if clean(line).lower() == "total goals"),\n            -1,\n        )\n    if idx == -1:\n        return mkt("Total Goals Over / Under", selections)\n\n    block = lines[idx:idx + 90]\n    seen = set()\n    started = False\n    misses_after_start = 0\n    i = 0\n\n    while i < len(block):\n        token = clean(block[i])\n        explicit = re.fullmatch(\n            r"(O|U|Over|Under)\\s*(\\d+(?:\\.\\d+)?)",\n            token,\n            re.I,\n        )\n\n        if explicit and i + 1 < len(block) and is_odds(block[i + 1]):\n            side_token = explicit.group(1).lower()\n            side = "over" if side_token in {"o", "over"} else "under"\n            line = explicit.group(2)\n            key = (side, line)\n\n            if key not in seen:\n                seen.add(key)\n                selections.append(\n                    sel(\n                        f"{side.title()} {line}",\n                        block[i + 1],\n                        {"side": side, "line": line},\n                    )\n                )\n\n            started = True\n            misses_after_start = 0\n            i += 2\n            continue\n\n        if started:\n            if token not in {"Show More", "Show Less", "Over", "Under"} and not is_odds(token):\n                misses_after_start += 1\n                if misses_after_start >= 2:\n                    break\n\n        i += 1\n\n    return mkt("Total Goals Over / Under", selections)\n'


def replace_function(source: str, function_name: str, replacement: str) -> str:
    match = re.search(
        rf"(?m)^def {re.escape(function_name)}\s*\(",
        source,
    )
    if not match:
        raise ValueError(f"Function not found: {function_name}")

    start = match.start()
    next_def = re.search(r"(?m)^def \w+\s*\(", source[match.end():])
    if not next_def:
        end = len(source)
    else:
        end = match.end() + next_def.start()

    return source[:start] + replacement.rstrip() + "\n\n" + source[end:]


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"Target not found: {TARGET}")

    source = TARGET.read_text(encoding="utf-8")

    try:
        if re.search(r"(?m)^def parse_over_under\s*\(", source):
            patched = replace_function(
                source,
                "parse_over_under",
                PARSE_OVER_UNDER,
            )
            patched_name = "parse_over_under"
        elif re.search(r"(?m)^def parse_total_goals\s*\(", source):
            patched = replace_function(
                source,
                "parse_total_goals",
                PARSE_TOTAL_GOALS,
            )
            patched_name = "parse_total_goals"
        else:
            raise SystemExit(
                "Could not find parse_over_under() or parse_total_goals(). "
                "No changes were made."
            )

        ast.parse(patched)
    except Exception as exc:
        raise SystemExit(f"Patch validation failed: {exc}") from exc

    if not BACKUP.exists():
        BACKUP.write_text(source, encoding="utf-8")

    TARGET.write_text(patched, encoding="utf-8")

    print(f"Patched function: {patched_name}")
    print(f"Updated: {TARGET}")
    print(f"Backup:  {BACKUP}")
    print("Syntax validation: OK")
    print("BetVictor goal thresholds now use the displayed lines exactly.")


if __name__ == "__main__":
    main()
