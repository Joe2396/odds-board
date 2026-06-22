#!/usr/bin/env python3
"""
Permanent LiveScoreBet Half Time Result fix.

Run from the odds-board repository root:

    python fix_livescorebet_half_time_long_term.py

The patch:
- captures only the marketGroupId=755 Half Time card;
- prevents full-time odds elsewhere on the page being reused;
- adds source-triplet validation to the arb analyzer;
- removes current LiveScoreBet Half Time Result rows so a short scraper test
  can repopulate them correctly;
- sets the scraper to MAX_MATCHES = 3 for testing.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SCRAPER = ROOT / "scripts" / "Football" / "fetch_livescorebet_worldcup_props.py"
ANALYZER = ROOT / "scripts" / "Football" / "analyze_football_arbitrage.py"
DATA = ROOT / "football" / "data" / "livescorebet_worldcup_props.json"

SCRAPER_BACKUP = SCRAPER.with_name(
    "fetch_livescorebet_worldcup_props.before_half_time_fix.py"
)
ANALYZER_BACKUP = ANALYZER.with_name(
    "analyze_football_arbitrage.before_lsb_half_time_fix.py"
)
DATA_BACKUP = DATA.with_name(
    "livescorebet_worldcup_props.before_half_time_fix.json"
)

NEW_HALF_PARSER = 'def parse_half_time_result(lines, home, away):\n    """\n    Parse only the scoped first-half 1X2 card.\n\n    The preferred input is a HALF_TIME_MARKER chunk captured directly from\n    LiveScoreBet\'s marketGroupId=755 Half Time card. The whole-page fallback is\n    retained only for resilience.\n    """\n    selections = []\n\n    marker_idx = next(\n        (\n            i for i, line in enumerate(lines)\n            if clean(line) == HALF_TIME_MARKER\n        ),\n        -1,\n    )\n\n    if marker_idx >= 0:\n        block = lines[marker_idx + 1:marker_idx + 24]\n    else:\n        idx = next(\n            (\n                i for i, line in enumerate(lines)\n                if clean(line) in {\n                    "Half Time",\n                    "Half-Time Result",\n                    "Half Time Result",\n                }\n            ),\n            -1,\n        )\n        if idx == -1:\n            return mkt("Half Time Result", selections)\n        block = lines[idx:idx + 35]\n\n    # Layout A:\n    # France\n    # Draw\n    # Iraq\n    # 1/4\n    # 29/10\n    # 14/1\n    for i in range(max(0, len(block) - 5)):\n        if (\n            clean(block[i]) == home\n            and clean(block[i + 1]) == "Draw"\n            and clean(block[i + 2]) == away\n            and is_odds(block[i + 3])\n            and is_odds(block[i + 4])\n            and is_odds(block[i + 5])\n        ):\n            selections = [\n                sel(\n                    home,\n                    block[i + 3],\n                    {\n                        "side": "home",\n                        "period": "first_half",\n                        "base_market": "half_time_result",\n                    },\n                ),\n                sel(\n                    "Draw",\n                    block[i + 4],\n                    {\n                        "side": "draw",\n                        "period": "first_half",\n                        "base_market": "half_time_result",\n                    },\n                ),\n                sel(\n                    away,\n                    block[i + 5],\n                    {\n                        "side": "away",\n                        "period": "first_half",\n                        "base_market": "half_time_result",\n                    },\n                ),\n            ]\n            break\n\n    # Layout B:\n    # France\n    # 1/4\n    # Draw\n    # 29/10\n    # Iraq\n    # 14/1\n    if not selections:\n        found = {}\n        labels = {\n            home: "home",\n            "Draw": "draw",\n            away: "away",\n        }\n\n        for i, token in enumerate(block[:-1]):\n            label = clean(token)\n            if label in labels and is_odds(block[i + 1]):\n                found[labels[label]] = (\n                    label,\n                    clean(block[i + 1]),\n                )\n\n        if set(found) == {"home", "draw", "away"}:\n            selections = [\n                sel(\n                    found["home"][0],\n                    found["home"][1],\n                    {\n                        "side": "home",\n                        "period": "first_half",\n                        "base_market": "half_time_result",\n                    },\n                ),\n                sel(\n                    found["draw"][0],\n                    found["draw"][1],\n                    {\n                        "side": "draw",\n                        "period": "first_half",\n                        "base_market": "half_time_result",\n                    },\n                ),\n                sel(\n                    found["away"][0],\n                    found["away"][1],\n                    {\n                        "side": "away",\n                        "period": "first_half",\n                        "base_market": "half_time_result",\n                    },\n                ),\n            ]\n\n    if len(selections) != 3:\n        return mkt("Half Time Result", [])\n\n    decimals = []\n    for selection in selections:\n        price = clean(selection.get("odds")).upper()\n        if price in {"EVS", "EVENS", "EVEN"}:\n            decimals.append(2.0)\n            continue\n        try:\n            num, den = price.split("/", 1)\n            decimals.append((float(num) / float(den)) + 1.0)\n        except Exception:\n            return mkt("Half Time Result", [])\n\n    implied_sum = sum(1.0 / value for value in decimals)\n    if not 0.98 <= implied_sum <= 1.35:\n        print(\n            f"    Rejecting implausible LiveScoreBet Half Time Result: "\n            f"{[s.get(\'odds\') for s in selections]} "\n            f"(sum {implied_sum:.3f})"\n        )\n        return mkt("Half Time Result", [])\n\n    return dedupe_market(mkt("Half Time Result", selections))\n'
NEW_HALF_HELPERS = 'def extract_market_card_text(page, heading, home, away):\n    """\n    Return the smallest visible DOM container containing one exact market card.\n    This prevents full-time match odds elsewhere on the page being parsed as\n    Half Time Result.\n    """\n    try:\n        return page.evaluate(\n            """({heading, home, away}) => {\n                const norm = value =>\n                    (value || "").replace(/\\s+/g, " ").trim();\n\n                const oddsPattern =\n                    /(?:^|\\s)(?:\\d+\\/\\d+|EVS|EVENS|EVEN)(?=\\s|$)/gi;\n\n                const headings = Array.from(\n                    document.querySelectorAll("body *")\n                ).filter(element =>\n                    norm(element.innerText) === heading\n                );\n\n                const candidates = [];\n\n                for (const headingElement of headings) {\n                    let node = headingElement;\n\n                    for (\n                        let depth = 0;\n                        depth < 10 && node;\n                        depth += 1, node = node.parentElement\n                    ) {\n                        const text = norm(node.innerText);\n                        const odds = text.match(oddsPattern) || [];\n\n                        if (\n                            text.includes(heading)\n                            && text.includes(home)\n                            && text.includes("Draw")\n                            && text.includes(away)\n                            && odds.length >= 3\n                        ) {\n                            candidates.push({\n                                text,\n                                length: text.length,\n                            });\n                            break;\n                        }\n                    }\n                }\n\n                candidates.sort((a, b) => a.length - b.length);\n                return candidates.length ? candidates[0].text : "";\n            }""",\n            {\n                "heading": heading,\n                "home": home,\n                "away": away,\n            },\n        )\n    except Exception as error:\n        print(f"    Market-card extraction failed ({heading}): {error}")\n        return ""\n\n\ndef collect_half_time_card_text(page, url, home, away):\n    half_url = f"{url}?marketGroupId={HALF_GRP_ID}"\n\n    try:\n        page.goto(\n            half_url,\n            wait_until="domcontentloaded",\n            timeout=60000,\n        )\n        page.wait_for_timeout(4500)\n        accept_cookies(page)\n\n        heading = page.get_by_text("Half Time", exact=True)\n        if not heading.count():\n            print("    Half Time card not found")\n            return ""\n\n        heading.last.scroll_into_view_if_needed(timeout=4000)\n        page.wait_for_timeout(900)\n\n        card_text = extract_market_card_text(\n            page,\n            "Half Time",\n            home,\n            away,\n        )\n\n        if not card_text:\n            print("    Half Time card could not be scoped")\n            return ""\n\n        print("    Half Time card captured directly")\n        return f"\\n{HALF_TIME_MARKER}\\n{card_text}\\n"\n\n    except Exception as error:\n        print(f"    Half Time card collection failed: {error}")\n        return ""\n'
NEW_ANALYZER_GUARD = 'def validate_half_time_result_sources(data, audit):\n    """\n    Fail closed on malformed Half Time Result source triplets.\n\n    Protections:\n    - a bookmaker must supply all three outcomes;\n    - the source triplet must have a plausible three-way implied sum;\n    - a props Half Time Result triplet must not exactly duplicate that\n      bookmaker\'s full-time moneyline triplet.\n    """\n    moneyline_reference = {}\n\n    for bookmaker, path in BOOK_FILES.items():\n        raw = load_json(path)\n        if not raw:\n            continue\n\n        for row in raw.get("matches") or []:\n            home = row.get("home_team") or ""\n            away = row.get("away_team") or ""\n            odds = row.get("odds") or {}\n\n            if not home or not away or not odds:\n                continue\n\n            decimals = tuple(\n                fractional_to_decimal(odds.get(key))\n                for key in ("home", "draw", "away")\n            )\n            if all(decimals):\n                moneyline_reference[\n                    (bookmaker, fixture_key(home, away))\n                ] = decimals\n\n    outcomes = ("home", "draw", "away")\n\n    for fixture_key_value, fixture in data.items():\n        htr = fixture.get("half_time_result") or {}\n\n        bookmakers = set()\n        for outcome in outcomes:\n            for offer in htr.get(outcome) or []:\n                bookmakers.add(offer.get("bookmaker"))\n\n        for bookmaker in sorted(bookmakers):\n            offers = {}\n\n            for outcome in outcomes:\n                candidates = [\n                    offer\n                    for offer in htr.get(outcome) or []\n                    if offer.get("bookmaker") == bookmaker\n                ]\n                if candidates:\n                    offers[outcome] = max(\n                        candidates,\n                        key=lambda offer: offer["decimal"],\n                    )\n\n            valid = len(offers) == 3\n            implied_sum = None\n            duplicates_moneyline = False\n\n            if valid:\n                decimals = tuple(\n                    offers[outcome]["decimal"]\n                    for outcome in outcomes\n                )\n                implied_sum = sum(1.0 / value for value in decimals)\n                valid = 0.98 <= implied_sum <= 1.35\n\n                moneyline = moneyline_reference.get(\n                    (bookmaker, fixture_key_value)\n                )\n                if moneyline:\n                    duplicates_moneyline = all(\n                        abs(first - second) < 1e-9\n                        for first, second in zip(decimals, moneyline)\n                    )\n                    if duplicates_moneyline:\n                        valid = False\n\n            if valid:\n                continue\n\n            removed = 0\n            for outcome in outcomes:\n                before = len(htr.get(outcome) or [])\n                htr[outcome] = [\n                    offer\n                    for offer in htr.get(outcome) or []\n                    if offer.get("bookmaker") != bookmaker\n                ]\n                removed += before - len(htr[outcome])\n\n            if removed:\n                counts = audit.setdefault(\n                    bookmaker,\n                    {"matches": 0, "offers": 0},\n                )\n                counts["half_time_result_rejected"] = (\n                    counts.get("half_time_result_rejected", 0)\n                    + removed\n                )\n\n                if duplicates_moneyline:\n                    reason = "duplicates full-time moneyline"\n                elif implied_sum is None:\n                    reason = "incomplete triplet"\n                else:\n                    reason = f"implied sum {implied_sum:.3f}"\n\n                print(\n                    f"  Half Time safety: removed {removed} "\n                    f"{bookmaker} offer(s) for "\n                    f"{fixture.get(\'match\')} ({reason})"\n                )\n'


