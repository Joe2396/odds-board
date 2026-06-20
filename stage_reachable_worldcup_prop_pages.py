#!/usr/bin/env python3
"""
Stage only reachable generated World Cup match/player-prop pages.

This avoids staging stale, unlinked player folders left behind by older
generator runs. It starts from every current match-props/index.html and
player-props/index.html, follows local HTML links recursively, and stages
only the reachable files.

Run from the repository root:
    python stage_reachable_worldcup_prop_pages.py
"""

from __future__ import annotations

import subprocess
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO = Path.cwd().resolve()
WORLD_CUP = (REPO / "football" / "world-cup").resolve()
BASE_PREFIXES = ("/odds-board/", "/")

class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)

def local_target(source: Path, href: str) -> Path | None:
    href = unquote(href.strip())
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None

    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        return None

    path = parts.path
    if not path:
        return None

    if path.startswith("/odds-board/"):
        candidate = REPO / path[len("/odds-board/"):]
    elif path.startswith("/"):
        candidate = REPO / path.lstrip("/")
    else:
        candidate = source.parent / path

    candidate = candidate.resolve()

    try:
        candidate.relative_to(WORLD_CUP)
    except ValueError:
        return None

    if candidate.is_dir() or path.endswith("/"):
        candidate = candidate / "index.html"

    if candidate.suffix == "":
        candidate = candidate / "index.html"

    if candidate.suffix.lower() != ".html":
        return None

    return candidate

def main() -> None:
    roots = sorted(WORLD_CUP.glob("*/match-props/index.html"))
    roots += sorted(WORLD_CUP.glob("*/player-props/index.html"))

    if not roots:
        raise SystemExit("No generated match-props/player-props index files found.")

    queue = deque(path.resolve() for path in roots)
    visited: set[Path] = set()
    reachable: list[Path] = []
    missing: set[Path] = set()

    while queue:
        path = queue.popleft()
        if path in visited:
            continue
        visited.add(path)

        if not path.exists():
            missing.add(path)
            continue

        reachable.append(path)

        parser = LinkParser()
        try:
            parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            print(f"WARNING: could not read {path}: {exc}")
            continue

        for href in parser.hrefs:
            target = local_target(path, href)
            if target and target not in visited:
                queue.append(target)

    relative_paths = [
        str(path.relative_to(REPO)).replace("\\", "/")
        for path in sorted(set(reachable))
    ]

    for start in range(0, len(relative_paths), 100):
        batch = relative_paths[start:start + 100]
        subprocess.run(["git", "add", "--", *batch], check=True)

    print(f"Root prop pages found: {len(roots)}")
    print(f"Reachable HTML pages staged: {len(relative_paths)}")

    if missing:
        print(f"Referenced pages missing locally: {len(missing)}")
        for path in sorted(missing)[:30]:
            print("  MISSING:", path.relative_to(REPO))
        if len(missing) > 30:
            print(f"  ... plus {len(missing) - 30} more")

    print("\nStaged World Cup prop-page files:")
    subprocess.run(
        [
            "git",
            "--no-pager",
            "diff",
            "--cached",
            "--name-only",
            "--",
            "football/world-cup",
        ],
        check=True,
    )

if __name__ == "__main__":
    main()
