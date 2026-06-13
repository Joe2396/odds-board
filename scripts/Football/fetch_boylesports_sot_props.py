#!/usr/bin/env python3
"""
fetch_boylesports_sot_props.py

Scrapes BoyleSports World Cup Player Shots On Target props.

Discovery:
  Boyle loads the Stats tab via partial HTML:
    ?partial=true&mm=1615

Reads:
  football/data/boylesports_worldcup_props.json

Writes:
  football/data/boylesports_stats_props.json
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
DEBUG_DIR = ROOT / "football" / "debug" / "boylesports_sot_html"

MAX_MATCHES = 15
SOT_MM_ID = "1615"

SKIP_MATCH_SUBSTRINGS = [
    "canada v bosnia",
    "usa v paraguay",
]

ALLOWED_THRESHOLDS = {
    "Over 0.5",
    "Over 1.5",
    "Over 2.5",
    "Over 3.5",
}

BAD_PLAYER_BITS = [
    " goals",
    "inside box",
    "outside box",
    "headed",
    "left foot",
    "right foot",
    "direct free kick",
    "on target",
    " total ",
    " total 0.5",
    " total 1.5",
    " total 2.5",
    " total 3.5",
    " total 4.5",
    " total 5.5",
    " total 6.5",
]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def make_partial_url(match_url: str, mm_id: str) -> str:
    parts = urlsplit(match_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, f"partial=true&mm={mm_id}", ""))


def is_bad_player_name(player: str) -> bool:
    lower = player.lower()

    if not player or len(player) < 3:
        return True

    if any(bad in lower for bad in BAD_PLAYER_BITS):
        return True

    if lower.startswith("over "):
        return True

    if lower.startswith("under "):
        return True

    if "show more" in lower:
        return True

    if "player shots" in lower:
        return True

    if "sub swap" in lower:
        return True

    if "betslip" in lower:
        return True

    if re.search(r"\d+/\d+", lower):
        return True

    return False


def parse_player_threshold_market(html: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    selections = []

    for player_el in soup.select(".player-name"):
        player = clean(player_el.get_text(" ", strip=True))

        if is_bad_player_name(player):
            continue

        row = player_el

        for _ in range(10):
            row = row.parent
            if row is None:
                break

            prices = row.select("[data-price]")

            if len(prices) >= 2:
                for price_el in prices:
                    threshold = clean(price_el.get("data-name", ""))
                    price = clean(price_el.get("data-price", ""))

                    if not threshold or not price:
                        continue

                    threshold = threshold.strip().title()

                    if threshold not in ALLOWED_THRESHOLDS:
                        continue

                    selections.append({
                        "player": player,
                        "threshold": threshold,
                        "price": price,
                        "name": f"{player} {threshold}",
                        "market_id": price_el.get("data-marketid", ""),
                        "selection_id": price_el.get("data-selectionid", ""),
                    })

                break

    final = []
    seen = set()
    player_counts = {}

    for s in selections:
        player = s["player"]
        threshold = s["threshold"]

        if is_bad_player_name(player):
            continue

        sig = (player, threshold)

        if sig in seen:
            continue

        if player_counts.get(player, 0) >= 4:
            continue

        seen.add(sig)
        player_counts[player] = player_counts.get(player, 0) + 1
        final.append(s)

    return final


def fetch_sot_for_match(session, match: dict) -> dict:
    match_name = match.get("match", "")
    match_url = match.get("url", "")

    partial_url = make_partial_url(match_url, SOT_MM_ID)

    headers = {
        "accept": "text/html",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "referer": match_url,
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "sec-fetch-dest": "empty",
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
    html_path = DEBUG_DIR / f"{slugify(match_name)}_sot.html"
    html_path.write_text(resp.text, encoding="utf-8")

    if resp.status_code != 200:
        print("  ⚠ Non-OK response")
        return {}

    if "Verify you are human" in resp.text or "security verification" in resp.text:
        print("  ⚠ Security verification returned")
        return {}

    if "Player Shots On Target Over" not in resp.text:
        print("  ⚠ SOT title not found in partial HTML")
        return {}

    selections = parse_player_threshold_market(resp.text)

    if not selections:
        print("  - no selections parsed")
        return {}

    print(f"  ✓ player_shots_on_target({len(selections)})")

    return {
        "player_shots_on_target": {
            "label": "Player Shots On Target Over",
            "mm_id": SOT_MM_ID,
            "partial_url": partial_url,
            "selections": selections,
        }
    }


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

        markets = fetch_sot_for_match(session, match)

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
        mk = r.get("markets", {})
        if not mk:
            status = "no SOT"
        else:
            status = f"player_shots_on_target({len(mk['player_shots_on_target']['selections'])})"

        print(f"  {r['match']:<40} {status}")

    print("─" * 60)


if __name__ == "__main__":
    main()