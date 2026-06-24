#!/usr/bin/env python3
"""
fetch_betvictor_player_tackles.py

BetVictor Player Tackles — scroll-container / Show More test fix.

Why this version exists:
BetVictor initially exposes only a handful of tackle rows. The sportsbook can
keep the full market inside an inner scrollable panel and/or behind a Show More
control. Scrolling only the browser window therefore keeps returning five rows.

This version:
- clicks Player Tackles;
- repeatedly clicks Show More / View More / Load More controls;
- discovers visible inner scrollable containers;
- scrolls every likely container and the browser window;
- harvests exact player + threshold + fractional odd rows at each position.

TEST MODE:
    MAX_MATCHES = 15
    Argentina v Austria is tested first.

Output:
    football/data/betvictor_player_tackles.json

The main BetVictor props JSON is not modified.
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
MAX_MATCHES = 15
HEADLESS = False
UPCOMING_BUFFER_MINUTES = 5

PRIORITY_MATCHES = ["Argentina v Austria"]

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


def click_text(page, label):
    try:
        locator = page.get_by_text(label, exact=True)
        for index in range(locator.count() - 1, -1, -1):
            item = locator.nth(index)
            try:
                item.scroll_into_view_if_needed(timeout=2500)
                item.click(timeout=2500)
                page.wait_for_timeout(1000)
                return True
            except Exception:
                try:
                    item.evaluate("(el) => el.click()")
                    page.wait_for_timeout(1000)
                    return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


def open_player_tackles(page):
    click_text(page, "Player")
    click_text(page, "Player Tackles")

    try:
        body = page.locator("body").inner_text(timeout=20000)
    except Exception:
        body = ""

    return bool(re.search(r"\d+\+\s+Tackles", body, re.I))


def click_more_controls(page):
    """
    Click visible expansion controls anywhere on the page.

    Limit the loop to avoid repeatedly toggling a control.
    """
    patterns = [
        re.compile(r"^Show More$", re.I),
        re.compile(r"^Show more$", re.I),
        re.compile(r"^View More$", re.I),
        re.compile(r"^View more$", re.I),
        re.compile(r"^Load More$", re.I),
        re.compile(r"^Load more$", re.I),
        re.compile(r"^Show All$", re.I),
        re.compile(r"^Show all$", re.I),
    ]

    clicked = 0

    for _ in range(12):
        made_click = False

        for pattern in patterns:
            try:
                locator = page.get_by_role("button", name=pattern)
                count = locator.count()

                for index in range(count):
                    item = locator.nth(index)
                    try:
                        if not item.is_visible():
                            continue
                        item.scroll_into_view_if_needed(timeout=1500)
                        item.click(timeout=2000)
                        page.wait_for_timeout(700)
                        clicked += 1
                        made_click = True
                    except Exception:
                        pass
            except Exception:
                pass

        if not made_click:
            break

    return clicked


def extract_visible_rows(page):
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


def add_rows(harvested, rows):
    before = len(harvested)

    for row in rows:
        key = (
            f"{clean(row.get('label'))}|"
            f"{clean(row.get('odds')).upper()}"
        )
        harvested[key] = row

    return len(harvested) - before


def mark_scroll_containers(page):
    """
    Mark large visible elements that have meaningful vertical scroll range.
    """
    return page.evaluate(
        """() => {
            document
                .querySelectorAll('[data-bv-scroll-id]')
                .forEach(el => el.removeAttribute('data-bv-scroll-id'));

            const items = [];

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

                items.push({
                    el,
                    range,
                    area: rect.width * rect.height,
                    width: rect.width,
                    height: rect.height,
                });
            }

            items.sort(
                (a, b) =>
                    (b.range * b.width) - (a.range * a.width) ||
                    b.area - a.area
            );

            return items.slice(0, 12).map((item, index) => {
                item.el.setAttribute('data-bv-scroll-id', String(index));
                return {
                    id: index,
                    range: item.range,
                    width: Math.round(item.width),
                    height: Math.round(item.height),
                    tag: item.el.tagName,
                    className: String(item.el.className || '').slice(0, 180),
                };
            });
        }"""
    )


def harvest_window(page, harvested):
    before = len(harvested)

    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(300)

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
    y = 0

    while y <= total_height:
        page.evaluate("(value) => window.scrollTo(0, value)", y)
        page.wait_for_timeout(260)
        add_rows(harvested, extract_visible_rows(page))
        y += step

    page.evaluate(
        "() => window.scrollTo(0, "
        "Math.max(document.body.scrollHeight, "
        "document.documentElement.scrollHeight))"
    )
    page.wait_for_timeout(450)
    add_rows(harvested, extract_visible_rows(page))

    return len(harvested) - before


def harvest_container(page, container_id, scroll_range, harvested):
    before = len(harvested)
    locator = page.locator(f'[data-bv-scroll-id="{container_id}"]')

    if not locator.count():
        return 0

    try:
        client_height = int(
            locator.evaluate("(el) => el.clientHeight")
        )
    except Exception:
        client_height = 700

    step = max(180, client_height // 3)
    position = 0

    while position <= scroll_range:
        try:
            locator.evaluate(
                "(el, value) => { el.scrollTop = value; }",
                position,
            )
            page.wait_for_timeout(320)
            add_rows(harvested, extract_visible_rows(page))
        except Exception:
            break

        position += step

    try:
        locator.evaluate(
            "(el) => { el.scrollTop = el.scrollHeight; }"
        )
        page.wait_for_timeout(500)
        add_rows(harvested, extract_visible_rows(page))
    except Exception:
        pass

    return len(harvested) - before


def harvest_all_rows(page):
    harvested = {}

    add_rows(harvested, extract_visible_rows(page))

    more_clicked = click_more_controls(page)
    add_rows(harvested, extract_visible_rows(page))
    print(f"    expansion controls clicked: {more_clicked}")

    window_new = harvest_window(page, harvested)
    print(
        f"    window harvest: {len(harvested)} total "
        f"({window_new} new)"
    )

    containers = mark_scroll_containers(page)
    print(f"    scrollable containers found: {len(containers)}")

    for info in containers:
        new_rows = harvest_container(
            page,
            info["id"],
            info["range"],
            harvested,
        )
        print(
            f"      container {info['id']} "
            f"{info['tag']} {info['width']}x{info['height']} "
            f"range={info['range']} -> {new_rows} new"
        )

    # A second expansion/harvest pass catches controls exposed by scrolling.
    more_clicked_2 = click_more_controls(page)
    if more_clicked_2:
        add_rows(harvested, extract_visible_rows(page))
        window_new_2 = harvest_window(page, harvested)
        print(
            f"    second expansion clicks: {more_clicked_2}; "
            f"window added {window_new_2}"
        )

        containers = mark_scroll_containers(page)
        for info in containers:
            harvest_container(
                page,
                info["id"],
                info["range"],
                harvested,
            )

    return list(harvested.values()), containers


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

        opened = open_player_tackles(page)
        raw_rows, containers = harvest_all_rows(page)
        selections = parse_rows(raw_rows)

        body = page.locator("body").inner_text(timeout=25000)

        page.screenshot(
            path=str(debug_dir / "player-tackles-scroll-fix.png"),
            full_page=True,
        )
        (debug_dir / "body-scroll-fix.txt").write_text(
            body,
            encoding="utf-8",
        )
        (debug_dir / "raw_rows_scroll_fix.json").write_text(
            json.dumps(raw_rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (debug_dir / "scroll_containers.json").write_text(
            json.dumps(containers, indent=2, ensure_ascii=False),
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

    print("BETVICTOR PLAYER TACKLES — SCROLL CONTAINER TEST")
    print("=" * 72)
    print(f"MAX_MATCHES = {MAX_MATCHES}")
    print(f"Started/finished fixtures removed: {len(removed_started)}")
    print(f"Unknown-kickoff fixtures removed:  {len(removed_unknown)}")
    print(f"Upcoming fixtures to scan:        {len(fixtures)}")

    print("\nTest order:")
    for index, fixture in enumerate(fixtures, 1):
        print(
            f"  {index:02d}. {fixture['match']} "
            f"| {fixture['kickoff']}"
        )

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
        f"{len(results)}/{len(fixtures)} test fixtures"
    )


if __name__ == "__main__":
    main()
