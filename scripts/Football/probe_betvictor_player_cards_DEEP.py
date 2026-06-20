#!/usr/bin/env python3
"""
probe_betvictor_player_cards_DEEP.py

Read-only deep discovery probe for BetVictor player-card markets.

It checks Argentina v Austria and:
- inspects all visible tabs/buttons/links;
- clicks card/player/bet-builder related controls;
- discovers and visits every market_group URL exposed by the event;
- expands Show More/View More controls;
- scrolls the browser and inner containers;
- captures XHR/fetch responses containing card/booked/yellow/caution terms;
- reports any exact player-card-looking rows.

It does NOT modify any production JSON.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_player_cards_DEEP_PROBE.json"
DEBUG_DIR = ROOT / "football" / "debug" / "betvictor_player_cards_deep_probe"

MATCH_NAME = "Argentina v Austria"
HEADLESS = False

KEYWORD_RE = re.compile(
    r"\b(?:card|carded|cards|booked|booking|yellow|red|caution)\b",
    re.I,
)

PLAYER_CARD_PATTERNS = [
    re.compile(r"^(.+?)\s+To\s+Be\s+Carded$", re.I),
    re.compile(r"^(.+?)\s+To\s+Get\s+A\s+Card$", re.I),
    re.compile(r"^(.+?)\s+To\s+Receive\s+A\s+Card$", re.I),
    re.compile(r"^(.+?)\s+Shown\s+A\s+Card$", re.I),
    re.compile(r"^(.+?)\s+To\s+Be\s+Booked$", re.I),
    re.compile(r"^(.+?)\s+Booked$", re.I),
    re.compile(r"^(.+?)\s+Carded$", re.I),
]

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN)$", re.I)

CONTROL_KEYWORDS = (
    "popular",
    "player",
    "card",
    "book",
    "yellow",
    "bet builder",
    "all markets",
    "more markets",
)


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
            raise SystemExit(f"{MATCH_NAME} has no usable BetVictor event URL")
        return url.split("?", 1)[0]

    raise SystemExit(f"Could not find {MATCH_NAME} in {PROPS_PATH}")


def accept_cookies(page):
    labels = (
        "Accept All",
        "Accept all",
        "I Accept",
        "Accept",
        "Agree",
        "Allow all",
        "OK",
    )

    for label in labels:
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


def expand_more(page):
    clicked = 0
    patterns = (
        re.compile(r"^Show More$", re.I),
        re.compile(r"^View More$", re.I),
        re.compile(r"^Load More$", re.I),
        re.compile(r"^Show All$", re.I),
    )

    for _ in range(10):
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
                        item.click(timeout=1800)
                        page.wait_for_timeout(500)
                        clicked += 1
                        changed = True
                    except Exception:
                        pass
            except Exception:
                pass

        if not changed:
            break

    return clicked


def scroll_everything(page):
    for _ in range(35):
        page.mouse.wheel(0, 650)
        page.wait_for_timeout(180)

    containers = page.evaluate(
        r"""() => {
            document
              .querySelectorAll('[data-bv-card-scroll]')
              .forEach(el => el.removeAttribute('data-bv-card-scroll'));

            const found = [];

            for (const el of document.querySelectorAll('*')) {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                const range = el.scrollHeight - el.clientHeight;

                if (rect.width < 260 || rect.height < 150) continue;
                if (range < 100) continue;
                if (!['auto', 'scroll', 'overlay'].includes(style.overflowY)) {
                    continue;
                }

                found.push({
                    el,
                    range,
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    tag: el.tagName,
                    className: String(el.className || '').slice(0, 160),
                });
            }

            found.sort(
                (a, b) => (b.range * b.width) - (a.range * a.width)
            );

            return found.slice(0, 12).map((item, index) => {
                item.el.setAttribute('data-bv-card-scroll', String(index));
                return {
                    id: index,
                    range: item.range,
                    width: item.width,
                    height: item.height,
                    tag: item.tag,
                    className: item.className,
                };
            });
        }"""
    )

    for info in containers:
        locator = page.locator(
            f'[data-bv-card-scroll="{info["id"]}"]'
        )
        if not locator.count():
            continue

        try:
            height = int(locator.evaluate("(el) => el.clientHeight"))
        except Exception:
            height = 600

        step = max(180, height // 3)
        position = 0

        while position <= info["range"]:
            try:
                locator.evaluate(
                    "(el, value) => { el.scrollTop = value; }",
                    position,
                )
                page.wait_for_timeout(220)
            except Exception:
                break
            position += step

    return containers


def collect_controls(page):
    return page.evaluate(
        r"""() => {
            const result = [];
            const seen = new Set();

            for (const el of document.querySelectorAll(
                'a,button,[role="tab"],[role="button"]'
            )) {
                const text = (el.innerText || el.textContent || '')
                    .trim()
                    .replace(/\s+/g, ' ');
                const href = el.href || el.getAttribute('href') || '';
                const role = el.getAttribute('role') || '';
                const key = `${text}|${href}|${role}`;

                if (!text && !href) continue;
                if (seen.has(key)) continue;
                seen.add(key);

                result.push({
                    text,
                    href,
                    role,
                    tag: el.tagName,
                    visible: !!(
                        el.offsetWidth ||
                        el.offsetHeight ||
                        el.getClientRects().length
                    ),
                });
            }

            return result;
        }"""
    )


def collect_keyword_context(body):
    lines = [clean(line) for line in body.splitlines() if clean(line)]
    hits = []
    seen = set()

    for index, line in enumerate(lines):
        if not KEYWORD_RE.search(line):
            continue

        context = lines[max(0, index - 3):min(len(lines), index + 7)]
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

    return hits


def extract_exact_rows(page):
    raw = page.evaluate(
        r"""() => {
            const oddsRe = /^(?:\d+\/\d+|EVS|EVENS|EVEN)$/i;
            const labelRes = [
                /^(.+?)\s+To\s+Be\s+Carded$/i,
                /^(.+?)\s+To\s+Get\s+A\s+Card$/i,
                /^(.+?)\s+To\s+Receive\s+A\s+Card$/i,
                /^(.+?)\s+Shown\s+A\s+Card$/i,
                /^(.+?)\s+To\s+Be\s+Booked$/i,
                /^(.+?)\s+Booked$/i,
                /^(.+?)\s+Carded$/i,
            ];

            const rows = [];
            const seen = new Set();

            for (const el of document.querySelectorAll('*')) {
                const label = (el.innerText || '')
                    .trim()
                    .replace(/\s+/g, ' ');

                if (!labelRes.some(re => re.test(label))) continue;
                if (label.length > 140) continue;

                let node = el;
                let foundOdd = null;
                let block = '';

                for (
                    let depth = 0;
                    depth < 10 && node;
                    depth++, node = node.parentElement
                ) {
                    block = (node.innerText || '').trim();
                    const lines = block
                        .split(/\n+/)
                        .map(x => x.trim())
                        .filter(Boolean);
                    foundOdd = lines.find(x => oddsRe.test(x));

                    if (foundOdd && block.length < 800) break;
                    foundOdd = null;
                }

                if (!foundOdd) continue;

                const key = `${label}|${foundOdd}`;
                if (seen.has(key)) continue;
                seen.add(key);

                rows.push({
                    label,
                    odds: foundOdd,
                    block,
                });
            }

            return rows;
        }"""
    )

    parsed = []
    seen = set()

    for row in raw:
        label = clean(row.get("label"))
        odds = clean(row.get("odds")).upper()
        player = ""

        for pattern in PLAYER_CARD_PATTERNS:
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

        parsed.append(
            {
                "player": player,
                "odds": odds,
                "selection": f"{player} To Get A Card",
                "normalized_selection": normalize(
                    f"{player} To Get A Card"
                ),
            }
        )

    return parsed, raw


def discover_market_groups(controls, current_url):
    groups = {}

    for control in controls:
        href = clean(control.get("href"))
        if not href or "market_group=" not in href:
            continue

        try:
            parsed = urlparse(href)
            query = parse_qs(parsed.query)
            group = query.get("market_group", [""])[0]
        except Exception:
            continue

        if not group:
            continue

        groups[group] = {
            "market_group": group,
            "text": clean(control.get("text")),
            "href": href,
        }

    current = urlparse(current_url)
    current_group = parse_qs(current.query).get("market_group", [""])[0]
    if current_group and current_group not in groups:
        groups[current_group] = {
            "market_group": current_group,
            "text": "current",
            "href": current_url,
        }

    return groups


def click_relevant_controls(page):
    controls = collect_controls(page)
    clicked = []

    for control in controls:
        text = clean(control.get("text"))
        lower = text.lower()

        if not text or not any(keyword in lower for keyword in CONTROL_KEYWORDS):
            continue

        try:
            locator = page.get_by_text(text, exact=True)

            for index in range(locator.count() - 1, -1, -1):
                item = locator.nth(index)
                try:
                    if not item.is_visible():
                        continue
                    item.scroll_into_view_if_needed(timeout=1600)
                    item.click(timeout=2200)
                    page.wait_for_timeout(900)
                    clicked.append(text)
                    break
                except Exception:
                    pass
        except Exception:
            pass

    return clicked


def inspect_view(page, label):
    expand_count = expand_more(page)
    containers = scroll_everything(page)
    expand_count += expand_more(page)

    body = page.locator("body").inner_text(timeout=25000)
    controls = collect_controls(page)
    exact_rows, raw_rows = extract_exact_rows(page)

    return {
        "label": label,
        "url": page.url,
        "expand_controls_clicked": expand_count,
        "scroll_containers": containers,
        "controls": controls,
        "keyword_hits": collect_keyword_context(body),
        "exact_player_card_rows": exact_rows,
        "raw_exact_rows": raw_rows,
        "body": body,
    }


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    base_url = load_event_url()
    response_hits = []
    response_seen = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(viewport={"width": 1700, "height": 1000})
        page = context.new_page()

        def on_response(response):
            try:
                request = response.request
                if request.resource_type not in {"xhr", "fetch"}:
                    return

                content_type = clean(response.headers.get("content-type", ""))
                if not any(
                    item in content_type.lower()
                    for item in ("json", "text", "javascript")
                ):
                    return

                text = response.text()
                if not text or len(text) > 5_000_000:
                    return
                if not KEYWORD_RE.search(text):
                    return

                key = (response.url, text[:500])
                if key in response_seen:
                    return
                response_seen.add(key)

                filename = (
                    f"response_{len(response_hits) + 1:03d}_"
                    f"{normalize(response.url)[-90:]}.txt"
                )
                (DEBUG_DIR / filename).write_text(
                    text,
                    encoding="utf-8",
                    errors="replace",
                )

                response_hits.append(
                    {
                        "url": response.url,
                        "status": response.status,
                        "resource_type": request.resource_type,
                        "content_type": content_type,
                        "debug_file": filename,
                        "sample": clean(text[:1000]),
                    }
                )
            except Exception:
                pass

        page.on("response", on_response)

        views = []
        discovered_groups = {}

        page.goto(
            base_url,
            wait_until="domcontentloaded",
            timeout=70000,
        )
        page.wait_for_timeout(6000)
        accept_cookies(page)

        base_view = inspect_view(page, "base")
        views.append(base_view)
        discovered_groups.update(
            discover_market_groups(
                base_view["controls"],
                base_view["url"],
            )
        )

        clicked = click_relevant_controls(page)
        if clicked:
            clicked_view = inspect_view(
                page,
                "clicked relevant controls: " + ", ".join(clicked),
            )
            views.append(clicked_view)
            discovered_groups.update(
                discover_market_groups(
                    clicked_view["controls"],
                    clicked_view["url"],
                )
            )

        # Visit every market-group URL exposed by the event navigation.
        for group, info in list(discovered_groups.items()):
            href = info["href"]

            if href.startswith("/"):
                parsed_base = urlparse(base_url)
                href = (
                    f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
                )

            try:
                page.goto(
                    href,
                    wait_until="domcontentloaded",
                    timeout=70000,
                )
                page.wait_for_timeout(4500)
                accept_cookies(page)

                view = inspect_view(
                    page,
                    f"market_group={group} text={info['text']}",
                )
                views.append(view)
                discovered_groups.update(
                    discover_market_groups(
                        view["controls"],
                        view["url"],
                    )
                )
            except Exception as exc:
                views.append(
                    {
                        "label": f"market_group={group}",
                        "url": href,
                        "error": f"{type(exc).__name__}: {exc}",
                        "controls": [],
                        "keyword_hits": [],
                        "exact_player_card_rows": [],
                        "raw_exact_rows": [],
                        "body": "",
                    }
                )

        # Save compact per-view debug files.
        compact_views = []

        for index, view in enumerate(views, 1):
            body = view.pop("body", "")
            controls = view.get("controls", [])

            (DEBUG_DIR / f"view_{index:02d}_body.txt").write_text(
                body,
                encoding="utf-8",
                errors="replace",
            )
            (DEBUG_DIR / f"view_{index:02d}_controls.json").write_text(
                json.dumps(
                    controls,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            compact = dict(view)
            compact["controls"] = [
                control
                for control in controls
                if (
                    "market_group=" in clean(control.get("href"))
                    or KEYWORD_RE.search(clean(control.get("text")))
                )
            ]
            compact_views.append(compact)

        browser.close()

    output = {
        "bookmaker": "BetVictor",
        "match": MATCH_NAME,
        "source_url": base_url,
        "discovered_market_groups": list(discovered_groups.values()),
        "views": compact_views,
        "network_response_hits": response_hits,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("BETVICTOR DEEP PLAYER-CARDS PROBE")
    print("=" * 72)
    print(f"Discovered market groups: {len(discovered_groups)}")

    for info in discovered_groups.values():
        print(
            f"  group={info['market_group']} "
            f"text={info['text']!r}"
        )

    total_exact = 0

    for view in compact_views:
        exact = view.get("exact_player_card_rows", [])
        hits = view.get("keyword_hits", [])
        total_exact += len(exact)

        print(
            f"\n{view.get('label')} "
            f"| keyword_hits={len(hits)} "
            f"| exact_rows={len(exact)}"
        )

        for row in exact[:20]:
            print(f"  EXACT: {row['player']} | {row['odds']}")

        for hit in hits[:12]:
            print("  HIT:", " | ".join(hit["context"]))

    print(f"\nNetwork responses containing card terms: {len(response_hits)}")
    for hit in response_hits[:20]:
        print(
            f"  {hit['status']} {hit['resource_type']} "
            f"{hit['url']}"
        )

    print(f"\nTotal exact player-card rows found: {total_exact}")
    print(f"Saved: {OUT_PATH}")
    print(f"Debug: {DEBUG_DIR}")
    print("No production JSON was modified.")


if __name__ == "__main__":
    main()
