#!/usr/bin/env python3
"""
Patch the production BetVictor World Cup props scraper so Total Goals
Over/Under lines are read from BetVictor's actual row labels.

Fixes cases where a market starts at 1.5 rather than 0.5. The old parser could
let the standalone "Under" column heading set a stale mode, then interpret
"O 1.5" or the first numeric row incorrectly.

Run from the repository root:
    python patch_betvictor_total_goals_parser.py
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scripts" / "Football" / "fetch_betvictor_worldcup_props.py"
BACKUP = TARGET.with_name("fetch_betvictor_worldcup_props.before_goal_line_fix.py")

NEW_FUNCTION = r