#!/usr/bin/env python3
"""
fetch_betvictor_player_tackles.py

BetVictor Player Tackles scraper — virtual-list fix.

BetVictor only keeps a handful of visible tackle rows in the DOM at once.
This scraper harvests exact player/threshold/odds rows while scrolling through
the full page, instead of inspecting the DOM only once at the bottom.

TEST MODE:
    MAX_MATCHES = 3

Output:
    football/data/betvictor_player_tackles.json

This script does not modify betvictor_worldcup_props.json.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "football" / "data"

PROPS_PATH = DATA_DIR / "betvictor_worldcup_props.json"
OUT_PATH = DATA_DIR / "betvictor_player_tackles.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_player_tackles"

MARKET_GROUP = "19296"

# Keep at 3 until the scrolling fix is verified.
MAX_MATCHES = 3

HEADLESS = False
UPCOMING_BUFFER_MINUTES = 5
SCROLL_STEP = 320
SCROLL_WAIT_MS = 320
MAX_SCROLL_PASSES = 3

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN)$", re.I)
ROW_RE = re.compile(
    r"^(.+?)\s+(\d+)\+\s+Tackles?(?:\s+90\s*Mins)?$",
    re.I,
)

KICKOFF_KEYS = (
    "kickoff",
    "kick_off",
    "commence_time",
    "start_time",
    "startTime",
    "event_time",
    "eventTime",
    "date_time",
    "datetime",
    "start",
    "start_date",
    "startDate",
    "date",
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def slugify(value):
    return normalize(value).replace("_", "-")


def parse_datetime(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except Exception:
            return None

    text = clean(value)
    if not text:
        return None

    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M",
        "%d %b %Y %H:%M",
        "%d %B %Y %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def extract_match_name(row):
    match_name = clean(row.get("match"))
    if match_name:
        return match_name

    home = clean(row.get("home") or row.get("home_team"))
    away = clean(row.get("away") or row.get("away_team"))

    if home and away:
        return f"{home} v {away}"

    return ""


def extract_kickoff(row):
    for key in KICKOFF_KEYS:
        parsed = parse_datetime(row.get(key))
        if parsed:
            return parsed
    return None


def load_kickoff_map():
    kickoff_map = {}

    for path in sorted(DATA_DIR.glob("*worldcup*moneyline*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        rows = data.get("matches", []) if isinstance(data, dict) else []
        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue

            match_name = extract_match_name(row)
            kickoff = extract_kickoff(row)

            if not match_name or not kickoff:
                continue

            key = normalize(match_name)
            existing = kickoff_map.get(key)

            if existing is None or kickoff > existing:
                kickoff_map[key] = kickoff

    return kickoff_map


def load_upcoming_fixtures():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing: {PROPS_PATH}")

    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    kickoff_map = load_kickoff_map()

    cutoff = datetime.now(timezone.utc) + timedelta(
        minutes=UPCOMING_BUFFER_MINUTES
    )

    upcoming = []
    removed_started = []
    removed_unknown = []

    for match in data.get("matches", []):
        name = clean(match.get("match"))
        home = clean(match.get("home_team"))
        away = clean(match.get("away_team"))
        url = clean(match.get("source_url") or match.get("url"))

        if not name and home and away:
            name = f"{home} v {away}"

        if not name or "/events/" not in url:
            continue

        kickoff = extract_kickoff(match) or kickoff_map.get(normalize(name))

        fixture = {
            "match": name,
            "home_team": home,
            "away_team": away,
            "source_url": url.split("?", 1)[0],
            "kickoff": kickoff.isoformat() if kickoff else None,
        }

        if kickoff is None:
            removed_unknown.append(fixture)
            continue

        if kickoff <= cutoff:
            removed_started.append(fixture)
            continue

        upcoming.append(fixture)

    upcoming.sort(key=lambda fixture: fixture["kickoff"])

    return (
        upcoming[:MAX_MATCHES],
        removed_started,
        removed_unknown,
        data.get("generated_at"),
    )


def accept_cookies(page):
    for label in (
        "Accept All",
        "Accept all",
        "I Accept",
        "Accept",
        "Agree",
        "Allow all",
        "OK",
    ):
        try:
            locator = page.get_by_role(
                "button",
                name=re.compile(f"^{re.escape(label)}$", re.I),
            )
            if locator.count():
                locator.first.click(timeout=1500)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def click_player_tackles(page):
    for label in ("Player", "Player Tackles"):
        try:
            locator = page.get_by_text(label, exact=True)
            if locator.count():
                item = locator.last
                item.scroll_into_view_if_needed(timeout=3000)
                item.click(timeout=3000)
                page.wait_for_timeout(1800)
        except Exception:
            pass

    try:
        body = page.locator("body").inner_text(timeout=20000)
    except Exception:
        body = ""

    return bool(re.search(r"\d+\+\s+Tackles", body, re.I))


def extract_visible_dom_rows(page):
    """
    Extract only tackle selections currently mounted in the DOM.

    BetVictor virtualises the list, so this function must be called repeatedly
    at different scroll positions.
    """
    return page.evaluate(
        """() => {
            const oddsRe = /^(?:\\d+\\/\\d+|EVS|EVENS|EVEN)$/i;
            const tackleRe = /^(.+?)\\s+(\\d+)\\+\\s+Tackles?(?:\\s+90\\s*Mins)?$/i;
            const rows = [];
            const seen = new Set();

            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_ELEMENT
            );

            while (walker.nextNode()) {
                const el = walker.currentNode;
                const label = (el.innerText || '')
                    .trim()
                    .replace(/\\s+/g, ' ');

                if (!tackleRe.test(label) || label.length > 120) continue;

                let node = el;
                let best = null;

                for (
                    let depth = 0;
                    depth < 10 && node;
                    depth++, node = node.parentElement
                ) {
                    const block = (node.innerText || '').trim();
                    const lines = block
                        .split(/\\n+/)
                        .map(x => x.trim())
                        .filter(Boolean);
                    const odds = lines.filter(x => oddsRe.test(x));

                    if (odds.length && block.length < 700) {
                        best = {
                            label,
                            odds: odds[0],
                            block,
                        };
                        break;
                    }
                }

                if (!best) continue;

                const key = best.label + '|' + best.odds;
                if (seen.has(key)) continue;

                seen.add(key);
                rows.push(best);
            }

            return rows;
        }"""
    )


def harvest_all_rows(page):
    """
    Harvest mounted tackle rows at every scroll position.

    A full pass may increase the document height as BetVictor lazy-loads.
    Repeat until a pass finds no new rows, or MAX_SCROLL_PASSES is reached.
    """
    harvested = {}

    try:
        viewport_height = int(
            page.evaluate("window.innerHeight || document.documentElement.clientHeight")
        )
    except Exception:
        viewport_height = 900

    step = min(SCROLL_STEP, max(220, viewport_height // 3))

    for pass_number in range(1, MAX_SCROLL_PASSES + 1):
        before_count = len(harvested)

        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        try:
            total_height = int(
                page.evaluate(
                    "Math.max(document.body.scrollHeight, "
                    "document.documentElement.scrollHeight)"
                )
            )
        except Exception:
            total_height = 5000

        y = 0

        while y <= total_height:
            page.evaluate("(position) => window.scrollTo(0, position)", y)
            page.wait_for_timeout(SCROLL_WAIT_MS)

            for row in extract_visible_dom_rows(page):
                key = f"{clean(row.get('label'))}|{clean(row.get('odds')).upper()}"
                harvested[key] = row

            try:
                current_height = int(
                    page.evaluate(
                        "Math.max(document.body.scrollHeight, "
                        "document.documentElement.scrollHeight)"
                    )
                )
                if current_height > total_height:
                    total_height = current_height
            except Exception:
                pass

            y += step

        # Capture the absolute bottom once more.
        page.evaluate(
            "() => window.scrollTo(0, "
            "Math.max(document.body.scrollHeight, "
            "document.documentElement.scrollHeight))"
        )
        page.wait_for_timeout(700)

        for row in extract_visible_dom_rows(page):
            key = f"{clean(row.get('label'))}|{clean(row.get('odds')).upper()}"
            harvested[key] = row

        new_rows = len(harvested) - before_count
        print(
            f"    scroll pass {pass_number}: "
            f"{len(harvested)} total rows ({new_rows} new)"
        )

        if new_rows == 0:
            break

    return list(harvested.values())


def parse_rows(rows):
    selections = []
    seen = set()

    for row in rows:
        label = clean(row.get("label"))
        match = ROW_RE.fullmatch(label)
        if not match:
            continue

        player = clean(match.group(1))
        threshold = f"{match.group(2)}+"
        odds = clean(row.get("odds")).upper()

        if not player or not ODDS_RE.fullmatch(odds):
            continue

        key = (normalize(player), threshold, odds)
        if key in seen:
            continue
        seen.add(key)

        selections.append(
            {
                "selection": f"{player} {threshold} Tackles",
                "normalized_selection": normalize(
                    f"{player} {threshold} Tackles"
                ),
                "odds": odds,
                "player": player,
                "threshold": threshold,
                "prop_type": "tackles",
            }
        )

    selections.sort(
        key=lambda item: (
            normalize(item["player"]),
            int(item["threshold"].rstrip("+")),
        )
    )
    return selections


def scrape_fixture(browser, fixture):
    context = browser.new_context(viewport={"width": 1700, "height": 1000})
    page = context.new_page()

    debug_dir = DEBUG_ROOT / slugify(fixture["match"])
    debug_dir.mkdir(parents=True, exist_ok=True)

    url = f"{fixture['source_url']}?market_group={MARKET_GROUP}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=70000)
        page.wait_for_timeout(6000)
        accept_cookies(page)
        page.wait_for_timeout(1200)

        opened = click_player_tackles(page)
        raw_rows = harvest_all_rows(page)
        selections = parse_rows(raw_rows)

        body = page.locator("body").inner_text(timeout=25000)

        page.screenshot(
            path=str(debug_dir / "player-tackles.png"),
            full_page=True,
        )
        (debug_dir / "body.txt").write_text(body, encoding="utf-8")
        (debug_dir / "raw_rows.json").write_text(
            json.dumps(raw_rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return {
            "match": fixture["match"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "source_url": fixture["source_url"],
            "kickoff": fixture["kickoff"],
            "player_tackles_opened": opened,
            "market_count": 1 if selections else 0,
            "markets": [
                {
                    "market": "Player Tackles",
                    "normalized_market": "player_tackles",
                    "selection_count": len(selections),
                    "selections": selections,
                }
            ] if selections else [],
        }

    except KeyboardInterrupt:
        raise
    except Exception as exc:
        return {
            "match": fixture["match"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "source_url": fixture["source_url"],
            "kickoff": fixture["kickoff"],
            "market_count": 0,
            "markets": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        context.close()


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_ROOT.mkdir(parents=True, exist_ok=True)

    fixtures, removed_started, removed_unknown, source_generated_at = (
        load_upcoming_fixtures()
    )

    print("BETVICTOR PLAYER TACKLES — VIRTUAL LIST TEST")
    print("=" * 72)
    print(f"MAX_MATCHES = {MAX_MATCHES}")
    print(f"Started/finished fixtures removed: {len(removed_started)}")
    print(f"Unknown-kickoff fixtures removed:  {len(removed_unknown)}")
    print(f"Upcoming fixtures to scan:        {len(fixtures)}")

    results = []
    unavailable = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)

        for index, fixture in enumerate(fixtures, 1):
            print(f"\n[{index}/{len(fixtures)}] {fixture['match']}")
            result = scrape_fixture(browser, fixture)

            if result.get("market_count"):
                market = result["markets"][0]
                print(
                    f"  SUCCESS: {market['selection_count']} "
                    f"exact tackle selections"
                )
                for item in market["selections"]:
                    print(
                        f"    {item['player']:<30} "
                        f"{item['threshold']:<3} {item['odds']}"
                    )
                results.append(result)
            else:
                reason = result.get("error") or "market unavailable"
                print(f"  NO TACKLES: {reason}")
                unavailable.append(
                    {
                        "match": fixture["match"],
                        "source_url": fixture["source_url"],
                        "kickoff": fixture["kickoff"],
                        "reason": reason,
                    }
                )

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BetVictor",
        "market_type": "player_tackles",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_props_generated_at": source_generated_at,
        "max_matches": MAX_MATCHES,
        "upcoming_fixture_count": len(fixtures),
        "successful_match_count": len(results),
        "started_or_finished_removed": len(removed_started),
        "unknown_kickoff_removed": len(removed_unknown),
        "matches": results,
        "unavailable": unavailable,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print(f"Saved: {OUT_PATH}")
    print(
        f"Successful tackle markets: "
        f"{len(results)}/{len(fixtures)} upcoming fixtures"
    )


if __name__ == "__main__":
    main()
