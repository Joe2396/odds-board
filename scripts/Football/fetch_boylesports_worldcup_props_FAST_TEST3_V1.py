#!/usr/bin/env python3
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

import importlib.util
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
PRODUCTION_SCRIPT = ROOT / "scripts" / "Football" / "fetch_boylesports_worldcup_props.py"
MONEYLINES_PATH = ROOT / "football" / "data" / "boylesports_worldcup_moneylines.json"
OUT_PATH = ROOT / "football" / "data" / "boylesports_worldcup_props_fast_test_v1.json"
DEBUG_DIR = ROOT / "football" / "debug" / "boylesports_props_fast_test_v1"

BASE_URL = "https://www.boylesports.com"
COMPETITION_URL = f"{BASE_URL}/sports/football/competition/international-world-cup"

MAX_FIXTURES = 3
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


def load_production_parser():
    spec = importlib.util.spec_from_file_location(
        "boylesports_core_parser",
        PRODUCTION_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {PRODUCTION_SCRIPT}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DEBUG_PATH = ThreadLocalDebugPath(DEBUG_DIR)
    return module


PARSER = load_production_parser()


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
        home, away = PARSER.parse_teams_from_slug(slug)
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
            markets = PARSER.parse_markets(
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

    print("BOYLESPORTS WORLD CUP PROPS — FAST TEST3 V1")
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
            print("  " + PARSER.summarise_markets(result["markets"]))
            if audit.get("error"):
                print(f"  ERROR: {audit['error']}")
            if audit.get("security_verification"):
                print("  SECURITY VERIFICATION")

    results = [item for item in ordered_results if item is not None]
    audits = [item for item in ordered_audits if item is not None]
    good_market_count = sum(1 for item in results if item["markets"])

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BoyleSports",
        "market_type": "props_fast_test_v1",
        "test_mode": True,
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
    print(f"Saved TEST output: {OUT_PATH}")
    print(f"Matches with markets: {good_market_count}/{len(results)}")
    print(f"Total elapsed: {output['elapsed_seconds']:.3f}s")
    print("Production BoyleSports files modified: NO")


if __name__ == "__main__":
    main()
