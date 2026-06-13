#!/usr/bin/env python3
"""
fetch_boylesports_stats_props.py

Scrapes BoyleSports World Cup Stats props from partial HTML.

Reads:
  football/data/boylesports_worldcup_props.json

Writes:
  football/data/boylesports_stats_props.json

Known Boyle partial:
  ?partial=true&mm=1615

This response contains many Stats sections, including:
  Player Shots
  Player Shots On Target
  Player Assists
  Player Tackles
  Team Shots
  Team Shots On Target
  Match Shots
  Match Shots On Target
"""

import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests
    print("✓ curl_cffi loaded")
except ImportError:
    print("✗ curl_cffi not installed. Run: pip install curl_cffi")
    raise SystemExit(1)


ROOT = Path(__file__).resolve().parents[2]

BASE_PROPS_PATH = ROOT / "football" / "data" / "boylesports_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "boylesports_stats_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "boylesports_stats_html"

MAX_MATCHES = 15
STATS_MM_ID = "1615"

SKIP_MATCH_SUBSTRINGS = [
    "canada v bosnia",
    "usa v paraguay",
]

MARKETS = {
    "player_shots": "Player Shots Over",
    "player_shots_on_target": "Player Shots On Target Over",
    "player_assists": "Player Assists Over",
    "player_tackles": "Player Tackles Over",
    "team_shots": "Team Shots Over",
    "team_shots_on_target": "Team Shots On Target Over",
    "match_shots": "Match Shots Over",
    "match_shots_on_target": "Match Shots On Target Over",
}

BAD_PLAYER_BITS = [
    "right foot",
    "left foot",
    "header",
    "headed",
    "inside box",
    "outside box",
    "direct free kick",
    "goals inside",
    "goals outside",
    "headed goals",
    "left foot goals",
    "right foot goals",
    "on target right foot",
    "on target left foot",
    "on target header",
    "to score",
    "show more",
    "sub swap",
    "betslip",
]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def make_partial_url(match_url: str) -> str:
    parts = urlsplit(match_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, f"partial=true&mm={STATS_MM_ID}", ""))


def is_bad_name(name: str) -> bool:
    low = name.lower()

    if not name or len(name) < 2:
        return True

    if re.search(r"\d+/\d+", low):
        return True

    if low.startswith("over ") or low.startswith("under "):
        return True

    return any(bad in low for bad in BAD_PLAYER_BITS)


def extract_section_html(html: str, title: str) -> str:
    """
    Pulls one market section from the large partial response.
    Starts at the requested title and stops at the next known title.
    """
    low = html.lower()
    start = low.find(title.lower())

    if start == -1:
        return ""

    stops = []

    for other_title in MARKETS.values():
        if other_title.lower() == title.lower():
            continue

        idx = low.find(other_title.lower(), start + len(title))
        if idx != -1:
            stops.append(idx)

    # Also stop before noisy sections we do not want.
    noisy_stops = [
        "Player Shots Inside / Outside The Box",
        "To Score With",
        "To Score From",
        "Team Assists Over",
        "Team Tackles Over",
        "Match Assists Over",
        "Match Tackles Over",
    ]

    for noisy in noisy_stops:
        idx = low.find(noisy.lower(), start + len(title))
        if idx != -1:
            stops.append(idx)

    end = min(stops) if stops else len(html)

    return html[start:end]


def parse_threshold_section(section_html: str, title: str, market_key: str) -> list:
    soup = BeautifulSoup(section_html, "lxml")
    selections = []

    for name_el in soup.select(".player-name"):
        name = clean(name_el.get_text(" ", strip=True))

        if is_bad_name(name):
            continue

        row = name_el

        for _ in range(10):
            row = row.parent
            if row is None:
                break

            prices = row.select("[data-price]")

            if not prices:
                continue

            for price_el in prices:
                threshold = clean(price_el.get("data-name", "")).title()
                price = clean(price_el.get("data-price", ""))

                if not threshold or not price:
                    continue

                if not threshold.startswith("Over "):
                    continue

                selections.append({
                    "name": f"{name} {threshold}",
                    "selection": name,
                    "threshold": threshold,
                    "price": price,
                    "market_id": price_el.get("data-marketid", ""),
                    "selection_id": price_el.get("data-selectionid", ""),
                })

            break

    final = []
    seen = set()
    counts = {}

    for s in selections:
        base = s["selection"]
        threshold = s["threshold"]

        if is_bad_name(base):
            continue

        sig = (base, threshold)

        if sig in seen:
            continue

        # Most sections have 1-4 lines per player/team/match.
        if counts.get(base, 0) >= 6:
            continue

        seen.add(sig)
        counts[base] = counts.get(base, 0) + 1
        final.append(s)

    return final


def fetch_stats_for_match(session, match: dict) -> dict:
    match_name = match.get("match", "")
    match_url = match.get("url", "")
    partial_url = make_partial_url(match_url)

    headers = {
        "accept": "text/html",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "referer": match_url,
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
    }

    print(f"\n{match_name}")
    print(f"  {partial_url}")

    try:
        resp = session.get(partial_url, headers=headers, timeout=30)
    except Exception as e:
        print(f"  ⚠ Error: {e}")
        return {}

    print(f"  Status: {resp.status_code}, length={len(resp.text)}")

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / f"{slugify(match_name)}_stats.html").write_text(resp.text, encoding="utf-8")

    if resp.status_code != 200:
        return {}

    if "Verify you are human" in resp.text or "security verification" in resp.text:
        print("  ⚠ Security verification returned")
        return {}

    markets = {}

    for market_key, title in MARKETS.items():
        section = extract_section_html(resp.text, title)

        if not section:
            print(f"  - {market_key}: not found")
            continue

        selections = parse_threshold_section(section, title, market_key)

        if selections:
            markets[market_key] = {
                "label": title,
                "mm_id": STATS_MM_ID,
                "partial_url": partial_url,
                "selections": selections,
            }
            print(f"  ✓ {market_key}({len(selections)})")
        else:
            print(f"  - {market_key}: 0 selections")

    return markets


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    if not BASE_PROPS_PATH.exists():
        raise FileNotFoundError(f"Missing {BASE_PROPS_PATH}")

    base = json.loads(BASE_PROPS_PATH.read_text(encoding="utf-8"))

    matches = []

    for m in base.get("matches", []):
        name = m.get("match", "").lower()

        if any(skip in name for skip in SKIP_MATCH_SUBSTRINGS):
            print(f"Skipping finished match: {m.get('match')}")
            continue

        matches.append(m)

    matches = matches[:MAX_MATCHES]

    if not matches:
        print("No matches found.")
        return

    session = requests.Session(impersonate="chrome124")
    results = []

    for i, match in enumerate(matches, 1):
        print(f"\n[{i}/{len(matches)}]", end=" ")

        markets = fetch_stats_for_match(session, match)

        results.append({
            "match": match.get("match", ""),
            "home_team": match.get("home_team", ""),
            "away_team": match.get("away_team", ""),
            "url": match.get("url", ""),
            "markets": markets,
        })

        time.sleep(1.0)

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BoyleSports",
        "market_type": "stats_props",
        "source_file": str(BASE_PROPS_PATH),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches": results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ Saved → {OUT_PATH}")

    print("\n── Summary ──────────────────────────────────────────────")
    for r in results:
        parts = [
            f"{k}({len(v.get('selections', []))})"
            for k, v in r.get("markets", {}).items()
        ]
        status = ", ".join(parts) if parts else "no stats"
        print(f"  {r['match']:<40} {status}")

    print("─" * 60)


if __name__ == "__main__":
    main()