#!/usr/bin/env python3
"""
fetch_boylesports_worldcup_props.py

Scrapes BoyleSports World Cup match props using curl_cffi.

Markets:
  Match Betting, Half Time Result, Handicap (-1/+1 only),
  Total Goals O/U, 1st Half Goals O/U, BTTS, Double Chance,
  Total Corners O/U, Team Total Corners O/U,
  Total Team Goals O/U, 1st Half Total Team Goals,
  First Goalscorer, Anytime Goalscorer, To Score 2+,
  Player To Be Booked, Player To Be Sent Off,
  Player Shots, Player Shots On Target

IMPORTANT:
  If Boyle returns 0 fixtures, this script will NOT overwrite the last good JSON.
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
    raise SystemExit(1)


ROOT       = Path(__file__).resolve().parents[2]
OUT_PATH   = ROOT / "football" / "data" / "boylesports_worldcup_props.json"
DEBUG_PATH = ROOT / "football" / "debug" / "boylesports_props_debug.txt"

BASE_URL        = "https://www.boylesports.com"
COMPETITION_URL = f"{BASE_URL}/sports/football/competition/international-world-cup"
MAX_FIXTURES    = 15


MARKET_MAP = {
    "Match Betting":                    "match_betting",
    "Half Time Result":                 "half_time_result",
    "Handicaps":                        "handicap",
    "Total Goals Over / Under":         "total_goals",
    "1st Half Goals Over / Under":      "first_half_goals",
    "Both Teams To Score":              "btts",
    "Double Chance":                    "double_chance",
    "Total Corners Over / Under":       "total_corners",
    "Team Total Corners Over / Under":  "team_total_corners",
    "Total Team Goals Over / Under":    "team_total_goals",
    "1st Half Total Team Goals":        "first_half_team_goals",
    "Main Goalscorer Markets":          "goalscorers",
    "Player To Be Booked":              "player_booked",
    "Player To Be Sent Off":            "player_sent_off",

    # These may or may not be exact Boyle labels.
    "Player Shots On Target Over":      "player_shots_on_target",
    "Player Shots On Target":           "player_shots_on_target",
    "Shots On Target":                  "player_shots_on_target",
    "Player Shots Over":                "player_shots",
    "Player Shots":                     "player_shots",
    "Total Shots":                      "player_shots",
}


def clean_text(text: str) -> str:
    text = re.sub(r"\bCash Out\b", "", text or "", flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def find_market_label(panel) -> str:
    luf = panel.parent
    if luf is None:
        return ""

    text = clean_text(luf.get_text(separator=" ", strip=True))
    text = re.sub(r"\bi\b", "", text).strip()

    # Try to cut the label before common table/header content.
    cut_patterns = [
        r"\bHome Draw Away\b",
        r"\bOver Under\b",
        r"\bFirst Anytime\b",
        r"\bYes No\b",
        r"\bIf your selected player\b",
        r"\bIf your team goes\b",
    ]

    label = text
    for pat in cut_patterns:
        m = re.search(pat, label, flags=re.I)
        if m:
            label = label[:m.start()].strip()
            break

    return clean_text(label[:120])


def force_market_key_from_text(label: str, full_text: str) -> str | None:
    blob = f"{label} {full_text}".lower()

    # Important: SOT before shots, because SOT includes the word shots.
    if "shots on target" in blob or "shot on target" in blob:
        return "player_shots_on_target"

    if (
        "player shots" in blob
        or "total shots" in blob
        or "to have 1+ shots" in blob
        or "to have 2+ shots" in blob
        or "to have 3+ shots" in blob
    ):
        return "player_shots"

    return None


def match_market_key(label: str, full_text: str = "") -> str | None:
    label_lower = label.lower().strip()

    for key, internal in MARKET_MAP.items():
        if key.lower() == label_lower:
            return internal

    for key, internal in sorted(MARKET_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if key.lower() in label_lower:
            return internal

    forced = force_market_key_from_text(label, full_text)
    if forced:
        return forced

    return None


def get_selections(panel) -> list:
    sels = []
    seen = set()

    for el in panel.select("[data-price]"):
        name  = el.get("data-name", "").strip()
        price = el.get("data-price", "").strip()

        if not name or not price:
            continue

        item = {
            "name":         name,
            "price":        price,
            "market_id":    el.get("data-marketid", ""),
            "selection_id": el.get("data-selectionid", ""),
        }

        sig = (item["name"], item["price"], item["market_id"], item["selection_id"])
        if sig in seen:
            continue
        seen.add(sig)

        sels.append(item)

    return sels


def parse_handicap_main_line(panel) -> list:
    all_sels = get_selections(panel)
    return [s for s in all_sels if re.search(r"[+-]1(?:\s|$)", s["name"])]


def parse_goalscorer_market(panel) -> dict:
    result = {"first": [], "anytime": [], "two_plus": [], "three_plus": []}

    headers = []
    header_row = panel.select_one("tr")
    if header_row:
        headers = [th.get_text(strip=True).lower() for th in header_row.select("th")]

    col_map = {}
    for i, h in enumerate(headers):
        if h == "first":
            col_map["first"] = i
        elif h == "anytime":
            col_map["anytime"] = i
        elif "2+" in h:
            col_map["two_plus"] = i
        elif "3+" in h:
            col_map["three_plus"] = i

    rows = panel.select("tr")[1:] if header_row else panel.select("tr")

    for row in rows:
        cells = row.select("td")
        if not cells:
            continue

        player_name = cells[0].get_text(strip=True)
        if not player_name or player_name.lower() in ("first", "anytime", "2+", "3+"):
            continue

        def get_price(col_key):
            idx = col_map.get(col_key)
            if idx is None or idx >= len(cells):
                return None
            el = cells[idx].select_one("[data-price]")
            return el.get("data-price", "").strip() if el else None

        for col_key in ["first", "anytime", "two_plus", "three_plus"]:
            price = get_price(col_key)
            if price and price != "N/A":
                result[col_key].append({"name": player_name, "price": price})

    if not any(result.values()):
        bucket_keys = ["first", "anytime", "two_plus", "three_plus"]
        player_sels = {}

        for sel in get_selections(panel):
            player_sels.setdefault(sel["name"], []).append(sel["price"])

        for player, prices in player_sels.items():
            for i, price in enumerate(prices[:4]):
                if price and price != "N/A":
                    result[bucket_keys[i]].append({"name": player, "price": price})

    return result


def parse_player_booked(panel) -> list:
    return get_selections(panel)


def parse_player_threshold_market(panel) -> list:
    """
    Handles player lines like:
      Christian Pulisic Over 0.5 4/6
      Christian Pulisic Over 1.5 3/1
      or data-name containing "Christian Pulisic To Have 1+ Shots On Target"
    """
    out = []
    seen = set()

    # First try row-based parsing.
    rows = panel.select(".sports-row, tr, .event-selection, .market-row, li")

    for row in rows:
        row_text = clean_text(row.get_text(" ", strip=True))
        prices = row.select("[data-price]")
        if not prices:
            continue

        player_el = row.select_one(".player-name, span.player-name, .participant-name")
        player = player_el.get_text(strip=True) if player_el else ""

        for el in prices:
            price = el.get("data-price", "").strip()
            data_name = clean_text(el.get("data-name", ""))

            if not price:
                continue

            name_text = data_name or row_text

            threshold = ""
            m = re.search(r"(Over\s+\d+(?:\.\d+)?)", name_text, flags=re.I)
            if m:
                threshold = m.group(1).title()

            plus = re.search(r"\b(\d+)\+\s+Shots?(?:\s+On\s+Target)?", name_text, flags=re.I)
            if plus:
                threshold = f"Over {int(plus.group(1)) - 0.5:g}"

            if not player:
                player = name_text
                player = re.sub(r"\bTo Have\b.*$", "", player, flags=re.I).strip()
                player = re.sub(r"\bOver\s+\d+(?:\.\d+)?.*$", "", player, flags=re.I).strip()

            if not player or not threshold:
                continue

            item = {
                "player": player,
                "threshold": threshold,
                "price": price,
                "name": f"{player} {threshold}",
                "market_id": el.get("data-marketid", ""),
                "selection_id": el.get("data-selectionid", ""),
            }

            sig = (item["player"], item["threshold"], item["price"], item["selection_id"])
            if sig in seen:
                continue
            seen.add(sig)
            out.append(item)

    # Fallback: pure data-price scan.
    if not out:
        for el in panel.select("[data-price]"):
            price = el.get("data-price", "").strip()
            data_name = clean_text(el.get("data-name", ""))

            if not price or not data_name:
                continue

            if "shot" not in data_name.lower():
                continue

            player = re.sub(r"\bTo Have\b.*$", "", data_name, flags=re.I).strip()

            threshold = ""
            plus = re.search(r"\b(\d+)\+\s+Shots?", data_name, flags=re.I)
            if plus:
                threshold = f"Over {int(plus.group(1)) - 0.5:g}"

            over = re.search(r"(Over\s+\d+(?:\.\d+)?)", data_name, flags=re.I)
            if over:
                threshold = over.group(1).title()

            if not player or not threshold:
                continue

            item = {
                "player": player,
                "threshold": threshold,
                "price": price,
                "name": f"{player} {threshold}",
                "market_id": el.get("data-marketid", ""),
                "selection_id": el.get("data-selectionid", ""),
            }

            sig = (item["player"], item["threshold"], item["price"], item["selection_id"])
            if sig in seen:
                continue
            seen.add(sig)
            out.append(item)

    return out


def parse_markets(html: str, home: str, away: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    markets = {}
    all_labels = []
    unknown_interesting = []

    for panel in soup.select("div.panel"):
        label = find_market_label(panel)
        panel_text = clean_text(panel.get_text(" ", strip=True))
        full_text = clean_text(f"{label} {panel_text}")

        if not label:
            continue

        all_labels.append(label)

        key = match_market_key(label, full_text)

        if not key:
            low = full_text.lower()
            if "shot" in low or "target" in low or "player" in low:
                unknown_interesting.append(label)
            continue

        if key in markets:
            continue

        if key == "handicap":
            sels = parse_handicap_main_line(panel)
            if sels:
                markets[key] = {"label": label, "selections": sels}

        elif key == "goalscorers":
            parsed = parse_goalscorer_market(panel)
            if any(parsed.values()):
                markets[key] = {"label": label, "selections": parsed}

        elif key in ("player_booked", "player_sent_off"):
            sels = parse_player_booked(panel)
            if sels:
                markets[key] = {"label": label, "selections": sels}

        elif key in ("player_shots_on_target", "player_shots"):
            sels = parse_player_threshold_market(panel)
            if sels:
                markets[key] = {"label": label, "selections": sels}
                print(f"  🎯 {key}: {len(sels)} selections from label: {label}")
            else:
                print(f"  ⚠ Found {key} label but parsed 0 selections: {label}")

        else:
            sels = get_selections(panel)
            if sels:
                markets[key] = {"label": label, "selections": sels}

    with DEBUG_PATH.open("a", encoding="utf-8") as f:
        f.write("\n\n============================================================\n")
        f.write(f"DEBUG MARKET LABELS — {datetime.now(timezone.utc).isoformat()}\n")
        f.write("============================================================\n")
        for lbl in sorted(set(all_labels)):
            f.write(lbl + "\n")

        if unknown_interesting:
            f.write("\nUNKNOWN INTERESTING LABELS\n")
            for lbl in sorted(set(unknown_interesting)):
                f.write(lbl + "\n")

    return markets


def parse_teams_from_slug(slug: str):
    parts = slug.split("-v-", 1)

    if len(parts) == 2:
        home = parts[0].replace("-", " ").title()
        away = parts[1].replace("-", " ").title()

        aliases = {
            "Usa": "USA",
            "Dr Congo": "DR Congo",
            "Turkey": "Turkey",
        }

        home = aliases.get(home, home)
        away = aliases.get(away, away)

        return home, away

    return "", ""


def get_fixture_urls(session) -> list:
    print("Fetching fixture list...")

    resp = session.get(COMPETITION_URL, timeout=30)
    print(f"  Status: {resp.status_code}")

    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.write_text(
        f"Fixture list status: {resp.status_code}\nURL: {COMPETITION_URL}\n\n{resp.text[:20000]}",
        encoding="utf-8",
    )

    if resp.status_code != 200:
        return []

    if "Verify you are human" in resp.text:
        print("  ⚠ Human verification page returned")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    seen = set()
    fixtures = []

    for a in soup.select("a[href*='/event/international-world-cup/']"):
        url = a.get("href", "")
        if not url:
            continue

        if not url.startswith("http"):
            url = BASE_URL + url

        if url in seen:
            continue

        seen.add(url)

        slug = url.split("/")[-1]
        home, away = parse_teams_from_slug(slug)
        name = f"{home} v {away}" if home and away else slug.replace("-", " ").title()

        fixtures.append({
            "name": name,
            "url": url,
            "home_team": home,
            "away_team": away,
        })

        if len(fixtures) >= MAX_FIXTURES:
            break

    print(f"  Found {len(fixtures)} fixtures")
    return fixtures


def summarise_markets(markets: dict) -> str:
    parts = []

    for key, val in markets.items():
        if key == "goalscorers":
            counts = {k: len(v) for k, v in val["selections"].items()}
            parts.append(f"goalscorers({counts})")
        else:
            parts.append(f"{key}({len(val['selections'])})")

    return ", ".join(parts) if parts else "none"


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("BoyleSports World Cup Props Scraper")
    print("=" * 60)

    session = requests.Session(impersonate="chrome124")

    print("\nWarming up session...")
    try:
        session.get(BASE_URL, timeout=20)
        time.sleep(2)
    except Exception as e:
        print(f"Warmup warning: {e}")

    fixtures = get_fixture_urls(session)

    if not fixtures:
        print("No fixtures found — keeping existing JSON safe.")
        print(f"Debug saved → {DEBUG_PATH}")
        return

    results = []

    for i, fixture in enumerate(fixtures):
        print(f"\n[{i + 1}/{len(fixtures)}] {fixture['name']}")

        try:
            resp = session.get(fixture["url"], timeout=30)
            print(f"  Status: {resp.status_code}")

            if "Verify you are human" in resp.text:
                print("  ⚠ Cloudflare / human verification block")
                markets = {}

            elif resp.status_code == 200:
                markets = parse_markets(resp.text, fixture["home_team"], fixture["away_team"])
                print(f"  ✓ {summarise_markets(markets)}")

            else:
                markets = {}

        except Exception as e:
            print(f"  ⚠ Error: {e}")
            markets = {}

        results.append({
            "match": fixture["name"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "url": fixture["url"],
            "markets": markets,
        })

        time.sleep(1.5)

    good_market_count = sum(1 for r in results if r["markets"])

    if good_market_count == 0:
        print("\n⚠ 0 matches returned markets — keeping existing JSON safe.")
        print(f"Debug saved → {DEBUG_PATH}")
        return

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BoyleSports",
        "market_type": "props",
        "source_url": COMPETITION_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches": results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ Saved → {OUT_PATH}")

    print("\n── Summary ──────────────────────────────────────────────")
    for r in results:
        status = "BLOCKED" if not r["markets"] else f"{len(r['markets'])} markets"
        print(f"  {r['match']:<40} {status}")
    print("─" * 60)

    print(f"\nDebug labels saved → {DEBUG_PATH}")


if __name__ == "__main__":
    main()