#!/usr/bin/env python3
"""
fetch_bwin_worldcup_match_stats.py

Standalone Bwin World Cup match/team shots scraper.

This script is deliberately separate from fetch_bwin_worldcup_props.py so the
working ordinary/player-props scraper is not modified.

Targets:
    - Match Total Shots
    - Home Team Total Shots
    - Away Team Total Shots
    - Match Total Shots on Target
    - Home Team Total Shots on Target
    - Away Team Total Shots on Target

Test settings:
    MAX_MATCHES = 3
    HEADLESS = False

Input:
    football/data/bwin_worldcup_moneylines.json

Output:
    football/data/bwin_worldcup_match_stats.json

Debug:
    football/debug/bwin_worldcup_match_stats/<match>_cards.json
    football/debug/bwin_worldcup_match_stats/<match>.txt
    football/debug/bwin_worldcup_match_stats/<match>.png
"""

from __future__ import annotations

# BWIN_MATCH_STATS_PROD15_AUDIT

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MONEYLINES_PATH = (
    ROOT / "football" / "data" / "bwin_worldcup_moneylines.json"
)
OUT_PATH = (
    ROOT / "football" / "data" / "bwin_worldcup_match_stats.json"
)
AUDIT_PATH = (
    ROOT / "football" / "data" / "bwin_worldcup_match_stats_audit.json"
)
DEBUG_DIR = (
    ROOT / "football" / "debug" / "bwin_worldcup_match_stats"
)

MAX_MATCHES = 15
HEADLESS = False
# Do not start scraping a fixture that is likely to move in-play before the
# three-match test completes.
KICKOFF_BUFFER_MINUTES = 60

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

ODDS_RE = re.compile(r"^\d{1,3}[.,]\d{1,3}$")
NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?$")


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalise(value: object) -> str:
    value = clean(value).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def slugify(value: object) -> str:
    value = clean(value).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def fix_url(value: object) -> str:
    url = clean(value)

    if url.startswith("https:/") and not url.startswith("https://"):
        url = "https://" + url[len("https:/"):].lstrip("/")

    if url.startswith("http:/") and not url.startswith("http://"):
        url = "http://" + url[len("http:/"):].lstrip("/")

    return url


def decimal_to_fractional(value: object) -> str:
    text = clean(value).replace(",", ".")

    try:
        decimal = float(text)
    except ValueError:
        return ""

    if decimal <= 1:
        return ""

    fraction = Fraction(decimal - 1).limit_denominator(100)

    if fraction.numerator == fraction.denominator:
        return "EVS"

    return f"{fraction.numerator}/{fraction.denominator}"


def is_decimal_odds(value: object) -> bool:
    text = clean(value).replace(",", ".")

    if not re.fullmatch(r"\d{1,3}\.\d{1,3}", text):
        return False

    try:
        decimal = float(text)
    except ValueError:
        return False

    return 1.001 <= decimal <= 1000


def parse_local_kickoff(match: dict) -> datetime | None:
    now = datetime.now().astimezone()
    date_label = clean(match.get("date_label"))
    time_label = clean(match.get("time"))
    combined = clean(f"{date_label} {time_label}")

    time_match = re.search(
        r"\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b",
        combined,
        re.I,
    )
    if not time_match:
        return None

    try:
        clock = datetime.strptime(
            clean(time_match.group(1)).upper(),
            "%I:%M %p",
        ).time()
    except ValueError:
        return None

    lowered = combined.lower()

    if "today" in lowered:
        event_date = now.date()
    elif "tomorrow" in lowered:
        event_date = (now + timedelta(days=1)).date()
    else:
        date_match = re.search(
            r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b",
            combined,
        )
        if not date_match:
            return None

        event_date = None

        for date_format in ("%m/%d/%y", "%m/%d/%Y"):
            try:
                event_date = datetime.strptime(
                    date_match.group(1),
                    date_format,
                ).date()
                break
            except ValueError:
                continue

        if event_date is None:
            return None

    return datetime.combine(
        event_date,
        clock,
        tzinfo=now.tzinfo,
    )


def is_safe_upcoming_match(match: dict) -> bool:
    kickoff = parse_local_kickoff(match)

    # Keep the match when Bwin's labels cannot be parsed. A second page-level
    # in-play check is performed after the event is opened.
    if kickoff is None:
        return True

    now = datetime.now().astimezone()
    return kickoff > now + timedelta(
        minutes=KICKOFF_BUFFER_MINUTES
    )


def load_matches() -> list[dict]:
    if not MONEYLINES_PATH.exists():
        raise RuntimeError(
            f"Bwin moneyline file not found: {MONEYLINES_PATH}"
        )

    payload = json.loads(
        MONEYLINES_PATH.read_text(encoding="utf-8")
    )
    rows = payload.get("matches") or []

    matches = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        home = clean(row.get("home_team"))
        away = clean(row.get("away_team"))
        url = fix_url(row.get("source_url"))

        if not home or not away or "/sports/events/" not in url:
            continue

        match = {
            "match": clean(row.get("match")) or f"{home} v {away}",
            "home_team": home,
            "away_team": away,
            "date_label": clean(row.get("date_label")),
            "time": clean(row.get("time")),
            "url": url,
        }

        if not is_safe_upcoming_match(match):
            print(
                "Skipping live/near-kickoff fixture: "
                f"{match['match']}"
            )
            continue

        matches.append(match)

        if MAX_MATCHES and len(matches) >= MAX_MATCHES:
            break

    return matches


def block_heavy_resources(route) -> None:
    if route.request.resource_type in {
        "image",
        "media",
        "font",
    }:
        route.abort()
    else:
        route.continue_()


