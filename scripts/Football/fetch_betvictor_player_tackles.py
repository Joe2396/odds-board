#!/usr/bin/env python3
# BETVICTOR_PLAYER_TACKLES_PROD15_FAST_V1
"""
fetch_betvictor_player_tackles_FAST_TEST3_V1.py

Fast isolated BetVictor Player Tackles test using the approved production
method from the exact Shots/SOT/Fouls scraper:

- exact Player Tackles accordion;
- safe Escape/modal handling;
- verified nearest Show More below the heading;
- scoped extraction from the expanded market;
- targeted market scrolling only;
- player + threshold deduplication;
- conflicting duplicate prices rejected.

PRODUCTION MODE:
    MAX_MATCHES = 7

Output:
    football/data/betvictor_player_tackles.json

This scraper writes football/data/betvictor_player_tackles.json.
It does not directly modify football/data/betvictor_worldcup_props.json.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "football" / "data"

PROPS_PATH = DATA_DIR / "betvictor_worldcup_props.json"
OUT_PATH = DATA_DIR / "betvictor_player_tackles.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_player_tackles"

PLAYER_GROUP = "19296"
MAX_MATCHES = 7
HEADLESS = False
UPCOMING_BUFFER_MINUTES = 15
BETVICTOR_LOCAL_TIMEZONE = ZoneInfo("Europe/Dublin")
PRIORITY_MATCHES = []
INITIAL_READY_TIMEOUT_MS = 12000
INITIAL_SETTLE_MS = 1800
HEADING_SCAN_STEP = 550
HEADING_SCAN_WAIT_MS = 180
HEADING_CLICK_WAIT_MS = 700
ROWS_READY_TIMEOUT_MS = 6000
SCOPED_SHOW_MORE_WAIT_MS = 450
MAX_SCOPED_SHOW_MORE_CLICKS = 4
SAVE_SCREENSHOTS = False
MIN_SCOPED_ROWS_BEFORE_FALLBACK = 8
SHOW_MORE_GROWTH_TIMEOUT_MS = 3500
MARKET_SCROLL_STEP = 420
MARKET_SCROLL_WAIT_MS = 110
MAX_MARKET_SCROLL_STEPS = 30

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN)$", re.I)

MARKETS = {
    "player_tackles": {
        "market": "Player Tackles",
        "headings": ["Player Tackles"],
        "row_re": re.compile(
            r"^(.+?)\s+(\d+)\+\s+Tackles?(?:\s+90\s*Mins)?$",
            re.I,
        ),
        "suffix": "Tackles",
        "prop_type": "tackles",
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
                parsed = parsed.replace(
                    tzinfo=BETVICTOR_LOCAL_TIMEZONE
                )

            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M",
        "%d %b %Y %H:%M", "%d %B %Y %H:%M",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            parsed = parsed.replace(
                tzinfo=BETVICTOR_LOCAL_TIMEZONE
            )
            return parsed.astimezone(timezone.utc)
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
    """
    Deduplicate by player + threshold, not by price.

    Multiple prices for the same player/threshold indicate duplicated or stale
    DOM rows. Conflicting entries are rejected instead of choosing arbitrarily.
    """
    grouped = {}

    for row in rows:
        label = clean(row.get("label"))
        match = config["row_re"].fullmatch(
            label
        )

        if not match:
            continue

        player = clean(match.group(1))
        threshold = f"{match.group(2)}+"
        odds = clean(row.get("odds")).upper()

        if (
            not player
            or not ODDS_RE.fullmatch(odds)
        ):
            continue

        key = (
            normalize(player),
            threshold,
        )

        entry = grouped.setdefault(
            key,
            {
                "player": player,
                "threshold": threshold,
                "odds": set(),
                "labels": set(),
            },
        )
        entry["odds"].add(odds)
        entry["labels"].add(label)

    selections = []
    conflicts = []

    for key, entry in grouped.items():
        prices = sorted(entry["odds"])

        if len(prices) != 1:
            conflicts.append(
                {
                    "player": entry["player"],
                    "threshold":
                        entry["threshold"],
                    "odds": prices,
                    "labels": sorted(
                        entry["labels"]
                    ),
                }
            )
            continue

        odds = prices[0]
        player = entry["player"]
        threshold = entry["threshold"]

        selections.append(
            {
                "selection": (
                    f"{player} {threshold} "
                    f"{config['suffix']}"
                ),
                "normalized_selection": normalize(
                    f"{player} {threshold} "
                    f"{config['suffix']}"
                ),
                "odds": odds,
                "player": player,
                "threshold": threshold,
                "prop_type":
                    config["prop_type"],
            }
        )

    selections.sort(
        key=lambda item: (
            normalize(item["player"]),
            int(
                item["threshold"].rstrip("+")
            ),
        )
    )

    threshold_counts = {}

    for item in selections:
        threshold = item["threshold"]
        threshold_counts[threshold] = (
            threshold_counts.get(
                threshold,
                0,
            )
            + 1
        )

    audit = {
        "raw_row_count": len(rows),
        "unique_player_threshold_count":
            len(grouped),
        "selection_count": len(selections),
        "player_count": len(
            {
                normalize(item["player"])
                for item in selections
            }
        ),
        "threshold_counts": dict(
            sorted(
                threshold_counts.items(),
                key=lambda row: int(
                    row[0].rstrip("+")
                ),
            )
        ),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }

    return selections, audit

def wait_for_market_page_ready(page, config):
    heading_terms = [
        clean(value).lower()
        for value in config.get("headings", [])
        if clean(value)
    ]

    try:
        page.wait_for_function(
            r"""(headingTerms) => {
                const text = document.body
                    ? document.body.innerText
                    : "";
                const lower = text.toLowerCase();

                return (
                    /(?:\d+\/\d+|EVS|EVENS|EVEN)/i.test(text)
                    || headingTerms.some(
                        term => lower.includes(term)
                    )
                    || /no markets available/i.test(text)
                );
            }""",
            heading_terms,
            timeout=INITIAL_READY_TIMEOUT_MS,
        )
    except Exception:
        pass

    page.wait_for_timeout(INITIAL_SETTLE_MS)


def dismiss_obvious_overlays(page):
    """
    Close only obvious modal-dismiss controls.

    Never click sportsbook odds, camera icons, accordions or generic buttons.
    """
    actions = []

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(120)
        actions.append("escape")
    except Exception:
        pass

    patterns = [
        re.compile(r"^Close$", re.I),
        re.compile(r"^Dismiss$", re.I),
        re.compile(r"^Not now$", re.I),
        re.compile(r"^Maybe later$", re.I),
        re.compile(r"^No thanks$", re.I),
        re.compile(r"^[×✕✖]$"),
    ]

    for pattern in patterns:
        try:
            locator = page.get_by_role(
                "button",
                name=pattern,
            )

            for index in range(locator.count()):
                item = locator.nth(index)

                try:
                    if not item.is_visible():
                        continue

                    item.click(timeout=1000)
                    page.wait_for_timeout(150)
                    actions.append(pattern.pattern)
                    break
                except Exception:
                    continue
        except Exception:
            pass

    for selector in (
        '[aria-label="Close"]',
        '[aria-label="close"]',
        '[title="Close"]',
        '[title="close"]',
        '[data-testid*="close" i]',
    ):
        try:
            locator = page.locator(selector)

            for index in range(min(locator.count(), 6)):
                item = locator.nth(index)

                try:
                    if not item.is_visible():
                        continue

                    item.click(timeout=900)
                    page.wait_for_timeout(140)
                    actions.append(selector)
                    break
                except Exception:
                    continue
        except Exception:
            pass

    return actions


def inspect_click_blocker(page, locator):
    try:
        return locator.evaluate(
            r"""(element) => {
                const rect = element.getBoundingClientRect();
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;
                const top = document.elementFromPoint(x, y);

                if (!top) {
                    return {
                        blocked: false,
                        reason: "no_element_from_point",
                    };
                }

                const unblocked =
                    element === top
                    || element.contains(top)
                    || top.contains(element);

                const style = getComputedStyle(top);
                const box = top.getBoundingClientRect();

                return {
                    blocked: !unblocked,
                    blocker_tag: top.tagName,
                    blocker_text: String(
                        top.innerText || ""
                    ).trim().replace(/\s+/g, " ").slice(0, 250),
                    blocker_class: String(
                        top.className || ""
                    ).slice(0, 220),
                    blocker_position: style.position,
                    blocker_rect: {
                        left: Math.round(box.left),
                        top: Math.round(box.top),
                        width: Math.round(box.width),
                        height: Math.round(box.height),
                    },
                };
            }"""
        )
    except Exception as error:
        return {
            "blocked": None,
            "error": str(error),
        }


def neutralise_actual_click_blocker(page, locator):
    """
    Disable pointer events only on a fixed/sticky ancestor that physically
    covers the requested control and occupies a large part of the viewport.
    """
    try:
        return locator.evaluate(
            r"""(element) => {
                const rect = element.getBoundingClientRect();
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;
                const top = document.elementFromPoint(x, y);

                if (
                    !top
                    || top === element
                    || element.contains(top)
                    || top.contains(element)
                ) {
                    return {
                        changed: false,
                        reason: "not_blocked",
                    };
                }

                let node = top;

                for (let depth = 0; depth < 9 && node; depth += 1) {
                    const style = getComputedStyle(node);
                    const box = node.getBoundingClientRect();
                    const viewportArea =
                        Math.max(1, window.innerWidth)
                        * Math.max(1, window.innerHeight);
                    const area =
                        Math.max(0, box.width)
                        * Math.max(0, box.height);
                    const coverage = area / viewportArea;
                    const fixedLike =
                        style.position === "fixed"
                        || style.position === "sticky";

                    if (
                        fixedLike
                        && coverage >= 0.35
                    ) {
                        node.style.setProperty(
                            "pointer-events",
                            "none",
                            "important"
                        );
                        node.setAttribute(
                            "data-bv-neutralised-overlay",
                            "1"
                        );

                        return {
                            changed: true,
                            tag: node.tagName,
                            class_name: String(
                                node.className || ""
                            ).slice(0, 220),
                            coverage,
                            position: style.position,
                        };
                    }

                    node = node.parentElement;
                }

                return {
                    changed: false,
                    reason: "no_large_fixed_blocker",
                    blocker_tag: top.tagName,
                    blocker_class: String(
                        top.className || ""
                    ).slice(0, 220),
                };
            }"""
        )
    except Exception as error:
        return {
            "changed": False,
            "error": str(error),
        }


def prepare_control_for_click(page, locator):
    actions = dismiss_obvious_overlays(page)

    try:
        locator.scroll_into_view_if_needed(
            timeout=2200,
        )
        page.wait_for_timeout(180)
    except Exception:
        pass

    before = inspect_click_blocker(
        page,
        locator,
    )

    neutralised = {
        "changed": False,
        "reason": "not_needed",
    }

    if before.get("blocked") is True:
        neutralised = neutralise_actual_click_blocker(
            page,
            locator,
        )
        page.wait_for_timeout(180)

    after = inspect_click_blocker(
        page,
        locator,
    )

    return {
        "dismiss_actions": actions,
        "before": before,
        "neutralised": neutralised,
        "after": after,
    }


def visible_exact_heading(page, labels):
    for label in labels:
        pattern = re.compile(
            rf"^{re.escape(clean(label))}$",
            re.I,
        )

        try:
            locator = page.get_by_text(
                pattern,
                exact=True,
            )

            visible = []

            for index in range(locator.count()):
                item = locator.nth(index)

                try:
                    if not item.is_visible():
                        continue

                    box = item.bounding_box()

                    if box:
                        visible.append(
                            (
                                box["width"] * box["height"],
                                item,
                                clean(label),
                            )
                        )
                except Exception:
                    continue

            if visible:
                visible.sort(key=lambda row: row[0])
                _, item, matched_label = visible[0]
                return item, matched_label

        except Exception:
            continue

    return None, None

def scan_for_market_heading(page, labels):
    """
    BetVictor renders these accordions low down the Player page. Scroll until
    the exact requested heading becomes visible.
    """
    for _ in range(2):
        try:
            total_height = int(
                page.evaluate(
                    "Math.max("
                    "document.body.scrollHeight,"
                    "document.documentElement.scrollHeight"
                    ")"
                )
            )
            viewport = int(page.evaluate("window.innerHeight || 900"))
        except Exception:
            total_height = 6000
            viewport = 900

        position = 0
        step = max(HEADING_SCAN_STEP, viewport // 2)

        while position <= total_height:
            try:
                page.evaluate(
                    "(value) => window.scrollTo(0, value)",
                    position,
                )
                page.wait_for_timeout(HEADING_SCAN_WAIT_MS)
            except Exception:
                pass

            heading, label = visible_exact_heading(
                page,
                labels,
            )

            if heading is not None:
                return heading, label

            position += step

        try:
            page.evaluate(
                "() => window.scrollTo("
                "0, document.documentElement.scrollHeight"
                ")"
            )
        except Exception:
            pass

        page.wait_for_timeout(500)

    return None, None


def click_market_accordion(page, labels, config):
    """
    Open a market by clicking only its exact heading text.

    Do not click generic buttons, camera icons, chevrons, odds cells or the
    right-most control in an ancestor. Those broad fallbacks can add odds to
    the betslip and trigger browser sounds.
    """
    heading, label = scan_for_market_heading(
        page,
        labels,
    )

    if heading is None:
        return None

    try:
        heading.scroll_into_view_if_needed(
            timeout=2500,
        )
    except Exception:
        pass

    # Normal Playwright click on the exact title.
    try:
        heading.click(
            timeout=3000,
            force=False,
        )
        page.wait_for_timeout(
            HEADING_CLICK_WAIT_MS,
        )
    except Exception:
        pass

    if wait_for_requested_rows(page, config):
        return label

    # Safe fallback: dispatch a click on that exact title element only.
    try:
        heading.evaluate(
            r"""(element) => {
                element.dispatchEvent(
                    new MouseEvent("click", {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                    })
                );
            }"""
        )
        page.wait_for_timeout(
            HEADING_CLICK_WAIT_MS,
        )
    except Exception:
        pass

    return (
        label
        if wait_for_requested_rows(page, config)
        else None
    )

def wait_for_requested_rows(page, config):
    pattern_source = config["row_re"].pattern

    try:
        page.wait_for_function(
            r"""(patternSource) => {
                const rowRe = new RegExp(patternSource, "i");
                const body = document.body
                    ? document.body.innerText
                    : "";

                return body
                    .split(/\n+/)
                    .map(value => value.trim().replace(/\s+/g, " "))
                    .some(value => rowRe.test(value));
            }""",
            pattern_source,
            timeout=ROWS_READY_TIMEOUT_MS,
        )
        return True
    except Exception:
        try:
            rows = extract_visible_rows(
                page,
                pattern_source,
            )
            return bool(rows)
        except Exception:
            return False


def mark_expanded_market_scope(page, labels, pattern_source):
    """
    Mark the smallest visible ancestor containing:
    - the exact requested market heading; and
    - at least one matching player/threshold row.

    This isolates the current market card from goalscorers and other expanded
    markets elsewhere on the Player page.
    """
    return page.evaluate(
        r"""({labels, patternSource}) => {
            document
                .querySelectorAll(
                    "[data-bv-exact-market-scope]"
                )
                .forEach(element => element.removeAttribute(
                    "data-bv-exact-market-scope"
                ));

            const normalise = value => String(value || "")
                .trim()
                .replace(/\s+/g, " ")
                .toLowerCase();

            const wanted = new Set(
                labels.map(normalise)
            );
            const rowRe = new RegExp(
                patternSource,
                "i"
            );
            const candidates = [];

            for (
                const heading
                of document.querySelectorAll(
                    "h1, h2, h3, h4, h5, "
                    + "button, [role='button'], div, span, p"
                )
            ) {
                const rect =
                    heading.getBoundingClientRect();

                if (
                    rect.width <= 0
                    || rect.height <= 0
                    || !wanted.has(
                        normalise(heading.innerText)
                    )
                ) {
                    continue;
                }

                let node = heading;

                for (
                    let depth = 0;
                    depth < 9 && node;
                    depth += 1, node = node.parentElement
                ) {
                    const raw = String(
                        node.innerText || ""
                    );

                    if (
                        !raw
                        || raw.length > 25000
                    ) {
                        continue;
                    }

                    const lines = raw
                        .split(/\n+/)
                        .map(value => value
                            .trim()
                            .replace(/\s+/g, " ")
                        )
                        .filter(Boolean);

                    const rowCount = lines.filter(
                        value => rowRe.test(value)
                    ).length;

                    if (!rowCount) {
                        continue;
                    }

                    const headingPresent = lines.some(
                        value => wanted.has(
                            normalise(value)
                        )
                    );

                    if (!headingPresent) {
                        continue;
                    }

                    const showMoreCount = Array.from(
                        node.querySelectorAll(
                            "button, [role='button']"
                        )
                    ).filter(control =>
                        /^Show More$/i.test(
                            normalise(control.innerText)
                        )
                    ).length;

                    candidates.push({
                        node,
                        rowCount,
                        showMoreCount,
                        textLength: raw.length,
                        depth,
                    });

                    break;
                }
            }

            if (!candidates.length) {
                return null;
            }

            candidates.sort((left, right) => {
                if (
                    left.textLength
                    !== right.textLength
                ) {
                    return (
                        left.textLength
                        - right.textLength
                    );
                }

                return right.rowCount - left.rowCount;
            });

            const best = candidates[0];

            best.node.setAttribute(
                "data-bv-exact-market-scope",
                "1"
            );

            return {
                row_count: best.rowCount,
                show_more_count:
                    best.showMoreCount,
                text_length: best.textLength,
                depth: best.depth,
                tag: best.node.tagName,
                class_name: String(
                    best.node.className || ""
                ).slice(0, 220),
            };
        }""",
        {
            "labels": labels,
            "patternSource": pattern_source,
        },
    )


def extract_scoped_rows(page, pattern_source):
    """
    Extract visible rows only from the currently marked market card.
    """
    return page.evaluate(
        r"""({patternSource}) => {
            const root = document.querySelector(
                "[data-bv-exact-market-scope='1']"
            );

            if (!root) {
                return [];
            }

            const oddsRe =
                /^(?:\d+\/\d+|EVS|EVENS|EVEN)$/i;
            const rowRe = new RegExp(
                patternSource,
                "i"
            );
            const output = [];
            const seenLabels = new Set();

            for (
                const element
                of root.querySelectorAll("*")
            ) {
                const rect =
                    element.getBoundingClientRect();

                if (
                    rect.width <= 0
                    || rect.height <= 0
                ) {
                    continue;
                }

                const label = String(
                    element.innerText || ""
                )
                    .trim()
                    .replace(/\s+/g, " ");

                if (
                    label.length > 150
                    || !rowRe.test(label)
                    || seenLabels.has(label)
                ) {
                    continue;
                }

                let node = element;
                let found = null;

                for (
                    let depth = 0;
                    depth < 8 && node && root.contains(node);
                    depth += 1, node = node.parentElement
                ) {
                    const lines = String(
                        node.innerText || ""
                    )
                        .split(/\n+/)
                        .map(value => value.trim())
                        .filter(Boolean);

                    const odds = lines.filter(
                        value => oddsRe.test(value)
                    );

                    if (
                        odds.length
                        && String(
                            node.innerText || ""
                        ).length < 700
                    ) {
                        found = {
                            label,
                            odds: odds[0],
                            block: String(
                                node.innerText || ""
                            ).trim(),
                        };
                        break;
                    }
                }

                if (!found) {
                    continue;
                }

                seenLabels.add(label);
                output.push(found);
            }

            return output;
        }""",
        {"patternSource": pattern_source},
    )


def mark_nearest_show_more_below_heading(
    page,
    labels,
    pattern_source,
):
    """
    Mark the nearest visible Show More physically below the exact heading.

    The real BetVictor layout is:
        exact heading
        matching player rows
        green Show More button

    We therefore use page geometry rather than requiring the heading and button
    to share a small DOM ancestor.
    """
    return page.evaluate(
        r"""({labels, patternSource}) => {
            document
                .querySelectorAll(
                    "[data-bv-nearest-show-more]"
                )
                .forEach(element => element.removeAttribute(
                    "data-bv-nearest-show-more"
                ));

            const normalise = value => String(value || "")
                .trim()
                .replace(/\s+/g, " ")
                .toLowerCase();

            const wanted = new Set(
                labels.map(normalise)
            );
            const rowRe = new RegExp(
                patternSource,
                "i"
            );

            const visible = element => {
                const rect =
                    element.getBoundingClientRect();
                const style =
                    getComputedStyle(element);

                return (
                    rect.width > 0
                    && rect.height > 0
                    && style.display !== "none"
                    && style.visibility !== "hidden"
                    && Number(style.opacity || 1) > 0
                );
            };

            const absoluteY = element => {
                const rect =
                    element.getBoundingClientRect();
                return window.scrollY + rect.top;
            };

            const headings = Array.from(
                document.querySelectorAll(
                    "h1, h2, h3, h4, h5, "
                    + "button, [role='button'], "
                    + "div, span, p"
                )
            ).filter(element =>
                visible(element)
                && wanted.has(
                    normalise(element.innerText)
                )
            );

            const rowElements = [];

            for (
                const element
                of document.querySelectorAll("*")
            ) {
                if (!visible(element)) {
                    continue;
                }

                const label = String(
                    element.innerText || ""
                )
                    .trim()
                    .replace(/\s+/g, " ");

                if (
                    label.length <= 160
                    && rowRe.test(label)
                ) {
                    rowElements.push({
                        element,
                        label,
                        y: absoluteY(element),
                    });
                }
            }

            const rawControls = Array.from(
                document.querySelectorAll(
                    "button, [role='button'], a, div, span"
                )
            ).filter(element =>
                visible(element)
                && /^show more$/i.test(
                    normalise(element.innerText)
                )
            );

            const buttons = [];
            const seen = new Set();

            for (const element of rawControls) {
                const target =
                    element.closest(
                        "button, [role='button'], a"
                    )
                    || element;

                if (
                    !visible(target)
                    || seen.has(target)
                ) {
                    continue;
                }

                seen.add(target);
                buttons.push(target);
            }

            const candidates = [];

            for (const heading of headings) {
                const headingRect =
                    heading.getBoundingClientRect();
                const headingTop =
                    window.scrollY + headingRect.top;
                const headingBottom =
                    window.scrollY + headingRect.bottom;

                for (const button of buttons) {
                    const buttonRect =
                        button.getBoundingClientRect();
                    const buttonTop =
                        window.scrollY + buttonRect.top;
                    const distance =
                        buttonTop - headingBottom;

                    if (
                        distance < 20
                        || distance > 2400
                    ) {
                        continue;
                    }

                    const rowsBetween =
                        rowElements.filter(row =>
                            row.y > headingBottom
                            && row.y < buttonTop + 5
                        );

                    if (!rowsBetween.length) {
                        continue;
                    }

                    candidates.push({
                        heading,
                        button,
                        distance,
                        headingTop,
                        headingBottom,
                        buttonTop,
                        rowsBetween,
                    });
                }
            }

            if (!candidates.length) {
                return {
                    found: false,
                    visible_headings: headings.length,
                    visible_rows: rowElements.length,
                    visible_show_more: buttons.length,
                };
            }

            candidates.sort((left, right) => {
                if (
                    left.distance
                    !== right.distance
                ) {
                    return left.distance - right.distance;
                }

                return (
                    right.rowsBetween.length
                    - left.rowsBetween.length
                );
            });

            const best = candidates[0];

            best.button.setAttribute(
                "data-bv-nearest-show-more",
                "1"
            );

            return {
                found: true,
                distance_px:
                    Math.round(best.distance),
                matching_rows_between:
                    best.rowsBetween.length,
                heading_y:
                    Math.round(best.headingTop),
                button_y:
                    Math.round(best.buttonTop),
                button_tag:
                    best.button.tagName,
                button_text: String(
                    best.button.innerText || ""
                )
                    .trim()
                    .replace(/\s+/g, " "),
                visible_headings: headings.length,
                visible_rows: rowElements.length,
                visible_show_more: buttons.length,
            };
        }""",
        {
            "labels": labels,
            "patternSource": pattern_source,
        },
    )

def nearest_show_more_locator(page):
    locator = page.locator(
        "[data-bv-nearest-show-more='1']"
    )

    if not locator.count():
        return None

    item = locator.first

    try:
        if item.is_visible():
            return item
    except Exception:
        pass

    return None

def harvest_expanded_market_range(
    page,
    config,
    store,
):
    """
    Scroll only through the marked expanded market card.

    This catches virtual/lazy rows without rescanning the entire sportsbook
    page or unrelated markets.
    """
    pattern_source = config["row_re"].pattern
    scope = mark_expanded_market_scope(
        page,
        config["headings"],
        pattern_source,
    )

    if scope is None:
        return {
            "used": False,
            "steps": 0,
            "rows_before": len(store),
            "rows_after": len(store),
        }

    bounds = page.evaluate(
        r"""() => {
            const root = document.querySelector(
                "[data-bv-exact-market-scope='1']"
            );

            if (!root) {
                return null;
            }

            const rect =
                root.getBoundingClientRect();

            return {
                top: Math.max(
                    0,
                    Math.floor(
                        window.scrollY
                        + rect.top
                        - 120
                    )
                ),
                bottom: Math.ceil(
                    window.scrollY
                    + rect.bottom
                    + 120
                ),
                height: Math.ceil(rect.height),
            };
        }"""
    )

    if not bounds:
        return {
            "used": False,
            "steps": 0,
            "rows_before": len(store),
            "rows_after": len(store),
        }

    before = len(store)
    position = int(bounds["top"])
    bottom = int(bounds["bottom"])
    steps = 0

    while (
        position <= bottom
        and steps < MAX_MARKET_SCROLL_STEPS
    ):
        page.evaluate(
            "(value) => window.scrollTo(0, value)",
            position,
        )
        page.wait_for_timeout(
            MARKET_SCROLL_WAIT_MS,
        )

        # The scope remains the same card; collect any newly mounted rows.
        add_rows(
            store,
            extract_scoped_rows(
                page,
                pattern_source,
            ),
        )

        position += MARKET_SCROLL_STEP
        steps += 1

    page.evaluate(
        "(value) => window.scrollTo(0, value)",
        bottom,
    )
    page.wait_for_timeout(
        MARKET_SCROLL_WAIT_MS,
    )

    add_rows(
        store,
        extract_scoped_rows(
            page,
            pattern_source,
        ),
    )

    return {
        "used": True,
        "steps": steps,
        "rows_before": before,
        "rows_after": len(store),
        "scope_height": bounds["height"],
    }


def click_scoped_show_more_fast(
    page,
    config,
    store,
):
    """
    Click the verified green Show More and scroll through only this market.
    """
    clicks = 0
    passes = []
    pattern_source = config["row_re"].pattern

    for pass_number in range(
        1,
        MAX_SCOPED_SHOW_MORE_CLICKS + 1,
    ):
        mark_expanded_market_scope(
            page,
            config["headings"],
            pattern_source,
        )

        add_rows(
            store,
            extract_scoped_rows(
                page,
                pattern_source,
            ),
        )
        before = len(store)

        button_meta = (
            mark_nearest_show_more_below_heading(
                page,
                config["headings"],
                pattern_source,
            )
        )

        if not button_meta.get("found"):
            passes.append(
                {
                    "pass": pass_number,
                    "rows_before": before,
                    "rows_after": len(store),
                    "rows_added": 0,
                    "button": button_meta,
                    "clicked": False,
                }
            )
            break

        control = nearest_show_more_locator(
            page
        )

        if control is None:
            passes.append(
                {
                    "pass": pass_number,
                    "rows_before": before,
                    "rows_after": len(store),
                    "rows_added": 0,
                    "button": button_meta,
                    "clicked": False,
                    "error":
                        "marked_button_not_locatable",
                }
            )
            break

        click_preparation = prepare_control_for_click(
            page,
            control,
        )

        print(
            "    Show More blocker: "
            f"before={click_preparation['before'].get('blocked')} "
            f"neutralised="
            f"{click_preparation['neutralised'].get('changed')} "
            f"after={click_preparation['after'].get('blocked')}"
        )

        try:
            control.click(
                timeout=2500,
                force=False,
            )
        except Exception as normal_error:
            try:
                clicked_safely = bool(
                    control.evaluate(
                        r"""(element) => {
                            const text = String(
                                element.innerText || ""
                            ).trim().replace(/\s+/g, " ");

                            if (!/^Show More$/i.test(text)) {
                                return false;
                            }

                            element.dispatchEvent(
                                new MouseEvent(
                                    "click",
                                    {
                                        bubbles: true,
                                        cancelable: true,
                                        view: window,
                                    }
                                )
                            );

                            return true;
                        }"""
                    )
                )
            except Exception:
                clicked_safely = False

            if not clicked_safely:
                passes.append(
                    {
                        "pass": pass_number,
                        "rows_before": before,
                        "rows_after": len(store),
                        "rows_added": 0,
                        "button": button_meta,
                        "click_preparation":
                            click_preparation,
                        "clicked": False,
                        "error": str(normal_error),
                    }
                )
                break

        clicks += 1
        page.wait_for_timeout(
            SCOPED_SHOW_MORE_WAIT_MS,
        )

        # Re-mark the expanded card after BetVictor updates the DOM.
        mark_expanded_market_scope(
            page,
            config["headings"],
            pattern_source,
        )

        add_rows(
            store,
            extract_scoped_rows(
                page,
                pattern_source,
            ),
        )

        scroll_audit = (
            harvest_expanded_market_range(
                page,
                config,
                store,
            )
        )

        after = len(store)

        passes.append(
            {
                "pass": pass_number,
                "rows_before": before,
                "rows_after": after,
                "rows_added": after - before,
                "button": button_meta,
                "click_preparation": click_preparation,
                "clicked": True,
                "market_scroll": scroll_audit,
            }
        )

        # Most BetVictor markets need a single Show More. Recheck once in case
        # a second button appears, then stop when there is no growth.
        if after == before:
            break

    return clicks, passes

def scrape_market(browser, fixture, key, config):
    market_started = time.perf_counter()
    context = browser.new_context(
        viewport={"width": 1700, "height": 1000},
        permissions=[],
    )
    page = context.new_page()
    page.add_init_script(
        r"""() => {
            const mute = () => {
                document.querySelectorAll('audio, video')
                    .forEach(element => {
                        element.muted = true;
                        element.volume = 0;
                    });
            };
            document.addEventListener(
                'DOMContentLoaded',
                mute,
                {once: false}
            );
        }"""
    )

    debug_dir = DEBUG_ROOT / slugify(fixture["match"]) / key
    debug_dir.mkdir(parents=True, exist_ok=True)

    url = f"{fixture['source_url']}?market_group={PLAYER_GROUP}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=70000)
        wait_for_market_page_ready(page, config)
        accept_cookies(page)

        overlay_actions = dismiss_obvious_overlays(page)

        if overlay_actions:
            print(
                "    overlay dismiss: "
                + ", ".join(overlay_actions)
            )

        # The direct market_group URL is already the Player group. Do not click
        # a generic "Player" label; find the exact accordion shown in the UI.
        heading_clicked = click_market_accordion(
            page,
            config["headings"],
            config,
        )

        pattern_source = config["row_re"].pattern
        store = {}
        phase_counts = {}

        scope = mark_expanded_market_scope(
            page,
            config["headings"],
            pattern_source,
        )
        phase_counts["initial_scope"] = scope

        add_rows(
            store,
            extract_scoped_rows(
                page,
                pattern_source,
            ),
        )
        phase_counts["initial_rows"] = len(store)

        show_more_clicked, show_more_passes = (
            click_scoped_show_more_fast(
                page,
                config,
                store,
            )
        )
        phase_counts["show_more_clicked"] = (
            show_more_clicked
        )
        phase_counts["show_more_passes"] = (
            show_more_passes
        )

        # Final scope refresh and one direct extraction.
        final_scope = mark_expanded_market_scope(
            page,
            config["headings"],
            pattern_source,
        )
        phase_counts["final_scope"] = final_scope

        add_rows(
            store,
            extract_scoped_rows(
                page,
                pattern_source,
            ),
        )
        phase_counts["rows_after_scoped"] = len(
            store
        )

        fallback_used = False
        containers = []
        containers_second = []

        if (
            final_scope is None
            or len(store)
            < MIN_SCOPED_ROWS_BEFORE_FALLBACK
        ):
            fallback_used = True
            extractor = lambda: extract_visible_rows(
                page,
                pattern_source,
            )
            harvest_window(
                page,
                extractor,
                store,
            )
            containers = harvest_containers(
                page,
                extractor,
                store,
            )

        phase_counts["fallback_used"] = (
            fallback_used
        )
        phase_counts["final_rows"] = len(store)

        more_clicked = show_more_clicked

        button_passes = phase_counts.get(
            "show_more_passes",
            [],
        )
        first_button = (
            button_passes[0].get("button", {})
            if button_passes
            else {}
        )

        print(
            "    overlay-safe harvest: "
            f"heading={heading_clicked} "
            f"initial={phase_counts['initial_rows']} "
            f"show_more={show_more_clicked} "
            f"button_found="
            f"{first_button.get('found')} "
            f"rows_between="
            f"{first_button.get('matching_rows_between')} "
            f"final_rows={len(store)} "
            f"fallback={fallback_used}"
        )

        rows = list(store.values())
        selections, selection_audit = parse_rows(
            rows,
            config,
        )

        print(
            "    validated: "
            f"players={selection_audit['player_count']} "
            f"thresholds="
            f"{selection_audit['threshold_counts']} "
            f"conflicts="
            f"{selection_audit['conflict_count']}"
        )

        body = page.locator("body").inner_text(timeout=25000)
        (debug_dir / "body.txt").write_text(body, encoding="utf-8")
        (debug_dir / "raw_rows.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (debug_dir / "scroll_containers.json").write_text(
            json.dumps(
                {
                    "fallback_pass": containers,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (debug_dir / "harvest_phases.json").write_text(
            json.dumps(
                phase_counts,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (debug_dir / "selection_audit.json").write_text(
            json.dumps(
                selection_audit,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if SAVE_SCREENSHOTS:
            page.screenshot(
                path=str(debug_dir / "page.png"),
                full_page=True,
            )

        return {
            "market": config["market"],
            "normalized_market": key,
            "heading_clicked": heading_clicked,
            "expansion_controls_clicked": more_clicked,
            "scroll_containers_found": len(containers),
            "scoped_show_more_clicked": show_more_clicked,
            "fallback_used": fallback_used,
            "harvest_phases": phase_counts,
            "selection_audit": selection_audit,
            "selection_count": len(selections),
            "elapsed_seconds": round(
                time.perf_counter() - market_started,
                2,
            ),
            "selections": selections,
        }

    finally:
        context.close()


def main():
    total_started = time.perf_counter()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_ROOT.mkdir(parents=True, exist_ok=True)

    fixtures, removed_started, removed_unknown, source_generated_at = (
        load_upcoming_fixtures()
    )

    print("BETVICTOR PLAYER TACKLES — PROD15 FAST")
    print("=" * 72)
    print(f"MAX_MATCHES = {MAX_MATCHES}")
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc + timedelta(
        minutes=UPCOMING_BUFFER_MINUTES
    )
    print(
        "Current Irish time:              "
        + now_utc.astimezone(
            BETVICTOR_LOCAL_TIMEZONE
        ).strftime("%d %b %Y %H:%M:%S %Z")
    )
    print(
        "Kickoff safety cutoff:           "
        + cutoff_utc.astimezone(
            BETVICTOR_LOCAL_TIMEZONE
        ).strftime("%d %b %Y %H:%M:%S %Z")
    )
    print(f"Started/in-play fixtures removed: {len(removed_started)}")
    print(f"Unknown-kickoff fixtures removed: {len(removed_unknown)}")
    print(f"Upcoming fixtures to scan:        {len(fixtures)}")

    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS,
            args=["--mute-audio"],
        )

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
                    f"containers={market.get('scroll_containers_found')} "
                    f"selections={market.get('selection_count')} "
                    f"time={market.get('elapsed_seconds'):.1f}s"
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
        "market_type": "player_tackles",
        "test_mode": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_props_generated_at": source_generated_at,
        "max_matches": MAX_MATCHES,
        "match_count": len(results),
        "matches_with_player_tackles": len(
            [row for row in results if row.get("market_count") == 1]
        ),
        "elapsed_seconds": round(
            time.perf_counter() - total_started,
            2,
        ),
        "matches": results,
    }

    temp_path = OUT_PATH.with_suffix(
        OUT_PATH.suffix + ".tmp"
    )
    temp_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(OUT_PATH)

    print("\n" + "=" * 72)
    print(f"Saved production output: {OUT_PATH}")
    print(
        "Matches with Player Tackles: "
        f"{output['matches_with_player_tackles']}/"
        f"{output['match_count']}"
    )
    print(
        f"Total elapsed: "
        f"{output['elapsed_seconds']:.1f}s"
    )
    print("Main BetVictor props JSON modified directly: NO")


if __name__ == "__main__":
    main()
