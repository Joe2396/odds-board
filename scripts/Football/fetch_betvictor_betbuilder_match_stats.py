#!/usr/bin/env python3
# BETVICTOR_BETBUILDER_MATCH_STATS_PROD15_FAST_V1_FIXED_PATH
"""
Fast isolated BetVictor Bet Builder Match/Team Stats test.

Markets:
- Match Shots On Target
- Match Shots
- Home/Away Shots On Target
- Home/Away Shots

Method:
- direct Bet Builder group URL;
- exact Match Stats tab;
- exact accordion heading;
- safe overlay handling;
- scoped threshold/odds extraction;
- optional scoped Show More;
- no repeated whole-page text captures;
- one browser context per fixture.

PRODUCTION MODE:
    MAX_MATCHES = 15

Output:
    football/data/
    betvictor_worldcup_betbuilder_stats.json

Production BetVictor files are not modified.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "football" / "data"

PROPS_PATH = DATA_DIR / "betvictor_worldcup_props.json"
OUT_PATH = (
    DATA_DIR
    / "betvictor_worldcup_betbuilder_stats.json"
)
DEBUG_ROOT = (
    ROOT
    / "football"
    / "debug"
    / "betvictor_betbuilder_stats"
)

BETBUILDER_GROUP = "12536"
MAX_MATCHES = 15
HEADLESS = False
UPCOMING_BUFFER_MINUTES = 15
LOCAL_TIMEZONE = ZoneInfo("Europe/Dublin")

INITIAL_READY_TIMEOUT_MS = 18000
INITIAL_SETTLE_MS = 5500
TAB_CLICK_WAIT_MS = 1400
HEADING_SCAN_STEP = 520
HEADING_SCAN_WAIT_MS = 140
HEADING_CLICK_WAIT_MS = 450
ROWS_READY_TIMEOUT_MS = 4500
SHOW_MORE_WAIT_MS = 350
MARKET_SCROLL_STEP = 360
MARKET_SCROLL_WAIT_MS = 90
MAX_MARKET_SCROLL_STEPS = 18

ODDS_RE = re.compile(
    r"^(?:\d+/\d+|EVS|EVENS|EVEN)$",
    re.I,
)
THRESHOLD_RE = re.compile(r"^(\d+)\+$")
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

TEAM_ALIASES = {
    "United States": "USA",
    "USA": "USA",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Türkiye": "Türkiye",
    "Czech Republic": "Czechia",
    "Bosnia and Herzegovina": "Bosnia",
    "Bosnia & Herzegovina": "Bosnia",
    "Curaçao": "Curacao",
}

TEAM_ROW_ALIASES = {
    "USA": [
        "USA",
        "United States",
        "United States of America",
    ],
    "Türkiye": [
        "Türkiye",
        "Turkey",
        "Turkiye",
    ],
    "Czechia": [
        "Czechia",
        "Czech Republic",
    ],
    "Bosnia": [
        "Bosnia",
        "Bosnia and Herzegovina",
        "Bosnia & Herzegovina",
    ],
    "Curacao": [
        "Curacao",
        "Curaçao",
    ],
}


def clean(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def normalize(value: Any) -> str:
    value = unicodedata.normalize(
        "NFKD",
        clean(value),
    )
    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        value.lower(),
    ).strip("_")


def slugify(value: Any) -> str:
    return normalize(value).replace("_", "-")


def canonical_team(value: Any) -> str:
    text = clean(value)
    return TEAM_ALIASES.get(text, text)


def row_team_aliases(team: str) -> list[str]:
    values = TEAM_ROW_ALIASES.get(
        team,
        [team],
    )
    output = []

    for value in values:
        value = clean(value)

        if value and value not in output:
            output.append(value)

    return output


def row_title_candidates(
    team: str,
    stat_label: str,
) -> list[str]:
    return [
        f"{name} {stat_label}"
        for name in row_team_aliases(team)
    ]


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            timestamp = float(value)

            if timestamp > 10_000_000_000:
                timestamp /= 1000

            return datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
        except Exception:
            return None

    text = clean(value)

    if not text:
        return None

    for candidate in (
        text,
        text.replace("Z", "+00:00"),
    ):
        try:
            parsed = datetime.fromisoformat(
                candidate
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=LOCAL_TIMEZONE
                )

            return parsed.astimezone(
                timezone.utc
            )
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
            parsed = datetime.strptime(
                text,
                fmt,
            )
            parsed = parsed.replace(
                tzinfo=LOCAL_TIMEZONE
            )
            return parsed.astimezone(
                timezone.utc
            )
        except ValueError:
            pass

    return None


def extract_match_name(
    row: dict[str, Any],
) -> str:
    name = clean(row.get("match"))

    if name:
        return name

    home = clean(
        row.get("home")
        or row.get("home_team")
    )
    away = clean(
        row.get("away")
        or row.get("away_team")
    )

    return (
        f"{home} v {away}"
        if home and away
        else ""
    )


def extract_kickoff(
    row: dict[str, Any],
) -> datetime | None:
    for key in KICKOFF_KEYS:
        parsed = parse_datetime(
            row.get(key)
        )

        if parsed:
            return parsed

    return None


def load_kickoff_map() -> dict[str, datetime]:
    kickoff_map: dict[str, datetime] = {}

    for path in sorted(
        DATA_DIR.glob(
            "*worldcup*moneyline*.json"
        )
    ):
        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            continue

        rows = (
            data.get("matches", [])
            if isinstance(data, dict)
            else []
        )

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

            if (
                existing is None
                or kickoff > existing
            ):
                kickoff_map[key] = kickoff

    return kickoff_map


def load_upcoming_fixtures():
    data = json.loads(
        PROPS_PATH.read_text(
            encoding="utf-8"
        )
    )
    kickoff_map = load_kickoff_map()
    cutoff = (
        datetime.now(timezone.utc)
        + timedelta(
            minutes=UPCOMING_BUFFER_MINUTES
        )
    )

    upcoming = []
    removed_started = []
    removed_unknown = []

    for match in data.get("matches", []):
        name = clean(match.get("match"))
        home = canonical_team(
            match.get("home_team")
        )
        away = canonical_team(
            match.get("away_team")
        )
        url = clean(
            match.get("source_url")
            or match.get("url")
        )

        if not name and home and away:
            name = f"{home} v {away}"

        if (
            not name
            or not home
            or not away
            or "/events/" not in url
        ):
            continue

        kickoff = (
            extract_kickoff(match)
            or kickoff_map.get(
                normalize(name)
            )
        )

        fixture = {
            "match": name,
            "home": home,
            "away": away,
            "source_url":
                url.split("?", 1)[0],
            "kickoff": (
                kickoff.isoformat()
                if kickoff
                else None
            ),
        }

        if kickoff is None:
            removed_unknown.append(
                fixture
            )
        elif kickoff <= cutoff:
            removed_started.append(
                fixture
            )
        else:
            upcoming.append(fixture)

    upcoming.sort(
        key=lambda item: item["kickoff"]
    )

    return (
        upcoming[:MAX_MATCHES],
        removed_started,
        removed_unknown,
        data.get("generated_at"),
    )


def market_configs(
    fixture: dict[str, Any],
) -> list[dict[str, Any]]:
    home = fixture["home"]
    away = fixture["away"]

    return [
        {
            "key":
                "match_shots_on_target",
            "market":
                "Match Shots On Target",
            "headings": [
                "Match Shots on Target",
                "Match Shots On Target",
            ],
            "team": None,
            "stat":
                "shots_on_target",
        },
        {
            "key": "match_shots",
            "market": "Match Shots",
            "headings": [
                "Match Shots",
            ],
            "team": None,
            "stat": "shots",
        },
        {
            "key": normalize(
                f"{home}_shots_on_target"
            ),
            "market":
                f"{home} Shots On Target",
            "headings":
                row_title_candidates(
                    home,
                    "Shots on Target",
                ),
            "team": home,
            "stat":
                "shots_on_target",
        },
        {
            "key": normalize(
                f"{home}_shots"
            ),
            "market": f"{home} Shots",
            "headings":
                row_title_candidates(
                    home,
                    "Shots",
                ),
            "team": home,
            "stat": "shots",
        },
        {
            "key": normalize(
                f"{away}_shots_on_target"
            ),
            "market":
                f"{away} Shots On Target",
            "headings":
                row_title_candidates(
                    away,
                    "Shots on Target",
                ),
            "team": away,
            "stat":
                "shots_on_target",
        },
        {
            "key": normalize(
                f"{away}_shots"
            ),
            "market": f"{away} Shots",
            "headings":
                row_title_candidates(
                    away,
                    "Shots",
                ),
            "team": away,
            "stat": "shots",
        },
    ]


def group_url(
    event_url: str,
) -> str:
    return (
        event_url.split("?", 1)[0]
        + f"?market_group={BETBUILDER_GROUP}"
    )


def body_text(page) -> str:
    try:
        return page.locator(
            "body"
        ).inner_text(timeout=15000)
    except Exception:
        return ""


def accept_cookies(page) -> None:
    labels = [
        "Accept All",
        "Accept all",
        "I Accept",
        "Accept",
        "Agree",
        "Allow all",
        "OK",
        "I have read the above",
        "Dismiss",
    ]

    for label in labels:
        try:
            locator = page.get_by_role(
                "button",
                name=re.compile(
                    rf"^{re.escape(label)}$",
                    re.I,
                ),
            )

            for index in range(
                min(locator.count(), 5)
            ):
                item = locator.nth(index)

                try:
                    if item.is_visible():
                        item.click(
                            timeout=1000
                        )
                        page.wait_for_timeout(
                            250
                        )
                        return
                except Exception:
                    continue
        except Exception:
            continue


def dismiss_obvious_overlays(
    page,
) -> list[str]:
    actions = []

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        actions.append("escape")
    except Exception:
        pass

    patterns = [
        re.compile(r"^Close$", re.I),
        re.compile(r"^Dismiss$", re.I),
        re.compile(r"^Not now$", re.I),
        re.compile(
            r"^Maybe later$",
            re.I,
        ),
        re.compile(
            r"^No thanks$",
            re.I,
        ),
        re.compile(r"^[×✕✖]$"),
    ]

    for pattern in patterns:
        try:
            locator = page.get_by_role(
                "button",
                name=pattern,
            )

            for index in range(
                min(locator.count(), 8)
            ):
                item = locator.nth(index)

                try:
                    if not item.is_visible():
                        continue

                    item.click(timeout=900)
                    page.wait_for_timeout(120)
                    actions.append(
                        pattern.pattern
                    )
                    break
                except Exception:
                    continue
        except Exception:
            continue

    return actions


def inspect_click_blocker(
    locator,
) -> dict[str, Any]:
    try:
        return locator.evaluate(
            r"""(element) => {
                const rect =
                    element.getBoundingClientRect();
                const x =
                    rect.left + rect.width / 2;
                const y =
                    rect.top + rect.height / 2;
                const top =
                    document.elementFromPoint(x, y);

                if (!top) {
                    return {
                        blocked: false,
                        reason:
                            "no_element_from_point",
                    };
                }

                const unblocked =
                    element === top
                    || element.contains(top)
                    || top.contains(element);

                return {
                    blocked: !unblocked,
                    blocker_tag: top.tagName,
                    blocker_class: String(
                        top.className || ""
                    ).slice(0, 200),
                };
            }"""
        )
    except Exception as error:
        return {
            "blocked": None,
            "error": str(error),
        }


def neutralise_actual_blocker(
    locator,
) -> dict[str, Any]:
    try:
        return locator.evaluate(
            r"""(element) => {
                const rect =
                    element.getBoundingClientRect();
                const x =
                    rect.left + rect.width / 2;
                const y =
                    rect.top + rect.height / 2;
                const top =
                    document.elementFromPoint(x, y);

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

                for (
                    let depth = 0;
                    depth < 9 && node;
                    depth += 1
                ) {
                    const style =
                        getComputedStyle(node);
                    const box =
                        node.getBoundingClientRect();
                    const viewportArea =
                        Math.max(
                            1,
                            window.innerWidth
                        )
                        * Math.max(
                            1,
                            window.innerHeight
                        );
                    const area =
                        Math.max(0, box.width)
                        * Math.max(0, box.height);
                    const coverage =
                        area / viewportArea;

                    if (
                        (
                            style.position === "fixed"
                            || style.position
                                === "sticky"
                        )
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
                            coverage,
                            tag: node.tagName,
                        };
                    }

                    node = node.parentElement;
                }

                return {
                    changed: false,
                    reason:
                        "no_large_fixed_blocker",
                };
            }"""
        )
    except Exception as error:
        return {
            "changed": False,
            "error": str(error),
        }


def prepare_control_for_click(
    page,
    locator,
) -> dict[str, Any]:
    actions = dismiss_obvious_overlays(
        page
    )

    try:
        locator.scroll_into_view_if_needed(
            timeout=1800
        )
        page.wait_for_timeout(120)
    except Exception:
        pass

    before = inspect_click_blocker(
        locator
    )
    neutralised = {
        "changed": False,
        "reason": "not_needed",
    }

    if before.get("blocked") is True:
        neutralised = (
            neutralise_actual_blocker(
                locator
            )
        )
        page.wait_for_timeout(120)

    after = inspect_click_blocker(
        locator
    )

    return {
        "dismiss_actions": actions,
        "before": before,
        "neutralised": neutralised,
        "after": after,
    }


def safe_exact_click(
    page,
    locator,
    expected_text: str,
    wait_ms: int,
) -> tuple[bool, dict[str, Any]]:
    preparation = prepare_control_for_click(
        page,
        locator,
    )

    try:
        locator.click(
            timeout=2200,
            force=False,
        )
        page.wait_for_timeout(wait_ms)
        return True, preparation
    except Exception:
        pass

    try:
        clicked = bool(
            locator.evaluate(
                r"""(element, expectedText) => {
                    const text = String(
                        element.innerText || ""
                    ).trim().replace(/\s+/g, " ");

                    if (
                        text.toLowerCase()
                        !== String(
                            expectedText || ""
                        ).trim().toLowerCase()
                    ) {
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
                }""",
                expected_text,
            )
        )

        if clicked:
            page.wait_for_timeout(wait_ms)
            return True, preparation
    except Exception:
        pass

    return False, preparation


def visible_exact_text(
    page,
    labels: list[str],
):
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

            for index in range(
                locator.count()
            ):
                item = locator.nth(index)

                try:
                    if not item.is_visible():
                        continue

                    box = item.bounding_box()

                    if box:
                        visible.append(
                            (
                                box["width"]
                                * box["height"],
                                item,
                                clean(label),
                            )
                        )
                except Exception:
                    continue

            if visible:
                visible.sort(
                    key=lambda row: row[0]
                )
                _, item, matched = visible[0]
                return item, matched

        except Exception:
            continue

    return None, None


def wait_for_event_page(
    page,
    fixture: dict[str, Any],
    timeout_ms: int = INITIAL_READY_TIMEOUT_MS,
) -> bool:
    """
    Production-proven readiness rule.

    BetVictor can initially render the event's Popular view even when a direct
    Bet Builder market-group URL is used. That is still a valid loaded event
    page and the Match Stats tab can then be opened.
    """
    deadline = (
        time.perf_counter()
        + timeout_ms / 1000
    )

    home_aliases = row_team_aliases(
        fixture["home"]
    )
    away_aliases = row_team_aliases(
        fixture["away"]
    )

    while time.perf_counter() < deadline:
        text_value = body_text(page)
        low = text_value.lower()

        has_team = (
            fixture["home"].lower() in low
            or fixture["away"].lower() in low
            or any(
                alias.lower() in low
                for alias in home_aliases
            )
            or any(
                alias.lower() in low
                for alias in away_aliases
            )
        )
        has_event_ui = (
            "bet builder" in low
            or "match stats" in low
            or "popular" in low
        )

        if has_team and has_event_ui:
            return True

        page.wait_for_timeout(750)

    return False


def robust_click_locator(
    page,
    locator,
    wait_ms: int = TAB_CLICK_WAIT_MS,
) -> bool:
    """
    Proven BetVictor click order:
    normal click -> element.click() -> exact centre mouse click.
    """
    try:
        locator.scroll_into_view_if_needed(
            timeout=2500
        )
    except Exception:
        pass

    try:
        locator.click(timeout=2500)
        page.wait_for_timeout(wait_ms)
        return True
    except Exception:
        pass

    try:
        locator.evaluate(
            "(element) => element.click()"
        )
        page.wait_for_timeout(wait_ms)
        return True
    except Exception:
        pass

    try:
        box = locator.bounding_box()

        if box:
            page.mouse.click(
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2,
            )
            page.wait_for_timeout(wait_ms)
            return True
    except Exception:
        pass

    return False

def match_stats_active(page) -> bool:
    low = body_text(page).lower()

    return (
        "match shots on target" in low
        and "match shots" in low
    )


def click_match_stats_tab(
    page,
) -> tuple[bool, dict[str, Any]]:
    if match_stats_active(page):
        return True, {
            "already_active": True,
        }

    try:
        page.evaluate(
            "() => window.scrollTo(0, 0)"
        )
    except Exception:
        pass

    page.wait_for_timeout(500)

    locators = []

    try:
        locators.append(
            page.get_by_role(
                "tab",
                name=re.compile(
                    r"^Match Stats$",
                    re.I,
                ),
            )
        )
    except Exception:
        pass

    try:
        locators.append(
            page.get_by_role(
                "button",
                name=re.compile(
                    r"^Match Stats$",
                    re.I,
                ),
            )
        )
    except Exception:
        pass

    try:
        locators.append(
            page.get_by_text(
                "Match Stats",
                exact=True,
            )
        )
    except Exception:
        pass

    attempts = []

    for locator in locators:
        try:
            count = min(
                locator.count(),
                12,
            )
        except Exception:
            count = 0

        for index in range(count):
            item = locator.nth(index)

            try:
                visible = item.is_visible()
            except Exception:
                visible = False

            if not visible:
                continue

            preparation = (
                prepare_control_for_click(
                    page,
                    item,
                )
            )
            clicked = robust_click_locator(
                page,
                item,
            )
            attempts.append(
                {
                    "clicked": clicked,
                    "preparation":
                        preparation,
                }
            )

            if (
                clicked
                and match_stats_active(page)
            ):
                return True, {
                    "already_active": False,
                    "attempts": attempts,
                }

    return match_stats_active(page), {
        "already_active": False,
        "attempts": attempts,
    }


def save_navigation_failure(
    page,
    fixture: dict[str, Any],
    label: str,
) -> None:
    debug_dir = (
        DEBUG_ROOT
        / slugify(fixture["match"])
        / "navigation"
    )
    debug_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        (
            debug_dir
            / f"{label}_body.txt"
        ).write_text(
            body_text(page),
            encoding="utf-8",
        )
    except Exception:
        pass

    try:
        page.screenshot(
            path=str(
                debug_dir
                / f"{label}.png"
            ),
            full_page=True,
        )
    except Exception:
        pass

def scan_for_heading(
    page,
    labels: list[str],
):
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
            viewport = int(
                page.evaluate(
                    "window.innerHeight || 900"
                )
            )
        except Exception:
            total_height = 5000
            viewport = 900

        position = 0
        step = max(
            HEADING_SCAN_STEP,
            viewport // 2,
        )

        while position <= total_height:
            try:
                page.evaluate(
                    "(value) => "
                    "window.scrollTo(0, value)",
                    position,
                )
                page.wait_for_timeout(
                    HEADING_SCAN_WAIT_MS
                )
            except Exception:
                pass

            item, label = visible_exact_text(
                page,
                labels,
            )

            if item is not None:
                return item, label

            position += step

        page.wait_for_timeout(250)

    return None, None


def mark_market_scope(
    page,
    labels: list[str],
) -> dict[str, Any] | None:
    return page.evaluate(
        r"""(labels) => {
            document
                .querySelectorAll(
                    "[data-bv-stats-scope]"
                )
                .forEach(element =>
                    element.removeAttribute(
                        "data-bv-stats-scope"
                    )
                );

            const normalise = value =>
                String(value || "")
                    .trim()
                    .replace(/\s+/g, " ")
                    .toLowerCase();

            const wanted = new Set(
                labels.map(normalise)
            );
            const thresholdRe =
                /^\d+\+$/;
            const oddsRe =
                /^(?:\d+\/\d+|EVS|EVENS|EVEN)$/i;
            const candidates = [];

            for (
                const heading
                of document.querySelectorAll(
                    "h1,h2,h3,h4,h5,"
                    + "button,[role='button'],"
                    + "div,span,p"
                )
            ) {
                const rect =
                    heading.getBoundingClientRect();

                if (
                    rect.width <= 0
                    || rect.height <= 0
                    || !wanted.has(
                        normalise(
                            heading.innerText
                        )
                    )
                ) {
                    continue;
                }

                let node = heading;

                for (
                    let depth = 0;
                    depth < 10 && node;
                    depth += 1,
                    node = node.parentElement
                ) {
                    const raw = String(
                        node.innerText || ""
                    );

                    if (
                        !raw
                        || raw.length > 14000
                    ) {
                        continue;
                    }

                    const lines = raw
                        .split(/\n+/)
                        .map(value =>
                            value.trim()
                                .replace(
                                    /\s+/g,
                                    " "
                                )
                        )
                        .filter(Boolean);

                    const thresholdCount =
                        lines.filter(value =>
                            thresholdRe.test(value)
                        ).length;
                    const oddsCount =
                        lines.filter(value =>
                            oddsRe.test(value)
                        ).length;
                    const headingPresent =
                        lines.some(value =>
                            wanted.has(
                                normalise(value)
                            )
                        );

                    if (
                        headingPresent
                        && thresholdCount > 0
                        && oddsCount > 0
                    ) {
                        candidates.push({
                            node,
                            thresholdCount,
                            oddsCount,
                            textLength:
                                raw.length,
                            depth,
                        });
                        break;
                    }
                }
            }

            if (!candidates.length) {
                return null;
            }

            candidates.sort(
                (left, right) => {
                    if (
                        left.textLength
                        !== right.textLength
                    ) {
                        return (
                            left.textLength
                            - right.textLength
                        );
                    }

                    return (
                        right.thresholdCount
                        - left.thresholdCount
                    );
                }
            );

            const best = candidates[0];

            best.node.setAttribute(
                "data-bv-stats-scope",
                "1"
            );

            return {
                thresholds:
                    best.thresholdCount,
                odds: best.oddsCount,
                text_length:
                    best.textLength,
                tag: best.node.tagName,
            };
        }""",
        labels,
    )


def extract_scoped_rows(
    page,
) -> list[dict[str, Any]]:
    """
    Pair each threshold with the odds displayed on the same visual row.

    BetVictor renders threshold labels and prices in sibling grid columns, so
    they do not always share a small row ancestor. Ancestor text extraction can
    therefore pair every threshold with the first price in the market. This
    method uses element geometry instead.
    """
    return page.evaluate(
        r"""() => {
            const root =
                document.querySelector(
                    "[data-bv-stats-scope='1']"
                );

            if (!root) {
                return [];
            }

            const thresholdRe =
                /^(\d+)\+$/;
            const oddsRe =
                /^(?:\d+\/\d+|EVS|EVENS|EVEN)$/i;

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

            const exactText = element =>
                String(element.innerText || "")
                    .trim()
                    .replace(/\s+/g, " ");

            const candidates = [];

            for (
                const element
                of root.querySelectorAll("*")
            ) {
                if (!visible(element)) {
                    continue;
                }

                const text = exactText(element);

                if (
                    !thresholdRe.test(text)
                    && !oddsRe.test(text)
                ) {
                    continue;
                }

                const rect =
                    element.getBoundingClientRect();

                candidates.push({
                    element,
                    text,
                    type:
                        thresholdRe.test(text)
                        ? "threshold"
                        : "odds",
                    left: rect.left,
                    right: rect.right,
                    top: rect.top,
                    bottom: rect.bottom,
                    width: rect.width,
                    height: rect.height,
                    centerX:
                        rect.left
                        + rect.width / 2,
                    centerY:
                        rect.top
                        + rect.height / 2,
                    area:
                        rect.width
                        * rect.height,
                });
            }

            /*
             * Nested span/button elements can expose the same exact text and
             * rectangle. Keep the smallest-area representative for each visual
             * text box.
             */
            const dedupedMap = new Map();

            for (const item of candidates) {
                const key = [
                    item.type,
                    item.text.toLowerCase(),
                    Math.round(item.left),
                    Math.round(item.top),
                    Math.round(item.width),
                    Math.round(item.height),
                ].join("|");

                const existing =
                    dedupedMap.get(key);

                if (
                    !existing
                    || item.area < existing.area
                ) {
                    dedupedMap.set(
                        key,
                        item
                    );
                }
            }

            const deduped =
                Array.from(
                    dedupedMap.values()
                );
            const thresholds =
                deduped.filter(
                    item =>
                        item.type
                        === "threshold"
                );
            const odds =
                deduped.filter(
                    item =>
                        item.type === "odds"
                );

            thresholds.sort(
                (left, right) =>
                    left.centerY
                    - right.centerY
                    || left.centerX
                    - right.centerX
            );
            odds.sort(
                (left, right) =>
                    left.centerY
                    - right.centerY
                    || left.centerX
                    - right.centerX
            );

            const output = [];
            const usedOdds = new Set();

            for (
                const threshold
                of thresholds
            ) {
                let best = null;

                for (
                    let index = 0;
                    index < odds.length;
                    index += 1
                ) {
                    if (
                        usedOdds.has(index)
                    ) {
                        continue;
                    }

                    const price = odds[index];
                    const verticalDistance =
                        Math.abs(
                            threshold.centerY
                            - price.centerY
                        );
                    const rowTolerance =
                        Math.max(
                            20,
                            Math.min(
                                48,
                                Math.max(
                                    threshold.height,
                                    price.height
                                ) * 1.25
                            )
                        );

                    if (
                        verticalDistance
                        > rowTolerance
                    ) {
                        continue;
                    }

                    /*
                     * Prices normally sit to the right. Allow a small overlap
                     * for responsive layouts, but reject clearly left-hand
                     * prices from unrelated rows.
                     */
                    if (
                        price.centerX
                        < threshold.centerX - 20
                    ) {
                        continue;
                    }

                    const horizontalDistance =
                        Math.max(
                            0,
                            price.centerX
                            - threshold.centerX
                        );
                    const score =
                        verticalDistance * 10000
                        + horizontalDistance;

                    if (
                        !best
                        || score < best.score
                    ) {
                        best = {
                            index,
                            price,
                            score,
                            verticalDistance,
                            horizontalDistance,
                        };
                    }
                }

                if (!best) {
                    continue;
                }

                usedOdds.add(best.index);

                output.push({
                    threshold:
                        threshold.text,
                    odds:
                        best.price.text,
                    pairing_method:
                        "same_visual_row",
                    vertical_distance_px:
                        Math.round(
                            best.verticalDistance
                        ),
                    horizontal_distance_px:
                        Math.round(
                            best.horizontalDistance
                        ),
                    threshold_box: {
                        left:
                            Math.round(
                                threshold.left
                            ),
                        top:
                            Math.round(
                                threshold.top
                            ),
                        width:
                            Math.round(
                                threshold.width
                            ),
                        height:
                            Math.round(
                                threshold.height
                            ),
                    },
                    odds_box: {
                        left:
                            Math.round(
                                best.price.left
                            ),
                        top:
                            Math.round(
                                best.price.top
                            ),
                        width:
                            Math.round(
                                best.price.width
                            ),
                        height:
                            Math.round(
                                best.price.height
                            ),
                    },
                });
            }

            return output;
        }"""
    )

def add_rows(
    store: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    for row in rows:
        threshold = clean(
            row.get("threshold")
        )
        odds = clean(
            row.get("odds")
        ).upper()

        if (
            THRESHOLD_RE.fullmatch(
                threshold
            )
            and ODDS_RE.fullmatch(odds)
        ):
            key = (
                f"{threshold}|{odds}"
            )
            store[key] = {
                "threshold": threshold,
                "odds": odds,
                "pairing_method":
                    clean(
                        row.get(
                            "pairing_method"
                        )
                    ),
                "vertical_distance_px":
                    row.get(
                        "vertical_distance_px"
                    ),
                "horizontal_distance_px":
                    row.get(
                        "horizontal_distance_px"
                    ),
                "threshold_box":
                    row.get("threshold_box"),
                "odds_box":
                    row.get("odds_box"),
            }


def wait_for_scope(
    page,
    labels: list[str],
) -> bool:
    deadline = (
        time.perf_counter()
        + ROWS_READY_TIMEOUT_MS / 1000
    )

    while time.perf_counter() < deadline:
        if mark_market_scope(
            page,
            labels,
        ):
            return True

        page.wait_for_timeout(150)

    return bool(
        mark_market_scope(
            page,
            labels,
        )
    )


def click_market_heading(
    page,
    labels: list[str],
) -> tuple[
    str | None,
    dict[str, Any],
]:
    item, matched = scan_for_heading(
        page,
        labels,
    )

    if item is None:
        return None, {
            "error": "heading_not_found",
        }

    clicked, preparation = safe_exact_click(
        page,
        item,
        matched,
        HEADING_CLICK_WAIT_MS,
    )

    if clicked and wait_for_scope(
        page,
        labels,
    ):
        return matched, {
            "clicked": True,
            "preparation":
                preparation,
        }

    # Safe second click on the exact heading only.
    clicked_second, preparation_second = (
        safe_exact_click(
            page,
            item,
            matched,
            HEADING_CLICK_WAIT_MS,
        )
    )

    return (
        matched
        if (
            clicked_second
            and wait_for_scope(
                page,
                labels,
            )
        )
        else None,
        {
            "clicked": clicked,
            "clicked_second":
                clicked_second,
            "preparation":
                preparation,
            "preparation_second":
                preparation_second,
        },
    )


def mark_nearest_show_more(
    page,
    labels: list[str],
) -> dict[str, Any]:
    return page.evaluate(
        r"""(labels) => {
            document
                .querySelectorAll(
                    "[data-bv-stats-show-more]"
                )
                .forEach(element =>
                    element.removeAttribute(
                        "data-bv-stats-show-more"
                    )
                );

            const normalise = value =>
                String(value || "")
                    .trim()
                    .replace(/\s+/g, " ")
                    .toLowerCase();
            const wanted = new Set(
                labels.map(normalise)
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
                );
            };
            const y = element =>
                window.scrollY
                + element
                    .getBoundingClientRect()
                    .top;

            const headings = Array.from(
                document.querySelectorAll(
                    "h1,h2,h3,h4,h5,"
                    + "button,[role='button'],"
                    + "div,span,p"
                )
            ).filter(element =>
                visible(element)
                && wanted.has(
                    normalise(
                        element.innerText
                    )
                )
            );

            const thresholds = Array.from(
                document.querySelectorAll("*")
            )
                .filter(element => {
                    if (!visible(element)) {
                        return false;
                    }

                    return /^\d+\+$/.test(
                        String(
                            element.innerText
                            || ""
                        )
                            .trim()
                            .replace(
                                /\s+/g,
                                " "
                            )
                    );
                })
                .map(element => ({
                    element,
                    y: y(element),
                }));

            const controls = [];
            const seen = new Set();

            for (
                const element
                of document.querySelectorAll(
                    "button,[role='button'],"
                    + "a,div,span"
                )
            ) {
                if (
                    !visible(element)
                    || !/^show more$/i.test(
                        normalise(
                            element.innerText
                        )
                    )
                ) {
                    continue;
                }

                const target =
                    element.closest(
                        "button,[role='button'],a"
                    )
                    || element;

                if (
                    visible(target)
                    && !seen.has(target)
                ) {
                    seen.add(target);
                    controls.push(target);
                }
            }

            const candidates = [];

            for (const heading of headings) {
                const headingRect =
                    heading
                        .getBoundingClientRect();
                const headingBottom =
                    window.scrollY
                    + headingRect.bottom;

                for (
                    const control
                    of controls
                ) {
                    const controlTop =
                        y(control);
                    const distance =
                        controlTop
                        - headingBottom;

                    if (
                        distance < 15
                        || distance > 1500
                    ) {
                        continue;
                    }

                    const rowsBetween =
                        thresholds.filter(row =>
                            row.y
                                > headingBottom
                            && row.y
                                < controlTop + 5
                        ).length;

                    if (!rowsBetween) {
                        continue;
                    }

                    candidates.push({
                        control,
                        distance,
                        rowsBetween,
                    });
                }
            }

            if (!candidates.length) {
                return {
                    found: false,
                    visible_show_more:
                        controls.length,
                };
            }

            candidates.sort(
                (left, right) =>
                    left.distance
                    - right.distance
            );

            const best = candidates[0];

            best.control.setAttribute(
                "data-bv-stats-show-more",
                "1"
            );

            return {
                found: true,
                distance_px:
                    Math.round(
                        best.distance
                    ),
                rows_between:
                    best.rowsBetween,
            };
        }""",
        labels,
    )


def click_scoped_show_more(
    page,
    labels: list[str],
    store: dict[str, dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    metadata = mark_nearest_show_more(
        page,
        labels,
    )

    if not metadata.get("found"):
        return 0, metadata

    locator = page.locator(
        "[data-bv-stats-show-more='1']"
    )

    if not locator.count():
        return 0, {
            **metadata,
            "error":
                "marked_button_missing",
        }

    control = locator.first
    clicked, preparation = safe_exact_click(
        page,
        control,
        "Show More",
        SHOW_MORE_WAIT_MS,
    )

    if not clicked:
        return 0, {
            **metadata,
            "preparation":
                preparation,
            "error": "click_failed",
        }

    mark_market_scope(
        page,
        labels,
    )
    add_rows(
        store,
        extract_scoped_rows(page),
    )

    return 1, {
        **metadata,
        "preparation": preparation,
    }


def harvest_scoped_range(
    page,
    labels: list[str],
    store: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    scope = mark_market_scope(
        page,
        labels,
    )

    if scope is None:
        return {
            "used": False,
            "steps": 0,
        }

    bounds = page.evaluate(
        r"""() => {
            const root =
                document.querySelector(
                    "[data-bv-stats-scope='1']"
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
                        - 100
                    )
                ),
                bottom: Math.ceil(
                    window.scrollY
                    + rect.bottom
                    + 100
                ),
            };
        }"""
    )

    if not bounds:
        return {
            "used": False,
            "steps": 0,
        }

    before = len(store)
    position = int(bounds["top"])
    bottom = int(bounds["bottom"])
    steps = 0

    while (
        position <= bottom
        and steps
            < MAX_MARKET_SCROLL_STEPS
    ):
        page.evaluate(
            "(value) => "
            "window.scrollTo(0, value)",
            position,
        )
        page.wait_for_timeout(
            MARKET_SCROLL_WAIT_MS
        )
        mark_market_scope(
            page,
            labels,
        )
        add_rows(
            store,
            extract_scoped_rows(page),
        )
        position += MARKET_SCROLL_STEP
        steps += 1

    return {
        "used": True,
        "steps": steps,
        "rows_before": before,
        "rows_after": len(store),
    }


def decimal_odds(
    value: str,
) -> float | None:
    text = clean(value).upper()

    if text in {
        "EVS",
        "EVENS",
        "EVEN",
    }:
        return 2.0

    try:
        return 1.0 + float(
            Fraction(text)
        )
    except Exception:
        return None


def parse_market_rows(
    store: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
]:
    grouped: dict[
        int,
        set[str],
    ] = {}

    for row in store.values():
        match = THRESHOLD_RE.fullmatch(
            clean(row.get("threshold"))
        )

        if not match:
            continue

        threshold_number = int(
            match.group(1)
        )
        odds = clean(
            row.get("odds")
        ).upper()

        grouped.setdefault(
            threshold_number,
            set(),
        ).add(odds)

    selections = []
    conflicts = []

    for threshold in sorted(grouped):
        prices = sorted(
            grouped[threshold]
        )

        if len(prices) != 1:
            conflicts.append(
                {
                    "threshold":
                        f"{threshold}+",
                    "odds": prices,
                }
            )
            continue

        odds = prices[0]
        threshold_label = (
            f"{threshold}+"
        )
        selection_name = (
            f"{config['market']} "
            f"{threshold_label}"
        )

        item = {
            "selection":
                selection_name,
            "normalized_selection":
                normalize(selection_name),
            "odds": odds,
            "threshold":
                threshold_label,
            "stat": config["stat"],
        }

        if config.get("team"):
            item["team"] = config["team"]

        selections.append(item)

    odds_order_violations = []

    for previous, current in zip(
        selections,
        selections[1:],
    ):
        previous_decimal = decimal_odds(
            previous["odds"]
        )
        current_decimal = decimal_odds(
            current["odds"]
        )

        if (
            previous_decimal is not None
            and current_decimal is not None
            and current_decimal
                < previous_decimal
        ):
            odds_order_violations.append(
                {
                    "lower_threshold":
                        previous[
                            "threshold"
                        ],
                    "lower_odds":
                        previous["odds"],
                    "higher_threshold":
                        current[
                            "threshold"
                        ],
                    "higher_odds":
                        current["odds"],
                }
            )

    thresholds = [
        int(
            item["threshold"].rstrip("+")
        )
        for item in selections
    ]
    ladder_gaps = []

    if thresholds:
        ladder_gaps = sorted(
            set(
                range(
                    min(thresholds),
                    max(thresholds) + 1,
                )
            )
            - set(thresholds)
        )

    unique_prices = sorted(
        {
            item["odds"]
            for item in selections
        }
    )
    equal_adjacent_price_count = sum(
        1
        for previous, current in zip(
            selections,
            selections[1:],
        )
        if previous["odds"]
            == current["odds"]
    )
    all_prices_identical = (
        len(selections) > 1
        and len(unique_prices) == 1
    )

    audit = {
        "raw_row_count": len(store),
        "unique_threshold_count":
            len(grouped),
        "selection_count":
            len(selections),
        "thresholds": [
            item["threshold"]
            for item in selections
        ],
        "conflict_count":
            len(conflicts),
        "conflicts": conflicts,
        "odds_order_violation_count":
            len(odds_order_violations),
        "odds_order_violations":
            odds_order_violations,
        "ladder_gap_count":
            len(ladder_gaps),
        "ladder_gaps": [
            f"{value}+"
            for value in ladder_gaps
        ],
        "unique_price_count":
            len(unique_prices),
        "unique_prices":
            unique_prices,
        "equal_adjacent_price_count":
            equal_adjacent_price_count,
        "all_prices_identical":
            all_prices_identical,
        "suspicious_identical_prices":
            all_prices_identical,
    }

    return selections, audit


def close_market_heading(
    page,
    labels: list[str],
) -> None:
    item, matched = visible_exact_text(
        page,
        labels,
    )

    if item is None:
        return

    try:
        safe_exact_click(
            page,
            item,
            matched,
            180,
        )
    except Exception:
        pass


def scrape_market(
    page,
    fixture: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    debug_dir = (
        DEBUG_ROOT
        / slugify(fixture["match"])
        / config["key"]
    )
    debug_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    heading, click_audit = (
        click_market_heading(
            page,
            config["headings"],
        )
    )

    store: dict[
        str,
        dict[str, Any],
    ] = {}

    scope = mark_market_scope(
        page,
        config["headings"],
    )
    add_rows(
        store,
        extract_scoped_rows(page),
    )

    show_more_clicked, show_more_audit = (
        click_scoped_show_more(
            page,
            config["headings"],
            store,
        )
    )
    scroll_audit = harvest_scoped_range(
        page,
        config["headings"],
        store,
    )

    mark_market_scope(
        page,
        config["headings"],
    )
    add_rows(
        store,
        extract_scoped_rows(page),
    )

    selections, selection_audit = (
        parse_market_rows(
            store,
            config,
        )
    )

    result = {
        "market": config["market"],
        "normalized_market":
            config["key"],
        "heading_clicked": heading,
        "show_more_clicked":
            show_more_clicked,
        "scope": scope,
        "click_audit": click_audit,
        "show_more_audit":
            show_more_audit,
        "scroll_audit": scroll_audit,
        "selection_audit":
            selection_audit,
        "selection_count":
            len(selections),
        "elapsed_seconds": round(
            time.perf_counter()
            - started,
            2,
        ),
        "selections": selections,
    }

    (debug_dir / "raw_rows.json").write_text(
        json.dumps(
            list(store.values()),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (
        debug_dir
        / "market_audit.json"
    ).write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        f"    heading={heading} "
        f"show_more={show_more_clicked} "
        f"selections="
        f"{len(selections)} "
        f"conflicts="
        f"{selection_audit['conflict_count']} "
        f"odds_order_errors="
        f"{selection_audit['odds_order_violation_count']} "
        f"identical="
        f"{selection_audit['all_prices_identical']} "
        f"unique_prices="
        f"{selection_audit['unique_price_count']} "
        f"gaps="
        f"{selection_audit['ladder_gap_count']} "
        f"time="
        f"{result['elapsed_seconds']:.1f}s"
    )

    close_market_heading(
        page,
        config["headings"],
    )

    return result


def scrape_fixture(
    browser,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    fixture_started = time.perf_counter()
    context = browser.new_context(
        viewport={
            "width": 1700,
            "height": 1000,
        },
        permissions=[],
    )
    page = context.new_page()
    page.add_init_script(
        r"""() => {
            const mute = () => {
                document
                    .querySelectorAll(
                        "audio,video"
                    )
                    .forEach(element => {
                        element.muted = true;
                        element.volume = 0;
                    });
            };
            document.addEventListener(
                "DOMContentLoaded",
                mute,
                {once: false}
            );
        }"""
    )

    url = group_url(
        fixture["source_url"]
    )
    markets = []
    tab_audit = {}

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=70000,
        )
        page.wait_for_timeout(
            INITIAL_SETTLE_MS
        )
        accept_cookies(page)
        overlay_actions = (
            dismiss_obvious_overlays(page)
        )
        ready = wait_for_event_page(
            page,
            fixture,
        )

        print(
            f"  Event page ready: {ready}"
        )

        if overlay_actions:
            print(
                "  Overlay dismiss: "
                + ", ".join(
                    overlay_actions
                )
            )

        tab_ok, tab_audit = (
            click_match_stats_tab(page)
        )

        if not tab_ok:
            print(
                "  First Match Stats attempt failed; "
                "reloading direct group URL once..."
            )
            save_navigation_failure(
                page,
                fixture,
                "attempt_1",
            )

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=70000,
            )
            page.wait_for_timeout(4500)
            accept_cookies(page)
            dismiss_obvious_overlays(page)
            ready = (
                wait_for_event_page(
                    page,
                    fixture,
                )
                or ready
            )
            tab_ok, second_tab_audit = (
                click_match_stats_tab(page)
            )
            tab_audit = {
                "first": tab_audit,
                "second":
                    second_tab_audit,
            }

        print(
            f"  Match Stats active: "
            f"{tab_ok}"
        )

        if not tab_ok:
            save_navigation_failure(
                page,
                fixture,
                "attempt_2",
            )
            return {
                "match": fixture["match"],
                "home_team":
                    fixture["home"],
                "away_team":
                    fixture["away"],
                "source_url":
                    fixture["source_url"],
                "kickoff":
                    fixture["kickoff"],
                "market_count": 0,
                "markets": [],
                "event_page_ready":
                    ready,
                "match_stats_active":
                    False,
                "tab_audit": tab_audit,
                "elapsed_seconds": round(
                    time.perf_counter()
                    - fixture_started,
                    2,
                ),
                "error":
                    "match_stats_tab_not_active",
            }

        for config in market_configs(
            fixture
        ):
            print(
                f"  {config['market']}..."
            )
            market = scrape_market(
                page,
                fixture,
                config,
            )

            if market[
                "selection_count"
            ]:
                markets.append(market)

        return {
            "match": fixture["match"],
            "home_team":
                fixture["home"],
            "away_team":
                fixture["away"],
            "source_url":
                fixture["source_url"],
            "kickoff":
                fixture["kickoff"],
            "market_count": len(markets),
            "markets": markets,
            "event_page_ready": ready,
            "match_stats_active": True,
            "tab_audit": tab_audit,
            "elapsed_seconds": round(
                time.perf_counter()
                - fixture_started,
                2,
            ),
        }

    finally:
        context.close()


def main() -> None:
    total_started = time.perf_counter()
    OUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    DEBUG_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        fixtures,
        removed_started,
        removed_unknown,
        source_generated_at,
    ) = load_upcoming_fixtures()

    now_local = datetime.now(
        LOCAL_TIMEZONE
    )
    cutoff_local = (
        now_local
        + timedelta(
            minutes=UPCOMING_BUFFER_MINUTES
        )
    )

    print(
        "BETVICTOR BET BUILDER MATCH STATS "
        "— PROD15 FAST"
    )
    print("=" * 76)
    print(f"MAX_MATCHES = {MAX_MATCHES}")
    print(
        "Current Irish time:              "
        f"{now_local:%d %b %Y %H:%M:%S %Z}"
    )
    print(
        "Kickoff safety cutoff:           "
        f"{cutoff_local:%d %b %Y %H:%M:%S %Z}"
    )
    print(
        "Started/in-play fixtures removed: "
        f"{len(removed_started)}"
    )
    print(
        "Unknown-kickoff fixtures removed: "
        f"{len(removed_unknown)}"
    )
    print(
        "Upcoming fixtures to scan:        "
        f"{len(fixtures)}"
    )

    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS,
            args=["--mute-audio"],
        )

        for index, fixture in enumerate(
            fixtures,
            start=1,
        ):
            print(
                f"\n[{index}/{len(fixtures)}] "
                f"{fixture['match']}"
            )
            results.append(
                scrape_fixture(
                    browser,
                    fixture,
                )
            )

        browser.close()

    output = {
        "sport": "football",
        "competition":
            "FIFA World Cup",
        "bookmaker": "BetVictor",
        "market_type":
            "bet_builder_match_stats",
        "test_mode": False,
        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "source_props_generated_at":
            source_generated_at,
        "max_matches": MAX_MATCHES,
        "match_count": len(results),
        "matches_with_all_six_markets": len(
            [
                row
                for row in results
                if row.get(
                    "market_count"
                ) == 6
            ]
        ),
        "elapsed_seconds": round(
            time.perf_counter()
            - total_started,
            2,
        ),
        "matches": results,
    }

    temp_path = OUT_PATH.with_suffix(
        OUT_PATH.suffix + ".tmp"
    )
    temp_path.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temp_path.replace(OUT_PATH)

    print("\n" + "=" * 76)
    print(
        f"Saved production output: "
        f"{OUT_PATH}"
    )
    print(
        "Matches with all six markets: "
        f"{output['matches_with_all_six_markets']}/"
        f"{output['match_count']}"
    )
    print(
        f"Total elapsed: "
        f"{output['elapsed_seconds']:.1f}s"
    )
    print(
        "Main BetVictor props JSON "
        "modified directly: NO"
    )


if __name__ == "__main__":
    main()
