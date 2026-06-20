#!/usr/bin/env python3
"""
validate_betvictor_match_stats.py

Read-only validator for the BetVictor deep match/team shots pipeline.

Checks:
1. Every market/selection/odd in betvictor_worldcup_betbuilder_stats.json
   exists unchanged in betvictor_worldcup_props.json.
2. The generated match-props HTML contains the market labels, selections,
   and odds for each successfully scraped fixture.

It does not modify any file.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_betbuilder_stats.json"
PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
WORLD_CUP_DIR = ROOT / "football" / "world-cup"


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def slugify(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def load_json(path: Path):
    if not path.exists():
        raise SystemExit(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def selection_key(item):
    return (
        normalize(item.get("selection")),
        clean(item.get("odds")).upper(),
        normalize(item.get("team")),
        normalize(item.get("stat")),
        clean(item.get("threshold") or item.get("line")),
    )


def html_text(path: Path):
    if not path.exists():
        return ""
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = html.unescape(raw)
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return clean(raw)


def find_match_props_page(match_name):
    direct = WORLD_CUP_DIR / slugify(match_name.replace(" v ", " v ")) / "match-props" / "index.html"
    if direct.exists():
        return direct

    # Fallback: scan generated match-props pages and match both team names.
    parts = [clean(x) for x in match_name.split(" v ", 1)]
    for path in WORLD_CUP_DIR.glob("*/match-props/index.html"):
        text = html_text(path).lower()
        if len(parts) == 2 and all(part.lower() in text for part in parts):
            return path

    return direct


def main():
    stats = load_json(STATS_PATH)
    props = load_json(PROPS_PATH)

    props_by_match = {
        normalize(m.get("match")): m
        for m in props.get("matches", [])
    }

    total_markets = 0
    total_selections = 0
    merge_market_failures = []
    merge_selection_failures = []
    html_failures = []
    html_pages_missing = []
    checked_matches = 0

    print("BETVICTOR MATCH/TEAM SHOTS VALIDATION")
    print("=" * 72)

    for stats_match in stats.get("matches", []):
        markets = stats_match.get("markets", [])
        if not markets:
            continue

        checked_matches += 1
        match_name = clean(stats_match.get("match"))
        props_match = props_by_match.get(normalize(match_name))

        print(f"\n{match_name}")

        if not props_match:
            merge_market_failures.append((match_name, "<entire match missing>"))
            print("  MERGE: FAIL — match missing from final props JSON")
            continue

        props_markets = {
            normalize(m.get("normalized_market") or m.get("market")): m
            for m in props_match.get("markets", [])
        }

        page = find_match_props_page(match_name)
        page_text = html_text(page)

        if not page.exists():
            html_pages_missing.append((match_name, str(page)))
            print(f"  HTML: MISSING — {page}")
        else:
            print(f"  HTML: {page.relative_to(ROOT)}")

        match_merge_ok = True
        match_html_ok = True

        for stats_market in markets:
            total_markets += 1
            market_name = clean(stats_market.get("market"))
            market_key = normalize(
                stats_market.get("normalized_market") or market_name
            )
            final_market = props_markets.get(market_key)

            if not final_market:
                merge_market_failures.append((match_name, market_name))
                match_merge_ok = False
                print(f"    MERGE FAIL market: {market_name}")
                continue

            expected = {
                selection_key(s): s
                for s in stats_market.get("selections", [])
            }
            actual = {
                selection_key(s): s
                for s in final_market.get("selections", [])
            }

            total_selections += len(expected)

            for key, selection in expected.items():
                if key not in actual:
                    merge_selection_failures.append(
                        (
                            match_name,
                            market_name,
                            clean(selection.get("selection")),
                            clean(selection.get("odds")),
                        )
                    )
                    match_merge_ok = False
                    print(
                        "    MERGE FAIL selection: "
                        f"{market_name} | {selection.get('selection')} | "
                        f"{selection.get('odds')}"
                    )

            if page_text:
                market_visible = market_name.lower() in page_text.lower()
                if not market_visible:
                    html_failures.append(
                        (match_name, market_name, "<market label>", "")
                    )
                    match_html_ok = False
                    print(f"    HTML FAIL market label: {market_name}")

                for selection in stats_market.get("selections", []):
                    selection_name = clean(selection.get("selection"))
                    odds = clean(selection.get("odds"))
                    selection_visible = selection_name.lower() in page_text.lower()
                    odds_visible = odds.lower() in page_text.lower()

                    if not selection_visible or not odds_visible:
                        html_failures.append(
                            (
                                match_name,
                                market_name,
                                selection_name,
                                odds,
                            )
                        )
                        match_html_ok = False
                        print(
                            "    HTML FAIL: "
                            f"{market_name} | {selection_name} | {odds} "
                            f"(selection={selection_visible}, odds={odds_visible})"
                        )

        print(
            f"  RESULT: merge={'PASS' if match_merge_ok else 'FAIL'}, "
            f"html={'PASS' if match_html_ok and page.exists() else 'FAIL'}"
        )

    print("\n" + "=" * 72)
    print("SUMMARY")
    print(f"Matches checked:              {checked_matches}")
    print(f"Markets checked:              {total_markets}")
    print(f"Selections/odds checked:      {total_selections}")
    print(f"Missing merged markets:       {len(merge_market_failures)}")
    print(f"Missing/changed selections:   {len(merge_selection_failures)}")
    print(f"Missing generated pages:      {len(html_pages_missing)}")
    print(f"HTML visibility failures:     {len(html_failures)}")

    if (
        not merge_market_failures
        and not merge_selection_failures
        and not html_pages_missing
        and not html_failures
    ):
        print("\nPASS: BetVictor deep shot markets and odds are preserved and visible.")
        raise SystemExit(0)

    print("\nFAIL: Review the reported items before locking BetVictor Part 5.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