def dismiss_cookies(page) -> None:
    labels = [
        "Allow All",
        "Accept All",
        "Accept all",
        "Accept",
        "I Accept",
        "Agree",
        "Allow all",
        "Continue",
        "Got it",
    ]

    for label in labels:
        exact = re.compile(
            rf"^{re.escape(label)}$",
            re.I,
        )

        locators = [
            page.get_by_role("button", name=exact),
            page.get_by_text(exact, exact=True),
        ]

        for locator in locators:
            try:
                count = min(locator.count(), 8)
            except Exception:
                continue

            for index in range(count):
                try:
                    item = locator.nth(index)

                    if not item.is_visible():
                        continue

                    item.click(
                        timeout=1800,
                        force=True,
                    )
                    page.wait_for_timeout(400)
                    return
                except Exception:
                    continue


def click_central_tab(page, label: str) -> bool:
    exact = re.compile(
        rf"^{re.escape(label)}$",
        re.I,
    )

    locators = [
        page.get_by_role("tab", name=exact),
        page.get_by_text(exact, exact=True),
    ]

    for locator in locators:
        try:
            count = min(locator.count(), 12)
        except Exception:
            continue

        for index in range(count):
            try:
                item = locator.nth(index)
                item.scroll_into_view_if_needed(timeout=2200)

                if not item.is_visible():
                    continue

                box = item.bounding_box(timeout=1200)
                if not box:
                    continue

                centre_x = (
                    float(box["x"])
                    + float(box["width"]) / 2
                )

                # Ignore labels in the left event coupon or right-hand panel.
                if not 250 <= centre_x <= 1380:
                    continue

                item.click(timeout=2200, force=True)
                page.wait_for_timeout(700)
                return True
            except Exception:
                continue

    return False



def shots_tab_content_visible(page) -> bool:
    """
    Verify that Bwin's Shots market page is mounted.

    Do not require an open odds grid; the six match/team stat headings can be
    collapsed and still prove that the correct tab loaded.
    """
    try:
        return bool(
            page.evaluate(
                r"""
                () => {
                    const clean = value =>
                        (value || "").replace(/\s+/g, " ").trim();

                    const norm = value =>
                        clean(value).toLowerCase()
                            .replace(/[^a-z0-9]+/g, " ").trim();

                    const patterns = [
                        /^total shots$/,
                        /^total shots on target$/,
                        / total shots$/,
                        / total shots on target$/,
                    ];

                    for (const element of document.querySelectorAll(
                        "div, span, button, [role='button']"
                    )) {
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);

                        if (
                            rect.width <= 0
                            || rect.height <= 0
                            || style.display === "none"
                            || style.visibility === "hidden"
                        ) {
                            continue;
                        }

                        const centreX =
                            rect.left + rect.width / 2;

                        if (centreX < 250 || centreX > 1380) {
                            continue;
                        }

                        const text = norm(element.innerText);

                        if (patterns.some(pattern => pattern.test(text))) {
                            return true;
                        }
                    }

                    return false;
                }
                """
            )
        )
    except Exception:
        return False


def click_shots_tab_javascript(page) -> bool:
    """
    Click Bwin's central event-page Shots tab through its actual clickable
    ancestor. This works when the text SPAN itself is not exposed as a tab.
    """
    try:
        result = page.evaluate(
            r"""
            () => {
                const clean = value =>
                    (value || "").replace(/\s+/g, " ").trim();

                const candidates = [];

                for (const leaf of document.querySelectorAll(
                    "a, button, div, span, [role='tab'], [role='button']"
                )) {
                    const rect = leaf.getBoundingClientRect();
                    const style = getComputedStyle(leaf);
                    const text = clean(leaf.innerText);

                    if (
                        text.toLowerCase() !== "shots"
                        || rect.width <= 0
                        || rect.height <= 0
                        || style.display === "none"
                        || style.visibility === "hidden"
                    ) {
                        continue;
                    }

                    let target = leaf.closest(
                        "a, button, [role='tab'], [role='button']"
                    ) || leaf;

                    // Bwin often uses a plain DIV tab. Climb only through
                    // compact ancestors and stop before reaching a full row.
                    let node = leaf;
                    for (
                        let depth = 0;
                        depth < 5 && node;
                        depth += 1, node = node.parentElement
                    ) {
                        const box = node.getBoundingClientRect();
                        const nodeStyle = getComputedStyle(node);
                        const role = (
                            node.getAttribute("role") || ""
                        ).toLowerCase();

                        if (
                            box.width >= 35
                            && box.width <= 150
                            && box.height >= 25
                            && box.height <= 75
                            && (
                                node.tagName === "A"
                                || node.tagName === "BUTTON"
                                || role === "tab"
                                || role === "button"
                                || nodeStyle.cursor === "pointer"
                                || /tab|nav|menu|item|active/i.test(
                                    String(node.className || "")
                                )
                            )
                        ) {
                            target = node;
                            break;
                        }
                    }

                    const targetRect =
                        target.getBoundingClientRect();
                    const centreX =
                        targetRect.left + targetRect.width / 2;

                    if (
                        centreX < 250
                        || centreX > 1380
                        || targetRect.height > 85
                    ) {
                        continue;
                    }

                    candidates.push({
                        target,
                        visible: (
                            targetRect.bottom > 0
                            && targetRect.top < innerHeight
                        ),
                        y: targetRect.top,
                        x: targetRect.left,
                        area: targetRect.width
                            * targetRect.height,
                    });
                }

                candidates.sort((a, b) => {
                    if (a.visible !== b.visible) {
                        return a.visible ? -1 : 1;
                    }
                    if (a.y !== b.y) {
                        return a.y - b.y;
                    }
                    return a.area - b.area;
                });

                const best = candidates[0];

                if (!best) {
                    return null;
                }

                best.target.scrollIntoView({
                    block: "center",
                    inline: "center",
                    behavior: "instant",
                });

                const box = best.target.getBoundingClientRect();
                best.target.setAttribute(
                    "data-btb-shots-tab",
                    "1"
                );

                return {
                    x: box.left + box.width / 2,
                    y: box.top + box.height / 2,
                };
            }
            """
        )
    except Exception:
        result = None

    if not result:
        return False

    try:
        page.mouse.move(
            float(result["x"]),
            float(result["y"]),
        )
        page.wait_for_timeout(80)
        page.mouse.click(
            float(result["x"]),
            float(result["y"]),
        )
        page.wait_for_timeout(850)

        if shots_tab_content_visible(page):
            return True
    except Exception:
        pass

    # Final fallback: dispatch the complete click sequence on the marked tab.
    try:
        page.locator(
            '[data-btb-shots-tab="1"]'
        ).first.evaluate(
            r"""
            element => {
                element.dispatchEvent(
                    new PointerEvent(
                        "pointerdown",
                        {
                            bubbles: true,
                            cancelable: true,
                            pointerId: 1,
                            pointerType: "mouse",
                            isPrimary: true,
                            button: 0,
                            buttons: 1,
                        }
                    )
                );
                element.dispatchEvent(
                    new MouseEvent(
                        "mousedown",
                        {
                            bubbles: true,
                            cancelable: true,
                            button: 0,
                            buttons: 1,
                        }
                    )
                );
                element.dispatchEvent(
                    new PointerEvent(
                        "pointerup",
                        {
                            bubbles: true,
                            cancelable: true,
                            pointerId: 1,
                            pointerType: "mouse",
                            isPrimary: true,
                            button: 0,
                            buttons: 0,
                        }
                    )
                );
                element.dispatchEvent(
                    new MouseEvent(
                        "mouseup",
                        {
                            bubbles: true,
                            cancelable: true,
                            button: 0,
                            buttons: 0,
                        }
                    )
                );
                element.dispatchEvent(
                    new MouseEvent(
                        "click",
                        {
                            bubbles: true,
                            cancelable: true,
                            button: 0,
                            buttons: 0,
                        }
                    )
                );
                element.click();
            }
            """
        )
        page.wait_for_timeout(850)
    except Exception:
        return False

    return shots_tab_content_visible(page)

