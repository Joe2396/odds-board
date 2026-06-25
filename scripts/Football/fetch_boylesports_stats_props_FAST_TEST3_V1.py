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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
OUT_PATH = ROOT / "football" / "data" / "boylesports_stats_props_fast_test_v1.json"
DEBUG_DIR = ROOT / "football" / "debug" / "boylesports_stats_fast_test_v1"

MAX_MATCHES = 3
MAX_WORKERS = 3
SAVE_FULL_HTML = True
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


def fetch_stats_for_match(match: dict) -> tuple[dict, dict]:
    started = time.perf_counter()
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

    audit = {
        "match": match_name,
        "partial_url": partial_url,
        "status_code": None,
        "response_bytes": 0,
        "request_seconds": 0.0,
        "parse_seconds": 0.0,
        "total_seconds": 0.0,
        "security_verification": False,
        "error": "",
        "market_counts": {},
    }

    session = requests.Session(impersonate="chrome124")
    request_started = time.perf_counter()

    try:
        resp = session.get(
            partial_url,
            headers=headers,
            timeout=30,
        )
    except Exception as error:
        audit["request_seconds"] = round(
            time.perf_counter() - request_started,
            3,
        )
        audit["total_seconds"] = round(
            time.perf_counter() - started,
            3,
        )
        audit["error"] = str(error)
        return {}, audit

    audit["request_seconds"] = round(
        time.perf_counter() - request_started,
        3,
    )
    audit["status_code"] = resp.status_code
    audit["response_bytes"] = len(resp.content or b"")
    html = resp.text

    if SAVE_FULL_HTML:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (
            DEBUG_DIR
            / f"{slugify(match_name)}_stats.html"
        ).write_text(
            html,
            encoding="utf-8",
        )

    if resp.status_code != 200:
        audit["total_seconds"] = round(
            time.perf_counter() - started,
            3,
        )
        return {}, audit

    if (
        "Verify you are human" in html
        or "security verification" in html
    ):
        audit["security_verification"] = True
        audit["total_seconds"] = round(
            time.perf_counter() - started,
            3,
        )
        return {}, audit

    parse_started = time.perf_counter()
    markets = {}

    for market_key, title in MARKETS.items():
        section = extract_section_html(html, title)

        if not section:
            continue

        selections = parse_threshold_section(
            section,
            title,
            market_key,
        )

        if selections:
            markets[market_key] = {
                "label": title,
                "mm_id": STATS_MM_ID,
                "partial_url": partial_url,
                "selections": selections,
            }
            audit["market_counts"][market_key] = len(selections)

    audit["parse_seconds"] = round(
        time.perf_counter() - parse_started,
        3,
    )
    audit["total_seconds"] = round(
        time.perf_counter() - started,
        3,
    )
    return markets, audit


def process_match(
    index: int,
    match: dict,
) -> tuple[int, dict, dict]:
    markets, audit = fetch_stats_for_match(match)

    result = {
        "match": match.get("match", ""),
        "home_team": match.get("home_team", ""),
        "away_team": match.get("away_team", ""),
        "url": match.get("url", ""),
        "markets": markets,
    }

    return index, result, audit

def main():
    started = time.perf_counter()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    if not BASE_PROPS_PATH.exists():
        raise FileNotFoundError(f"Missing {BASE_PROPS_PATH}")

    base = json.loads(
        BASE_PROPS_PATH.read_text(encoding="utf-8")
    )

    matches = []

    for match in base.get("matches", []):
        name = match.get("match", "").lower()

        if any(
            skip in name
            for skip in SKIP_MATCH_SUBSTRINGS
        ):
            continue

        if not match.get("url"):
            continue

        matches.append(match)

    matches = matches[:MAX_MATCHES]

    print("BOYLESPORTS STATS PROPS — FAST TEST3 V1")
    print("=" * 72)
    print(f"MAX_MATCHES = {MAX_MATCHES}")
    print(f"MAX_WORKERS = {MAX_WORKERS}")
    print(f"Fixtures selected: {len(matches)}")

    for index, match in enumerate(matches, start=1):
        print(f"  {index:02d}. {match.get('match', '')}")

    if not matches:
        print("No matches found.")
        return

    ordered_results = [None] * len(matches)
    ordered_audits = [None] * len(matches)

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:
        futures = {
            executor.submit(
                process_match,
                index,
                match,
            ): index
            for index, match in enumerate(matches)
        }

        for future in as_completed(futures):
            fallback_index = futures[future]

            try:
                index, result, audit = future.result()
            except Exception as error:
                match = matches[fallback_index]
                index = fallback_index
                result = {
                    "match": match.get("match", ""),
                    "home_team": match.get("home_team", ""),
                    "away_team": match.get("away_team", ""),
                    "url": match.get("url", ""),
                    "markets": {},
                }
                audit = {
                    "match": result["match"],
                    "status_code": None,
                    "response_bytes": 0,
                    "request_seconds": 0.0,
                    "parse_seconds": 0.0,
                    "total_seconds": 0.0,
                    "security_verification": False,
                    "error": str(error),
                    "market_counts": {},
                }

            ordered_results[index] = result
            ordered_audits[index] = audit

            parts = [
                f"{key}({count})"
                for key, count
                in audit.get("market_counts", {}).items()
            ]
            markets_text = ", ".join(parts) if parts else "no stats"

            print(f"\n[{index + 1}/{len(matches)}] {result['match']}")
            print(
                f"  status={audit.get('status_code')} "
                f"bytes={audit.get('response_bytes', 0):,}"
            )
            print(
                f"  request={audit.get('request_seconds', 0):.3f}s "
                f"parse={audit.get('parse_seconds', 0):.3f}s "
                f"total={audit.get('total_seconds', 0):.3f}s"
            )
            print(f"  {markets_text}")

            if audit.get("error"):
                print(f"  ERROR: {audit['error']}")

            if audit.get("security_verification"):
                print("  SECURITY VERIFICATION")

    results = [
        result
        for result in ordered_results
        if result is not None
    ]
    audits = [
        audit
        for audit in ordered_audits
        if audit is not None
    ]

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BoyleSports",
        "market_type": "stats_props_fast_test_v1",
        "test_mode": True,
        "source_file": str(BASE_PROPS_PATH),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches": results,
        "audit": audits,
        "elapsed_seconds": round(
            time.perf_counter() - started,
            3,
        ),
    }

    OUT_PATH.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    complete = sum(
        1
        for result in results
        if len(result.get("markets", {})) == len(MARKETS)
    )

    print("\n" + "=" * 72)
    print(f"Saved TEST output: {OUT_PATH}")
    print(
        "Matches with all eight markets: "
        f"{complete}/{len(results)}"
    )
    print(f"Total elapsed: {output['elapsed_seconds']:.3f}s")
    print("Production BoyleSports files modified: NO")


if __name__ == "__main__":
    main()