#!/usr/bin/env python3
"""
integrate_bwin_moneylines_FIXED.py

Safely wire football/data/bwin_worldcup_moneylines.json into:

- scripts/Football/generate_worldcup_page.py
- scripts/Football/analyze_football_arbitrage.py
- scripts/Football/build_football_ev_alerts.py
- validate_worldcup_moneylines.py

The master script is deliberately NOT changed.

This patch is transactional:
- every modified Python file is syntax-checked first;
- nothing is written unless all four patches validate.

Run from the repository root:

    python integrate_bwin_moneylines_FIXED.py
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

GENERATOR = ROOT / "scripts" / "Football" / "generate_worldcup_page.py"
ARBITRAGE = ROOT / "scripts" / "Football" / "analyze_football_arbitrage.py"
EV_ALERTS = ROOT / "scripts" / "Football" / "build_football_ev_alerts.py"
VALIDATOR = ROOT / "validate_worldcup_moneylines.py"

BWIN_LOADER = 'def load_bwin_moneylines():\n    data = load_json(BWIN_PATH)\n    rows = []\n    generated = data.get("generated_at", "") if isinstance(data, dict) else ""\n\n    for m in data.get("matches") or []:\n        home = display_team(m.get("home_team"))\n        away = display_team(m.get("away_team"))\n        if not home or not away:\n            continue\n\n        odds = {}\n        for side, value in (m.get("odds") or {}).items():\n            try:\n                decimal = float(str(value).replace(",", "."))\n            except (TypeError, ValueError):\n                continue\n\n            if decimal <= 1:\n                continue\n\n            odds[side] = decimal_to_fractional(f"{decimal:.8g}")\n\n        if not all(odds.get(side) for side in ("home", "draw", "away")):\n            continue\n\n        rows.append({\n            "bookmaker": "Bwin",\n            "date_label": m.get("date_label", ""),\n            "time": m.get("time", ""),\n            "match": f"{home} v {away}",\n            "home_team": home,\n            "away_team": away,\n            "odds": odds,\n            "source_url": m.get("source_url", ""),\n            "strict_key": fixture_key(home, away),\n            "loose_key": loose_fixture_key(home, away),\n        })\n\n    return rows, generated'


def validate_python(path: Path, source: str) -> None:
    ast.parse(source)
    compile(source, str(path), "exec")


def insert_after_line(source: str, pattern: str, line: str) -> str:
    match = re.search(pattern, source, re.M)
    if not match:
        raise RuntimeError(f"Could not find insertion anchor: {pattern}")

    return source[:match.end()] + "\n" + line + source[match.end():]


def find_mapping_bounds(source: str, filename: str) -> tuple[int, int]:
    marker = source.find(filename)
    if marker < 0:
        raise RuntimeError(f"Could not find mapping containing {filename}")

    open_brace = source.rfind("{", 0, marker)
    if open_brace < 0:
        raise RuntimeError("Could not find mapping opening brace")

    depth = 0
    for index in range(open_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return open_brace, index

    raise RuntimeError("Could not find mapping closing brace")


def clone_mapping_line(
    source: str,
    source_bookmaker: str,
    source_filename: str,
    new_bookmaker: str,
    new_filename: str,
) -> str:
    start, end = find_mapping_bounds(source, source_filename)
    block = source[start:end + 1]

    if re.search(
        rf'(?m)^\s*["\']{re.escape(new_bookmaker)}["\']\s*:',
        block,
    ):
        return source

    line_match = re.search(
        rf'(?m)^(\s*)["\']{re.escape(source_bookmaker)}["\']'
        rf'\s*:\s*.*{re.escape(source_filename)}.*$',
        block,
    )
    if not line_match:
        raise RuntimeError(
            f"Could not clone {source_bookmaker} mapping line "
            f"from {source_filename}"
        )

    line = line_match.group(0)
    line = re.sub(
        rf'(["\']){re.escape(source_bookmaker)}\1',
        rf'\1{new_bookmaker}\1',
        line,
        count=1,
    )
    line = line.replace(source_filename, new_filename)

    return source[:end] + "\n" + line + source[end:]


def patch_generator(source: str) -> str:
    patched = source

    if "BWIN_PATH" not in patched:
        patched = insert_after_line(
            patched,
            r'^\s*MIDNITE_PATH\s*=.*midnite_worldcup_moneylines\.json.*$',
            'BWIN_PATH           = ROOT / "football" / "data" / '
            '"bwin_worldcup_moneylines.json"',
        )

    if "def load_bwin_moneylines(" not in patched:
        marker = re.search(r'(?m)^def\s+_dec_to_str\s*\(', patched)
        if not marker:
            marker = re.search(
                r'(?m)^def\s+load_midnite_props\s*\(',
                patched,
            )
        if not marker:
            raise RuntimeError(
                "Could not locate Bwin loader insertion point"
            )

        patched = (
            patched[:marker.start()]
            + BWIN_LOADER
            + "\n\n"
            + patched[marker.start():]
        )

    load_all_match = re.search(
        r'(?m)^def\s+load_all\s*\(\s*\)\s*:',
        patched,
    )
    if not load_all_match:
        raise RuntimeError("Could not find load_all()")

    next_function = re.search(
        r'(?m)^def\s+\w+\s*\(',
        patched[load_all_match.end():],
    )
    load_all_end = (
        len(patched)
        if not next_function
        else load_all_match.end() + next_function.start()
    )

    block = patched[load_all_match.start():load_all_end]

    if 'load_bwin_moneylines()' not in block:
        anchor = re.search(
            r'(?m)^(\s*)midnite_rows(?:\s*,\s*\w+)?'
            r'\s*=\s*load_midnite_moneylines\(\)\s*$',
            block,
        )
        if not anchor:
            raise RuntimeError(
                "Could not find Midnite moneyline load in load_all()"
            )

        addition = (
            f'\n{anchor.group(1)}bwin_rows,    bwin_gen'
            f'      = load_bwin_moneylines()'
        )
        block = block[:anchor.end()] + addition + block[anchor.end():]

    if '(bwin_rows,"Bwin")' not in block and '(bwin_rows, "Bwin")' not in block:
        if '(midnite_rows,"Midnite")]' in block:
            block = block.replace(
                '(midnite_rows,"Midnite")]',
                '(midnite_rows,"Midnite"),(bwin_rows,"Bwin")]',
                1,
            )
        elif '(midnite_rows, "Midnite")]' in block:
            block = block.replace(
                '(midnite_rows, "Midnite")]',
                '(midnite_rows, "Midnite"), (bwin_rows, "Bwin")]',
                1,
            )
        else:
            raise RuntimeError(
                "Could not add Bwin to generator bookmaker row list"
            )

    generated_line = re.search(
        r'(?m)^(\s*)generated\s*=\s*(.+)$',
        block,
    )
    if not generated_line:
        raise RuntimeError("Could not find generated timestamp line")

    if "bwin_gen" not in generated_line.group(2):
        replacement = (
            generated_line.group(1)
            + "generated = "
            + generated_line.group(2).rstrip()
            + " or bwin_gen"
        )
        block = (
            block[:generated_line.start()]
            + replacement
            + block[generated_line.end():]
        )

    patched = (
        patched[:load_all_match.start()]
        + block
        + patched[load_all_end:]
    )

    return patched


def patch_arbitrage(source: str) -> str:
    return clone_mapping_line(
        source,
        "PaddyPower",
        "paddypower_worldcup_moneylines.json",
        "Bwin",
        "bwin_worldcup_moneylines.json",
    )


def patch_ev_alerts(source: str) -> str:
    return clone_mapping_line(
        source,
        "PaddyPower",
        "paddypower_worldcup_moneylines.json",
        "Bwin",
        "bwin_worldcup_moneylines.json",
    )


def patch_validator(source: str) -> str:
    return clone_mapping_line(
        source,
        "PaddyPower",
        "paddypower_worldcup_moneylines.json",
        "Bwin",
        "bwin_worldcup_moneylines.json",
    )


def main() -> None:
    files = {
        GENERATOR: patch_generator,
        ARBITRAGE: patch_arbitrage,
        EV_ALERTS: patch_ev_alerts,
        VALIDATOR: patch_validator,
    }

    missing = [str(path) for path in files if not path.exists()]
    if missing:
        raise SystemExit(
            "Missing required file(s):\n- " + "\n- ".join(missing)
        )

    patched_sources: dict[Path, str] = {}

    for path, patcher in files.items():
        original = path.read_text(encoding="utf-8")
        patched = patcher(original)
        validate_python(path, patched)
        patched_sources[path] = patched
        print(f"Validated: {path}")

    for path, source in patched_sources.items():
        temporary = path.with_suffix(path.suffix + ".bwin_tmp")
        temporary.write_text(source, encoding="utf-8", newline="\n")
        temporary.replace(path)
        print(f"Updated:   {path}")

    print("")
    print("Bwin moneyline integration completed successfully.")
    print("The master script was not changed.")
    print("")
    print("Next commands:")
    print(r"  python validate_worldcup_moneylines.py")
    print(r"  python scripts\Football\analyze_football_arbitrage.py")
    print(r"  python scripts\Football\build_football_ev_alerts.py")
    print(r"  python scripts\build_ev_alerts_all.py")
    print(r"  python scripts\build_arbitrage_all.py")


if __name__ == "__main__":
    main()
