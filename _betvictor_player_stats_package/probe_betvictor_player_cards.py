#!/usr/bin/env python3
"""
probe_betvictor_player_cards.py

Read-only Argentina v Austria card-market discovery probe.

It checks the base event plus the Player and Cards-style views, then prints
every unique line containing:
    card, booked, booking, yellow, red, caution

It does not modify any JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_player_cards_DISCOVERY.json"
DEBUG_DIR = ROOT / "football" / "debug" / "betvictor_player_cards_discovery"

MATCH_NAME = "Argentina v Austria"
PLAYER_GROUP = "19296"
HEADLESS = False

KEYWORDS = re.compile(
    r"\b(card|carded|booked|booking|yellow|red|caution)\b",
    re.I,
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_url():
    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))

    for match in data.get("matches", []):
        if clean(match.get("match")) == MATCH_NAME:
            url = clean(match.get("source_url") or match.get("url"))
            return url.split("?", 1)[0]

    raise SystemExit(f"Missing {MATCH_NAME}")


def accept_cookies(page):
    for label in (
        "Accept All", "Accept all", "I Accept",
        "Accept", "Agree", "Allow all", "OK",
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


def click_exact(page, label):
    try:
        locator = page.get_by_text(label, exact=True)

        for index in range(locator.count() - 1, -1, -1):
            item = locator.nth(index)

            try:
                if not item.is_visible():
                    continue
                item.scroll_into_view_if_needed(timeout=2000)
                item.click(timeout=2500)
                page.wait_for_timeout(1200)
                return True
            except Exception:
                pass
    except Exception:
        pass

    return False


def expand_and_scroll(page):
    for _ in range(10):
        changed = False

        for label in ("Show More", "View More", "Load More", "Show All"):
            try:
                locator = page.get_by_role(
                    "button",
                    name=re.compile(f"^{label}$", re.I),
                )

                for index in range(locator.count()):
                    item = locator.nth(index)

                    try:
                        if not item.is_visible():
                            continue
                        item.click(timeout=1500)
                        page.wait_for_timeout(500)
                        changed = True
                    except Exception:
                        pass
            except Exception:
                pass

        if not changed:
            break

    for _ in range(30):
        page.mouse.wheel(0, 650)
        page.wait_for_timeout(220)


def collect(page, label):
    expand_and_scroll(page)
    body = page.locator("body").inner_text(timeout=25000)
    lines = [clean(line) for line in body.splitlines() if clean(line)]

    hits = []
    seen = set()

    for index, line in enumerate(lines):
        if not KEYWORDS.search(line):
            continue

        context = lines[max(0, index - 2):min(len(lines), index + 5)]
        key = tuple(context)

        if key in seen:
            continue
        seen.add(key)

        hits.append(
            {
                "line": line,
                "context": context,
            }
        )

    return {
        "view": label,
        "url": page.url,
        "hits": hits,
        "body": body,
    }


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    base_url = load_url()
    views = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        page.goto(base_url, wait_until="domcontentloaded", timeout=70000)
        page.wait_for_timeout(6000)
        accept_cookies(page)
        views.append(collect(page, "base"))

        for label in ("Popular", "Player", "Cards", "Bet Builder"):
            page.goto(base_url, wait_until="domcontentloaded", timeout=70000)
            page.wait_for_timeout(4500)
            accept_cookies(page)
            clicked = click_exact(page, label)
            view = collect(page, f"{label} clicked={clicked}")
            views.append(view)

        page.goto(
            f"{base_url}?market_group={PLAYER_GROUP}",
            wait_until="domcontentloaded",
            timeout=70000,
        )
        page.wait_for_timeout(5000)
        accept_cookies(page)
        views.append(collect(page, "market_group=19296"))

        browser.close()

    compact = []

    for view in views:
        compact.append(
            {
                "view": view["view"],
                "url": view["url"],
                "hits": view["hits"],
            }
        )

        safe_name = re.sub(
            r"[^a-z0-9]+",
            "_",
            view["view"].lower(),
        ).strip("_")
        (DEBUG_DIR / f"{safe_name}.txt").write_text(
            view["body"],
            encoding="utf-8",
        )

    OUT_PATH.write_text(
        json.dumps(
            {
                "match": MATCH_NAME,
                "source_url": base_url,
                "views": compact,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("BETVICTOR CARD DISCOVERY")
    print("=" * 72)

    for view in compact:
        print(f"\n{view['view']} | hits={len(view['hits'])}")

        for hit in view["hits"][:30]:
            print("  " + " | ".join(hit["context"]))

    print(f"\nSaved: {OUT_PATH}")
    print("The main BetVictor props JSON was NOT changed.")


if __name__ == "__main__":
    main()
