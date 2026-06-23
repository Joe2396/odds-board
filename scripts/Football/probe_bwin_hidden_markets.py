#!/usr/bin/env python3
"""
probe_bwin_hidden_markets.py

Fast one-match diagnostic for Bwin's collapsed player-market rows.

This does NOT replace the working scraper and does NOT write production odds.
It opens one event, enters the Players tab, finds the exact market headings,
tests likely clickable ancestors one at a time, and reports which DOM depth
actually expands a card containing odds.

Output:
    football/debug/bwin_worldcup_props/bwin_hidden_market_probe.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MONEYLINES = ROOT / "football" / "data" / "bwin_worldcup_moneylines.json"
OUT = (
    ROOT
    / "football"
    / "debug"
    / "bwin_worldcup_props"
    / "bwin_hidden_market_probe.json"
)

HEADLESS = False

TARGETS = [
    "To be shown a Card",
    "Player Total Tackles",
    "Player Total Assists",
    "Player Total Fouls",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_match() -> dict:
    payload = json.loads(MONEYLINES.read_text(encoding="utf-8"))
    matches = payload.get("matches") or []

    for row in matches:
        name = clean(row.get("match"))
        if name.lower() == "england v ghana":
            return row

    for row in matches:
        url = clean(row.get("source_url"))
        if "/sports/events/" in url:
            return row

    raise RuntimeError("No usable Bwin event found.")


def dismiss_cookies(page) -> None:
    for label in ["Allow All", "Accept All", "Accept all", "Accept"]:
        try:
            locator = page.get_by_text(
                re.compile(rf"^{re.escape(label)}$", re.I),
                exact=True,
            )
            if locator.count():
                locator.first.click(timeout=1800, force=True)
                page.wait_for_timeout(400)
                return
        except Exception:
            continue


def click_tab(page, label: str) -> bool:
    locators = [
        page.get_by_role(
            "tab",
            name=re.compile(rf"^{re.escape(label)}$", re.I),
        ),
        page.get_by_text(
            re.compile(rf"^{re.escape(label)}$", re.I),
            exact=True,
        ),
    ]

    for locator in locators:
        try:
            for index in range(min(locator.count(), 8)):
                item = locator.nth(index)
                if not item.is_visible():
                    continue
                box = item.bounding_box()
                if not box:
                    continue
                centre = box["x"] + box["width"] / 2
                if not 250 <= centre <= 1235:
                    continue
                item.click(timeout=2000, force=True)
                page.wait_for_timeout(700)
                return True
        except Exception:
            continue

    return False


def click_show_more(page, max_clicks: int = 12) -> int:
    clicked = 0

    for _ in range(max_clicks):
        locator = page.get_by_text(
            re.compile(r"^(Show More|View More)$", re.I),
            exact=True,
        )

        candidate = None
        try:
            for index in range(min(locator.count(), 20)):
                item = locator.nth(index)
                if not item.is_visible():
                    continue
                box = item.bounding_box()
                if not box:
                    continue
                centre = box["x"] + box["width"] / 2
                if 250 <= centre <= 1235:
                    candidate = item
                    break
        except Exception:
            candidate = None

        if candidate is None:
            break

        try:
            candidate.scroll_into_view_if_needed(timeout=1600)
            candidate.click(timeout=1600, force=True)
            page.wait_for_timeout(350)
            clicked += 1
        except Exception:
            break

    return clicked


def card_with_odds_visible(page, heading: str) -> bool:
    return bool(
        page.evaluate(
            r"""
            heading => {
                const clean = value =>
                    (value || "").replace(/\s+/g, " ").trim();

                const norm = value =>
                    clean(value).toLowerCase()
                        .replace(/[^a-z0-9]+/g, " ").trim();

                const oddRe = /^\d{1,3}[.,]\d{1,3}$/;
                const target = norm(heading);

                for (const element of document.querySelectorAll("body *")) {
                    if (norm(element.innerText) !== target) {
                        continue;
                    }

                    let node = element;

                    for (
                        let depth = 0;
                        depth < 9 && node;
                        depth += 1, node = node.parentElement
                    ) {
                        const rect = node.getBoundingClientRect();
                        if (
                            rect.width < 180
                            || rect.width > 1050
                            || rect.height < 35
                            || rect.height > 1800
                        ) {
                            continue;
                        }

                        const lines = clean(node.innerText)
                            .split(/\n+/)
                            .map(clean)
                            .filter(Boolean);

                        if (
                            lines.length > 2
                            && norm(lines[0]) === target
                            && lines.some(line => oddRe.test(line))
                        ) {
                            return true;
                        }
                    }
                }

                return false;
            }
            """,
            heading,
        )
    )


def inspect_target(page, heading: str) -> dict:
    result = {
        "heading": heading,
        "found": False,
        "opened": False,
        "successful_depth": None,
        "candidates": [],
    }

    if card_with_odds_visible(page, heading):
        result["found"] = True
        result["opened"] = True
        result["successful_depth"] = "already-open"
        return result

    # Sweep all scrollable panes so virtualised rows are mounted.
    for sweep in range(18):
        candidate = page.evaluate(
            r"""
            ({heading, sweep}) => {
                const clean = value =>
                    (value || "").replace(/\s+/g, " ").trim();

                const norm = value =>
                    clean(value).toLowerCase()
                        .replace(/[^a-z0-9]+/g, " ").trim();

                const target = norm(heading);
                const matches = [];

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

                    const text = clean(element.innerText);
                    if (norm(text) !== target) {
                        continue;
                    }

                    const centreX = rect.left + rect.width / 2;
                    if (centreX < 250 || centreX > 1235) {
                        continue;
                    }

                    matches.push({
                        text,
                        x: rect.left,
                        y: rect.top,
                        width: rect.width,
                        height: rect.height,
                    });
                }

                if (!matches.length) {
                    for (const element of document.querySelectorAll("body *")) {
                        const style = getComputedStyle(element);
                        if (
                            /(auto|scroll)/.test(style.overflowY || "")
                            && element.scrollHeight
                                > element.clientHeight + 80
                        ) {
                            element.scrollTop = Math.min(
                                element.scrollHeight,
                                sweep * 550
                            );
                        }
                    }
                    window.scrollTo(0, sweep * 550);
                    return null;
                }

                matches.sort((a, b) => {
                    const av = a.y >= 0 && a.y < innerHeight;
                    const bv = b.y >= 0 && b.y < innerHeight;
                    if (av !== bv) {
                        return av ? -1 : 1;
                    }
                    return a.width * a.height - b.width * b.height;
                });

                const best = matches[0];
                const leaf = document.elementFromPoint(
                    Math.max(1, Math.min(innerWidth - 2, best.x + best.width / 2)),
                    Math.max(1, Math.min(innerHeight - 2, best.y + best.height / 2))
                );

                const exact = Array.from(document.querySelectorAll(
                    "div, span, button, [role='button']"
                )).find(element => {
                    const rect = element.getBoundingClientRect();
                    return (
                        norm(element.innerText) === target
                        && Math.abs(rect.left - best.x) < 2
                        && Math.abs(rect.top - best.y) < 2
                        && Math.abs(rect.width - best.width) < 2
                    );
                });

                if (!exact) {
                    return null;
                }

                exact.scrollIntoView({
                    block: "center",
                    inline: "nearest",
                    behavior: "instant",
                });

                const chain = [];
                let node = exact;

                for (
                    let depth = 0;
                    depth < 8 && node;
                    depth += 1, node = node.parentElement
                ) {
                    const rect = node.getBoundingClientRect();
                    const style = getComputedStyle(node);

                    chain.push({
                        depth,
                        tag: node.tagName,
                        role: node.getAttribute("role") || "",
                        ariaExpanded:
                            node.getAttribute("aria-expanded"),
                        className: String(node.className || "").slice(0, 220),
                        cursor: style.cursor,
                        x: rect.left,
                        y: rect.top,
                        width: rect.width,
                        height: rect.height,
                        text: clean(node.innerText).slice(0, 220),
                    });
                }

                exact.setAttribute("data-btb-probe", "0");
                return {chain};
            }
            """,
            {"heading": heading, "sweep": sweep},
        )

        page.wait_for_timeout(180)

        if candidate:
            result["found"] = True
            result["candidates"] = candidate.get("chain") or []
            break

    if not result["found"]:
        return result

    # Try only compact ancestor rows. This finishes in seconds, not minutes.
    for entry in result["candidates"]:
        depth = entry.get("depth")
        width = float(entry.get("width") or 0)
        height = float(entry.get("height") or 0)

        if not (
            0 <= int(depth) <= 6
            and 180 <= width <= 1050
            and 28 <= height <= 115
        ):
            continue

        try:
            page.evaluate(
                r"""
                ({depth}) => {
                    let node = document.querySelector(
                        '[data-btb-probe="0"]'
                    );
                    for (let index = 0; index < depth && node; index += 1) {
                        node = node.parentElement;
                    }
                    if (!node) {
                        return false;
                    }

                    node.scrollIntoView({
                        block: "center",
                        inline: "nearest",
                        behavior: "instant",
                    });
                    node.setAttribute(
                        "data-btb-click-depth",
                        String(depth)
                    );
                    return true;
                }
                """,
                {"depth": depth},
            )
            page.wait_for_timeout(180)

            row = page.locator(
                f'[data-btb-click-depth="{depth}"]'
            ).first
            row.click(timeout=1800, force=True)
            page.wait_for_timeout(800)

            if card_with_odds_visible(page, heading):
                result["opened"] = True
                result["successful_depth"] = depth
                return result
        except Exception as error:
            entry["click_error"] = str(error)

    return result


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed.")
        return 1

    match = load_match()
    url = clean(match.get("source_url"))
    name = clean(match.get("match"))

    print(f"Opening diagnostic match: {name}")
    print(url)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-background-networking",
                "--disable-extensions",
                "--mute-audio",
                "--no-first-run",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1700, "height": 1000},
            user_agent=USER_AGENT,
            locale="en-GB",
        )
        page = context.new_page()

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=90000,
        )
        page.wait_for_timeout(5000)
        dismiss_cookies(page)

        if not click_tab(page, "Players"):
            print("Players tab was not found.")
            browser.close()
            return 1

        expanded = click_show_more(page)
        print(f"Players Show More clicks: {expanded}")

        for heading in TARGETS:
            print(f"\nTesting: {heading}")
            result = inspect_target(page, heading)
            results.append(result)

            if result["opened"]:
                print(
                    "  OPENED at ancestor depth "
                    f"{result['successful_depth']}"
                )
            elif result["found"]:
                print("  heading found, but no tested ancestor opened it")
            else:
                print("  heading was not mounted/found")

        OUT.write_text(
            json.dumps(
                {
                    "match": name,
                    "url": url,
                    "results": results,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        browser.close()

    print("")
    print(f"Probe output: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
