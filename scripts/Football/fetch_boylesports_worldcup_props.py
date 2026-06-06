#!/usr/bin/env python3
"""
fetch_boylesports_worldcup_props.py

Uses curl_cffi to mimic Chrome's TLS fingerprint — bypasses Cloudflare.

Usage:
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
    "Both Teams To Score And Match Result": "btts_result",
    "Both Teams To Score":                  "btts",
    "Correct Score":                        "correct_score",
    "Half Time / Full Time":                "ht_ft",
    "Half Time Result":                     "half_time_result",
    "Double Chance":                        "double_chance",
    "Handicaps":                            "handicap",
    "Total Goals Over / Under":             "total_goals",
    "1st Half Goals Over / Under":          "first_half_goals",
    "Match Result And Total Goals":         "result_total_goals",
    "1 Goal Ahead":                         "one_goal_ahead",
}
PLAYER_MARKETS = {
    "Main Goalscorer Markets": "anytime_scorer",
    "Anytime Goalscorer":      "anytime_scorer",
    "First Goalscorer":        "first_scorer",
    "To Score 2 Or More":      "scorer_2_plus",
}
ALL_MARKETS = {**MATCH_MARKETS, **PLAYER_MARKETS}


def _find_market_name(panel) -> str:
    sibling = panel.find_previous_sibling()
    while sibling:
        text = sibling.get_text(separator=" ", strip=True)
        text = re.sub(r"\s*(Cash Out|i|\|)\s*", " ", text).strip()
        # Skip single chars, dates, empty strings
        if text and len(text) > 3 and not re.match(r'^\w{3}\s+\d+\s+\w+\s+\d{4}$', text):
            return text.split("\n")[0].strip()
        sibling = sibling.find_previous_sibling()
    return ""


def _match_market(label: str, mapping: dict):
    label_lower = label.lower().strip()
    # Exact match first
    for key, internal in mapping.items():
        if key.lower() == label_lower:
            return internal
    # Substring match — longer keys first so "Both Teams To Score And Match Result"
    # doesn't accidentally match the shorter "Both Teams To Score" key
    for key, internal in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
        if key.lower() in label_lower:
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


def parse_teams_from_slug(slug: str):
    """Extract home/away team names from URL slug like 'mexico-v-south-africa'."""
    parts = slug.split("-v-", 1)
    if len(parts) == 2:
        home = parts[0].replace("-", " ").title()
        away = parts[1].replace("-", " ").title()
        # Fix known aliases
        aliases = {
            "Bosnia & Herzegovina": "Bosnia & Herzegovina",
            "Usa": "USA",
            "Dr Congo": "DR Congo",
        }
        home = aliases.get(home, home)
        away = aliases.get(away, away)
        return home, away
    return "", ""


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
        home, away = parse_teams_from_slug(slug)
        name = f"{home} v {away}" if home and away else slug.replace("-", " ").title()

        fixtures.append({
            "name":      name,
            "url":       url,
            "home_team": home,
            "away_team": away,
        })

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

    session = requests.Session(impersonate="chrome124")

    print("\nWarming up session...")
    session.get(BASE_URL, timeout=20)
    time.sleep(2)

    fixtures = get_fixture_urls(session)
    if not fixtures:
        print("No fixtures found.")
        return

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
            "match":      fixture["name"],
            "home_team":  fixture["home_team"],
            "away_team":  fixture["away_team"],
            "url":        fixture["url"],
            "markets":    markets,
        })

        time.sleep(1.5)

    output = {
        "sport":        "football",
        "competition":  "FIFA World Cup",
        "bookmaker":    "BoyleSports",
        "source_url":   COMPETITION_URL,
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