def open_shots_tab(
    page,
    event_url: str,
    reload_on_failure: bool = True,
) -> bool:
    """
    Open and verify the Shots tab without performing a long in-page reload.
    The caller owns page retries so a failed event cannot poison the next one.
    """
    del event_url, reload_on_failure

    if shots_tab_content_visible(page):
        return True

    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(180)
    except Exception:
        pass

    for _attempt in range(3):
        dismiss_cookies(page)

        if click_central_tab(page, "Shots"):
            page.wait_for_timeout(450)
            if shots_tab_content_visible(page):
                return True

        if click_shots_tab_javascript(page):
            page.wait_for_timeout(450)
            if shots_tab_content_visible(page):
                return True

        page.wait_for_timeout(550)

    return False

def slug_label(value: str) -> str:
    acronyms = {
        "dr": "DR",
        "usa": "USA",
        "uae": "UAE",
        "uk": "UK",
    }

    words = []

    for word in clean(value).strip("-").split("-"):
        if not word:
            continue

        words.append(
            acronyms.get(word.lower(), word.title())
        )

    return " ".join(words)


def team_aliases_from_event(
    match: dict,
    side: str,
) -> list[str]:
    """
    Return bookmaker display-name aliases.

    Example:
        moneyline home_team = "Bosnia"
        event URL slug       = "bosnia-herzegovina-qatar"
        Bwin market heading = "Bosnia & Herzegovina - Total Shots"
    """
    home = clean(match["home_team"])
    away = clean(match["away_team"])
    event_url = clean(match["url"])

    aliases = {
        home if side == "home" else away,
    }

    try:
        event_slug = event_url.split(
            "/sports/events/",
            1,
        )[1].split("?", 1)[0]

        event_slug = re.sub(
            r"-2:\d+$",
            "",
            event_slug,
        ).strip("-")

        home_slug = slugify(home)
        away_slug = slugify(away)

        derived_home = ""
        derived_away = ""

        if (
            away_slug
            and event_slug.endswith("-" + away_slug)
        ):
            derived_home = event_slug[
                :-(len(away_slug) + 1)
            ]
            derived_away = away_slug
        elif (
            home_slug
            and event_slug.startswith(home_slug + "-")
        ):
            derived_home = home_slug
            derived_away = event_slug[
                len(home_slug) + 1:
            ]

        derived = (
            derived_home
            if side == "home"
            else derived_away
        )

        if derived:
            aliases.add(slug_label(derived))
    except Exception:
        pass

    # Also allow names that differ only by a conjunction.
    for alias in list(aliases):
        if " And " in alias:
            aliases.add(alias.replace(" And ", " & "))

    # The moneyline feed may abbreviate a team while the event URL contains
    # Bwin's full display name. Example:
    #   home_team = Bosnia
    #   URL slug  = bosnia-herzegovina-qatar
    #   heading   = Bosnia & Herzegovina - Total Shots
    base_name = home if side == "home" else away

    for alias in list(aliases):
        base_words = clean(base_name).split()
        alias_words = clean(alias).split()

        if (
            base_words
            and len(alias_words) > len(base_words)
            and [
                word.lower()
                for word in alias_words[:len(base_words)]
            ] == [
                word.lower()
                for word in base_words
            ]
        ):
            remainder = " ".join(
                alias_words[len(base_words):]
            )
            if remainder:
                aliases.add(
                    clean(base_name)
                    + " & "
                    + remainder
                )

    return sorted(
        {
            clean(alias)
            for alias in aliases
            if clean(alias)
        },
        key=lambda value: (
            -len(value),
            value.lower(),
        ),
    )

