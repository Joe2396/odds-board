#!/usr/bin/env python3
"""
fetch_bwin_worldcup_props.py

Bwin World Cup 2026 props scraper — deep tabs, scroll, and exact cards.

It reads event URLs from bwin_worldcup_moneylines.json, opens the next three
fixtures, expands visible market groups, visits useful market tabs, and extracts
market cards directly from the rendered DOM.

The first run is deliberately a TEST3 run:

    MAX_MATCHES = 3
    HEADLESS = False

Output:
    football/data/bwin_worldcup_props.json

Debug:
    football/debug/bwin_worldcup_props/<match>.txt
    football/debug/bwin_worldcup_props/<match>_cards.json
    football/debug/bwin_worldcup_props/<match>.png

The raw card dump is preserved even when a newly encountered Bwin layout cannot
yet be normalised. That makes the next parser adjustment deterministic rather
than guesswork.
"""

from __future__ import annotations

# BWIN_V5_SCROLL_ALL_MARKETS

import json
import re
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]

MONEYLINES_PATH = (
    ROOT / "football" / "data" / "bwin_worldcup_moneylines.json"
)
OUT_PATH = ROOT / "football" / "data" / "bwin_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "bwin_worldcup_props"

MAX_MATCHES = 3
HEADLESS = False

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

TARGET_HEADINGS = [
    "Match Result",
    "Match Betting",
    "Both Teams To Score",
    "Double Chance",
    "Half Time Result",
    "Total Goals",
    "Total Corners",
    "Total Cards",
    "Player Total Shots",
    "Player Total Shots On Target",
    "Player Total Shots on Target",
    "Goalscorers",
    "Anytime Goalscorer",
    "To be shown a Card",
    "Player to be shown a Card",
    "Player Cards",
    "Player Total Tackles",
    "Player Tackles",
    "Total Tackles",
    "Player Total Assists",
    "Player Assists",
    "Player To Assist",
    "Player Total Fouls",
    "Player Fouls",
    "Player Total Fouls Committed",
    "Player Fouls Committed",
    "Total Fouls Committed",
    "Player Total Fouls Won",
    "Player Fouls Won",
    "Total Fouls Won",
]

TARGET_TABS = [
    "All",
    "Main",
    "Goals",
    "Players",
    "Cards",
    "Corners",
    "Build A Bet",
]

# Bwin changes the wording of the same player market between fixtures and
# tabs. Each group is searched using every known exact alias.
ACCORDION_GROUPS = [
    (
        "Player Cards",
        [
            "To be shown a Card",
            "Player to be shown a Card",
            "Player Cards",
        ],
    ),
    (
        "Player Tackles",
        [
            "Player Total Tackles",
            "Player Tackles",
            "Total Tackles",
        ],
    ),
    (
        "Player Assists",
        [
            "Player Total Assists",
            "Player Assists",
            "Player To Assist",
        ],
    ),
    (
        "Player Fouls",
        [
            "Player Total Fouls",
            "Player Fouls",
            "Player Total Fouls Committed",
            "Player Fouls Committed",
            "Total Fouls Committed",
            "Player Total Fouls Won",
            "Player Fouls Won",
            "Total Fouls Won",
        ],
    ),
]

# Try player accordions on every tab where Bwin has previously placed them.
TAB_ACCORDION_LABELS = {
    "All": {"Player Cards", "Player Tackles", "Player Assists", "Player Fouls"},
    "Players": {"Player Cards", "Player Tackles", "Player Assists", "Player Fouls"},
    "Cards": {"Player Cards", "Player Fouls"},
    "Build A Bet": {"Player Cards", "Player Tackles", "Player Assists", "Player Fouls"},
}

# User-required output limits. The source can show larger ladders, but they are
# intentionally discarded from the JSON.
MAX_PLAYER_THRESHOLD = {
    "shots": 4,            # keep 1+, 2+, 3+, 4+
    "shots_on_target": 3,  # keep 1+, 2+, 3+
}

ODDS_RE = re.compile(r"^\d{1,3}[.,]\d{1,3}$")
PLUS_RE = re.compile(r"^(\d+)\+$")
NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?$")


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value: object) -> str:
    value = clean(value).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def normalize_key(value: object) -> str:
    value = clean(value).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


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


def canonical_market_name(heading: str) -> tuple[str, str] | None:
    """
    Map only exact Bwin market headings.

    Broad substring matching caused unrelated cards to be merged into markets
    such as Match Betting and Double Chance. Keep this deliberately strict.
    """
    key = normalize_key(heading)

    mapping = {
        "match_result": ("Match Betting", "match_betting"),
        "match_betting": ("Match Betting", "match_betting"),
        "both_teams_to_score": ("Both Teams To Score", "btts"),
        "double_chance": ("Double Chance", "double_chance"),
        "half_time_result": ("Half Time Result", "half_time_result"),
        "total_goals": ("Total Goals Over/Under", "total_goals"),
        "total_corners": ("Total Corners Over/Under", "total_corners"),
        "total_cards": ("Total Cards Over/Under", "total_match_cards"),
        "player_total_shots": ("Player Shots", "shots"),
        "player_total_shots_on_target": (
            "Player Shots On Target",
            "shots_on_target",
        ),
        "anytime_goalscorer": ("Anytime Goalscorer", "anytime_scorer"),
        "goalscorers": ("Anytime Goalscorer", "anytime_scorer"),
        "to_be_shown_a_card": (
            "Player To Get A Card",
            "player_to_get_a_card",
        ),
        "player_total_tackles": (
            "Player Tackles",
            "player_tackles_completed",
        ),
        "player_total_assists": (
            "Player To Assist",
            "player_to_assist",
        ),
        "player_total_fouls": (
            "Player Fouls",
            "player_fouls",
        ),
        "player_fouls": (
            "Player Fouls",
            "player_fouls",
        ),
        "player_total_fouls_committed": (
            "Player Fouls Committed",
            "player_fouls_committed",
        ),
        "player_fouls_committed": (
            "Player Fouls Committed",
            "player_fouls_committed",
        ),
        "total_fouls_committed": (
            "Player Fouls Committed",
            "player_fouls_committed",
        ),
        "player_total_fouls_won": (
            "Player Fouls Won",
            "player_fouls_won",
        ),
        "player_fouls_won": (
            "Player Fouls Won",
            "player_fouls_won",
        ),
        "total_fouls_won": (
            "Player Fouls Won",
            "player_fouls_won",
        ),
        "player_to_be_shown_a_card": (
            "Player To Get A Card",
            "player_to_get_a_card",
        ),
        "player_cards": (
            "Player To Get A Card",
            "player_to_get_a_card",
        ),
        "player_tackles": (
            "Player Tackles",
            "player_tackles_completed",
        ),
        "total_tackles": (
            "Player Tackles",
            "player_tackles_completed",
        ),
        "player_assists": (
            "Player To Assist",
            "player_to_assist",
        ),
        "player_to_assist": (
            "Player To Assist",
            "player_to_assist",
        ),
    }

    return mapping.get(key)

