#!/usr/bin/env python3
# BOYLESPORTS_WORLD_CUP_PROPS_PROD15_FAST_STANDALONE_V2
# BOYLESPORTS_WORLD_CUP_PROPS_FAST_TEST3_V1

"""
Three-fixture concurrent speed test for BoyleSports core World Cup props.

Uses the existing production parser functions unchanged, but:
- discovers fixture URLs once;
- joins them to BoyleSports moneyline kickoff data;
- removes started/in-play fixtures using Europe/Dublin time + 15 minutes;
- fetches the next three event pages concurrently;
- writes only separate test JSON/debug files.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from curl_cffi import requests

ROOT = Path(__file__).resolve().parents[2]
MONEYLINES_PATH = ROOT / "football" / "data" / "boylesports_worldcup_moneylines.json"
OUT_PATH = ROOT / "football" / "data" / "boylesports_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "boylesports_props_fast"

BASE_URL = "https://www.boylesports.com"
COMPETITION_URL = f"{BASE_URL}/sports/football/competition/international-world-cup"

MAX_FIXTURES = 7
MAX_WORKERS = 3
UPCOMING_BUFFER_MINUTES = 15
LOCAL_TIMEZONE = ZoneInfo("Europe/Dublin")

_thread_state = threading.local()


class ThreadLocalDebugPath:
    """Redirect the imported parser's debug append into one file per fixture."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def open(self, mode: str = "r", encoding: str | None = None):
        slug = getattr(_thread_state, "fixture_slug", "unknown-fixture")
        path = self.root / f"{slug}_labels.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open(mode, encoding=encoding)


# The original validated BoyleSports parser is embedded below.
# DEBUG_PATH is redirected to one file per worker/fixture.
DEBUG_PATH = ThreadLocalDebugPath(DEBUG_DIR)


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



# BOYLESPORTS_TEAM_CORNERS_SCOPE_V1

def _boylesports_corner_row(price_el, panel, home, away):
    node = price_el
    teams = [clean_text(x) for x in (home, away) if clean_text(x)]
    for _ in range(9):
        node = getattr(node, 'parent', None)
        if node is None:
            break
        text = clean_text(node.get_text(' ', strip=True))
        for team in teams:
            m = re.search(
                rf'(?:^|\s){re.escape(team)}\s+Total\s+Corners\s+O\s*/\s*U\s+(\d+(?:\.\d+)?)(?:\s|$)',
                text,
                re.I,
            )
            if m:
                return team, m.group(1), text
        if node == panel:
            break
    return '', '', ''


def parse_team_total_corners_markets(panel, home, away):
    grouped = {}
    for el in panel.select('[data-price][data-marketid]'):
        market_id = clean_text(el.get('data-marketid', ''))
        price = clean_text(el.get('data-price', ''))
        data_name = clean_text(el.get('data-name', ''))
        m = re.search(r'\b(Over|Under)\s+(\d+(?:\.\d+)?)\b', data_name, re.I)
        if not market_id or not price or not m:
            continue
        side, data_line = m.group(1).lower(), m.group(2)
        team, row_line, row_text = _boylesports_corner_row(el, panel, home, away)
        if not team or not row_line or row_line != data_line:
            continue
        entry = grouped.setdefault(market_id, {'team': team, 'line': row_line, 'sides': {}})
        if entry['team'] != team or entry['line'] != row_line:
            entry['conflict'] = True
            continue
        label = f'{team} {side.title()} {row_line}'
        entry['sides'][side] = {
            'name': label,
            'selection': label,
            'price': price,
            'odds': price,
            'team': team,
            'side': side,
            'line': row_line,
            'market_id': market_id,
            'selection_id': clean_text(el.get('data-selectionid', '')),
            'source_row': row_text,
        }

    by_team = {clean_text(home): [], clean_text(away): []}
    for entry in grouped.values():
        if entry.get('conflict'):
            continue
        over = entry['sides'].get('over')
        under = entry['sides'].get('under')
        team = entry['team']
        if over and under and team in by_team:
            by_team[team].extend([over, under])

    markets = {}
    for team in (clean_text(home), clean_text(away)):
        selections = by_team.get(team, [])
        selections.sort(key=lambda x: (float(x['line']), 0 if x['side'] == 'over' else 1))
        if not selections:
            continue
        name = f'{team} Total Corners Over / Under'
        markets[name] = {
            'label': name,
            'market': name,
            'normalized_market': re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_'),
            'selection_count': len(selections),
            'complete_pair_count': len(selections) // 2,
            'scope': 'team',
            'team': team,
            'parser': 'boylesports_market_id_row_scope_v1',
            'selections': selections,
        }
    return markets


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

        if key == "team_total_corners":
            scoped = parse_team_total_corners_markets(panel, home, away)
            markets.update(scoped)
            if scoped:
                print("  Team total corners scoped: " + ", ".join(
                    f"{name}({market.get('complete_pair_count', 0)} pairs)"
                    for name, market in scoped.items()
                ))
            else:
                print("  WARNING: Team Total Corners found but no safe scoped pairs parsed")
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