def replace_function(source, name, replacement):
    match = re.search(rf"(?m)^def {re.escape(name)}\s*\(", source)
    if not match:
        raise RuntimeError(f"Could not find {name}()")

    next_def = re.search(r"(?m)^def \w+\s*\(", source[match.end():])
    end = len(source) if not next_def else match.end() + next_def.start()

    return source[:match.start()] + replacement.rstrip() + "\n\n" + source[end:]


def ensure_constant(source, name, value, after_name):
    if re.search(rf"(?m)^{re.escape(name)}\s*=", source):
        return re.sub(
            rf"(?m)^{re.escape(name)}\s*=.*$",
            f'{name} = "{value}"',
            source,
            count=1,
        )

    after = re.search(
        rf"(?m)^{re.escape(after_name)}\s*=.*$",
        source,
    )
    if not after:
        raise RuntimeError(
            f"Could not insert {name} after {after_name}"
        )

    insert_at = after.end()
    return (
        source[:insert_at]
        + f'\n{name} = "{value}"'
        + source[insert_at:]
    )


def patch_scraper():
    original = SCRAPER.read_text(encoding="utf-8")
    patched = original

    patched = ensure_constant(
        patched,
        "HALF_GRP_ID",
        "755",
        "PLAYER_GRP_ID",
    )
    patched = ensure_constant(
        patched,
        "HALF_TIME_MARKER",
        "__LSB_HALF_TIME__",
        "SCOPE_MARKER",
    )

    patched = re.sub(
        r"(?m)^MAX_MATCHES\s*=\s*\d+",
        "MAX_MATCHES    = 3",
        patched,
        count=1,
    )

    patched = replace_function(
        patched,
        "parse_half_time_result",
        NEW_HALF_PARSER,
    )

    if "def collect_half_time_card_text(" not in patched:
        marker = "def scrape_match(page, fixture):"
        index = patched.find(marker)
        if index < 0:
            raise RuntimeError("Could not find scrape_match()")
        patched = (
            patched[:index]
            + NEW_HALF_HELPERS.rstrip()
            + "\n\n\n"
            + patched[index:]
        )

    if "half_time_text = collect_half_time_card_text(" not in patched:
        scoped_line = re.search(
            r"(?m)^(\s*)scoped_text\s*=\s*"
            r"collect_shots_scope_text\(page, home, away\)\s*$",
            patched,
        )
        if not scoped_line:
            raise RuntimeError(
                "Could not find collect_shots_scope_text() call"
            )

        indent = scoped_line.group(1)
        addition = (
            scoped_line.group(0)
            + "\n"
            + indent
            + "half_time_text = collect_half_time_card_text("
            + "page, url, home, away)"
        )
        patched = (
            patched[:scoped_line.start()]
            + addition
            + patched[scoped_line.end():]
        )

    patched = re.sub(
        r"(?m)^([ \t]*)text1_for_parse\s*=\s*"
        r"text1\s*\+\s*scoped_text\s*$",
        r"\1text1_for_parse = text1 + scoped_text + half_time_text",
        patched,
        count=1,
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

    if "def validate_half_time_result_sources(" not in patched:
        marker = "def scan_named_prop_arbitrage(root):"
        index = patched.find(marker)
        if index < 0:
            raise RuntimeError("Could not find scan_named_prop_arbitrage()")
        patched = (
            patched[:index]
            + NEW_ANALYZER_GUARD.rstrip()
            + "\n\n\n"
            + patched[index:]
        )

    function_start = patched.find("def scan_named_prop_arbitrage(root):")
    arbs_marker = patched.find("\n    arbs = []", function_start)
    if arbs_marker < 0:
        raise RuntimeError(
            "Could not find named-market arb calculation block"
        )

    call = "\n    validate_half_time_result_sources(data, audit)\n"
    before_arbs = patched[function_start:arbs_marker]

    if "validate_half_time_result_sources(data, audit)" not in before_arbs:
        patched = (
            patched[:arbs_marker]
            + call
            + patched[arbs_marker:]
        )

    ast.parse(patched)

    if not ANALYZER_BACKUP.exists():
        ANALYZER_BACKUP.write_text(original, encoding="utf-8")
    ANALYZER.write_text(patched, encoding="utf-8")

    print(f"Patched analyzer: {ANALYZER}")
    print(f"Backup: {ANALYZER_BACKUP}")


def normalized(value):
    value = str(value or "").lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def clear_current_half_time_rows():
    if not DATA.exists():
        print(f"Current LiveScoreBet JSON not found: {DATA}")
        return

    if not DATA_BACKUP.exists():
        shutil.copy2(DATA, DATA_BACKUP)

    payload = json.loads(DATA.read_text(encoding="utf-8"))
    removed = 0

    for match in payload.get("matches") or []:
        markets = match.get("markets") or []
        if not isinstance(markets, list):
            continue

        kept = []

        for market in markets:
            key = normalized(
                market.get("normalized_market")
                or market.get("market")
                or ""
            )
            if key == "half_time_result":
                removed += 1
                continue
            kept.append(market)

        match["markets"] = kept
        if "market_count" in match:
            match["market_count"] = len(kept)

    DATA.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Removed current LiveScoreBet Half Time markets: {removed}")
    print(f"JSON backup: {DATA_BACKUP}")


def main():
    patch_scraper()
    patch_analyzer()
    clear_current_half_time_rows()

    print("")
    print("LiveScoreBet Half Time Result fix completed.")
    print("The scraper is set to MAX_MATCHES = 3 for testing.")
    print("")
    print("Next commands:")
    print(
        r"  python scripts\Football\fetch_livescorebet_worldcup_props.py"
    )
    print(
        r"  python scripts\Football\analyze_football_arbitrage.py"
    )
    print(r"  python scripts\build_arbitrage_all.py")


if __name__ == "__main__":
    main()