def page_event_looks_live(page, home: str, away: str) -> bool:
    """
    Detect an event that has moved in-play after loading.

    The left coupon can contain unrelated live fixtures, so inspect compact
    containers that contain both teams from the current event.
    """
    try:
        return bool(
            page.evaluate(
                r"""
                ({home, away}) => {
                    const clean = value =>
                        (value || "").replace(/\s+/g, " ").trim();

                    const norm = value =>
                        clean(value).toLowerCase()
                            .replace(/[^a-z0-9]+/g, " ").trim();

                    const h = norm(home);
                    const a = norm(away);
                    const liveClock = /\b(?:1H|2H|HT|ET)\b|\b\d{1,3}:\d{2}\b/i;

                    for (const node of document.querySelectorAll("body *")) {
                        const rect = node.getBoundingClientRect();

                        if (
                            rect.width < 300
                            || rect.width > 1300
                            || rect.height < 80
                            || rect.height > 420
                        ) {
                            continue;
                        }

                        const text = clean(node.innerText);
                        const key = norm(text);

                        if (
                            !key.includes(h)
                            || !key.includes(a)
                        ) {
                            continue;
                        }

                        if (
                            /\bstarting in\b/i.test(text)
                            || /\btomorrow\b/i.test(text)
                        ) {
                            continue;
                        }

                        if (
                            /\bin[- ]?play\b/i.test(text)
                            || liveClock.test(text)
                        ) {
                            return true;
                        }
                    }

                    return false;
                }
                """,
                {
                    "home": home,
                    "away": away,
                },
            )
        )
    except Exception:
        return False


def expand_show_more(page, max_clicks: int = 12) -> int:
    clicked = 0
    seen = set()

    for _ in range(max_clicks):
        try:
            candidates = page.evaluate(
                r"""
                () => {
                    const clean = value =>
                        (value || "").replace(/\s+/g, " ").trim();

                    const wanted = new Set([
                        "show more",
                        "view more",
                        "more markets",
                    ]);

                    const output = [];

                    for (const element of document.querySelectorAll(
                        "span, div, button, [role='button']"
                    )) {
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        const text = clean(element.innerText).toLowerCase();

                        if (
                            !wanted.has(text)
                            || rect.width <= 0
                            || rect.height <= 0
                            || rect.bottom <= 0
                            || rect.top >= innerHeight
                            || style.display === "none"
                            || style.visibility === "hidden"
                        ) {
                            continue;
                        }

                        const centreX =
                            rect.left + rect.width / 2;

                        if (centreX < 250 || centreX > 1380) {
                            continue;
                        }

                        output.push({
                            x: centreX,
                            y: rect.top + rect.height / 2,
                            key: [
                                Math.round(rect.left),
                                Math.round(rect.top),
                                Math.round(rect.width),
                                Math.round(rect.height),
                            ].join("|"),
                        });
                    }

                    return output;
                }
                """
            ) or []
        except Exception:
            candidates = []

        candidate = next(
            (
                item
                for item in candidates
                if item.get("key") not in seen
            ),
            None,
        )

        if candidate is None:
            break

        seen.add(candidate.get("key"))

        try:
            page.mouse.click(
                float(candidate["x"]),
                float(candidate["y"]),
            )
            page.wait_for_timeout(350)
            clicked += 1
        except Exception:
            continue

    return clicked


def build_targets(match: dict) -> list[dict]:
    home = match["home_team"]
    away = match["away_team"]

    home_names = team_aliases_from_event(
        match,
        "home",
    )
    away_names = team_aliases_from_event(
        match,
        "away",
    )

    def team_market_aliases(
        names: list[str],
        suffix: str,
    ) -> list[str]:
        aliases = []

        for name in names:
            aliases.extend(
                [
                    f"{name} - {suffix}",
                    f"{name} {suffix}",
                ]
            )

        return aliases

    return [
        {
            "market": "Match Total Shots",
            "normalized_market": "match_total_shots",
            "scope": "match",
            "team": "",
            "stat": "shots",
            "heading": "Total Shots",
            "aliases": [
                "Total Shots",
            ],
        },
        {
            "market": f"{home} Total Shots",
            "normalized_market": "team_total_shots",
            "scope": "home",
            "team": home,
            "stat": "shots",
            "heading": f"{home} - Total Shots",
            "aliases": team_market_aliases(
                home_names,
                "Total Shots",
            ),
        },
        {
            "market": f"{away} Total Shots",
            "normalized_market": "team_total_shots",
            "scope": "away",
            "team": away,
            "stat": "shots",
            "heading": f"{away} - Total Shots",
            "aliases": team_market_aliases(
                away_names,
                "Total Shots",
            ),
        },
        {
            "market": "Match Total Shots On Target",
            "normalized_market": "match_total_shots_on_target",
            "scope": "match",
            "team": "",
            "stat": "shots_on_target",
            "heading": "Total Shots on Target",
            "aliases": [
                "Total Shots on Target",
                "Total Shots On Target",
            ],
        },
        {
            "market": f"{home} Total Shots On Target",
            "normalized_market": "team_total_shots_on_target",
            "scope": "home",
            "team": home,
            "stat": "shots_on_target",
            "heading": f"{home} - Total Shots on Target",
            "aliases": team_market_aliases(
                home_names,
                "Total Shots on Target",
            ),
        },
        {
            "market": f"{away} Total Shots On Target",
            "normalized_market": "team_total_shots_on_target",
            "scope": "away",
            "team": away,
            "stat": "shots_on_target",
            "heading": f"{away} - Total Shots on Target",
            "aliases": team_market_aliases(
                away_names,
                "Total Shots on Target",
            ),
        },
    ]