def load_matches() -> list[dict]:
    if not MONEYLINES_PATH.exists():
        raise RuntimeError(
            f"Bwin moneyline file not found: {MONEYLINES_PATH}"
        )

    payload = json.loads(MONEYLINES_PATH.read_text(encoding="utf-8"))
    rows = payload.get("matches") or []

    output = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        home = clean(row.get("home_team"))
        away = clean(row.get("away_team"))
        url = clean(row.get("source_url"))

        if not home or not away or "/sports/events/" not in url:
            continue

        output.append(
            {
                "match": clean(row.get("match")) or f"{home} v {away}",
                "home_team": home,
                "away_team": away,
                "date_label": clean(row.get("date_label")),
                "time": clean(row.get("time")),
                "url": url,
            }
        )

    return output[:MAX_MATCHES] if MAX_MATCHES else output


def dismiss_cookies(page) -> None:
    labels = [
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
        try:
            button = page.get_by_role(
                "button",
                name=re.compile(rf"^{re.escape(label)}$", re.I),
            )
            if button.count():
                button.first.click(timeout=2200)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def block_heavy_resources(route) -> None:
    if route.request.resource_type in {"image", "media", "font"}:
        route.abort()
    else:
        route.continue_()


def click_visible_text(page, label: str) -> bool:
    """Click an exact tab/control label and scroll it into view first."""
    patterns = [
        page.get_by_role(
            "tab",
            name=re.compile(rf"^{re.escape(label)}$", re.I),
        ),
        page.get_by_role(
            "button",
            name=re.compile(rf"^{re.escape(label)}$", re.I),
        ),
        page.get_by_text(
            re.compile(rf"^{re.escape(label)}$", re.I),
            exact=True,
        ),
    ]

    for locator in patterns:
        try:
            count = min(locator.count(), 8)
        except Exception:
            continue

        for index in range(count):
            try:
                item = locator.nth(index)
                item.scroll_into_view_if_needed(timeout=2500)
                page.wait_for_timeout(120)
                if item.is_visible():
                    item.click(timeout=3000)
                    page.wait_for_timeout(750)
                    return True
            except Exception:
                continue

    return False


def market_card_visible(page, aliases: list[str]) -> str:
    """Return the exact rendered heading when its card contains real odds."""
    try:
        return clean(
            page.evaluate(
                r"""
                (aliases) => {
                    const clean = value =>
                        (value || "").replace(/\s+/g, " ").trim();
                    const norm = value =>
                        clean(value).toLowerCase()
                            .replace(/[^a-z0-9]+/g, " ").trim();
                    const wanted = new Set(aliases.map(norm));
                    const oddRe = /^\d{1,3}[.,]\d{1,3}$/;

                    const visible = element => {
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        return (
                            rect.width > 0 && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                        );
                    };

                    for (const element of document.querySelectorAll("body *")) {
                        if (!visible(element)) {
                            continue;
                        }

                        const own = Array.from(element.childNodes)
                            .filter(node => node.nodeType === Node.TEXT_NODE)
                            .map(node => clean(node.textContent))
                            .filter(Boolean).join(" ");
                        const full = clean(element.innerText);
                        const heading = wanted.has(norm(own)) ? own : full;

                        if (!wanted.has(norm(heading))) {
                            continue;
                        }

                        let node = element;
                        for (
                            let depth = 0;
                            depth < 9 && node;
                            depth += 1, node = node.parentElement
                        ) {
                            const lines = clean(node.innerText)
                                .split(/\n+/).map(clean).filter(Boolean);
                            if (
                                !lines.length
                                || !wanted.has(norm(lines[0]))
                                || lines.length > 500
                            ) {
                                continue;
                            }
                            if (lines.some(line => oddRe.test(line))) {
                                return lines[0];
                            }
                        }
                    }
                    return "";
                }
                """,
                aliases,
            )
        )
    except Exception:
        return ""


def discover_market_headings(page) -> list[str]:
    """Collect likely market-row titles for debugging missing Bwin aliases."""
    try:
        rows = page.evaluate(
            r"""
            () => {
                const clean = value =>
                    (value || "").replace(/\s+/g, " ").trim();
                const keyword = /goal|corner|card|shot|tackle|assist|foul|score|chance|result/i;
                const output = new Set();

                for (const element of document.querySelectorAll("div, span, button")) {
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    const text = clean(element.innerText);

                    if (
                        rect.width < 140 || rect.width > 1100
                        || rect.height < 14 || rect.height > 90
                        || style.display === "none"
                        || style.visibility === "hidden"
                        || !text || text.length > 80
                        || !keyword.test(text)
                    ) {
                        continue;
                    }

                    const childTexts = Array.from(element.children)
                        .map(child => clean(child.innerText))
                        .filter(Boolean);
                    if (childTexts.length > 3) {
                        continue;
                    }
                    output.add(text);
                }

                return Array.from(output).sort();
            }
            """
        ) or []
        return [clean(row) for row in rows if clean(row)]
    except Exception:
        return []


def open_market_accordion(page, aliases: list[str]) -> str:
    """
    Search the full tab vertically, click a plain DIV/SPAN market row using a
    real mouse event, and only report success after an exact card has odds.
    """
    already = market_card_visible(page, aliases)
    if already:
        return already

    # Some accordion rows only mount after an inner Show More is clicked.
    expand_visible_markets(page, max_clicks=18)

    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(150)
    except Exception:
        pass

    try:
        document_height = int(
            page.evaluate(
                """
                Math.max(
                    document.body.scrollHeight,
                    document.documentElement.scrollHeight
                )
                """
            ) or 8000
        )
    except Exception:
        document_height = 8000

    for scroll_y in range(0, max(document_height + 1600, 9000), 500):
        try:
            page.evaluate("(y) => window.scrollTo(0, y)", scroll_y)
            page.wait_for_timeout(180)

            candidate = page.evaluate(
                r"""
                (aliases) => {
                    const clean = value =>
                        (value || "").replace(/\s+/g, " ").trim();
                    const norm = value =>
                        clean(value).toLowerCase()
                            .replace(/[^a-z0-9]+/g, " ").trim();
                    const wanted = new Set(aliases.map(norm));

                    const visible = element => {
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        return (
                            rect.width > 0 && rect.height > 0
                            && rect.bottom > 0 && rect.top < innerHeight
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                        );
                    };

                    const directText = element =>
                        Array.from(element.childNodes)
                            .filter(node => node.nodeType === Node.TEXT_NODE)
                            .map(node => clean(node.textContent))
                            .filter(Boolean).join(" ");

                    const matches = Array.from(
                        document.querySelectorAll("div, span, button, [role='button']")
                    ).filter(element => {
                        if (!visible(element)) {
                            return false;
                        }
                        return (
                            wanted.has(norm(directText(element)))
                            || wanted.has(norm(element.innerText))
                        );
                    });

                    const candidates = [];
                    for (const match of matches) {
                        let node = match;
                        for (
                            let depth = 0;
                            depth < 8 && node;
                            depth += 1, node = node.parentElement
                        ) {
                            const rect = node.getBoundingClientRect();
                            const style = getComputedStyle(node);
                            const text = clean(node.innerText);
                            const first = text.split(/\n+/)[0] || "";

                            if (
                                rect.width < 180 || rect.width > 1150
                                || rect.height < 25 || rect.height > 105
                                || !wanted.has(norm(first))
                            ) {
                                continue;
                            }

                            const role = (node.getAttribute("role") || "").toLowerCase();
                            const cls = String(node.className || "");
                            const clickable = (
                                node.tagName === "BUTTON"
                                || role === "button"
                                || node.getAttribute("aria-expanded") !== null
                                || style.cursor === "pointer"
                                || typeof node.onclick === "function"
                                || /accordion|header|market|title|expand|collapse|click|item/i.test(cls)
                                || (rect.width >= 280 && rect.height >= 36)
                            );

                            if (!clickable) {
                                continue;
                            }

                            candidates.push({
                                heading: first,
                                xRight: Math.max(
                                    10,
                                    Math.min(innerWidth - 10, rect.right - 28)
                                ),
                                xLeft: Math.max(
                                    10,
                                    Math.min(innerWidth - 10, rect.left + 120)
                                ),
                                y: Math.max(
                                    10,
                                    Math.min(innerHeight - 10, rect.top + rect.height / 2)
                                ),
                                area: rect.width * rect.height,
                                depth,
                            });
                            break;
                        }
                    }

                    candidates.sort((a, b) => {
                        if (a.area !== b.area) {
                            return a.area - b.area;
                        }
                        return a.depth - b.depth;
                    });
                    return candidates[0] || null;
                }
                """,
                aliases,
            )

            if not candidate:
                continue

            for x_key in ("xRight", "xLeft"):
                page.mouse.move(
                    float(candidate[x_key]),
                    float(candidate["y"]),
                )
                page.wait_for_timeout(80)
                page.mouse.click(
                    float(candidate[x_key]),
                    float(candidate["y"]),
                )
                page.wait_for_timeout(1000)

                opened = market_card_visible(page, aliases)
                if opened:
                    expand_visible_markets(page, max_clicks=20)
                    return opened

        except Exception:
            continue

    return ""


def expand_visible_markets(page, max_clicks: int = 50) -> int:
    """
    Sweep the entire active tab and click every exact Show More/View More
    control, including controls inside player tables and Build A Bet sections.
    """
    labels = [
        "show more",
        "view more",
        "see more",
        "more markets",
        "all markets",
    ]
    clicked = 0
    seen = set()

    for _sweep in range(5):
        sweep_clicks = 0
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(120)
        except Exception:
            pass

        try:
            height = int(
                page.evaluate(
                    """
                    Math.max(
                        document.body.scrollHeight,
                        document.documentElement.scrollHeight
                    )
                    """
                ) or 7000
            )
        except Exception:
            height = 7000

        scroll_y = 0
        while scroll_y <= height + 900 and clicked < max_clicks:
            try:
                page.evaluate("(y) => window.scrollTo(0, y)", scroll_y)
                page.wait_for_timeout(150)
            except Exception:
                break

            while clicked < max_clicks:
                try:
                    candidates = page.evaluate(
                        r"""
                        (labels) => {
                            const clean = value =>
                                (value || "").replace(/\s+/g, " ").trim();
                            const norm = value => clean(value).toLowerCase();
                            const wanted = new Set(labels);
                            const output = [];

                            for (const element of document.querySelectorAll(
                                "button, span, div, [role='button']"
                            )) {
                                const rect = element.getBoundingClientRect();
                                const style = getComputedStyle(element);
                                const text = norm(element.innerText);

                                if (
                                    !wanted.has(text)
                                    || rect.width <= 0 || rect.height <= 0
                                    || rect.bottom <= 0 || rect.top >= innerHeight
                                    || style.display === "none"
                                    || style.visibility === "hidden"
                                ) {
                                    continue;
                                }

                                let node = element;
                                for (
                                    let depth = 0;
                                    depth < 5 && node;
                                    depth += 1, node = node.parentElement
                                ) {
                                    const box = node.getBoundingClientRect();
                                    const nodeStyle = getComputedStyle(node);
                                    const role = (node.getAttribute("role") || "").toLowerCase();
                                    const cls = String(node.className || "");

                                    if (
                                        box.width < 35 || box.width > 1100
                                        || box.height < 18 || box.height > 85
                                    ) {
                                        continue;
                                    }

                                    if (
                                        node.tagName === "BUTTON"
                                        || role === "button"
                                        || nodeStyle.cursor === "pointer"
                                        || typeof node.onclick === "function"
                                        || /show|more|expand|button|click/i.test(cls)
                                        || (box.width >= 80 && box.height >= 24)
                                    ) {
                                        output.push({
                                            text: clean(node.innerText),
                                            x: Math.max(
                                                8,
                                                Math.min(innerWidth - 8, box.left + box.width / 2)
                                            ),
                                            y: Math.max(
                                                8,
                                                Math.min(innerHeight - 8, box.top + box.height / 2)
                                            ),
                                            absoluteY: Math.round(box.top + window.scrollY),
                                            absoluteX: Math.round(box.left),
                                            width: Math.round(box.width),
                                        });
                                        break;
                                    }
                                }
                            }

                            output.sort((a, b) => b.absoluteY - a.absoluteY);
                            return output;
                        }
                        """,
                        labels,
                    ) or []
                except Exception:
                    candidates = []

                fresh = None
                for candidate in candidates:
                    key = (
                        normalize_key(candidate.get("text")),
                        round(float(candidate.get("absoluteY") or 0) / 8),
                        round(float(candidate.get("absoluteX") or 0) / 8),
                        round(float(candidate.get("width") or 0) / 8),
                    )
                    if key not in seen:
                        seen.add(key)
                        fresh = candidate
                        break

                if not fresh:
                    break

                try:
                    page.mouse.click(
                        float(fresh["x"]),
                        float(fresh["y"]),
                    )
                    page.wait_for_timeout(420)
                    clicked += 1
                    sweep_clicks += 1
                    height = int(
                        page.evaluate(
                            """
                            Math.max(
                                document.body.scrollHeight,
                                document.documentElement.scrollHeight
                            )
                            """
                        ) or height
                    )
                except Exception:
                    continue

            scroll_y += 520

        if sweep_clicks == 0:
            break

    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(150)
    except Exception:
        pass

    return clicked

CARD_EXTRACTOR = r"""
(headings) => {
    const clean = value =>
        (value || "").replace(/\s+/g, " ").trim();

    const normalise = value =>
        clean(value).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

    const oddRe = /^\d{1,3}[.,]\d{1,3}$/;
    const wanted = new Set(headings.map(normalise));

    const visible = element => {
        const box = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return (
            box.width > 0
            && box.height > 0
            && style.visibility !== "hidden"
            && style.display !== "none"
        );
    };

    const headingElements = Array.from(
        document.querySelectorAll("body *")
    ).filter(element => {
        if (!visible(element)) {
            return false;
        }

        const text = clean(element.innerText);
        if (!text || text.length > 80) {
            return false;
        }

        // Exact heading matching only. Prefix matching was the reason hundreds
        // of unrelated cards were being captured.
        return wanted.has(normalise(text));
    });

    const output = [];
    const seen = new Set();

    for (const headingElement of headingElements) {
        const heading = clean(headingElement.innerText);
        let node = headingElement;
        let best = null;

        for (
            let depth = 0;
            depth < 8 && node;
            depth += 1, node = node.parentElement
        ) {
            const raw = node.innerText || "";
            const lines = raw
                .split(/\n+/)
                .map(clean)
                .filter(Boolean);

            if (
                !lines.length
                || normalise(lines[0]) !== normalise(heading)
            ) {
                continue;
            }

            const odds = lines.filter(line => oddRe.test(line));
            if (!odds.length) {
                continue;
            }

            // Stop the card from growing into a whole tab/page container.
            if (raw.length > 9000 || lines.length > 500) {
                continue;
            }

            const candidate = {
                node,
                lines,
                size: raw.length,
            };

            if (!best || candidate.size < best.size) {
                best = candidate;
            }
        }

        if (!best) {
            continue;
        }

        const cardBox = best.node.getBoundingClientRect();
        const signature = (
            normalise(heading)
            + "|"
            + best.lines.join("|")
        );

        if (seen.has(signature)) {
            continue;
        }
        seen.add(signature);

        const leaves = Array.from(
            best.node.querySelectorAll("*")
        ).filter(element => (
            visible(element)
            && element.childElementCount === 0
            && clean(element.innerText)
        )).map(element => {
            const box = element.getBoundingClientRect();
            return {
                text: clean(element.innerText),
                x: Math.round(box.left),
                y: Math.round(box.top + window.scrollY),
                width: Math.round(box.width),
                height: Math.round(box.height),
                tag: element.tagName,
            };
        });

        output.push({
            heading,
            lines: best.lines,
            leaves,
            signature,
            card_top: Math.round(cardBox.top + window.scrollY),
        });
    }

    return output;
}
"""


def collect_cards(page) -> list[dict]:
    all_cards: dict[str, dict] = {}
    stable_rounds = 0
    previous_count = -1

    for _ in range(28):
        cards = page.evaluate(CARD_EXTRACTOR, TARGET_HEADINGS) or []

        for card in cards:
            key = clean(card.get("signature")) or (
                normalize_key(card.get("heading"))
                + "|"
                + "|".join(card.get("lines") or [])
            )
            all_cards[key] = card

        count = len(all_cards)
        if count == previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        previous_count = count

        if stable_rounds >= 4:
            break

        page.mouse.wheel(0, 850)
        page.wait_for_timeout(450)

    return list(all_cards.values())


def clean_candidate_label(text: str, heading: str) -> str:
    text = clean(text)
    if not text:
        return ""

    rejected = {
        normalize_key(heading),
        "all",
        "main",
        "goals",
        "players",
        "player",
        "cards",
        "corners",
        "build_a_bet",
        "show_more",
        "view_more",
    }

    key = normalize_key(text)
    if key in rejected:
        return ""
    if is_decimal_odds(text):
        return ""
    if len(text) > 90:
        return ""

    return text


def threshold_to_line(value: str) -> str:
    match = PLUS_RE.fullmatch(clean(value))
    if not match:
        return ""

    return str(float(match.group(1)) - 0.5).rstrip("0").rstrip(".")


def nearest_row_label(
    odd_leaf: dict,
    leaves: list[dict],
    heading: str,
) -> str:
    odd_y = float(odd_leaf.get("y") or 0)
    odd_x = float(odd_leaf.get("x") or 0)
    tolerance = max(14, float(odd_leaf.get("height") or 0) + 7)

    candidates = []
    for leaf in leaves:
        text = clean_candidate_label(leaf.get("text"), heading)
        if not text:
            continue

        x = float(leaf.get("x") or 0)
        y = float(leaf.get("y") or 0)

        if x >= odd_x:
            continue
        if abs(y - odd_y) > tolerance:
            continue

        candidates.append((odd_x - x, text))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def nearest_column_header(
    odd_leaf: dict,
    leaves: list[dict],
    heading: str,
) -> str:
    odd_y = float(odd_leaf.get("y") or 0)
    odd_x = float(odd_leaf.get("x") or 0)
    odd_width = float(odd_leaf.get("width") or 0)
    odd_center = odd_x + odd_width / 2

    candidates = []
    for leaf in leaves:
        text = clean_candidate_label(leaf.get("text"), heading)
        if not text:
            continue

        if not (
            PLUS_RE.fullmatch(text)
            or text in {"1", "X", "2", "Yes", "No", "Over", "Under"}
            or NUMBER_RE.fullmatch(text)
        ):
            continue

        x = float(leaf.get("x") or 0)
        width = float(leaf.get("width") or 0)
        center = x + width / 2
        y = float(leaf.get("y") or 0)

        if y >= odd_y:
            continue
        if abs(center - odd_center) > 80:
            continue

        candidates.append((odd_y - y, abs(center - odd_center), text))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def sequential_pairs(lines: list[str], heading: str) -> list[tuple[str, str]]:
    output = []
    previous_labels: list[str] = []

    for raw in lines:
        line = clean(raw)
        if not line:
            continue

        embedded = re.fullmatch(
            r"(.+?)\s+(\d{1,3}[.,]\d{1,3})",
            line,
        )
        if embedded and is_decimal_odds(embedded.group(2)):
            label = clean_candidate_label(embedded.group(1), heading)
            if label:
                output.append((label, embedded.group(2)))
            continue

        if is_decimal_odds(line):
            label = previous_labels[-1] if previous_labels else ""
            if label:
                output.append((label, line))
            continue

        label = clean_candidate_label(line, heading)
        if label:
            previous_labels.append(label)
            previous_labels = previous_labels[-4:]

    return output


def geometry_pairs(card: dict) -> list[tuple[str, str, str]]:
    heading = clean(card.get("heading"))
    leaves = card.get("leaves") or []
    output = []

    for leaf in leaves:
        raw = clean(leaf.get("text"))

        embedded = re.fullmatch(
            r"(.+?)\s+(\d{1,3}[.,]\d{1,3})",
            raw,
        )
        if embedded and is_decimal_odds(embedded.group(2)):
            row = clean_candidate_label(embedded.group(1), heading)
            if row:
                output.append((row, "", embedded.group(2)))
            continue

        if not is_decimal_odds(raw):
            continue

        row = nearest_row_label(leaf, leaves, heading)
        header = nearest_column_header(leaf, leaves, heading)
        output.append((row, header, raw))

    return output


def make_selection(
    market_key: str,
    row: str,
    header: str,
    decimal_odds: str,
) -> dict | None:
    row = clean(row)
    header = clean(header)
    fractional = decimal_to_fractional(decimal_odds)

    if not fractional:
        return None

    selection = ""
    side = ""
    line = ""
    player = ""

    if market_key in {
        "shots",
        "shots_on_target",
        "player_to_assist",
        "player_to_get_a_card",
        "player_tackles_completed",
        "player_fouls_committed",
        "player_fouls_won",
        "player_fouls",
        "anytime_scorer",
    }:
        player = row

        if PLUS_RE.fullmatch(header):
            line = threshold_to_line(header)
            selection = f"{player} Over {line}"
            side = "over"
        elif header:
            selection = f"{player} {header}"
        else:
            selection = player

    elif market_key in {
        "total_goals",
        "total_corners",
        "total_match_cards",
    }:
        values = [row, header]
        over_under = next(
            (
                value.title()
                for value in values
                if value.lower() in {"over", "under"}
            ),
            "",
        )
        numeric = next(
            (
                clean(value).replace(",", ".")
                for value in values
                if NUMBER_RE.fullmatch(clean(value))
            ),
            "",
        )

        if over_under and numeric:
            selection = f"{over_under} {numeric}"
            side = over_under.lower()
            line = numeric
        else:
            selection = " ".join(value for value in values if value)

    elif market_key == "btts":
        value = row or header
        if value.lower() in {"yes", "no"}:
            selection = (
                "Both Teams To Score - " + value.title()
            )
            side = value.lower()
        else:
            selection = value

    elif market_key == "double_chance":
        selection = row or header

    elif market_key in {"half_time_result", "match_betting"}:
        selection = row or header

    else:
        selection = " ".join(
            value for value in (row, header) if value
        )

    selection = clean(selection)
    if not selection:
        return None

    output = {
        "selection": selection,
        "normalized_selection": normalize_key(selection),
        "odds": fractional,
        "decimal_odds": float(clean(decimal_odds).replace(",", ".")),
    }

    if side:
        output["side"] = side
    if line:
        output["line"] = line
    if player:
        output["player"] = player

    return output


def _selection(
    name: str,
    decimal_odds: object,
    extra: dict | None = None,
) -> dict | None:
    fractional = decimal_to_fractional(decimal_odds)
    if not fractional:
        return None

    output = {
        "selection": clean(name),
        "normalized_selection": normalize_key(name),
        "odds": fractional,
        "decimal_odds": float(
            clean(decimal_odds).replace(",", ".")
        ),
    }

    if extra:
        output.update(extra)

    return output


def _market(
    market_name: str,
    market_key: str,
    heading: str,
    selections: list[dict | None],
) -> dict | None:
    unique = []
    seen = set()

    for selection in selections:
        if not isinstance(selection, dict):
            continue

        key = (
            selection.get("normalized_selection"),
            selection.get("side"),
            selection.get("line"),
            selection.get("player"),
        )
        if key in seen:
            continue

        seen.add(key)
        unique.append(selection)

    if not unique:
        return None

    return {
        "market": market_name,
        "normalized_market": market_key,
        "raw_heading": heading,
        "selection_count": len(unique),
        "selections": unique,
    }


def parse_match_result_card(
    card: dict,
    home: str,
    away: str,
) -> dict | None:
    lines = [clean(line) for line in card.get("lines") or []]

    for index in range(len(lines) - 5):
        if (
            lines[index] == home
            and is_decimal_odds(lines[index + 1])
            and lines[index + 2].upper() == "X"
            and is_decimal_odds(lines[index + 3])
            and lines[index + 4] == away
            and is_decimal_odds(lines[index + 5])
        ):
            return _market(
                "Match Betting",
                "match_betting",
                clean(card.get("heading")),
                [
                    _selection(
                        home,
                        lines[index + 1],
                        {"side": "home"},
                    ),
                    _selection(
                        "Draw",
                        lines[index + 3],
                        {"side": "draw"},
                    ),
                    _selection(
                        away,
                        lines[index + 5],
                        {"side": "away"},
                    ),
                ],
            )

    return None


def parse_ou_card(
    card: dict,
    market_name: str,
    market_key: str,
    prop_type: str,
) -> dict | None:
    lines = [clean(line) for line in card.get("lines") or []]
    lower = [line.lower() for line in lines]
    selections = []

    if "over" in lower and "under" in lower:
        start = max(lower.index("over"), lower.index("under")) + 1
        index = start

        while index + 2 < len(lines):
            raw_line = lines[index]
            over_odds = lines[index + 1]
            under_odds = lines[index + 2]
            line = raw_line.replace(",", ".")

            if (
                NUMBER_RE.fullmatch(raw_line)
                and is_decimal_odds(over_odds)
                and is_decimal_odds(under_odds)
            ):
                selections.extend(
                    [
                        _selection(
                            f"Over {line}",
                            over_odds,
                            {
                                "side": "over",
                                "line": line,
                                "prop_type": prop_type,
                            },
                        ),
                        _selection(
                            f"Under {line}",
                            under_odds,
                            {
                                "side": "under",
                                "line": line,
                                "prop_type": prop_type,
                            },
                        ),
                    ]
                )
                index += 3
                continue

            index += 1

    if not selections:
        for index, raw_line in enumerate(lines):
            if not NUMBER_RE.fullmatch(raw_line):
                continue

            line = raw_line.replace(",", ".")
            window = lines[index + 1:index + 7]
            over_odds = ""
            under_odds = ""

            for offset, token in enumerate(window):
                match = re.fullmatch(
                    r"(Over|Under)\s+(\d{1,3}[.,]\d{1,3})",
                    token,
                    re.I,
                )
                if match:
                    side = match.group(1).lower()
                    odd = match.group(2)
                    if side == "over":
                        over_odds = odd
                    else:
                        under_odds = odd
                    continue

                if token.lower() == "over":
                    for candidate in window[offset + 1:offset + 3]:
                        if is_decimal_odds(candidate):
                            over_odds = candidate
                            break

                if token.lower() == "under":
                    for candidate in window[offset + 1:offset + 3]:
                        if is_decimal_odds(candidate):
                            under_odds = candidate
                            break

            if over_odds:
                selections.append(
                    _selection(
                        f"Over {line}",
                        over_odds,
                        {
                            "side": "over",
                            "line": line,
                            "prop_type": prop_type,
                        },
                    )
                )

            if under_odds:
                selections.append(
                    _selection(
                        f"Under {line}",
                        under_odds,
                        {
                            "side": "under",
                            "line": line,
                            "prop_type": prop_type,
                        },
                    )
                )

    return _market(
        market_name,
        market_key,
        clean(card.get("heading")),
        selections,
    )


def _player_prefix_start(
    prefix: list[str],
    heading: str,
    home: str,
    away: str,
) -> int:
    ignored = {
        normalize_key(heading),
        "bb",
        "popular",
        "all",
        "main",
        "players",
        "player",
        normalize_key(home),
        normalize_key(away),
    }

    last_meta = -1

    for index, value in enumerate(prefix):
        if normalize_key(value) in ignored:
            last_meta = index

    return last_meta + 1


def parse_player_threshold_matrix(
    card: dict,
    home: str,
    away: str,
    market_name: str,
    market_key: str,
) -> dict | None:
    """
    Parse Bwin's sparse player grid by real x/y coordinates.

    Rows do not always contain every threshold. Sequentially dividing the odds
    list by the player count shifts prices onto the wrong 1+/2+/3+/4+ columns.
    geometry_pairs() maps each price to the player at the same y coordinate and
    the threshold header at the same x coordinate.
    """
    heading = clean(card.get("heading"))
    selections = []
    maximum = MAX_PLAYER_THRESHOLD.get(market_key)

    for row, header, odds in geometry_pairs(card):
        player = clean(row)
        threshold_match = PLUS_RE.fullmatch(clean(header))

        if not player or not threshold_match:
            continue

        threshold = int(threshold_match.group(1))
        if maximum is not None and threshold > maximum:
            continue

        if normalize_key(player) in {
            normalize_key(heading),
            normalize_key(home),
            normalize_key(away),
            "bb",
            "popular",
            "show_more",
            "show_less",
        }:
            continue

        line = threshold_to_line(header)
        if not line:
            continue

        selections.append(
            _selection(
                f"{player} Over {line}",
                odds,
                {
                    "player": player,
                    "side": "over",
                    "line": line,
                    "prop_type": market_key,
                    "source_threshold": f"{threshold}+",
                },
            )
        )

    return _market(
        market_name,
        market_key,
        heading,
        selections,
    )

def parse_geometry_player_market(
    card: dict,
    market_name: str,
    market_key: str,
    required_header: str = "",
) -> dict | None:
    heading = clean(card.get("heading"))
    selections = []
    maximum = MAX_PLAYER_THRESHOLD.get(market_key)

    for row, header, odds in geometry_pairs(card):
        row = clean(row)
        header = clean(header)

        if not row:
            continue

        if required_header and header.lower() != required_header.lower():
            continue

        if normalize_key(row) in {
            normalize_key(heading),
            "bb",
            "show_more",
            "show_less",
            "view_more",
            "popular",
        }:
            continue

        extra = {
            "player": row,
            "prop_type": market_key,
        }

        threshold_match = PLUS_RE.fullmatch(header)
        if threshold_match:
            threshold = int(threshold_match.group(1))
            if maximum is not None and threshold > maximum:
                continue

            line = threshold_to_line(header)
            if not line:
                continue
            name = f"{row} Over {line}"
            extra.update(
                {
                    "side": "over",
                    "line": line,
                    "source_threshold": f"{threshold}+",
                }
            )
        else:
            name = row

        selection = _selection(name, odds, extra)
        if selection:
            selections.append(selection)

    return _market(
        market_name,
        market_key,
        heading,
        selections,
    )

def parse_label_market(
    card: dict,
    market_name: str,
    market_key: str,
) -> dict | None:
    heading = clean(card.get("heading"))
    selections = []

    for row, header, odds in geometry_pairs(card):
        label = clean(row or header)
        if not label:
            continue

        key = normalize_key(label)
        if key in {
            normalize_key(heading),
            "bb",
            "show_more",
            "view_more",
            "regular_time",
            "1st_half",
            "2nd_half",
        }:
            continue

        extra = {}

        if market_key == "btts":
            if label.lower() not in {"yes", "no"}:
                continue
            extra["side"] = label.lower()
            label = "Both Teams To Score - " + label.title()

        selection = _selection(label, odds, extra)
        if selection:
            selections.append(selection)

    return _market(
        market_name,
        market_key,
        heading,
        selections,
    )


def parse_card(
    card: dict,
    home: str,
    away: str,
) -> dict | None:
    heading = clean(card.get("heading"))
    canonical = canonical_market_name(heading)
    if not canonical:
        return None

    market_name, market_key = canonical

    if market_key == "match_betting":
        return parse_match_result_card(card, home, away)

    if market_key == "total_goals":
        return parse_ou_card(
            card, market_name, market_key, "goals"
        )

    if market_key == "total_corners":
        return parse_ou_card(
            card, market_name, market_key, "corners"
        )

    if market_key == "total_match_cards":
        return parse_ou_card(
            card, market_name, market_key, "cards"
        )

    if market_key in {
        "shots",
        "shots_on_target",
        "player_tackles_completed",
        "player_fouls",
        "player_fouls_committed",
        "player_fouls_won",
    }:
        parsed = parse_player_threshold_matrix(
            card,
            home,
            away,
            market_name,
            market_key,
        )
        if parsed:
            return parsed

        return parse_geometry_player_market(
            card,
            market_name,
            market_key,
        )

    if market_key == "anytime_scorer":
        return parse_geometry_player_market(
            card,
            market_name,
            market_key,
            required_header="Anytime",
        )

    if market_key in {
        "player_to_get_a_card",
        "player_to_assist",
    }:
        return parse_geometry_player_market(
            card,
            market_name,
            market_key,
        )

    if market_key in {
        "btts",
        "double_chance",
        "half_time_result",
    }:
        return parse_label_market(
            card,
            market_name,
            market_key,
        )

    return None

def merge_market(existing: dict, incoming: dict) -> None:
    """
    Merge the same exact market captured from multiple tabs.

    Keep one row per semantic selection. The old key included the price, which
    allowed duplicate rows with slightly different captures to inflate counts.
    """
    existing_rows = existing.setdefault("selections", [])
    index_by_selection = {
        selection.get("normalized_selection"): index
        for index, selection in enumerate(existing_rows)
        if selection.get("normalized_selection")
    }

    for selection in incoming.get("selections") or []:
        key = selection.get("normalized_selection")
        if not key:
            continue

        if key not in index_by_selection:
            index_by_selection[key] = len(existing_rows)
            existing_rows.append(selection)
            continue

        current = existing_rows[index_by_selection[key]]

        # Same bookmaker and same selection: retain the higher decimal price if
        # the same market was captured twice.
        if (
            float(selection.get("decimal_odds") or 0)
            > float(current.get("decimal_odds") or 0)
        ):
            existing_rows[index_by_selection[key]] = selection

    existing["selection_count"] = len(existing_rows)


def validate_market_shape(market: dict) -> bool:
    key = market.get("normalized_market")
    selections = market.get("selections") or []

    exact_counts = {
        "match_betting": 3,
        "double_chance": 3,
        "btts": 2,
        "half_time_result": 3,
    }

    if key in exact_counts:
        return len(selections) == exact_counts[key]

    if key in {
        "total_goals",
        "total_corners",
        "total_match_cards",
    }:
        return bool(selections) and all(
            selection.get("side") in {"over", "under"}
            and selection.get("line") not in {None, ""}
            for selection in selections
        )

    if key in {
        "shots",
        "shots_on_target",
        "player_tackles_completed",
        "player_fouls",
        "player_fouls_committed",
        "player_fouls_won",
    }:
        if not selections or not all(
            selection.get("player")
            and selection.get("line") not in {None, ""}
            for selection in selections
        ):
            return False

        maximum = MAX_PLAYER_THRESHOLD.get(key)
        if maximum is None:
            return True

        maximum_line = float(maximum) - 0.5
        return all(
            float(selection.get("line")) <= maximum_line
            for selection in selections
        )

    if key in {
        "player_to_get_a_card",
        "player_to_assist",
        "anytime_scorer",
    }:
        return bool(selections) and all(
            selection.get("player")
            for selection in selections
        )

    return bool(selections)

def scrape_one(page, match: dict) -> dict:
    url = match["url"]
    name = match["match"]
    slug = slugify(name)

    print("")
    print(f"Opening {name}")
    print(url)

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=90000,
    )
    page.wait_for_timeout(5500)
    dismiss_cookies(page)

    clicked = expand_visible_markets(page, max_clicks=60)
    print(f"Expanded market controls: {clicked}")

    cards_by_key: dict[str, dict] = {}
    discovered_by_tab: dict[str, list[str]] = {}

    def capture(label: str) -> None:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(250)
        cards = collect_cards(page)

        for card in cards:
            key = clean(card.get("signature")) or (
                normalize_key(card.get("heading"))
                + "|"
                + "|".join(card.get("lines") or [])
            )
            cards_by_key[key] = card

        print(
            f"  {label}: {len(cards)} visible target card(s), "
            f"{len(cards_by_key)} accumulated"
        )

    capture("default")

    for tab in TARGET_TABS:
        if not click_visible_text(page, tab):
            print(f"  {tab}: tab not found")
            continue

        tab_expanded = expand_visible_markets(page, max_clicks=70)
        print(f"  {tab}: expanded {tab_expanded} inner control(s)")
        discovered_by_tab[tab] = discover_market_headings(page)
        capture(tab)

        wanted_groups = TAB_ACCORDION_LABELS.get(tab, set())
        for group_name, aliases in ACCORDION_GROUPS:
            if group_name not in wanted_groups:
                continue

            opened_heading = open_market_accordion(page, aliases)
            if opened_heading:
                print(
                    f"    accordion {group_name}: opened as "
                    f"{opened_heading}"
                )
                inner_expanded = expand_visible_markets(
                    page,
                    max_clicks=45,
                )
                if inner_expanded:
                    print(
                        f"      expanded {inner_expanded} row control(s)"
                    )
                capture(f"{tab} / {opened_heading}")
            else:
                print(f"    accordion {group_name}: not found")

    raw_cards = list(cards_by_key.values())
    markets_by_key: dict[str, dict] = {}

    for card in raw_cards:
        parsed = parse_card(
            card,
            match["home_team"],
            match["away_team"],
        )
        if not parsed:
            continue

        key = parsed["normalized_market"]
        if key not in markets_by_key:
            markets_by_key[key] = parsed
        else:
            merge_market(markets_by_key[key], parsed)

    markets = []
    for market in markets_by_key.values():
        if validate_market_shape(market):
            markets.append(market)
        else:
            print(
                f"Rejected malformed {market['market']}: "
                f"{market['selection_count']} selection(s)"
            )

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / f"{slug}.txt").write_text(
        page.locator("body").inner_text(timeout=30000),
        encoding="utf-8",
    )
    (DEBUG_DIR / f"{slug}_cards.json").write_text(
        json.dumps(raw_cards, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (DEBUG_DIR / f"{slug}_headings.json").write_text(
        json.dumps(
            discovered_by_tab,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        page.screenshot(
            path=str(DEBUG_DIR / f"{slug}.png"),
            full_page=False,
        )
    except Exception:
        pass

    print(f"Parsed markets: {len(markets)}")
    for market in markets:
        thresholds = sorted(
            {
                selection.get("source_threshold")
                for selection in market.get("selections") or []
                if selection.get("source_threshold")
            }
        )
        suffix = f" [{', '.join(thresholds)}]" if thresholds else ""
        print(
            f"  - {market['market']}: "
            f"{market['selection_count']} selections{suffix}"
        )

    return {
        "bookmaker": "Bwin",
        "match": name,
        "home_team": match["home_team"],
        "away_team": match["away_team"],
        "date_label": match.get("date_label", ""),
        "time": match.get("time", ""),
        "source_url": url,
        "market_count": len(markets),
        "markets": markets,
    }

def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed.")
        return 1

    matches = load_matches()
    if not matches:
        print("No usable Bwin event URLs found in the moneyline JSON.")
        return 1

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    errors = []

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
                viewport={"width": 1700, "height": 1000},
                user_agent=USER_AGENT,
                locale="en-GB",
            )
            context.route("**/*", block_heavy_resources)
            page = context.new_page()

            for index, match in enumerate(matches, start=1):
                print(
                    f"\n[{index}/{len(matches)}] "
                    f"{match['match']}"
                )

                try:
                    results.append(scrape_one(page, match))
                except Exception as error:
                    errors.append(
                        {
                            "match": match["match"],
                            "error": str(error),
                        }
                    )
                    print(f"ERROR: {error}")
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()

    payload = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "Bwin",
        "odds_format": "fractional",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "error_count": len(errors),
        "matches": results,
        "errors": errors,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("")
    print("Bwin World Cup props test completed")
    print(f"Matches saved: {len(results)}")
    print(f"Errors: {len(errors)}")
    print(f"Output: {OUT_PATH}")

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