def summarise_markets(markets: dict) -> str:
    parts = []

    for key, val in markets.items():
        if key == "goalscorers":
            counts = {k: len(v) for k, v in val["selections"].items()}
            parts.append(f"goalscorers({counts})")
        else:
            parts.append(f"{key}({len(val['selections'])})")

    return ", ".join(parts) if parts else "none"


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean(value).lower()).strip("-")


def norm_team(value: str) -> str:
    value = clean(value).lower().replace("&", "and")
    replacements = {
        "bosnia and herzegovina": "bosnia",
        "bosnia herzegovina": "bosnia",
        "united states": "usa",
        "u s a": "usa",
        "south korea": "korea republic",
        "korea republic": "korea republic",
        "czech republic": "czechia",
        "turkey": "turkiye",
        "türkiye": "turkiye",
        "curaçao": "curacao",
        "ivory coast": "cote divoire",
        "côte d ivoire": "cote divoire",
        "cote d ivoire": "cote divoire",
        "dr congo": "congo dr",
        "d r congo": "congo dr",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def split_match_name(value: str) -> tuple[str, str]:
    value = clean(value)
    for separator in (" v ", " vs ", " versus "):
        parts = re.split(re.escape(separator), value, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            return clean(parts[0]), clean(parts[1])
    return "", ""


def fixture_key(row: dict) -> tuple[str, str]:
    home = clean(row.get("home_team") or row.get("home") or row.get("home_name"))
    away = clean(row.get("away_team") or row.get("away") or row.get("away_name"))
    if not home or not away:
        fallback_home, fallback_away = split_match_name(row.get("match") or row.get("name"))
        home = home or fallback_home
        away = away or fallback_away
    return norm_team(home), norm_team(away)


def parse_kickoff_value(value: object) -> datetime | None:
    raw = clean(value)
    if not raw:
        return None

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=LOCAL_TIMEZONE)
        return parsed.astimezone(LOCAL_TIMEZONE)
    except Exception:
        pass

    for fmt in (
        "%a %d %B %Y %H:%M",
        "%A %d %B %Y %H:%M",
        "%a %d %b %Y %H:%M",
        "%A %d %b %Y %H:%M",
        "%d %B %Y %H:%M",
        "%d %b %Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=LOCAL_TIMEZONE)
        except Exception:
            continue

    return None


def row_kickoff(row: dict) -> datetime | None:
    for field in (
        "kickoff",
        "commence_time",
        "start_time",
        "starts_at",
        "datetime",
        "date_time",
    ):
        parsed = parse_kickoff_value(row.get(field))
        if parsed is not None:
            return parsed

    date_label = clean(row.get("date_label") or row.get("date"))
    time_label = clean(row.get("time") or row.get("time_label"))
    if date_label and time_label:
        return parse_kickoff_value(f"{date_label} {time_label}")
    return None


def load_moneyline_kickoffs() -> dict[tuple[str, str], datetime]:
    if not MONEYLINES_PATH.exists():
        raise FileNotFoundError(
            f"Missing BoyleSports moneyline file required for kickoff filtering: {MONEYLINES_PATH}"
        )

    data = json.loads(MONEYLINES_PATH.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        rows = data.get("matches") or data.get("results") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    lookup: dict[tuple[str, str], datetime] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = fixture_key(row)
        kickoff = row_kickoff(row)
        if all(key) and kickoff is not None:
            lookup[key] = kickoff
    return lookup


def discover_fixture_urls() -> tuple[list[dict], dict]:
    started = time.perf_counter()
    session = requests.Session(impersonate="chrome124")
    response = session.get(COMPETITION_URL, timeout=30)

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / "fixture_list_debug.txt").write_text(
        f"Status: {response.status_code}\nURL: {COMPETITION_URL}\n\n{response.text[:20000]}",
        encoding="utf-8",
    )

    if response.status_code != 200:
        return [], {
            "status_code": response.status_code,
            "request_seconds": round(time.perf_counter() - started, 3),
            "error": "fixture_list_http_error",
        }

    if "Verify you are human" in response.text:
        return [], {
            "status_code": response.status_code,
            "request_seconds": round(time.perf_counter() - started, 3),
            "error": "security_verification",
        }

    soup = BeautifulSoup(response.text, "lxml")
    fixtures: list[dict] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href*='/event/international-world-cup/']"):
        url = clean(anchor.get("href"))
        if not url:
            continue
        if not url.startswith("http"):
            url = BASE_URL + url
        if url in seen:
            continue
        seen.add(url)

        slug = url.rstrip("/").split("/")[-1]
        home, away = parse_teams_from_slug(slug)
        name = f"{home} v {away}" if home and away else slug.replace("-", " ").title()
        fixtures.append(
            {
                "name": name,
                "match": name,
                "url": url,
                "home_team": home,
                "away_team": away,
            }
        )

    kickoff_lookup = load_moneyline_kickoffs()
    now_local = datetime.now(LOCAL_TIMEZONE)
    cutoff = now_local + timedelta(minutes=UPCOMING_BUFFER_MINUTES)
    upcoming: list[dict] = []
    started_removed = 0
    unknown_removed = 0

    for fixture in fixtures:
        kickoff = kickoff_lookup.get(fixture_key(fixture))
        if kickoff is None:
            unknown_removed += 1
            continue
        if kickoff <= cutoff:
            started_removed += 1
            continue
        enriched = dict(fixture)
        enriched["_kickoff"] = kickoff
        upcoming.append(enriched)

    upcoming.sort(key=lambda item: item["_kickoff"])

    audit = {
        "status_code": response.status_code,
        "request_seconds": round(time.perf_counter() - started, 3),
        "discovered_total": len(fixtures),
        "now_local": now_local,
        "cutoff": cutoff,
        "started_removed": started_removed,
        "unknown_removed": unknown_removed,
        "upcoming_total": len(upcoming),
        "error": "",
    }
    return upcoming[:MAX_FIXTURES], audit


def fetch_fixture(index: int, fixture: dict) -> tuple[int, dict, dict]:
    started = time.perf_counter()
    session = requests.Session(impersonate="chrome124")
    headers = {
        "accept": "text/html",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "referer": COMPETITION_URL,
    }
    audit = {
        "match": fixture["name"],
        "status_code": None,
        "response_bytes": 0,
        "request_seconds": 0.0,
        "parse_seconds": 0.0,
        "total_seconds": 0.0,
        "security_verification": False,
        "error": "",
        "market_count": 0,
    }

    request_started = time.perf_counter()
    try:
        response = session.get(fixture["url"], headers=headers, timeout=30)
    except Exception as error:
        audit["request_seconds"] = round(time.perf_counter() - request_started, 3)
        audit["total_seconds"] = round(time.perf_counter() - started, 3)
        audit["error"] = str(error)
        markets = {}
    else:
        audit["request_seconds"] = round(time.perf_counter() - request_started, 3)
        audit["status_code"] = response.status_code
        audit["response_bytes"] = len(response.content or b"")

        if "Verify you are human" in response.text:
            audit["security_verification"] = True
            markets = {}
        elif response.status_code == 200:
            parse_started = time.perf_counter()
            _thread_state.fixture_slug = slugify(fixture["name"])
            markets = parse_markets(
                response.text,
                fixture["home_team"],
                fixture["away_team"],
            )
            audit["parse_seconds"] = round(time.perf_counter() - parse_started, 3)
        else:
            markets = {}

    audit["market_count"] = len(markets)
    audit["total_seconds"] = round(time.perf_counter() - started, 3)
    result = {
        "match": fixture["name"],
        "home_team": fixture["home_team"],
        "away_team": fixture["away_team"],
        "url": fixture["url"],
        "kickoff": fixture["_kickoff"].isoformat(),
        "markets": markets,
    }
    return index, result, audit


def main() -> None:
    started = time.perf_counter()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("BOYLESPORTS WORLD CUP PROPS — PROD15 FAST STANDALONE V2")
    print("=" * 72)
    print(f"MAX_FIXTURES = {MAX_FIXTURES}")
    print(f"MAX_WORKERS = {MAX_WORKERS}")

    fixtures, filter_audit = discover_fixture_urls()
    if not fixtures:
        print("No upcoming fixtures found. Production files modified: NO")
        if filter_audit.get("error"):
            print(f"ERROR: {filter_audit['error']}")
        return

    print(f"Fixture-list request:      {filter_audit['request_seconds']:.3f}s")
    print(f"Fixture URLs discovered:   {filter_audit['discovered_total']}")
    print(
        "Current Irish time:        "
        f"{filter_audit['now_local']:%d %b %Y %H:%M:%S %Z}"
    )
    print(
        "Kickoff safety cutoff:     "
        f"{filter_audit['cutoff']:%d %b %Y %H:%M:%S %Z}"
    )
    print(f"Started/in-play removed:   {filter_audit['started_removed']}")
    print(f"Unknown kickoff removed:   {filter_audit['unknown_removed']}")
    print(f"Upcoming fixtures found:   {filter_audit['upcoming_total']}")
    print(f"Fixtures selected:         {len(fixtures)}")

    for position, fixture in enumerate(fixtures, start=1):
        print(
            f"  {position:02d}. {fixture['_kickoff']:%a %d %B %Y %H:%M} | "
            f"{fixture['name']}"
        )

    ordered_results: list[dict | None] = [None] * len(fixtures)
    ordered_audits: list[dict | None] = [None] * len(fixtures)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_fixture, index, fixture): index
            for index, fixture in enumerate(fixtures)
        }
        for future in as_completed(futures):
            fallback_index = futures[future]
            try:
                index, result, audit = future.result()
            except Exception as error:
                fixture = fixtures[fallback_index]
                index = fallback_index
                result = {
                    "match": fixture["name"],
                    "home_team": fixture["home_team"],
                    "away_team": fixture["away_team"],
                    "url": fixture["url"],
                    "kickoff": fixture["_kickoff"].isoformat(),
                    "markets": {},
                }
                audit = {
                    "match": fixture["name"],
                    "status_code": None,
                    "response_bytes": 0,
                    "request_seconds": 0.0,
                    "parse_seconds": 0.0,
                    "total_seconds": 0.0,
                    "security_verification": False,
                    "error": str(error),
                    "market_count": 0,
                }

            ordered_results[index] = result
            ordered_audits[index] = audit

            print(f"\n[{index + 1}/{len(fixtures)}] {result['match']}")
            print(
                f"  status={audit.get('status_code')} "
                f"bytes={audit.get('response_bytes', 0):,}"
            )
            print(
                f"  request={audit.get('request_seconds', 0):.3f}s "
                f"parse={audit.get('parse_seconds', 0):.3f}s "
                f"total={audit.get('total_seconds', 0):.3f}s"
            )
            print("  " + summarise_markets(result["markets"]))
            if audit.get("error"):
                print(f"  ERROR: {audit['error']}")
            if audit.get("security_verification"):
                print("  SECURITY VERIFICATION")

    results = [item for item in ordered_results if item is not None]
    audits = [item for item in ordered_audits if item is not None]
    good_market_count = sum(1 for item in results if item["markets"])

    if good_market_count == 0:
        print(
            "\n0 matches returned markets — "
            "keeping the existing production JSON untouched."
        )
        return

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BoyleSports",
        "market_type": "props",
        "test_mode": False,
        "source_url": COMPETITION_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches": results,
        "filter_audit": {
            "now_local": filter_audit["now_local"].isoformat(),
            "cutoff": filter_audit["cutoff"].isoformat(),
            "started_removed": filter_audit["started_removed"],
            "unknown_removed": filter_audit["unknown_removed"],
            "upcoming_total": filter_audit["upcoming_total"],
            "discovered_total": filter_audit["discovered_total"],
        },
        "audit": audits,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"Saved production output: {OUT_PATH}")
    print(f"Matches with markets: {good_market_count}/{len(results)}")
    print(f"Total elapsed: {output['elapsed_seconds']:.3f}s")
    print("Production BoyleSports props updated: YES")


if __name__ == "__main__":
    main()