def extract_open_card(page, aliases: list[str]) -> dict | None:
    try:
        return page.evaluate(
            r"""
            aliases => {
                const clean = value =>
                    (value || "").replace(/\s+/g, " ").trim();

                const norm = value =>
                    clean(value).toLowerCase()
                        .replace(/[^a-z0-9]+/g, " ").trim();

                const canonical = value =>
                    norm(value).replace(/\s+bb$/, "").trim();

                const wanted = new Set(
                    aliases.map(canonical)
                );

                const headingMatches = value => {
                    const key = canonical(value);

                    for (const target of wanted) {
                        if (key === target) {
                            return true;
                        }

                        // Accept compact Bwin card lines such as:
                        // "Switzerland - Total Shots BB Over Under"
                        // without allowing Total Shots to match
                        // Total Shots on Target.
                        for (const suffix of [
                            " bb",
                            " over",
                            " under",
                            " regular time",
                        ]) {
                            if (key.startsWith(target + suffix)) {
                                return true;
                            }
                        }
                    }

                    return false;
                };

                const oddRe = /^\d{1,3}[.,]\d{1,3}$/;

                const rendered = element => {
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);

                    return (
                        rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                    );
                };

                let best = null;

                for (const element of document.querySelectorAll(
                    "div, span, button, [role='button']"
                )) {
                    if (!rendered(element)) {
                        continue;
                    }

                    const direct = Array.from(element.childNodes)
                        .filter(node => node.nodeType === Node.TEXT_NODE)
                        .map(node => clean(node.textContent))
                        .filter(Boolean)
                        .join(" ");

                    const full = clean(element.innerText);

                    if (
                        !headingMatches(direct)
                        && !headingMatches(full)
                    ) {
                        continue;
                    }

                    let node = element;

                    for (
                        let depth = 0;
                        depth < 10 && node;
                        depth += 1, node = node.parentElement
                    ) {
                        const rect = node.getBoundingClientRect();
                        const raw = node.innerText || "";
                        const lines = raw
                            .split(/\n+/)
                            .map(clean)
                            .filter(Boolean);

                        if (
                            !lines.length
                            || rect.width < 250
                            || rect.width > 1100
                            || rect.height < 70
                            || rect.height > 5000
                            || raw.length > 20000
                        ) {
                            continue;
                        }

                        const headingIndex = lines.findIndex(
                            line => headingMatches(line)
                        );

                        if (headingIndex < 0 || headingIndex > 12) {
                            continue;
                        }

                        const odds = lines.filter(
                            line => oddRe.test(line)
                        );

                        if (odds.length < 2) {
                            continue;
                        }

                        const score = (
                            raw.length
                            + headingIndex * 500
                            + depth * 20
                        );

                        if (!best || score < best.score) {
                            best = {
                                node,
                                score,
                                heading: lines[headingIndex],
                                lines,
                            };
                        }
                    }
                }

                if (!best) {
                    return null;
                }

                const box = best.node.getBoundingClientRect();

                return {
                    heading: best.heading,
                    lines: best.lines,
                    card_top: Math.round(
                        box.top + window.scrollY
                    ),
                };
            }
            """,
            aliases,
        )
    except Exception:
        return None



def expand_target_market(
    page,
    aliases: list[str],
    max_clicks: int = 4,
) -> int:
    """
    Expand Show More only inside the requested market card.

    The old global expander could click unrelated cards and change the DOM
    before the target card was captured.
    """
    clicked = 0

    for _ in range(max_clicks):
        try:
            candidate = page.evaluate(
                r"""
                aliases => {
                    const clean = value =>
                        (value || "").replace(/\s+/g, " ").trim();

                    const norm = value =>
                        clean(value).toLowerCase()
                            .replace(/[^a-z0-9]+/g, " ").trim();

                    const canonical = value =>
                        norm(value).replace(/\s+bb$/, "").trim();

                    const wanted = new Set(
                        aliases.map(canonical)
                    );

                    const headingMatches = value => {
                        const key = canonical(value);

                        for (const target of wanted) {
                            if (key === target) {
                                return true;
                            }

                            for (const suffix of [
                                " bb",
                                " over",
                                " under",
                                " regular time",
                            ]) {
                                if (key.startsWith(target + suffix)) {
                                    return true;
                                }
                            }
                        }

                        return false;
                    };

                    const rendered = element => {
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);

                        return (
                            rect.width > 0
                            && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                        );
                    };

                    let bestCard = null;

                    for (const element of document.querySelectorAll(
                        "div, span, button, [role='button']"
                    )) {
                        if (!rendered(element)) {
                            continue;
                        }

                        const direct = Array.from(element.childNodes)
                            .filter(
                                node => node.nodeType === Node.TEXT_NODE
                            )
                            .map(node => clean(node.textContent))
                            .filter(Boolean)
                            .join(" ");

                        const full = clean(element.innerText);

                        if (
                            !headingMatches(direct)
                            && !headingMatches(full)
                        ) {
                            continue;
                        }

                        let node = element;

                        for (
                            let depth = 0;
                            depth < 10 && node;
                            depth += 1, node = node.parentElement
                        ) {
                            const rect = node.getBoundingClientRect();
                            const raw = node.innerText || "";
                            const lines = raw
                                .split(/\n+/)
                                .map(clean)
                                .filter(Boolean);

                            if (
                                !lines.length
                                || rect.width < 220
                                || rect.width > 1150
                                || rect.height < 40
                                || rect.height > 5000
                                || raw.length > 20000
                            ) {
                                continue;
                            }

                            const headingIndex = lines.findIndex(
                                line => headingMatches(line)
                            );

                            if (
                                headingIndex < 0
                                || headingIndex > 12
                            ) {
                                continue;
                            }

                            const controls = Array.from(
                                node.querySelectorAll(
                                    "span, div, button, [role='button']"
                                )
                            ).filter(control => {
                                if (!rendered(control)) {
                                    return false;
                                }

                                const text = clean(
                                    control.innerText
                                ).toLowerCase();

                                return (
                                    text === "show more"
                                    || text === "view more"
                                );
                            });

                            if (!controls.length) {
                                continue;
                            }

                            const score =
                                raw.length
                                + headingIndex * 500
                                + depth * 20;

                            if (
                                !bestCard
                                || score < bestCard.score
                            ) {
                                bestCard = {
                                    node,
                                    control: controls[0],
                                    score,
                                };
                            }
                        }
                    }

                    if (!bestCard) {
                        return null;
                    }

                    bestCard.control.scrollIntoView({
                        block: "center",
                        inline: "nearest",
                        behavior: "instant",
                    });

                    const rect =
                        bestCard.control.getBoundingClientRect();

                    return {
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                    };
                }
                """,
                aliases,
            )
        except Exception:
            candidate = None

        if not candidate:
            break

        try:
            page.mouse.click(
                float(candidate["x"]),
                float(candidate["y"]),
            )
            page.wait_for_timeout(350)
            clicked += 1
        except Exception:
            break

    return clicked

