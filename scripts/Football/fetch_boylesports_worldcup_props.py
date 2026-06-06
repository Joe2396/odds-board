#!/usr/bin/env python3
"""
fetch_boylesports_worldcup_props.py

Uses curl_cffi to mimic Chrome's TLS fingerprint — the actual thing Cloudflare checks.
No browser needed. Install with:

    pip install curl_cffi beautifulsoup4 lxml
    python fetch_boylesports_worldcup_props.py
"""

import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests
    print("✓ curl_cffi loaded")
except ImportError:
    print("✗ curl_cffi not installed. Run: pip install curl_cffi")
    exit(1)

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH   = ROOT / "football" / "data" / "boylesports_worldcup_props.json"
DEBUG_PATH = ROOT / "football" / "debug" / "boylesports_props_debug.txt"

BASE_URL        = "https://www.boylesports.com"
COMPETITION_URL = f"{BASE_URL}/sports/football/competition/international-world-cup"
MAX_FIXTURES    = 15

MATCH_MARKETS = {
    "Match Betting":                        "match_betting",
    "Both Teams To Score":                  "btts",
    "Correct Score":                        "correct_score",
    "Half Time Result":                     "half_time_result",
    "Double Chance":                        "double_chance",
    "Handicaps":                            "handicap",
    "Total Goals Over / Under":             "total_goals",
    "1st Half Goals Over / Under":          "first_half_goals",
    "Half Time / Full Time":                "ht_ft",
    "Both Teams To Score And Match Result": "btts_result",
    "Match Result And Total Goals":         "result_total_goals",
}
PLAYER_MARKETS = {
    "Anytime Goalscorer": "anytime_scorer",
    "First Goalscorer":   "first_scorer",
    "To Score 2 Or More": "scorer_2_plus",
}
ALL_MARKETS = {**MATCH_MARKETS, **PLAYER_MARKETS}


def _find_market_name(panel) -> str:
    sibling = panel.find_previous_sibling()
    while sibling:
        text = sibling.get_text(separator=" ", strip=True)
        text = re.sub(r"\s*(Cash Out|i|\|)\s*", " ", text).strip()
        if text and len(text) > 2:
            return text.split("\n")[0].strip()
        sibling = sibling.find_previous_sibling()
    return ""


def _match_market(label: str, mapping: dict):
    label_lower = label.lower()
    for key, internal in mapping.items():
        if key.lower() in label_lower or label_lower in key.lower():
            return internal
    return None


def parse_markets(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    markets = {}
    for panel in soup.select("div.panel"):
        market_name = _find_market_name(panel)
        if not market_name:
            continue
        internal = _match_market(market_name, ALL_MARKETS)
        if not internal:
            continue
        selections = []
        for el in panel.select("[data-price]"):
            name  = el.get("data-name", "").strip()
            price = el.get("data-price", "").strip()
            if name and price:
                selections.append({
                    "name":         name,
                    "price":        price,
                    "market_id":    el.get("data-marketid", ""),
                    "selection_id": el.get("data-selectionid", ""),
                })
        if selections:
            markets[internal] = {"label": market_name, "selections": selections}
    return markets


def get_fixture_urls(session) -> list:
    print(f"Fetching fixture list...")
    resp = session.get(COMPETITION_URL, timeout=30)
    print(f"  Competition page status: {resp.status_code}")

    if resp.status_code != 200:
        print(f"  ⚠ Failed to load competition page")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    seen = set()
    fixtures = []
    for a in soup.select("a[href*='/event/international-world-cup/']"):
        url = a["href"]
        if not url.startswith("http"):
            url = BASE_URL + url
        if url in seen:
            continue
        seen.add(url)
        slug = url.split("/")[-1]
        name = slug.replace("-v-", " v ").replace("-", " ").title()
        fixtures.append({"name": name, "url": url})
        if len(fixtures) >= MAX_FIXTURES:
            break

    print(f"  Found {len(fixtures)} fixtures")
    return fixtures


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("BoyleSports World Cup Props Scraper (curl_cffi)")
    print("=" * 60)

    # curl_cffi session impersonating Chrome 124
    session = requests.Session(impersonate="chrome124")

    # Warm up with homepage first
    print("\nWarming up session...")
    session.get(BASE_URL, timeout=20)
    time.sleep(2)

    # Get fixture list
    fixtures = get_fixture_urls(session)
    if not fixtures:
        print("No fixtures found.")
        return

    # Scrape each match page
    results = []
    for i, fixture in enumerate(fixtures):
        print(f"\n[{i+1}/{len(fixtures)}] {fixture['name']}")

        try:
            resp = session.get(fixture["url"], timeout=30)
            print(f"  Status: {resp.status_code}")

            if "Verify you are human" in resp.text:
                print("  ⚠ Cloudflare block")
                markets = {}
            elif resp.status_code == 200:
                markets = parse_markets(resp.text)
                print(f"  ✓ {len(markets)} markets: {list(markets.keys())}")
            else:
                markets = {}

        except Exception as e:
            print(f"  ⚠ Error: {e}")
            markets = {}

        results.append({
            "match":   fixture["name"],
            "url":     fixture["url"],
            "markets": markets,
        })

        time.sleep(1.5)

    # Save
    output = {
        "sport":        "football",
        "competition":  "FIFA World Cup",
        "bookmaker":    "BoyleSports",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count":  len(results),
        "matches":      results,
    }
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved → {OUT_PATH}")
    print("\n── Summary ─────────────────────────────────────────────")
    for r in results:
        status = "BLOCKED" if not r["markets"] else f"{len(r['markets'])} markets"
        print(f"  {r['match']:<40} {status}")
    print("─" * 60)


if __name__ == "__main__":
    main()