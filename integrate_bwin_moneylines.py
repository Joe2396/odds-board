#!/usr/bin/env python3
"""
integrate_bwin_moneylines.py

Wire football/data/bwin_worldcup_moneylines.json into:

- scripts/Football/generate_worldcup_page.py
- scripts/Football/analyze_football_arbitrage.py
- scripts/Football/build_football_ev_alerts.py
- validate_worldcup_moneylines.py

The master script is deliberately NOT changed yet.

Run from the repository root:

    python integrate_bwin_moneylines.py
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


def atomic_python_write(path: Path, source: str) -> None:
    ast.parse(source)
    compile(source, str(path), "exec")

    temporary = path.with_suffix(path.suffix + ".bwin_tmp")
    temporary.write_text(source, encoding="utf-8", newline="\n")
    temporary.replace(path)


def find_dict_block(source: str, filename_marker: str) -> tuple[int, int]:
    marker = source.find(filename_marker)
    if marker < 0:
        raise RuntimeError(
            f"Could not find mapping containing {filename_marker}"
        )

    open_brace = source.rfind("{", 0, marker)
    if open_brace < 0:
        raise RuntimeError("Could not find mapping opening brace")

    depth = 0
    for index in range(open_brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return open_brace, index

    raise RuntimeError("Could not find mapping closing brace")


def add_dict_entry(
    source: str,
    filename_marker: str,
    bookmaker: str,
    entry: str,
) -> str:
    start, end = find_dict_block(source, filename_marker)
    block = source[start:end + 1]

    if re.search(
        rf'(?m)^\s*["\']{re.escape(bookmaker)}["\']\s*:',
        block,
    ):
        return source

    indentation = "    "
    existing_line = re.search(
        rf'(?m)^(\s*)["\'][^"\']+["\']\s*:.*{re.escape(filename_marker)}',
        block,
    )
    if existing_line:
        indentation = existing_line.group(1)

    insertion = "\n" + indentation + entry
    return source[:end] + insertion + source[end:]


def patch_generator() -> None:
    source = GENERATOR.read_text(encoding="utf-8")
    patched = source

    if "BWIN_PATH" not in patched:
        anchor = re.search(
            r'(?m)^(\s*)MIDNITE_PATH\s*=.*midnite_worldcup_moneylines\.json.*$',
            patched,
        )
        if not anchor:
            anchor = re.search(
                r'(?m)^(\s*)LADBROKES_PATH\s*=.*ladbrokes_worldcup_moneylines\.json.*$',
                patched,
            )
        if not anchor:
            raise RuntimeError(
                "Could not locate generator moneyline path constants"
            )

        line = (
            f'\n{anchor.group(1)}BWIN_PATH'
            f'          = ROOT / "football" / "data" / '
            f'"bwin_worldcup_moneylines.json"'
        )
        patched = (
            patched[:anchor.end()]
            + line
            + patched[anchor.end():]
        )

    # Current generator uses load_all(); older versions use load_all_matches().
    function_match = re.search(
        r'(?m)^def\s+(load_all|load_all_matches)\s*\(\s*\)\s*:',
        patched,
    )
    if not function_match:
        raise RuntimeError(
            "Could not locate load_all()/load_all_matches()"
        )

    function_start = function_match.start()
    next_function = re.search(
        r'(?m)^def\s+\w+\s*\(',
        patched[function_match.end():],
    )
    function_end = (
        len(patched)
        if not next_function
        else function_match.end() + next_function.start()
    )
    block = patched[function_start:function_end]

    if 'load_book("Bwin"' not in block:
        anchor = re.search(
            r'(?m)^(\s*)midnite_rows(?:\s*,\s*\w+)?\s*=.*$',
            block,
        )
        if not anchor:
            anchor = re.search(
                r'(?m)^(\s*)ladb_rows\s*,\s*ladb_gen\s*=.*$',
                block,
            )
        if not anchor:
            raise RuntimeError(
                "Could not locate generator moneyline load section"
            )

        addition = (
            f'\n{anchor.group(1)}bwin_rows,     bwin_gen'
            f'      = load_book("Bwin",         BWIN_PATH)'
        )
        block = block[:anchor.end()] + addition + block[anchor.end():]

    if '(bwin_rows,"Bwin")' not in block and '(bwin_rows, "Bwin")' not in block:
        list_match = re.search(
            r'(?ms)for\s+rows\s*,\s*bk\s+in\s*\[(.*?)\]\s*:',
            block,
        )
        if not list_match:
            raise RuntimeError(
                "Could not locate generator bookmaker row list"
            )

        content = list_match.group(1).rstrip()
        comma = "" if content.endswith(",") else ","
        new_content = content + comma + '\n                    (bwin_rows,"Bwin")'
        block = (
            block[:list_match.start(1)]
            + new_content
            + block[list_match.end(1):]
        )

    generated_match = re.search(
        r'(?m)^(\s*)generated\s*=\s*(.+)$',
        block,
    )
    if generated_match and "bwin_gen" not in generated_match.group(2):
        replacement = (
            generated_match.group(1)
            + "generated = "
            + generated_match.group(2).rstrip()
            + " or bwin_gen"
        )
        block = (
            block[:generated_match.start()]
            + replacement
            + block[generated_match.end():]
        )

    # Keep the public site in fractional format while retaining decimal Bwin
    # source data for EV and arbitrage calculations.
    if "bookmaker == \"Bwin\"" not in patched:
        load_book_match = re.search(
            r'(?ms)^def\s+load_book\s*\(.*?\):\s*\n(.*?)(?=^def\s+)',
            patched,
        )
        if load_book_match:
            load_block = load_book_match.group(0)
            odds_line = re.search(
                r'(?m)^(\s*)"odds"\s*:\s*m\.get\("odds"\)\s*or\s*\{\},\s*$',
                load_block,
            )
            if odds_line:
                indent = odds_line.group(1)
                replacement = (
                    indent
                    + '"odds": ({\n'
                    + indent
                    + '    side: decimal_to_fractional(price)\n'
                    + indent
                    + '    for side, price in (m.get("odds") or {}).items()\n'
                    + indent
                    + '} if bookmaker == "Bwin" else (m.get("odds") or {})),'
                )
                load_block = (
                    load_block[:odds_line.start()]
                    + replacement
                    + load_block[odds_line.end():]
                )
                patched = (
                    patched[:load_book_match.start()]
                    + load_block
                    + patched[load_book_match.end():]
                )

    patched = patched[:function_start] + block + patched[function_end:]

    atomic_python_write(GENERATOR, patched)
    print(f"Updated generator: {GENERATOR}")


def patch_arbitrage() -> None:
    source = ARBITRAGE.read_text(encoding="utf-8")
    patched = add_dict_entry(
        source,
        "paddypower_worldcup_moneylines.json",
        "Bwin",
        '"Bwin": os.path.join(ROOT, "football", "data", '
        '"bwin_worldcup_moneylines.json"),',
    )
    atomic_python_write(ARBITRAGE, patched)
    print(f"Updated arbitrage: {ARBITRAGE}")


def patch_ev_alerts() -> None:
    source = EV_ALERTS.read_text(encoding="utf-8")

    start, end = find_dict_block(
        source,
        "paddypower_worldcup_moneylines.json",
    )
    block = source[start:end + 1]

    if re.search(r'(?m)^\s*["\']Bwin["\']\s*:', block):
        patched = source
    else:
        # Match the mapping's path style instead of assuming pathlib or os.path.
        sample = re.search(
            r'(?m)^(\s*)["\']PaddyPower["\']\s*:\s*(.+)$',
            block,
        )
        if not sample:
            raise RuntimeError(
                "Could not determine EV bookmaker mapping style"
            )

        indentation = sample.group(1)
        expression = sample.group(2)

        expression = expression.replace(
            "paddypower_worldcup_moneylines.json",
            "bwin_worldcup_moneylines.json",
        )
        expression = re.sub(
            r'(["\'])PaddyPower\1',
            r'\1Bwin\1',
            expression,
        )

        patched = (
            source[:end]
            + "\n"
            + indentation
            + '"Bwin": '
            + expression
            + source[end:]
        )

    atomic_python_write(EV_ALERTS, patched)
    print(f"Updated EV alerts: {EV_ALERTS}")


def patch_validator() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")

    patched = add_dict_entry(
        source,
        "paddypower_worldcup_moneylines.json",
        "Bwin",
        '"Bwin":        ROOT / "football" / "data" / '
        '"bwin_worldcup_moneylines.json",',
    )

    atomic_python_write(VALIDATOR, patched)
    print(f"Updated validator: {VALIDATOR}")


def main() -> None:
    required = [GENERATOR, ARBITRAGE, EV_ALERTS, VALIDATOR]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            "Missing required file(s):\n- " + "\n- ".join(missing)
        )

    patch_generator()
    patch_arbitrage()
    patch_ev_alerts()
    patch_validator()

    print("")
    print("Bwin moneyline integration completed.")
    print("The master script was not changed.")
    print("")
    print("Safe checks:")
    print(r"  python validate_worldcup_moneylines.py")
    print(r"  python scripts\Football\analyze_football_arbitrage.py")
    print(r"  python scripts\Football\build_football_ev_alerts.py")
    print(r"  python scripts\build_ev_alerts_all.py")
    print(r"  python scripts\build_arbitrage_all.py")


if __name__ == "__main__":
    main()
