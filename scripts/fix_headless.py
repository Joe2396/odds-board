"""
Run this from inside C:\\Users\\joete\\odds-board\\scripts

Fixes the 7 scripts that hardcode headless=False (which crashes on GitHub
Actions runners with no display) by:
  1. Adding `import os` if missing
  2. Adding an `is_github_actions()` helper if missing
  3. Replacing `headless=False` -> `headless=is_github_actions()`

Safe to run multiple times - it skips files that are already fixed.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # the scripts/ folder

FILES = [
    "fetch_coral_fight_urls.py",
    "fetch_coral_props.py",
    "fetch_888sport_props.py",
    "fetch_betfred_props.py",
    "fetch_bwin_props.py",
    "fetch_livescorebet_ufc_moneylines.py",
    "fetch_williamhill_props.py",
]

HELPER = (
    "\n"
    "def is_github_actions():\n"
    "    return os.getenv(\"GITHUB_ACTIONS\") == \"true\"\n"
    "\n"
)


def find_import_block_end(lines):
    """Return index right after the last contiguous top-of-file import line."""
    insert_at = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_at = i + 1
        elif insert_at > 0:
            break
    return insert_at


def fix_file(path: Path):
    text = path.read_text(encoding="utf-8")
    original = text
    changed_parts = []

    if not re.search(r"(?m)^import os\s*$", text):
        lines = text.splitlines(keepends=True)
        insert_at = find_import_block_end(lines)
        lines.insert(insert_at, "import os\n")
        text = "".join(lines)
        changed_parts.append("added 'import os'")

    if "def is_github_actions" not in text:
        lines = text.splitlines(keepends=True)
        insert_at = find_import_block_end(lines)
        lines.insert(insert_at, HELPER)
        text = "".join(lines)
        changed_parts.append("added is_github_actions() helper")

    text, n = re.subn(r"headless=False", "headless=is_github_actions()", text)
    if n:
        changed_parts.append(f"replaced {n} occurrence(s) of headless=False")
    else:
        changed_parts.append("WARNING: no headless=False found")

    if text != original:
        path.write_text(text, encoding="utf-8")
        print(f"{path.name}: " + "; ".join(changed_parts))
    else:
        print(f"{path.name}: no changes needed")


def main():
    for fname in FILES:
        path = ROOT / fname
        if not path.exists():
            print(f"{fname}: MISSING, skipping")
            continue
        fix_file(path)


if __name__ == "__main__":
    main()