def click_market_row(page, aliases: list[str]) -> str:
    """
    Scroll the Bwin Shots tab until an exact collapsed row is mounted and click
    it once. This is based on the proven row-click logic from the props scraper,
    but is isolated in this standalone match-stats script.
    """
    try:
        page.evaluate(
            r"""
            () => {
                window.scrollTo(0, 0);

                for (const element of document.querySelectorAll("body *")) {
                    const style = getComputedStyle(element);

                    if (
                        /(auto|scroll)/.test(style.overflowY || "")
                        && element.scrollHeight
                            > element.clientHeight + 80
                    ) {
                        element.scrollTop = 0;
                    }
                }
            }
            """
        )
        page.wait_for_timeout(150)
    except Exception:
        pass

    target_id = (
        "btb-match-stat-"
        + str(int(time.time() * 1000))
    )

    for sweep in range(16):
        try:
            result = page.evaluate(
                r"""
                ({aliases, targetId}) => {
                    const clean = value =>
                        (value || "").replace(/\s+/g, " ").trim();

                    const norm = value =>
                        clean(value).toLowerCase()
                            .replace(/[^a-z0-9]+/g, " ").trim();

                    const canonical = value =>
                        norm(value).replace(/\s+bb$/, "").trim();

                    const wanted = new Set(
                        aliases.map(canonical)
                    );

                    const matchesWanted = value =>
                        wanted.has(canonical(value));

                    const rendered = element => {
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);

                        return (
                            rect.width > 0
                            && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                        );
                    };

                    const directText = element =>
                        Array.from(element.childNodes)
                            .filter(
                                node => node.nodeType === Node.TEXT_NODE
                            )
                            .map(node => clean(node.textContent))
                            .filter(Boolean)
                            .join(" ");

                    const rows = [];

                    for (const leaf of document.querySelectorAll(
                        "div, span, button, [role='button']"
                    )) {
                        if (!rendered(leaf)) {
                            continue;
                        }

                        const own = directText(leaf);
                        const full = clean(leaf.innerText);

                        if (
                            !matchesWanted(own)
                            && !matchesWanted(full)
                        ) {
                            continue;
                        }

                        let node = leaf;

                        for (
                            let depth = 0;
                            depth < 8 && node;
                            depth += 1, node = node.parentElement
                        ) {
                            if (!rendered(node)) {
                                continue;
                            }

                            const rect = node.getBoundingClientRect();
                            const lines = clean(node.innerText)
                                .split(/\n+/)
                                .map(clean)
                                .filter(Boolean);

                            if (
                                !lines.length
                                || !matchesWanted(lines[0])
                                || rect.width < 220
                                || rect.width > 1100
                                || rect.height < 28
                                || rect.height > 115
                            ) {
                                continue;
                            }

                            const centreX =
                                rect.left + rect.width / 2;

                            if (centreX < 250 || centreX > 1380) {
                                continue;
                            }

                            rows.push({
                                node,
                                heading: lines[0],
                                visible: (
                                    rect.bottom > 100
                                    && rect.top < innerHeight - 30
                                ),
                                area: rect.width * rect.height,
                                depth,
                            });

                            break;
                        }
                    }

                    rows.sort((a, b) => {
                        if (a.visible !== b.visible) {
                            return a.visible ? -1 : 1;
                        }

                        if (a.area !== b.area) {
                            return a.area - b.area;
                        }

                        return a.depth - b.depth;
                    });

                    const best = rows[0];

                    if (best) {
                        for (const old of document.querySelectorAll(
                            "[data-btb-match-stat]"
                        )) {
                            old.removeAttribute(
                                "data-btb-match-stat"
                            );
                        }

                        best.node.setAttribute(
                            "data-btb-match-stat",
                            targetId
                        );

                        best.node.scrollIntoView({
                            block: "center",
                            inline: "nearest",
                            behavior: "instant",
                        });

                        return {
                            found: true,
                            heading: best.heading,
                        };
                    }

                    let moved = false;

                    for (const element of document.querySelectorAll(
                        "body *"
                    )) {
                        const style = getComputedStyle(element);

                        if (
                            !/(auto|scroll)/.test(
                                style.overflowY || ""
                            )
                            || element.scrollHeight
                                <= element.clientHeight + 80
                        ) {
                            continue;
                        }

                        const before = element.scrollTop;

                        element.scrollTop = Math.min(
                            element.scrollHeight,
                            before + 520
                        );

                        if (element.scrollTop !== before) {
                            moved = true;
                        }
                    }

                    const beforeWindow = window.scrollY;

                    window.scrollTo(
                        0,
                        beforeWindow + 520
                    );

                    if (window.scrollY !== beforeWindow) {
                        moved = true;
                    }

                    return {
                        found: false,
                        moved,
                    };
                }
                """,
                {
                    "aliases": aliases,
                    "targetId": target_id,
                },
            )
        except Exception:
            result = None

        page.wait_for_timeout(160)

        if not result:
            continue

        if not result.get("found"):
            if not result.get("moved"):
                break
            continue

        row = page.locator(
            f'[data-btb-match-stat="{target_id}"]'
        ).first

        try:
            row.scroll_into_view_if_needed(timeout=1800)
            page.wait_for_timeout(120)
            row.click(timeout=1800, force=True)
            page.wait_for_timeout(650)
            return clean(result.get("heading"))
        except Exception:
            continue

    return ""


