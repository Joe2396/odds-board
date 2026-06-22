#!/usr/bin/env python3
"""
Permanent Paddy Power BTTS fix.

This script:
1. Patches the Paddy Power scraper so "Both Teams To Score" contains ONLY the
   standard full-time Yes/No pair.
2. Patches the football arb analyzer so exotic BTTS variants can never be
   treated as the standard full-time market.
3. Repairs the current Paddy Power props JSON immediately, so no scraper rerun
   is required before rebuilding the arb board.

Run from the odds-board repository root:
    python fix_paddypower_btts_long_term.py
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PP_SCRIPT = ROOT / "scripts" / "Football" / "fetch_paddypower_worldcup_props.py"
ARB_SCRIPT = ROOT / "scripts" / "Football" / "analyze_football_arbitrage.py"
PP_JSON = ROOT / "football" / "data" / "paddypower_worldcup_props.json"

PP_BACKUP = PP_SCRIPT.with_name(
    "fetch_paddypower_worldcup_props.before_standard_btts_fix.py"
)
ARB_BACKUP = ARB_SCRIPT.with_name(
    "analyze_football_arbitrage.before_standard_btts_fix.py"
)
JSON_BACKUP = PP_JSON.with_name(
    "paddypower_worldcup_props.before_standard_btts_fix.json"
)


NEW_PP_PARSE_BTTS = r