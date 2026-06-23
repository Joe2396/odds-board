#!/usr/bin/env python3
"""
fetch_bwin_worldcup_moneylines.py

Bwin World Cup 2026 moneyline scraper.

The earlier text-only versions failed because Bwin renders each fixture inside
an event link/card and may virtualise the fixture list while scrolling.

This version:
1. Parses event links/cards directly from the HTTP HTML.
2. Falls back to Playwright DOM-card extraction.
3. Accumulates cards before any virtualised rows disappear.
4. Validates every 1/X/2 triplet before saving it.

Testing:
    MAX_MATCHES = 15
    HEADLESS = True

Production:
    MAX_MATCHES = 15
    HEADLESS = True

Output:
    football/data/bwin_worldcup_moneylines.json
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "bwin_worldcup_moneylines.json"
DEBUG_DIR = ROOT / "football" / "debug"
DEBUG_HTML = DEBUG_DIR / "bwin_worldcup_moneylines.html"
DEBUG_TEXT = DEBUG_DIR / "bwin_worldcup_moneylines_text.txt"
DEBUG_CARDS = DEBUG_DIR / "bwin_worldcup_moneyline_cards.json"
DEBUG_SCREENSHOT = DEBUG_DIR / "bwin_worldcup_moneylines.png"

URL = (
    "https://www.bwin.com/en/sports/football-4/"
    "betting/world-6/world-cup-2026-0%3A14"
)

MAX_MATCHES = 15
HEADLESS = True
HTTP_TIMEOUT = 45

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

WORLD_CUP_TEAMS = {
    "Mexico",
    "South Africa",
    "South Korea",
    "Korea Republic",
    "Czech Republic",
    "Czechia",
    "Canada",
    "Bosnia & Herzegovina",
    "Bosnia and Herzegovina",
    "Bosnia-Herzegovina",
    "Bosnia",
    "USA",
    "United States",
    "Paraguay",
    "Qatar",
    "Switzerland",
    "Brazil",
    "Morocco",
    "Haiti",
    "Scotland",
    "Australia",
    "Turkey",
    "Turkiye",
    "Türkiye",
    "Germany",
    "Curacao",
    "Curaçao",
    "Netherlands",
    "Japan",
    "Ivory Coast",
    "Côte d'Ivoire",
    "Cote d'Ivoire",
    "Ecuador",
    "Sweden",
    "Tunisia",
    "Spain",
    "Cape Verde",
    "Cape Verde Islands",
    "Belgium",
    "Egypt",
    "Saudi Arabia",
    "Uruguay",
    "Iran",
    "New Zealand",
    "France",
    "Senegal",
    "Iraq",
    "Norway",
    "Argentina",
    "Algeria",
    "Austria",
    "Jordan",
    "Portugal",
    "DR Congo",
    "Congo DR",
    "Democratic Republic of Congo",
    "England",
    "Croatia",
    "Ghana",
    "Panama",
    "Colombia",
    "Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Bosnia-Herzegovina": "Bosnia",
    "United States": "USA",
    "Korea Republic": "South Korea",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
    "Cape Verde Islands": "Cape Verde",
    "Congo DR": "DR Congo",
    "Democratic Republic of Congo": "DR Congo",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
}

DECIMAL_ODDS_RE = re.compile(r"^\d{1,3}[.,]\d{1,3}$")
EVENT_MARKER_RE = re.compile(
    r"\b(?:Today|Tomorrow|Starting in|BB)\b|"
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.I,
)
TIME_RE = re.compile(
    r"\b(\d{1,2}:\d{2}\s*(?:AM|PM)?)\b",
    re.I,
)
DATE_RE = re.compile(
    r"\b(Today|Tomorrow|\d{1,2}/\d{1,2}/\d{2,4})\b",
    re.I,
)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_team(value: object) -> str:
    name = clean(value)
    for raw, canonical in TEAM_ALIASES.items():
        if name.casefold() == raw.casefold():
            return canonical
    return name


def normalise_decimal(value: object) -> str:
    return clean(value).replace(",", ".")


def is_decimal_odds(value: object) -> bool:
    text = normalise_decimal(value)
    if not re.fullmatch(r"\d{1,3}\.\d{1,3}", text):
        return False

    try:
        decimal = float(text)
    except ValueError:
        return False

    return 1.001 <= decimal <= 1000


def implied_sum(prices: Iterable[str]) -> float:
    return sum(1.0 / float(normalise_decimal(price)) for price in prices)


def valid_triplet(prices: list[str]) -> bool:
    if len(prices) != 3 or not all(is_decimal_odds(price) for price in prices):
        return False

    total = implied_sum(prices)
    return 0.95 <= total <= 1.35


def team_spans(text: str) -> list[tuple[int, int, str]]:
    value = clean(text)
    found: list[tuple[int, int, str]] = []

    for team in sorted(WORLD_CUP_TEAMS, key=len, reverse=True):
        match = re.search(
            rf"(?<![\w]){re.escape(team)}(?![\w])",
            value,
            re.I,
        )
        if not match:
            continue

        candidate = (
            match.start(),
            match.end(),
            canonical_team(team),
        )

        if any(
            not (
                candidate[1] <= existing[0]
                or candidate[0] >= existing[1]
            )
            for existing in found
        ):
            continue

        found.append(candidate)

    found.sort(key=lambda item: item[0])
    return found


def parse_event_text(text: str) -> tuple[str, str, str, str] | None:
    value = clean(text)

    if not EVENT_MARKER_RE.search(value):
        return None

    # Exclude promos such as "World Cup: Argentina - Austria".
    if "world cup:" in value.casefold():
        return None

    spans = team_spans(value)
    if len(spans) < 2:
        return None

    home = spans[0][2]
    away = spans[1][2]

    if not home or not away or home == away:
        return None

    date_label = ""
    time_label = ""

    date_match = DATE_RE.search(value)
    if date_match:
        date_label = clean(date_match.group(1))
    elif re.search(r"\bStarting in\b", value, re.I):
        date_label = "Today"

    time_match = TIME_RE.search(value)
    if time_match:
        time_label = clean(time_match.group(1))

    return home, away, date_label, time_label


def first_valid_decimal_triplet(lines: list[str]) -> list[str] | None:
    decimals = [
        normalise_decimal(line)
        for line in lines
        if is_decimal_odds(line)
    ]

    for index in range(max(0, len(decimals) - 2)):
        candidate = decimals[index:index + 3]
        if valid_triplet(candidate):
            return candidate

    return None


def find_1x2_prices(lines: list[str]) -> list[str] | None:
    """
    Handle Bwin's common visual orders:

      1, price, X, price, 2, price
      price, 1, price, X, price, 2
      1, X, 2, price, price, price
      price, price, price, 1, X, 2
    """
    tokens = [
        clean(line)
        for line in lines
        if clean(line) in {"1", "X", "2"} or is_decimal_odds(line)
    ]

    for index in range(max(0, len(tokens) - 5)):
        window = tokens[index:index + 6]
        candidates: list[list[str]] = []

        if window[0::2] == ["1", "X", "2"]:
            candidates.append([window[1], window[3], window[5]])

        if window[1::2] == ["1", "X", "2"]:
            candidates.append([window[0], window[2], window[4]])

        if window[:3] == ["1", "X", "2"]:
            candidates.append(window[3:6])

        if window[3:6] == ["1", "X", "2"]:
            candidates.append(window[:3])

        for candidate in candidates:
            candidate = [normalise_decimal(value) for value in candidate]
            if valid_triplet(candidate):
                return candidate

    # The smallest event card sometimes contains only the three price cells.
    return first_valid_decimal_triplet(lines)


def parse_card(card: dict) -> dict | None:
    event_text = clean(card.get("event_text"))
    event = parse_event_text(event_text)

    if not event:
        return None

    home, away, date_label, time_label = event
    lines = [clean(line) for line in card.get("lines") or []]
    lines = [line for line in lines if line]
    prices = find_1x2_prices(lines)

    if not prices:
        return None

    href = urljoin(URL, clean(card.get("href")))

    return {
        "competition": "FIFA World Cup",
        "bookmaker": "Bwin",
        "date_label": date_label,
        "time": time_label,
        "match": f"{home} v {away}",
        "home_team": home,
        "away_team": away,
        "market": "Match Odds",
        "odds": {
            "home": prices[0],
            "draw": prices[1],
            "away": prices[2],
        },
        "source_url": href or URL,
    }


def dedupe(matches: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    output: list[dict] = []

    for match in matches:
        key = (
            match["home_team"],
            match["away_team"],
            match.get("time", ""),
        )
        if key in seen:
            continue

        seen.add(key)
        output.append(match)

    return output


def extract_http_cards(html: str) -> list[dict]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as error:
        raise RuntimeError(
            "Install BeautifulSoup with: pip install beautifulsoup4"
        ) from error

    soup = BeautifulSoup(html, "html.parser")
    cards: list[dict] = []

    for anchor in soup.select('a[href*="/sports/events/"]'):
        event_text = clean(anchor.get_text(" ", strip=True))
        if not parse_event_text(event_text):
            continue

        best: dict | None = None
        node = anchor

        for _ in range(10):
            if node is None:
                break

            lines = [
                clean(value)
                for value in node.stripped_strings
                if clean(value)
            ]
            prices = find_1x2_prices(lines)

            if prices:
                candidate = {
                    "event_text": event_text,
                    "href": anchor.get("href") or "",
                    "lines": lines,
                    "size": len(" ".join(lines)),
                }
                if best is None or candidate["size"] < best["size"]:
                    best = candidate

            node = node.parent

        if best:
            best.pop("size", None)
            cards.append(best)

    return cards


def fetch_http() -> tuple[str, str, list[dict]]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
        "Cache-Control": "no-cache",
    }

    try:
        from curl_cffi import requests as curl_requests

        response = curl_requests.get(
            URL,
            headers=headers,
            timeout=HTTP_TIMEOUT,
            impersonate="chrome",
        )
    except ImportError:
        import requests

        response = requests.get(
            URL,
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )

    response.raise_for_status()
    html = response.text
    cards = extract_http_cards(html)

    try:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text("\n")
    except Exception:
        text = html

    return html, text, cards


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
                button.first.click(timeout=2500)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue


def block_heavy_resources(route) -> None:
    if route.request.resource_type in {"image", "media", "font"}:
        route.abort()
    else:
        route.continue_()


DOM_EXTRACTOR = r"""
() => {
    const clean = value =>
        (value || "").replace(/\s+/g, " ").trim();

    const oddRe = /^\d{1,3}[.,]\d{1,3}$/;
    const anchors = Array.from(
        document.querySelectorAll('a[href*="/sports/events/"]')
    );

    const output = [];

    for (const anchor of anchors) {
        const eventText = clean(anchor.innerText);

        if (!eventText) {
            continue;
        }

        let best = null;
        let node = anchor;

        for (
            let depth = 0;
            depth < 10 && node;
            depth += 1, node = node.parentElement
        ) {
            const raw = node.innerText || "";
            const lines = raw
                .split(/\n+/)
                .map(clean)
                .filter(Boolean);

            const prices = lines.filter(line => oddRe.test(line));

            if (prices.length < 3) {
                continue;
            }

            const candidate = {
                event_text: eventText,
                href: anchor.getAttribute("href") || "",
                lines,
                size: raw.length,
            };

            if (!best || candidate.size < best.size) {
                best = candidate;
            }
        }

        if (best) {
            delete best.size;
            output.push(best);
        }
    }

    return output;
}
"""


def scroll_best_container(page) -> bool:
    return bool(
        page.evaluate(
            r"""
            () => {
                const candidates = Array.from(
                    document.querySelectorAll("body *")
                ).filter(element => {
                    const style = getComputedStyle(element);
                    return (
                        element.scrollHeight > element.clientHeight + 150
                        && element.clientHeight > 250
                        && ["auto", "scroll"].includes(style.overflowY)
                    );
                });

                candidates.sort(
                    (a, b) =>
                        (b.clientHeight * b.clientWidth)
                        - (a.clientHeight * a.clientWidth)
                );

                const target = candidates[0];

                if (target) {
                    const before = target.scrollTop;
                    target.scrollTop += Math.max(
                        500,
                        Math.floor(target.clientHeight * 0.8)
                    );
                    return target.scrollTop > before;
                }

                const before = window.scrollY;
                window.scrollBy(0, 700);
                return window.scrollY > before;
            }
            """
        )
    )


def fetch_playwright() -> tuple[str, str, list[dict]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Install Playwright with:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        ) from error

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
            print(f"Opening Bwin with Playwright:\n{URL}")

            page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(7000)
            dismiss_cookies(page)

            try:
                page.locator(
                    'a[href*="/sports/events/"]'
                ).first.wait_for(
                    state="attached",
                    timeout=30000,
                )
            except Exception:
                pass

            # Start at the first actual event rather than blindly jumping to
            # the bottom of Bwin's virtualised fixture list.
            try:
                first_event = page.locator(
                    'a[href*="/sports/events/"]'
                ).first
                if first_event.count():
                    first_event.scroll_into_view_if_needed(timeout=10000)
                    page.wait_for_timeout(700)
            except Exception:
                pass

            cards_by_href: dict[str, dict] = {}

            for step in range(35):
                current_cards = page.evaluate(DOM_EXTRACTOR) or []

                for card in current_cards:
                    href = clean(card.get("href"))
                    event_text = clean(card.get("event_text"))
                    key = href or event_text

                    if key and key not in cards_by_href:
                        cards_by_href[key] = card

                parsed_count = len(
                    dedupe(
                        [
                            parsed
                            for parsed in (
                                parse_card(card)
                                for card in cards_by_href.values()
                            )
                            if parsed
                        ]
                    )
                )

                print(
                    f"DOM pass {step + 1}: "
                    f"{len(cards_by_href)} card(s), "
                    f"{parsed_count} valid moneyline fixture(s)"
                )

                if MAX_MATCHES and parsed_count >= MAX_MATCHES:
                    break

                moved = scroll_best_container(page)
                page.wait_for_timeout(650)

                if not moved and step >= 3:
                    break

            html = page.content()
            text = page.locator("body").inner_text(timeout=30000)

            try:
                page.screenshot(
                    path=str(DEBUG_SCREENSHOT),
                    full_page=False,
                )
            except Exception:
                pass

            return html, text, list(cards_by_href.values())
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()


def save(
    matches: list[dict],
    html: str,
    text: str,
    cards: list[dict],
    method: str,
) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    DEBUG_HTML.write_text(html, encoding="utf-8")
    DEBUG_TEXT.write_text(text, encoding="utf-8")
    DEBUG_CARDS.write_text(
        json.dumps(cards, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    limited = matches[:MAX_MATCHES] if MAX_MATCHES else matches

    payload = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "Bwin",
        "market": "Match Odds",
        "odds_format": "decimal",
        "source_url": URL,
        "scrape_method": method,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(limited),
        "matches": limited,
    }

    OUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("")
    print(f"Saved {len(limited)} Bwin World Cup moneyline matches:")
    print(OUT_PATH)
    print(f"Method: {method}")
    print("")

    for match in limited:
        odds = match["odds"]
        print(
            f"- {match['date_label']} {match['time']} | "
            f"{match['match']} | "
            f"H {odds['home']} D {odds['draw']} A {odds['away']}"
        )


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    html = ""
    text = ""
    cards: list[dict] = []
    matches: list[dict] = []
    method = ""

    try:
        print("Trying fast HTTP card scrape...")
        html, text, cards = fetch_http()
        matches = dedupe(
            [
                parsed
                for parsed in (parse_card(card) for card in cards)
                if parsed
            ]
        )
        method = "http-dom"
        print(
            f"HTTP card parser found {len(cards)} card(s), "
            f"{len(matches)} valid fixture(s)."
        )
    except Exception as error:
        print(f"HTTP card scrape failed: {error}")

    minimum_required = min(MAX_MATCHES or 3, 3)

    if len(matches) < minimum_required:
        print("")
        print(
            "HTTP result was incomplete; switching to Playwright DOM cards..."
        )

        try:
            html, text, cards = fetch_playwright()
            matches = dedupe(
                [
                    parsed
                    for parsed in (parse_card(card) for card in cards)
                    if parsed
                ]
            )
            method = "playwright-dom"
            print(
                f"Playwright DOM parser found {len(cards)} card(s), "
                f"{len(matches)} valid fixture(s)."
            )
        except Exception as error:
            print(f"Playwright DOM scrape failed: {error}")
            return 1

    if not matches:
        DEBUG_HTML.write_text(html, encoding="utf-8")
        DEBUG_TEXT.write_text(text, encoding="utf-8")
        DEBUG_CARDS.write_text(
            json.dumps(cards, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print("")
        print("No Bwin World Cup moneylines found.")
        print(f"Debug text: {DEBUG_TEXT}")
        print(f"Debug cards: {DEBUG_CARDS}")
        print(f"Debug HTML: {DEBUG_HTML}")
        return 1

    save(matches, html, text, cards, method)

    if len(matches) < minimum_required:
        print("")
        print(
            f"WARNING: only {len(matches)} match(es) found; "
            f"expected at least {minimum_required}."
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
