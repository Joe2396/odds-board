#!/usr/bin/env python3
"""
probe_betvictor_argentina_player_markets.py

Read-only probe for the current Argentina v Austria BetVictor player markets.

Checks exact live rows for:
- Player Shots On Target
- Player Shots
- Player Fouls
- Player Cards / To Be Carded

It uses the same Show More + scroll-container harvesting method that fixed
Player Tackles. It does not modify betvictor_worldcup_props.json.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_argentina_player_markets_PROBE.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_argentina_player_markets_probe"

MATCH_NAME = "Argentina v Austria"
PLAYER_GROUP = "19296"
HEADLESS = False

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN)$", re.I)

MARKETS = {
    "player_shots_on_target": {
        "label": "Player Shots On Target",
        "tab": "Player",
        "headings": ["Player Shots on Target", "Player Shots On Target"],
        "row_re": re.compile(
            r"^(.+?)\s+(\d+)\+\s+Shots?\s+On\s+Target$",
            re.I,
        ),
        "prop_type": "shots_on_target",
    },
    "player_shots": {
        "label": "Player Shots",
        "tab": "Player",
        "headings": ["Player Shots"],
        "row_re": re.compile(
            r"^(.+?)\s+(\d+)\+\s+Shots?$",
            re.I,
        ),
        "prop_type": "shots",
    },
    "player_fouls_committed": {
        "label": "Player Fouls Committed",
        "tab": "Player",
        "headings": ["Player Fouls", "Player Fouls Committed"],
        "row_re": re.compile(
            r"^(.+?)\s+(\d+)\+\s+Fouls?(?:\s+Committed)?$",
            re.I,
        ),
        "prop_type": "fouls_committed",
    },
}

CARD_HEADINGS = [
    "Player To Be Carded",
    "Player to Be Carded",
    "Player To Get A Card",
    "Player to Get a Card",
    "Player Cards",
    "To Be Carded",
]

CARD_ROW_PATTERNS = [
    re.compile(r"^(.+?)\s+To\s+Be\s+Carded$", re.I),
    re.compile(r"^(.+?)\s+To\s+Get\s+A\s+Card$", re.I),
    re.compile(r"^(.+?)\s+Carded$", re.I),
    re.compile(r"^(.+?)\s+To\s+Receive\s+A\s+Card$", re.I),
    re.compile(r"^(.+?)\s+Shown\s+A\s+Card$", re.I),
]


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def load_event_url():
    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))

    for match in data.get("matches", []):
        if clean(match.get("match")) != MATCH_NAME:
            continue

        url = clean(match.get("source_url") or match.get("url"))
        if "/events/" not in url:
            raise SystemExit(f"{MATCH_NAME} has no usable BetVictor event URL.")
        return url.split("?", 1)[0]

    raise SystemExit(f"Could not find {MATCH_NAME} in {PROPS_PATH}")


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
                .querySelectorAll('[data-bv-probe-scroll-id]')
                .forEach(el => el.removeAttribute('data-bv-probe-scroll-id'));

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
                item.el.setAttribute(
                    'data-bv-probe-scroll-id',
                    String(index)
                );

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


def extract_visible_threshold_rows(page, pattern_source):
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


def harvest_window(page, extractor):
    store = {}

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

    return store


def harvest_containers(page, extractor, store):
    containers = mark_scroll_containers(page)

    for info in containers:
        locator = page.locator(
            f'[data-bv-probe-scroll-id="{info["id"]}"]'
        )

        if not locator.count():
            continue

        try:
            client_height = int(
                locator.evaluate("(el) => el.clientHeight")
            )
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
            locator.evaluate(
                "(el) => { el.scrollTop = el.scrollHeight; }"
            )
            page.wait_for_timeout(450)
            add_rows(store, extractor())
        except Exception:
            pass

    return containers


def parse_threshold_rows(rows, row_re, prop_type, market_label):
    selections = []
    seen = set()

    for row in rows:
        label = clean(row.get("label"))
        match = row_re.fullmatch(label)

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
                "selection": f"{player} {threshold} {market_label}",
                "normalized_selection": normalize(
                    f"{player} {threshold} {market_label}"
                ),
                "odds": odds,
                "player": player,
                "threshold": threshold,
                "prop_type": prop_type,
            }
        )

    selections.sort(
        key=lambda item: (
            normalize(item["player"]),
            int(item["threshold"].rstrip("+")),
        )
    )

    return selections


def probe_threshold_market(browser, base_url, key, config):
    context = browser.new_context(viewport={"width": 1700, "height": 1000})
    page = context.new_page()
    debug_dir = DEBUG_ROOT / key
    debug_dir.mkdir(parents=True, exist_ok=True)

    url = f"{base_url}?market_group={PLAYER_GROUP}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=70000)
        page.wait_for_timeout(6000)
        accept_cookies(page)

        click_exact_text(page, [config["tab"]])
        heading_clicked = click_exact_text(page, config["headings"])
        more_clicked = click_more_controls(page)

        pattern_source = config["row_re"].pattern
        extractor = lambda: extract_visible_threshold_rows(
            page,
            pattern_source,
        )

        store = harvest_window(page, extractor)
        containers = harvest_containers(page, extractor, store)

        # A second expansion pass catches controls revealed lower down.
        more_clicked += click_more_controls(page)
        add_rows(store, extractor())
        harvest_containers(page, extractor, store)

        rows = list(store.values())
        selections = parse_threshold_rows(
            rows,
            config["row_re"],
            config["prop_type"],
            config["label"].replace("Player ", ""),
        )

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
            "market": config["label"],
            "normalized_market": key,
            "heading_clicked": heading_clicked,
            "expansion_controls_clicked": more_clicked,
            "selection_count": len(selections),
            "selections": selections,
        }

    finally:
        context.close()


def plausible_player_name(value):
    value = clean(value)

    if not 3 <= len(value) <= 70:
        return False
    if ODDS_RE.fullmatch(value):
        return False
    if re.search(r"\d", value):
        return False
    if value.lower() in {
        "player cards",
        "player to be carded",
        "player to get a card",
        "cards",
        "show more",
        "show less",
    }:
        return False
    if value.lower().startswith(
        (
            "over ",
            "under ",
            "total ",
            "match ",
            "first ",
            "last ",
            "both ",
        )
    ):
        return False

    return bool(re.search(r"[A-Za-z]", value))


def parse_card_rows_from_body(body, known_players):
    lines = [clean(line) for line in body.splitlines() if clean(line)]
    heading_indexes = [
        index
        for index, line in enumerate(lines)
        if any(line.lower() == heading.lower() for heading in CARD_HEADINGS)
    ]

    selections = []
    seen = set()

    for start in heading_indexes:
        block = lines[start + 1:start + 350]

        for index in range(len(block) - 1):
            player = block[index]
            odds = block[index + 1].upper()

            if not ODDS_RE.fullmatch(odds):
                continue
            if not plausible_player_name(player):
                continue

            if known_players and normalize(player) not in known_players:
                continue

            key = (normalize(player), odds)

            if key in seen:
                continue
            seen.add(key)

            selections.append(
                {
                    "selection": f"{player} To Get A Card",
                    "normalized_selection": normalize(
                        f"{player} To Get A Card"
                    ),
                    "odds": odds,
                    "player": player,
                    "prop_type": "player_to_get_a_card",
                }
            )

    selections.sort(key=lambda item: normalize(item["player"]))
    return selections


def probe_cards(browser, base_url, known_players):
    context = browser.new_context(viewport={"width": 1700, "height": 1000})
    page = context.new_page()
    debug_dir = DEBUG_ROOT / "player_to_get_a_card"
    debug_dir.mkdir(parents=True, exist_ok=True)

    try:
        page.goto(base_url, wait_until="domcontentloaded", timeout=70000)
        page.wait_for_timeout(6000)
        accept_cookies(page)

        cards_tab_clicked = click_exact_text(page, ["Cards"])
        heading_clicked = click_exact_text(page, CARD_HEADINGS)
        more_clicked = click_more_controls(page)

        # Scroll the page and inner containers to expose all card rows.
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
        position = 0

        while position <= total_height:
            page.evaluate("(value) => window.scrollTo(0, value)", position)
            page.wait_for_timeout(250)
            position += step

        containers = mark_scroll_containers(page)

        for info in containers:
            locator = page.locator(
                f'[data-bv-probe-scroll-id="{info["id"]}"]'
            )

            if not locator.count():
                continue

            try:
                locator.evaluate(
                    "(el) => { el.scrollTop = el.scrollHeight; }"
                )
                page.wait_for_timeout(500)
            except Exception:
                pass

        more_clicked += click_more_controls(page)
        body = page.locator("body").inner_text(timeout=25000)

        # First try explicit card labels in the DOM.
        explicit_rows = page.evaluate(
            """() => {
                const oddsRe = /^(?:\\d+\\/\\d+|EVS|EVENS|EVEN)$/i;
                const patterns = [
                    /^(.+?)\\s+To\\s+Be\\s+Carded$/i,
                    /^(.+?)\\s+To\\s+Get\\s+A\\s+Card$/i,
                    /^(.+?)\\s+Carded$/i,
                    /^(.+?)\\s+To\\s+Receive\\s+A\\s+Card$/i,
                    /^(.+?)\\s+Shown\\s+A\\s+Card$/i,
                ];
                const rows = [];
                const seen = new Set();

                for (const el of document.querySelectorAll('*')) {
                    const label = (el.innerText || '')
                        .trim()
                        .replace(/\\s+/g, ' ');

                    if (!patterns.some(pattern => pattern.test(label))) {
                        continue;
                    }

                    let node = el;
                    let odd = null;

                    for (
                        let depth = 0;
                        depth < 10 && node;
                        depth++, node = node.parentElement
                    ) {
                        const lines = (node.innerText || '')
                            .split(/\\n+/)
                            .map(x => x.trim())
                            .filter(Boolean);
                        odd = lines.find(x => oddsRe.test(x));

                        if (odd) break;
                    }

                    if (!odd) continue;

                    const key = label + '|' + odd;
                    if (seen.has(key)) continue;

                    seen.add(key);
                    rows.push({label, odds: odd});
                }

                return rows;
            }"""
        )

        selections = []
        seen = set()

        for row in explicit_rows:
            label = clean(row.get("label"))
            odds = clean(row.get("odds")).upper()
            player = ""

            for pattern in CARD_ROW_PATTERNS:
                match = pattern.fullmatch(label)
                if match:
                    player = clean(match.group(1))
                    break

            if not player or not ODDS_RE.fullmatch(odds):
                continue

            key = (normalize(player), odds)
            if key in seen:
                continue
            seen.add(key)

            selections.append(
                {
                    "selection": f"{player} To Get A Card",
                    "normalized_selection": normalize(
                        f"{player} To Get A Card"
                    ),
                    "odds": odds,
                    "player": player,
                    "prop_type": "player_to_get_a_card",
                }
            )

        if not selections:
            selections = parse_card_rows_from_body(
                body,
                known_players,
            )

        (debug_dir / "body.txt").write_text(body, encoding="utf-8")
        (debug_dir / "explicit_rows.json").write_text(
            json.dumps(explicit_rows, indent=2, ensure_ascii=False),
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
            "market": "Player To Get A Card",
            "normalized_market": "player_to_get_a_card",
            "cards_tab_clicked": cards_tab_clicked,
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

    base_url = load_event_url()
    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)

        known_players = set()

        for key, config in MARKETS.items():
            print(f"\nProbing {config['label']}...")
            market = probe_threshold_market(
                browser,
                base_url,
                key,
                config,
            )
            results.append(market)

            for selection in market.get("selections", []):
                known_players.add(normalize(selection.get("player")))

            print(
                f"  heading={market.get('heading_clicked')} "
                f"show_more={market.get('expansion_controls_clicked')} "
                f"selections={market.get('selection_count')}"
            )
            for selection in market.get("selections", [])[:12]:
                print(
                    f"    {selection['player']:<30} "
                    f"{selection['threshold']:<3} "
                    f"{selection['odds']}"
                )

        print("\nProbing Player Cards...")
        card_market = probe_cards(
            browser,
            base_url,
            known_players,
        )
        results.append(card_market)

        print(
            f"  cards_tab={card_market.get('cards_tab_clicked')} "
            f"heading={card_market.get('heading_clicked')} "
            f"show_more={card_market.get('expansion_controls_clicked')} "
            f"selections={card_market.get('selection_count')}"
        )
        for selection in card_market.get("selections", [])[:20]:
            print(
                f"    {selection['player']:<30} "
                f"{selection['odds']}"
            )

        browser.close()

    output = {
        "bookmaker": "BetVictor",
        "match": MATCH_NAME,
        "source_url": base_url,
        "market_count": len(
            [market for market in results if market.get("selection_count")]
        ),
        "markets": results,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print(f"Saved read-only probe: {OUT_PATH}")
    print("The main BetVictor props JSON was NOT changed.")


if __name__ == "__main__":
    main()