def restore_shots_tab(
    page,
    event_url: str,
) -> bool:
    """
    Return to the event Shots tab without a full page navigation.
    """
    del event_url

    try:
        return open_shots_tab(
            page,
            "",
            reload_on_failure=False,
        )
    except Exception:
        return False

def parse_over_under_card(
    card: dict,
    target: dict,
) -> dict | None:
    lines = [
        clean(line)
        for line in card.get("lines") or []
        if clean(line)
    ]
    lower = [line.lower() for line in lines]
    selections = []

    if "over" in lower and "under" in lower:
        start = max(
            lower.index("over"),
            lower.index("under"),
        ) + 1

        index = start

        while index + 2 < len(lines):
            raw_line = lines[index]
            over_odds = lines[index + 1]
            under_odds = lines[index + 2]

            if (
                NUMBER_RE.fullmatch(raw_line)
                and is_decimal_odds(over_odds)
                and is_decimal_odds(under_odds)
            ):
                line = raw_line.replace(",", ".")

                for side, odds in (
                    ("over", over_odds),
                    ("under", under_odds),
                ):
                    fractional = decimal_to_fractional(odds)

                    if not fractional:
                        continue

                    selections.append(
                        {
                            "selection": (
                                f"{side.title()} {line}"
                            ),
                            "normalized_selection": (
                                f"{side}_{line.replace('.', '_')}"
                            ),
                            "side": side,
                            "line": line,
                            "odds": fractional,
                            "decimal_odds": float(
                                odds.replace(",", ".")
                            ),
                            "scope": target["scope"],
                            "stat": target["stat"],
                            "team": target["team"],
                        }
                    )

                index += 3
                continue

            index += 1

    if not selections:
        return None

    return {
        "market": target["market"],
        "normalized_market": target["normalized_market"],
        "raw_heading": clean(card.get("heading")),
        "scope": target["scope"],
        "stat": target["stat"],
        "team": target["team"],
        "selection_count": len(selections),
        "selections": selections,
    }


def safe_open_event_page(
    context,
    match: dict,
):
    """
    Open one event on a fresh Playwright page.

    Waiting for domcontentloaded can hang indefinitely on Bwin background
    resources. Waiting only for the navigation commit, then checking the body,
    gives the app time to render without carrying a poisoned page into the next
    fixture.
    """
    last_error = ""

    for attempt in range(1, 3):
        page = context.new_page()

        try:
            page.goto(
                match["url"],
                wait_until="commit",
                timeout=35000,
            )
        except Exception as error:
            last_error = str(error)

            # A commit timeout can still leave the event document usable.
            if "/sports/events/" not in clean(page.url):
                page.close()
                continue

        try:
            page.wait_for_selector(
                "body",
                timeout=10000,
            )
            page.wait_for_timeout(5000)
            dismiss_cookies(page)

            body_text = page.locator("body").inner_text(
                timeout=8000,
            )

            has_fixture = (
                normalise(match["home_team"])
                in normalise(body_text)
                and normalise(match["away_team"])
                in normalise(body_text)
            )

            has_event_navigation = any(
                token in normalise(body_text)
                for token in (
                    "all main",
                    "goals players",
                    "players shots",
                    "shots price boosts",
                    "corners cards",
                )
            )

            if (
                len(body_text) >= 500
                and has_fixture
                and has_event_navigation
            ):
                return page
        except Exception as error:
            last_error = str(error)

        try:
            page.close()
        except Exception:
            pass

        print(
            f"  event load retry {attempt}/2 failed"
        )

    raise RuntimeError(
        "Event page did not become usable"
        + (
            f": {last_error}"
            if last_error
            else ""
        )
    )


