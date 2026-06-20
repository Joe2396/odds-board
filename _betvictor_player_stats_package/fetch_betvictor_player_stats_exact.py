#!/usr/bin/env python3
"""
fetch_betvictor_player_stats_exact.py

Exact BetVictor player-stat scraper for:
- Player Shots On Target
- Player Shots
- Player Fouls Committed

Uses the same Show More + scroll-container DOM harvesting method that fixed
Player Tackles.

TEST MODE:
    MAX_MATCHES = 3

Output:
    football/data/betvictor_player_stats_exact.json

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
OUT_PATH = DATA_DIR / "betvictor_player_stats_exact.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_player_stats_exact"

PLAYER_GROUP = "19296"
MAX_MATCHES = 3
HEADLESS = False
UPCOMING_BUFFER_MINUTES = 5
PRIORITY_MATCHES = ["Argentina v Austria"]

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN)$", re.I)

MARKETS = {
    "player_shots_on_target": {
        "market": "Player Shots On Target",
        "headings": ["Player Shots on Target", "Player Shots On Target"],
        "row_re": re.compile(
            r"^(.+?)\s+(\d+)\+\s+Shots?\s+On\s+Target$",
            re.I,
        ),
        "suffix": "Shots On Target",
        "prop_type": "shots_on_target",
    },
    "player_shots": {
        "market": "Player Shots",
        "headings": ["Player Shots"],
        "row_re": re.compile(r"^(.+?)\s+(\d+)\+\s+Shots?$", re.I),
        "suffix": "Shots",
        "prop_type": "shots",
    },
    "player_fouls_committed": {
        "market": "Player Fouls Committed",
        "headings": ["Player Fouls", "Player Fouls Committed"],
        "row_re": re.compile(
            r"^(.+?)\s+(\d+)\+\s+Fouls?(?:\s+Committed)?$",
            re.I,
        ),
        "suffix": "Fouls Committed",
        "prop_type": "fouls_committed",
    },
}

KICKOFF_KEYS = (
    "kickoff", "kick_off", "commence_time", "start_time", "startTime",
    "event_time", "eventTime", "date_time", "datetime", "start",
    "start_date", "startDate", "date",
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
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M",
        "%d %b %Y %H:%M", "%d %B %Y %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def extract_match_name(row):
    name = clean(row.get("match"))
    if name:
        return name

    home = clean(row.get("home") or row.get("home_team"))
    away = clean(row.get("away") or row.get("away_team"))
    return f"{home} v {away}" if home and away else ""


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

            name = extract_match_name(row)
            kickoff = extract_kickoff(row)

            if not name or not kickoff:
                continue

            key = normalize(name)
            existing = kickoff_map.get(key)

            if existing is None or kickoff > existing:
                kickoff_map[key] = kickoff

    return kickoff_map


def load_upcoming_fixtures():
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
        elif kickoff <= cutoff:
            removed_started.append(fixture)
        else:
            upcoming.append(fixture)

    upcoming.sort(key=lambda item: item["kickoff"])

    by_name = {item["match"]: item for item in upcoming}
    ordered = []

    for name in PRIORITY_MATCHES:
        item = by_name.get(name)
        if item and item not in ordered:
            ordered.append(item)

    for item in upcoming:
        if item not in ordered:
            ordered.append(item)

    return (
        ordered[:MAX_MATCHES],
        removed_started,
        removed_unknown,
        data.get("generated_at"),
    )


def accept_cookies(page):
    for label in (
        "Accept All", "Accept all", "I Accept", "Accept",
        "Agree", "Allow all", "OK",
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


def click_exact_text(page, labels):
    for label in labels:
        try:
            locator = page.get_by_text(label, exact=True)

            for index in range(locator.count() - 1, -1, -1):
                item = locator.nth(index)

                try:
                    if not item.is_visible():
                        continue
                except Exception:
                    pass

                try:
                    item.scroll_into_view_if_needed(timeout=2500)
                    item.click(timeout=3000)
                    page.wait_for_timeout(1200)
                    return label
                except Exception:
                    try:
                        item.evaluate("(el) => el.click()")
                        page.wait_for_timeout(1200)
                        return label
                    except Exception:
                        pass
        except Exception:
            pass

    return None


def click_more_controls(page):
    patterns = [
        re.compile(r"^Show More$", re.I),
        re.compile(r"^View More$", re.I),
        re.compile(r"^Load More$", re.I),
        re.compile(r"^Show All$", re.I),
    ]

    clicked = 0

    for _ in range(12):
        changed = False

        for pattern in patterns:
            try:
                locator = page.get_by_role("button", name=pattern)

                for index in range(locator.count()):
                    item = locator.nth(index)

                    try:
                        if not item.is_visible():
                            continue
                        item.scroll_into_view_if_needed(timeout=1500)
                        item.click(timeout=2000)
                        page.wait_for_timeout(650)
                        clicked += 1
                        changed = True
                    except Exception:
                        pass
            except Exception:
                pass

        if not changed:
            break

    return clicked


def mark_scroll_containers(page):
    return page.evaluate(
        """() => {
            document
                .querySelectorAll('[data-bv-stat-scroll-id]')
                .forEach(el => el.removeAttribute('data-bv-stat-scroll-id'));

            const candidates = [];

            for (const el of document.querySelectorAll('*')) {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                const range = el.scrollHeight - el.clientHeight;

                if (rect.width < 280 || rect.height < 180) continue;
                if (range < 120) continue;
                if (
                    style.overflowY !== 'auto' &&
                    style.overflowY !== 'scroll' &&
                    style.overflowY !== 'overlay'
                ) continue;

                candidates.push({
                    el,
                    range,
                    width: rect.width,
                    height: rect.height,
                });
            }

            candidates.sort(
                (a, b) =>
                    (b.range * b.width) - (a.range * a.width)
            );

            return candidates.slice(0, 12).map((item, index) => {
                item.el.setAttribute('data-bv-stat-scroll-id', String(index));
                return {
                    id: index,
                    range: item.range,
                    width: Math.round(item.width),
                    height: Math.round(item.height),
                    tag: item.el.tagName,
                    class_name: String(item.el.className || '').slice(0, 180),
                };
            });
        }"""
    )


def extract_visible_rows(page, pattern_source):
    return page.evaluate(
        """({patternSource}) => {
            const oddsRe = /^(?:\\d+\\/\\d+|EVS|EVENS|EVEN)$/i;
            const rowRe = new RegExp(patternSource, 'i');
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

                if (!rowRe.test(label) || label.length > 140) continue;

                let node = el;
                let found = null;

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

                    if (odds.length && block.length < 750) {
                        found = {
                            label,
                            odds: odds[0],
                            block,
                        };
                        break;
                    }
                }

                if (!found) continue;

                const key = found.label + '|' + found.odds;
                if (seen.has(key)) continue;

                seen.add(key);
                rows.push(found);
            }

            return rows;
        }""",
        {"patternSource": pattern_source},
    )


def add_rows(store, rows):
    before = len(store)

    for row in rows:
        key = (
            f"{clean(row.get('label'))}|"
            f"{clean(row.get('odds')).upper()}"
        )
        store[key] = row

    return len(store) - before


def harvest_window(page, extractor, store):
    try:
        total_height = int(
            page.evaluate(
                "Math.max(document.body.scrollHeight, "
                "document.documentElement.scrollHeight)"
            )
        )
        viewport = int(page.evaluate("window.innerHeight"))
    except Exception:
        total_height = 5000
        viewport = 900

    step = max(220, viewport // 3)
    position = 0

    while position <= total_height:
        page.evaluate("(value) => window.scrollTo(0, value)", position)
        page.wait_for_timeout(250)
        add_rows(store, extractor())
        position += step

    page.evaluate(
        "() => window.scrollTo(0, "
        "Math.max(document.body.scrollHeight, "
        "document.documentElement.scrollHeight))"
    )
    page.wait_for_timeout(450)
    add_rows(store, extractor())


def harvest_containers(page, extractor, store):
    containers = mark_scroll_containers(page)

    for info in containers:
        locator = page.locator(
            f'[data-bv-stat-scroll-id="{info["id"]}"]'
        )

        if not locator.count():
            continue

        try:
            client_height = int(locator.evaluate("(el) => el.clientHeight"))
        except Exception:
            client_height = 700

        step = max(180, client_height // 3)
        position = 0

        while position <= info["range"]:
            try:
                locator.evaluate(
                    "(el, value) => { el.scrollTop = value; }",
                    position,
                )
                page.wait_for_timeout(300)
                add_rows(store, extractor())
            except Exception:
                break

            position += step

        try:
            locator.evaluate("(el) => { el.scrollTop = el.scrollHeight; }")
            page.wait_for_timeout(450)
            add_rows(store, extractor())
        except Exception:
            pass

    return containers


def parse_rows(rows, config):
    selections = []
    seen = set()

    for row in rows:
        label = clean(row.get("label"))
        match = config["row_re"].fullmatch(label)

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
                "selection": f"{player} {threshold} {config['suffix']}",
                "normalized_selection": normalize(
                    f"{player} {threshold} {config['suffix']}"
                ),
                "odds": odds,
                "player": player,
                "threshold": threshold,
                "prop_type": config["prop_type"],
            }
        )

    selections.sort(
        key=lambda item: (
            normalize(item["player"]),
            int(item["threshold"].rstrip("+")),
        )
    )

    return selections


def scrape_market(browser, fixture, key, config):
    context = browser.new_context(viewport={"width": 1700, "height": 1000})
    page = context.new_page()

    debug_dir = DEBUG_ROOT / slugify(fixture["match"]) / key
    debug_dir.mkdir(parents=True, exist_ok=True)

    url = f"{fixture['source_url']}?market_group={PLAYER_GROUP}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=70000)
        page.wait_for_timeout(6000)
        accept_cookies(page)

        click_exact_text(page, ["Player"])
        heading_clicked = click_exact_text(page, config["headings"])
        more_clicked = click_more_controls(page)

        pattern_source = config["row_re"].pattern
        extractor = lambda: extract_visible_rows(page, pattern_source)

        store = {}
        add_rows(store, extractor())
        harvest_window(page, extractor, store)
        containers = harvest_containers(page, extractor, store)

        more_clicked += click_more_controls(page)
        add_rows(store, extractor())
        harvest_window(page, extractor, store)
        harvest_containers(page, extractor, store)

        rows = list(store.values())
        selections = parse_rows(rows, config)

        body = page.locator("body").inner_text(timeout=25000)
        (debug_dir / "body.txt").write_text(body, encoding="utf-8")
        (debug_dir / "raw_rows.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (debug_dir / "scroll_containers.json").write_text(
            json.dumps(containers, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        page.screenshot(
            path=str(debug_dir / "page.png"),
            full_page=True,
        )

        return {
            "market": config["market"],
            "normalized_market": key,
            "heading_clicked": heading_clicked,
            "expansion_controls_clicked": more_clicked,
            "selection_count": len(selections),
            "selections": selections,
        }

    finally:
        context.close()


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_ROOT.mkdir(parents=True, exist_ok=True)

    fixtures, removed_started, removed_unknown, source_generated_at = (
        load_upcoming_fixtures()
    )

    print("BETVICTOR EXACT PLAYER STATS — TEST")
    print("=" * 72)
    print(f"MAX_MATCHES = {MAX_MATCHES}")
    print(f"Started/finished fixtures removed: {len(removed_started)}")
    print(f"Unknown-kickoff fixtures removed:  {len(removed_unknown)}")
    print(f"Upcoming fixtures to scan:        {len(fixtures)}")

    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)

        for index, fixture in enumerate(fixtures, 1):
            print(f"\n[{index}/{len(fixtures)}] {fixture['match']}")
            markets = []

            for key, config in MARKETS.items():
                print(f"  {config['market']}...")
                market = scrape_market(
                    browser,
                    fixture,
                    key,
                    config,
                )

                print(
                    f"    heading={market.get('heading_clicked')} "
                    f"show_more={market.get('expansion_controls_clicked')} "
                    f"selections={market.get('selection_count')}"
                )

                if market.get("selection_count"):
                    markets.append(market)

            results.append(
                {
                    "match": fixture["match"],
                    "home_team": fixture["home_team"],
                    "away_team": fixture["away_team"],
                    "source_url": fixture["source_url"],
                    "kickoff": fixture["kickoff"],
                    "market_count": len(markets),
                    "markets": markets,
                }
            )

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BetVictor",
        "market_type": "exact_player_stats",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_props_generated_at": source_generated_at,
        "max_matches": MAX_MATCHES,
        "match_count": len(results),
        "matches": results,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print(f"Saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
