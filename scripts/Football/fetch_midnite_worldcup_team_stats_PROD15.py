#!/usr/bin/env python3
"""
Production Midnite World Cup match/team shots PROD15 scraper.

Targets:
- Match/Home/Away Total Shots
- Match/Home/Away Total Shots on Target

The ladder reader makes no assumptions about starting values, number of rows,
or consecutive thresholds. Each rendered threshold is paired with the nearest
rendered odds button on the same horizontal row.

Input:
  football/data/midnite_worldcup_props_fixtures_prod15.json
Output:
  football/data/midnite_worldcup_team_stats_prod15.json
Debug:
  football/debug/midnite_worldcup_team_stats_prod15/

Production props JSON is never modified.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_PATH = ROOT / "football" / "data" / "midnite_worldcup_props_fixtures_prod15.json"
OUT_PATH = ROOT / "football" / "data" / "midnite_worldcup_team_stats_prod15.json"
DEBUG_DIR = ROOT / "football" / "debug" / "midnite_worldcup_team_stats_prod15"
PROFILE_DIR = ROOT / "scripts" / "Football" / "midnite_team_stats_prod15_profile"

MAX_MATCHES = 15
TEST_START_INDEX = 0
HEADLESS = False
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

NEXT_HEADINGS = [
    "Total Shots on Target",
    "Total Shots",
    "Total Shots Outside the Box",
    "Total Fouls",
    "Total Cards",
    "Total Corners",
    "Team to Score",
    "Both Teams To Score",
    "Double Chance",
    "Half Result",
    "Half Time/Full Time",
]


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean(value).lower()).strip("-")


def frac_to_decimal(value: Any) -> float | None:
    text = clean(value).upper()
    if text in {"EVS", "EVENS"}:
        return 2.0
    try:
        return round(float(Fraction(text)) + 1.0, 4)
    except Exception:
        return None


def load_matches() -> list[dict[str, Any]]:
    if not FIXTURES_PATH.exists():
        raise FileNotFoundError(
            "Midnite fixture snapshot is missing. Run "
            "prepare_midnite_worldcup_props_fixtures.py first."
        )

    payload = json.loads(
        FIXTURES_PATH.read_text(
            encoding="utf-8"
        )
    )
    matches = payload.get(
        "matches",
        [],
    )

    if len(matches) != MAX_MATCHES:
        raise RuntimeError(
            f"Expected {MAX_MATCHES} fixtures in snapshot, "
            f"found {len(matches)}"
        )

    return matches


def dismiss_popups(page: Page) -> None:
    """
    Dismiss visible Cookiebot/Midnite overlays.

    Cookiebot leaves hidden buttons in the DOM, so only rendered controls are
    clicked.
    """
    try:
        page.evaluate(
            r"""() => {
                const visible = element => {
                    if (!element) return false;
                    const rect =
                        element.getBoundingClientRect();
                    const style =
                        window.getComputedStyle(element);
                    return (
                        rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                    );
                };

                const ids = [
                    "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
                    "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection",
                    "CybotCookiebotDialogBodyButtonAccept",
                    "CybotCookiebotDialogBodyLevelButtonAccept",
                    "CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll",
                    "CybotCookiebotDialogBodyButtonDecline",
                ];

                for (const id of ids) {
                    const button =
                        document.getElementById(id);
                    if (
                        button
                        && visible(button)
                    ) {
                        button.click();
                        return true;
                    }
                }

                const labels = [
                    "Confirm my choices",
                    "Allow all",
                    "Accept all",
                    "Accept All",
                    "Accept",
                    "Got it",
                    "Save",
                    "Reject all",
                    "Decline all",
                ];

                const buttons = Array.from(
                    document.querySelectorAll("button")
                ).filter(visible);

                for (const label of labels) {
                    const button = buttons.find(
                        element =>
                            (
                                element.innerText || ""
                            )
                            .replace(/\s+/g, " ")
                            .trim()
                            .toLowerCase()
                            === label.toLowerCase()
                    );

                    if (button) {
                        button.click();
                        return true;
                    }
                }

                return false;
            }"""
        )
    except Exception:
        pass

    page.wait_for_timeout(350)

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def wait_for_event_page(
    page: Page,
    home: str,
    away: str,
) -> bool:
    """
    Wait for a rendered Midnite event page.

    Exact team-name text is not required because Midnite may abbreviate or
    localise names differently from the moneylines JSON.
    """
    try:
        page.wait_for_function(
            r"""() => {
                const text = (
                    document.body?.innerText || ""
                ).replace(/\s+/g, " ").trim();

                const tabCount =
                    document.querySelectorAll(
                        '[data-cy="Tab"]'
                    ).length;

                const marketHits = [
                    "Match Result",
                    "Total Goals",
                    "Both Teams To Score",
                    "Double Chance",
                    "Player Shots",
                    "Total Shots",
                    "Total Cards",
                    "Total Corners",
                ].filter(label =>
                    text.includes(label)
                ).length;

                return (
                    text.length > 350
                    && (
                        tabCount >= 2
                        || marketHits >= 2
                    )
                );
            }""",
            timeout=18000,
        )
        return True
    except Exception:
        dismiss_popups(page)
        page.wait_for_timeout(700)

        try:
            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=3000
            )
        except Exception:
            return False

        market_hits = sum(
            marker in body_text
            for marker in (
                "Match Result",
                "Total Goals",
                "Both Teams To Score",
                "Double Chance",
                "Player Shots",
                "Total Shots",
                "Total Cards",
                "Total Corners",
            )
        )

        return (
            len(body_text) > 350
            and market_hits >= 2
        )


def click_all_tab(page: Page) -> None:
    try:
        tabs = page.locator('[data-cy="Tab"]')
        for i in range(min(tabs.count(), 12)):
            tab = tabs.nth(i)
            if clean(tab.inner_text(timeout=800)) == "All":
                tab.click(force=True, timeout=1500)
                page.wait_for_timeout(650)
                return
    except Exception:
        pass


def snapshot(page: Page, heading: str, scope: str, home: str, away: str) -> dict[str, Any] | None:
    """Return exact-card pills and row/odds pairs using viewport geometry."""
    try:
        return page.evaluate(
            r"""payload => {
                const heading = payload.heading;
                const scope = payload.scope;
                const home = payload.home;
                const away = payload.away;
                const nextHeadings = payload.nextHeadings;

                const norm = value => (value || '').replace(/\s+/g, ' ').trim();
                const direct = element => Array.from(element.childNodes)
                    .filter(node => node.nodeType === Node.TEXT_NODE)
                    .map(node => norm(node.textContent)).filter(Boolean).join(' ');
                const rendered = element => {
                    const r = element.getBoundingClientRect();
                    const s = getComputedStyle(element);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                };
                const own = element => direct(element) || (element.childElementCount === 0 ? norm(element.innerText) : '');

                const headings = Array.from(document.querySelectorAll('body *'))
                    .filter(rendered)
                    .filter(element => own(element) === heading)
                    .map(element => ({element, rect: element.getBoundingClientRect()}))
                    .filter(item => {
                        const cx = item.rect.left + item.rect.width / 2;
                        return cx >= 220 && cx <= window.innerWidth - 30;
                    })
                    .sort((a, b) => a.rect.width * a.rect.height - b.rect.width * b.rect.height);

                if (!headings.length) return null;
                const h = headings[0];
                h.element.scrollIntoView({block: 'center', inline: 'nearest'});
                const hr = h.element.getBoundingClientRect();

                const next = Array.from(document.querySelectorAll('body *'))
                    .filter(rendered)
                    .map(element => ({text: own(element), rect: element.getBoundingClientRect()}))
                    .filter(item => nextHeadings.includes(item.text) && item.text !== heading)
                    .filter(item => item.rect.top > hr.bottom + 4 && Math.abs(item.rect.left - hr.left) < 200)
                    .sort((a, b) => a.rect.top - b.rect.top);

                const region = {
                    left: Math.max(180, hr.left - 55),
                    right: window.innerWidth - 20,
                    top: hr.bottom + 2,
                    bottom: next.length ? next[0].rect.top - 5 : hr.bottom + 700,
                    headingX: hr.left + hr.width / 2,
                    headingY: hr.top + hr.height / 2,
                    nextHeading: next.length ? next[0].text : ''
                };

                const inside = element => {
                    const r = element.getBoundingClientRect();
                    const cx = r.left + r.width / 2;
                    const cy = r.top + r.height / 2;
                    return rendered(element) && cx >= region.left && cx <= region.right && cy >= region.top && cy <= region.bottom;
                };

                const all = Array.from(document.querySelectorAll('body *')).filter(inside);
                const pillLabels = ['Combined', 'Match', home, away].filter(Boolean);
                const pills = [];
                for (const label of pillLabels) {
                    const leaf = all
                        .filter(element => norm(element.innerText) === label)
                        .sort((a, b) => {
                            const ar = a.getBoundingClientRect();
                            const br = b.getBoundingClientRect();
                            return ar.width * ar.height - br.width * br.height;
                        })[0];
                    if (!leaf) continue;
                    let target = leaf;
                    for (let node = leaf; node && inside(node); node = node.parentElement) {
                        const tag = node.tagName.toLowerCase();
                        const role = (node.getAttribute('role') || '').toLowerCase();
                        const style = getComputedStyle(node);
                        if (tag === 'button' || role === 'button' || role === 'tab' || style.cursor === 'pointer') {
                            target = node;
                            break;
                        }
                    }
                    const r = target.getBoundingClientRect();
                    pills.push({label, x: r.left + r.width / 2, y: r.top + r.height / 2});
                }

                const requestedLabels = scope === 'Combined' ? ['Combined', 'Match'] : [scope];
                const requestedPill = pills.find(p => requestedLabels.includes(p.label)) || null;

                const thresholdCandidates = all.map(element => {
                    const text = own(element);
                    const m = text.match(/^(?:(.+?)\s+)?(\d+)\+$/);
                    if (!m) return null;
                    const prefix = norm(m[1] || '');
                    if (scope === 'Combined' && prefix) return null;
                    if (scope !== 'Combined' && prefix.toLowerCase() !== scope.toLowerCase()) return null;
                    const r = element.getBoundingClientRect();
                    return {label: text, threshold: Number(m[2]), x: r.left + r.width / 2, y: r.top + r.height / 2, area: r.width * r.height};
                }).filter(Boolean);

                const thresholdMap = new Map();
                for (const row of thresholdCandidates) {
                    const key = Math.round(row.y);
                    const old = thresholdMap.get(key);
                    if (!old || row.area < old.area) thresholdMap.set(key, row);
                }
                const thresholds = Array.from(thresholdMap.values()).sort((a, b) => a.y - b.y);

                const oddCandidates = all.map(element => {
                    const text = norm(element.innerText);
                    if (!/^(?:\d+\/\d+|EVS|EVENS)$/i.test(text)) return null;
                    const r = element.getBoundingClientRect();
                    const role = (element.getAttribute('role') || '').toLowerCase();
                    return {text, x: r.left + r.width / 2, y: r.top + r.height / 2, area: r.width * r.height, isButton: element.tagName.toLowerCase() === 'button' || role === 'button'};
                }).filter(Boolean);

                const oddMap = new Map();
                for (const odd of oddCandidates) {
                    const key = `${Math.round(odd.x)}|${Math.round(odd.y)}|${odd.text}`;
                    const old = oddMap.get(key);
                    if (!old || (odd.isButton && !old.isButton) || odd.area < old.area) oddMap.set(key, odd);
                }
                const odds = Array.from(oddMap.values());
                const used = new Set();
                const rows = [];

                for (const threshold of thresholds) {
                    let best = -1;
                    let bestScore = Infinity;
                    odds.forEach((odd, index) => {
                        if (used.has(index)) return;
                        const dy = Math.abs(odd.y - threshold.y);
                        const dx = odd.x - threshold.x;
                        if (dy > 35 || dx < 80) return;
                        const score = dy + Math.abs(dx) * 0.002;
                        if (score < bestScore) { bestScore = score; best = index; }
                    });
                    if (best < 0) continue;
                    used.add(best);
                    const odd = odds[best];
                    rows.push({
                        label: threshold.label,
                        threshold: threshold.threshold,
                        fractional_odds: odd.text,
                        label_y: threshold.y,
                        odds_y: odd.y,
                        vertical_delta: Math.round(Math.abs(odd.y - threshold.y) * 10) / 10
                    });
                }

                return {region, pills, requestedPill, rows, thresholdCount: thresholds.length, oddsCount: odds.length};
            }""",
            {"heading": heading, "scope": scope, "home": home, "away": away, "nextHeadings": NEXT_HEADINGS},
        )
    except Exception:
        return None


def ensure_open(page: Page, heading: str, home: str, away: str) -> bool:
    state = snapshot(page, heading, "Combined", home, away)
    if state and (state.get("pills") or state.get("rows")):
        return True
    if not state:
        # find and click the exact heading using a simple locator fallback
        try:
            loc = page.get_by_text(re.compile(rf"^{re.escape(heading)}$", re.I), exact=True)
            for i in range(min(loc.count(), 8)):
                item = loc.nth(i)
                if item.is_visible():
                    item.scroll_into_view_if_needed(timeout=1500)
                    item.click(force=True, timeout=1500)
                    break
        except Exception:
            return False
    else:
        page.mouse.click(float(state["region"]["headingX"]), float(state["region"]["headingY"]))
    for _ in range(16):
        page.wait_for_timeout(250)
        state = snapshot(page, heading, "Combined", home, away)
        if state and (state.get("pills") or state.get("rows")):
            return True
    return False


def select_scope(page: Page, heading: str, scope: str, home: str, away: str) -> dict[str, Any] | None:
    if not ensure_open(page, heading, home, away):
        return None

    state = snapshot(page, heading, scope, home, away)
    if state and state.get("rows"):
        return state

    pill = (state or {}).get("requestedPill")
    if not pill:
        return None

    page.mouse.click(float(pill["x"]), float(pill["y"]))
    for _ in range(24):
        page.wait_for_timeout(250)
        state = snapshot(page, heading, scope, home, away)
        if state and state.get("rows"):
            return state
    return None



def click_sot_scope_dropdown(
    page: Page,
    scope: str,
    home: str,
    away: str,
) -> bool:
    """
    Select Combined/Home/Away from the FIRST dropdown inside the exact
    Total Shots on Target market.

    Midnite's SOT card has two dropdowns:
        1. Combined / Home / Away
        2. Match / 1st Half / 2nd Half

    This function deliberately targets only the first dropdown.
    """
    heading = "Total Shots on Target"

    if not ensure_open(
        page,
        heading,
        home,
        away,
    ):
        return False

    try:
        trigger = page.evaluate(
            r"""payload => {
                const heading =
                    payload.heading;
                const home =
                    payload.home;
                const away =
                    payload.away;

                const norm = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const visible = element => {
                    if (!element) return false;

                    const rect =
                        element.getBoundingClientRect();
                    const style =
                        window.getComputedStyle(
                            element
                        );

                    return (
                        rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                    );
                };

                const directText = element =>
                    Array.from(
                        element.childNodes
                    )
                    .filter(
                        node =>
                            node.nodeType
                            === Node.TEXT_NODE
                    )
                    .map(
                        node =>
                            norm(node.textContent)
                    )
                    .filter(Boolean)
                    .join(" ");

                const exactText = element =>
                    directText(element)
                    || (
                        element.childElementCount
                            === 0
                        ? norm(element.innerText)
                        : ""
                    );

                const headingElement =
                    Array.from(
                        document.querySelectorAll(
                            "body *"
                        )
                    )
                    .filter(visible)
                    .find(
                        element =>
                            exactText(element)
                            === heading
                    );

                if (!headingElement) {
                    return null;
                }

                headingElement.scrollIntoView({
                    block: "center",
                    inline: "nearest",
                });

                const headingRect =
                    headingElement
                    .getBoundingClientRect();

                const allowed = [
                    "Combined",
                    home,
                    away,
                ];

                const candidates =
                    Array.from(
                        document.querySelectorAll(
                            "body *"
                        )
                    )
                    .filter(visible)
                    .filter(element => {
                        const text =
                            norm(element.innerText);

                        if (
                            !allowed.includes(text)
                        ) {
                            return false;
                        }

                        const rect =
                            element.getBoundingClientRect();
                        const centreY =
                            rect.top
                            + rect.height / 2;

                        return (
                            centreY
                                > headingRect.bottom
                            && centreY
                                < headingRect.bottom
                                    + 115
                            && rect.left
                                >= headingRect.left - 30
                            && rect.left
                                < headingRect.left + 450
                        );
                    })
                    .map(element => {
                        let target = element;

                        for (
                            let node = element;
                            node
                            && node
                                !== document.body;
                            node =
                                node.parentElement
                        ) {
                            const rect =
                                node.getBoundingClientRect();

                            if (
                                rect.top
                                    < headingRect.bottom
                                || rect.top
                                    > headingRect.bottom
                                        + 120
                            ) {
                                break;
                            }

                            const tag =
                                node.tagName
                                    .toLowerCase();
                            const role = (
                                node.getAttribute(
                                    "role"
                                ) || ""
                            ).toLowerCase();
                            const style =
                                window.getComputedStyle(
                                    node
                                );

                            if (
                                tag === "button"
                                || role === "button"
                                || role === "combobox"
                                || style.cursor
                                    === "pointer"
                            ) {
                                target = node;
                                break;
                            }
                        }

                        const rect =
                            target
                            .getBoundingClientRect();

                        return {
                            label:
                                norm(
                                    element.innerText
                                ),
                            x:
                                rect.left
                                + rect.width / 2,
                            y:
                                rect.top
                                + rect.height / 2,
                            left:
                                rect.left,
                            top:
                                rect.top,
                            area:
                                rect.width
                                * rect.height,
                        };
                    })
                    .sort((a, b) => {
                        if (
                            Math.abs(
                                a.top - b.top
                            ) > 6
                        ) {
                            return a.top - b.top;
                        }

                        if (
                            Math.abs(
                                a.left - b.left
                            ) > 6
                        ) {
                            return a.left - b.left;
                        }

                        return a.area - b.area;
                    });

                return candidates[0] || null;
            }""",
            {
                "heading": heading,
                "home": home,
                "away": away,
            },
        )
    except Exception:
        trigger = None

    if not trigger:
        return False

    page.mouse.click(
        float(trigger["x"]),
        float(trigger["y"]),
    )
    page.wait_for_timeout(350)

    desired = (
        "Combined"
        if scope == "Combined"
        else scope
    )

    try:
        option = page.evaluate(
            r"""payload => {
                const desired =
                    payload.desired;
                const trigger =
                    payload.trigger;

                const norm = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const visible = element => {
                    if (!element) return false;

                    const rect =
                        element.getBoundingClientRect();
                    const style =
                        window.getComputedStyle(
                            element
                        );

                    return (
                        rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                    );
                };

                const leaves =
                    Array.from(
                        document.querySelectorAll(
                            "body *"
                        )
                    )
                    .filter(visible)
                    .filter(element =>
                        element.childElementCount
                            === 0
                        && norm(
                            element.innerText
                        ) === desired
                    )
                    .map(element => {
                        let target = element;
                        let popupLike = false;

                        for (
                            let node = element;
                            node
                            && node
                                !== document.body;
                            node =
                                node.parentElement
                        ) {
                            const cls =
                                String(
                                    node.className
                                    || ""
                                ).toLowerCase();
                            const role = (
                                node.getAttribute(
                                    "role"
                                ) || ""
                            ).toLowerCase();
                            const style =
                                window.getComputedStyle(
                                    node
                                );

                            if (
                                cls.includes(
                                    "popper"
                                )
                                || cls.includes(
                                    "dropdown"
                                )
                                || cls.includes(
                                    "menu"
                                )
                                || role === "menu"
                                || role === "listbox"
                                || style.position
                                    === "absolute"
                                || style.position
                                    === "fixed"
                            ) {
                                popupLike = true;
                            }

                            const tag =
                                node.tagName
                                    .toLowerCase();

                            if (
                                tag === "button"
                                || role === "option"
                                || role === "menuitem"
                                || role === "button"
                                || tag === "li"
                                || style.cursor
                                    === "pointer"
                            ) {
                                target = node;
                            }

                            const rect =
                                node.getBoundingClientRect();

                            if (
                                rect.width > 420
                                || rect.height > 420
                            ) {
                                break;
                            }
                        }

                        const rect =
                            target
                            .getBoundingClientRect();
                        const cx =
                            rect.left
                            + rect.width / 2;
                        const cy =
                            rect.top
                            + rect.height / 2;
                        const distance =
                            Math.abs(
                                cx - trigger.x
                            )
                            + Math.abs(
                                cy - trigger.y
                            );

                        return {
                            x: cx,
                            y: cy,
                            distance,
                            popupLike,
                            area:
                                rect.width
                                * rect.height,
                        };
                    })
                    .filter(item =>
                        item.y
                            > trigger.y - 80
                        && item.y
                            < trigger.y + 420
                        && Math.abs(
                            item.x - trigger.x
                        ) < 360
                    )
                    .sort((a, b) => {
                        if (
                            a.popupLike
                            !== b.popupLike
                        ) {
                            return (
                                a.popupLike
                                ? -1
                                : 1
                            );
                        }

                        if (
                            Math.abs(
                                a.distance
                                - b.distance
                            ) > 5
                        ) {
                            return (
                                a.distance
                                - b.distance
                            );
                        }

                        return a.area - b.area;
                    });

                return leaves[0] || null;
            }""",
            {
                "desired": desired,
                "trigger": trigger,
            },
        )
    except Exception:
        option = None

    if not option:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    page.mouse.click(
        float(option["x"]),
        float(option["y"]),
    )
    page.wait_for_timeout(450)
    return True


def select_sot_scope(
    page: Page,
    scope: str,
    home: str,
    away: str,
) -> dict[str, Any] | None:
    """
    Select and verify one SOT scope using the first dropdown.
    """
    heading = "Total Shots on Target"

    state = snapshot(
        page,
        heading,
        scope,
        home,
        away,
    )

    if state and state.get("rows"):
        return state

    if not click_sot_scope_dropdown(
        page,
        scope,
        home,
        away,
    ):
        return None

    for _ in range(24):
        page.wait_for_timeout(250)

        state = snapshot(
            page,
            heading,
            scope,
            home,
            away,
        )

        if state and state.get("rows"):
            return state

    return None


def build_ladder(state: dict[str, Any] | None) -> tuple[dict[str, float], list[dict[str, Any]]]:
    ladder: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    if not state:
        return ladder, rows
    for row in state.get("rows") or []:
        decimal = frac_to_decimal(row.get("fractional_odds"))
        if decimal is None or decimal <= 1:
            continue
        threshold = int(row["threshold"])
        ladder[f"over_{threshold}"] = decimal
        saved = dict(row)
        saved["decimal_odds"] = decimal
        rows.append(saved)
    return ladder, rows


def open_event_with_retries(
    context,
    match: dict[str, Any],
    attempts: int = 3,
) -> Page:
    """
    Open each fixture on a fresh page and retry intermittent Midnite loads.
    """
    home = clean(match.get("home"))
    away = clean(match.get("away"))
    url = clean(match.get("url"))

    last_error = None

    for attempt in range(1, attempts + 1):
        if context.pages is None:
            raise RuntimeError(
                "Persistent browser context is unavailable"
            )

        page = context.new_page()

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except Exception as error:
            last_error = error

        page.wait_for_timeout(
            900 + attempt * 350
        )
        dismiss_popups(page)

        if wait_for_event_page(
            page,
            home,
            away,
        ):
            dismiss_popups(page)
            click_all_tab(page)
            page.wait_for_timeout(700)
            return page

        try:
            page.reload(
                wait_until="domcontentloaded",
                timeout=25000,
            )
        except Exception as error:
            last_error = error

        page.wait_for_timeout(
            1000 + attempt * 300
        )
        dismiss_popups(page)

        if wait_for_event_page(
            page,
            home,
            away,
        ):
            dismiss_popups(page)
            click_all_tab(page)
            page.wait_for_timeout(700)
            return page

        try:
            page.close()
        except Exception:
            pass

    raise RuntimeError(
        "Midnite event content did not load "
        f"after {attempts} attempts"
        + (
            f": {last_error}"
            if last_error
            else ""
        )
    )


def scrape_fixture(page: Page, match: dict[str, Any]) -> dict[str, Any]:
    home = clean(match.get("home"))
    away = clean(match.get("away"))
    url = clean(match.get("url"))
    if not home or not away or not url:
        raise RuntimeError("Fixture missing home, away or URL")

    dismiss_popups(page)
    click_all_tab(page)
    page.wait_for_timeout(500)

    targets = [
        ("Total Shots on Target", "Combined", "total_shots_on_target"),
        ("Total Shots on Target", home, "home_shots_on_target"),
        ("Total Shots on Target", away, "away_shots_on_target"),
        ("Total Shots", "Combined", "total_shots"),
        ("Total Shots", home, "home_shots"),
        ("Total Shots", away, "away_shots"),
    ]

    markets: dict[str, dict[str, float]] = {}
    audit: dict[str, Any] = {}

    for heading, scope, key in targets:
        if heading == "Total Shots on Target":
            state = select_sot_scope(
                page,
                scope,
                home,
                away,
            )
        else:
            state = select_scope(
                page,
                heading,
                scope,
                home,
                away,
            )

        ladder, rows = build_ladder(state)
        audit[key] = {"heading": heading, "scope": scope, "rows": rows, "raw": state or {}}
        if ladder:
            markets[key] = ladder
            print(f"    {key}: {len(ladder)} lines -> {', '.join(ladder.keys())}")
        else:
            print(f"    {key}: unavailable")

    removed = []
    for sot_key, shots_key in [
        ("total_shots_on_target", "total_shots"),
        ("home_shots_on_target", "home_shots"),
        ("away_shots_on_target", "away_shots"),
    ]:
        if markets.get(sot_key) and markets.get(sot_key) == markets.get(shots_key):
            markets.pop(sot_key, None)
            removed.append(sot_key)

    market_count = len(markets)
    availability_status = (
        "complete"
        if market_count == 6
        else (
            "unavailable"
            if market_count == 0
            else "partial"
        )
    )

    return {
        "match_id": clean(match.get("match_id")),
        "event_id": clean(match.get("event_id")),
        "home": home,
        "away": away,
        "kickoff": clean(match.get("kickoff")),
        "bookmaker": "Midnite",
        "url": url,
        "market_count": market_count,
        "availability_status": availability_status,
        "markets": markets,
        "removed_identical_sot_markets": removed,
        "audit": audit,
    }


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    matches = load_matches()

    if len(matches) != MAX_MATCHES:
        raise RuntimeError(
            f"Expected {MAX_MATCHES} fixtures from moneylines, "
            f"found {len(matches)}"
        )

    print("=" * 72)
    print("MIDNITE WORLD CUP TEAM STATS PROD15")
    print("=" * 72)
    print("No expected threshold values or consecutive-line assumptions")
    print("Temporary stage output only — production JSON is not modified here")

    results = []
    errors = []
    started = time.perf_counter()

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=HEADLESS,
            viewport={"width": 1500, "height": 950},
            user_agent=USER_AGENT,
            locale="en-GB",
        )
        # Keep one page alive for the lifetime of the persistent context.
        # Closing the final page can close the whole context/browser.
        keeper_page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        try:
            keeper_page.goto(
                "about:blank",
                wait_until="domcontentloaded",
                timeout=5000,
            )
        except Exception:
            pass

        for index, match in enumerate(matches, 1):
            label = f"{match.get('home', '?')} v {match.get('away', '?')}"
            print(f"\n[{index}/{len(matches)}] {label}")
            page = None

            try:
                page = open_event_with_retries(
                    context,
                    match,
                    attempts=3,
                )
                result = scrape_fixture(
                    page,
                    match,
                )
                results.append(result)
                stem = slugify(label)
                (DEBUG_DIR / f"{stem}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                page.screenshot(path=str(DEBUG_DIR / f"{stem}.png"), full_page=True)
            except Exception as error:
                print(f"    ERROR: {error}")

                stem = slugify(label)

                try:
                    if page is None:
                        raise RuntimeError(
                            "No page available"
                        )

                    page.screenshot(
                        path=str(
                            DEBUG_DIR
                            / f"{stem}_error.png"
                        ),
                        full_page=True,
                    )
                except Exception:
                    pass

                try:
                    if page is None:
                        raise RuntimeError(
                            "No page available"
                        )

                    body_text = page.locator(
                        "body"
                    ).inner_text(
                        timeout=3000
                    )
                    (
                        DEBUG_DIR
                        / f"{stem}_error.txt"
                    ).write_text(
                        body_text,
                        encoding="utf-8",
                    )
                except Exception:
                    pass

                errors.append({
                    "match": label,
                    "url": match.get("url"),
                    "error": str(error),
                })
            finally:
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass

        context.close()

    elapsed = time.perf_counter() - started
    output = {
        "bookmaker": "Midnite",
        "competition": "FIFA World Cup 2026",
        "market_type": "match_and_team_shots",
        "core_markets": [
            "total_shots_on_target",
            "total_shots",
            "home_shots",
            "away_shots",
        ],
        "required_markets": [
            "total_shots_on_target",
            "home_shots_on_target",
            "away_shots_on_target",
            "total_shots",
            "home_shots",
            "away_shots",
        ],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "production_stage": True,
        "production_modified": False,
        "max_matches": MAX_MATCHES,
        "start_index": TEST_START_INDEX,
        "match_count": len(results),
        "error_count": len(errors),
        "errors": errors,
        "elapsed_seconds": round(elapsed, 3),
        "matches": results,
    }
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    all_six = sum(
        1
        for result in results
        if result.get("market_count") == 6
    )
    unavailable = sum(
        1
        for result in results
        if result.get("market_count") == 0
    )
    partial = [
        result
        for result in results
        if result.get("market_count") not in {0, 6}
    ]

    output["availability_summary"] = {
        "complete": all_six,
        "unavailable": unavailable,
        "partial": len(partial),
    }
    OUT_PATH.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("MIDNITE TEAM STATS PROD15 COMPLETE")
    print("=" * 72)
    print(f"Matches scraped: {len(results)}/{MAX_MATCHES}")
    print(
        "Fixtures with all six markets: "
        f"{all_six}"
    )
    print(
        "Fixtures with no published team stats: "
        f"{unavailable}"
    )
    print(
        "Partial fixtures: "
        f"{len(partial)}"
    )
    print(f"Errors: {len(errors)}")
    print(f"Elapsed: {elapsed:.2f}s")
    print(f"Wrote: {OUT_PATH}")
    print(f"Debug: {DEBUG_DIR}")
    print("Production JSON modified: NO")
    print("=" * 72)

    if partial:
        print("")
        print(
            "PARTIAL TEAM-STAT SETS DETECTED "
            "(production will not continue):"
        )
        for result in partial:
            print(
                "  - "
                f"{result.get('home')} v "
                f"{result.get('away')}: "
                f"{result.get('market_count')}/6"
            )

    if (
        errors
        or len(results) != MAX_MATCHES
        or partial
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