def scrape_one(page, match: dict) -> dict:
    name = match["match"]
    home = match["home_team"]
    away = match["away_team"]
    event_url = match["url"]
    slug = slugify(name)

    print("")
    print(f"Opening {name}")
    print(event_url)

    if page_event_looks_live(page, home, away):
        raise RuntimeError(
            "Fixture is already in-play; skipped."
        )

    if not open_shots_tab(page, event_url):
        raise RuntimeError(
            "Shots tab could not be opened after retry."
        )

    initial_more = expand_show_more(page)
    print(
        f"Shots tab Show More controls: {initial_more}"
    )

    targets = build_targets(match)

    print(
        "Team aliases: "
        f"home={team_aliases_from_event(match, 'home')} | "
        f"away={team_aliases_from_event(match, 'away')}"
    )

    raw_cards = []
    markets = []

    for index, target in enumerate(targets, start=1):
        aliases = target["aliases"]
        card = extract_open_card(page, aliases)

        if card is None:
            clicked_heading = click_market_row(
                page,
                aliases,
            )

            if not clicked_heading:
                print(
                    f"  [{index}/6] {target['heading']}: "
                    "not found"
                )
                continue

            print(
                f"  [{index}/6] {target['heading']}: "
                f"clicked {clicked_heading}"
            )

            # Capture immediately. Some Bwin layouts are briefly valid after
            # the row opens but change when unrelated Show More controls click.
            page.wait_for_timeout(250)
            card = extract_open_card(page, aliases)

            local_expanded = expand_target_market(
                page,
                aliases,
                max_clicks=3,
            )

            if local_expanded:
                print(
                    f"      expanded {local_expanded} "
                    "target line control(s)"
                )
                page.wait_for_timeout(250)
                refreshed = extract_open_card(
                    page,
                    aliases,
                )
                if refreshed is not None:
                    card = refreshed

            # One small fallback for layouts where the card only mounts after
            # a general Show More click. Do not repeatedly expand the page.
            if card is None:
                fallback_expanded = expand_show_more(
                    page,
                    max_clicks=2,
                )

                if fallback_expanded:
                    print(
                        f"      expanded {fallback_expanded} "
                        "fallback control(s)"
                    )
                    page.wait_for_timeout(250)
                    card = extract_open_card(
                        page,
                        aliases,
                    )

        if card is None:
            print(
                f"  [{index}/6] {target['heading']}: "
                "opened but card could not be captured"
            )
        else:
            raw_cards.append(
                {
                    "target": target,
                    "card": card,
                }
            )

            parsed = parse_over_under_card(
                card,
                target,
            )

            if parsed is None:
                print(
                    f"  [{index}/6] {target['heading']}: "
                    "card captured but O/U rows were not parsed"
                )
            else:
                markets.append(parsed)
                lines = sorted(
                    {
                        selection["line"]
                        for selection in parsed["selections"]
                    },
                    key=float,
                )
                print(
                    f"  [{index}/6] {target['heading']}: "
                    f"{parsed['selection_count']} selections "
                    f"[{', '.join(lines)}]"
                )

        # Clicking a market can alter the Bwin route. Restore the event Shots
        # tab before searching for the next exact heading.
        if index < len(targets):
            restore_shots_tab(
                page,
                event_url,
            )
            expand_show_more(
                page,
                max_clicks=4,
            )

    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    (DEBUG_DIR / f"{slug}_cards.json").write_text(
        json.dumps(
            raw_cards,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        body_text = page.locator("body").inner_text(
            timeout=8000
        )
    except Exception as error:
        body_text = (
            "DEBUG BODY CAPTURE FAILED: "
            + str(error)
        )

    (DEBUG_DIR / f"{slug}.txt").write_text(
        body_text,
        encoding="utf-8",
    )

    try:
        page.screenshot(
            path=str(DEBUG_DIR / f"{slug}.png"),
            full_page=False,
        )
    except Exception:
        pass

    print(
        f"Parsed match-stat markets: {len(markets)}/6"
    )

    return {
        "bookmaker": "Bwin",
        "match": name,
        "home_team": home,
        "away_team": away,
        "date_label": match.get("date_label", ""),
        "time": match.get("time", ""),
        "source_url": event_url,
        "market_count": len(markets),
        "markets": markets,
    }


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed.")
        return 1

    try:
        matches = load_matches()
    except Exception as error:
        print(f"ERROR: {error}")
        return 1

    if not matches:
        print(
            "No safe upcoming Bwin fixtures were found."
        )
        return 1

    complete_results = []
    incomplete_results = []
    errors = []

    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with sync_playwright() as playwright:
        browser = None
        context = None

        try:
            browser = playwright.chromium.launch(
                headless=HEADLESS,
                args=[
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-breakpad",
                    "--disable-extensions",
                    "--disable-renderer-backgrounding",
                    "--mute-audio",
                    "--no-first-run",
                ],
            )

            context = browser.new_context(
                viewport={
                    "width": 1700,
                    "height": 1000,
                },
                user_agent=USER_AGENT,
                locale="en-GB",
            )
            context.route(
                "**/*",
                block_heavy_resources,
            )

            for index, match in enumerate(
                matches,
                start=1,
            ):
                print(
                    f"\n[{index}/{len(matches)}] "
                    f"{match['match']}"
                )

                page = None

                try:
                    page = safe_open_event_page(
                        context,
                        match,
                    )
                    result = scrape_one(page, match)

                    if result.get("market_count") == 6:
                        complete_results.append(result)
                    else:
                        incomplete_results.append(result)
                        print(
                            "AUDIT ONLY: incomplete match-stat coverage "
                            f"({result.get('market_count', 0)}/6)"
                        )
                except Exception as error:
                    errors.append(
                        {
                            "match": match["match"],
                            "error": str(error),
                        }
                    )
                    print(f"ERROR: {error}")
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:
                            pass
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()

    audit_payload = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "Bwin",
        "dataset": "match_team_shots_stats_audit",
        "odds_format": "fractional",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "complete_match_count": len(complete_results),
        "incomplete_match_count": len(incomplete_results),
        "error_count": len(errors),
        "complete_matches": complete_results,
        "incomplete_matches": incomplete_results,
        "errors": errors,
    }

    AUDIT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    audit_temp = AUDIT_PATH.with_suffix(".json.tmp")
    audit_temp.write_text(
        json.dumps(
            audit_payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    audit_temp.replace(AUDIT_PATH)

    if complete_results:
        production_payload = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "Bwin",
            "dataset": "match_team_shots_stats",
            "odds_format": "fractional",
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "match_count": len(complete_results),
            "error_count": 0,
            "matches": complete_results,
            "errors": [],
        }

        OUT_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        production_temp = OUT_PATH.with_suffix(".json.tmp")
        production_temp.write_text(
            json.dumps(
                production_payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        production_temp.replace(OUT_PATH)
    else:
        print(
            "WARNING: no complete 6/6 fixtures; "
            "existing production match-stats JSON was left untouched."
        )

    print("")
    print("Bwin World Cup match-stats 15-match audit completed")
    print(
        f"Complete 6/6 matches promoted: "
        f"{len(complete_results)}"
    )
    print(
        f"Incomplete matches kept in audit only: "
        f"{len(incomplete_results)}"
    )
    print(f"Errors: {len(errors)}")
    print(f"Production output: {OUT_PATH}")
    print(f"Audit output: {AUDIT_PATH}")

    return 0 if complete_results else 1


if __name__ == "__main__":
    sys.exit(main())
