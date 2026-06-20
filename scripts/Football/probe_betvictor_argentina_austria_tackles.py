#!/usr/bin/env python3
"""
probe_betvictor_argentina_austria_tackles.py

Read-only live probe for the CURRENT Argentina v Austria BetVictor tackle market.

It:
- reads the current event URL from betvictor_worldcup_props.json;
- opens BetVictor market_group=19296;
- finds exact rows such as "Nahuel Molina 3+ Tackles";
- extracts the fractional odd from the same DOM row;
- saves JSON, text and screenshot diagnostics.

It does NOT modify betvictor_worldcup_props.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_argentina_austria_tackles_PROBE.json"
DEBUG_DIR = ROOT / "football" / "debug" / "betvictor_argentina_austria_tackles_probe"

MATCH_NAME = "Argentina v Austria"
MARKET_GROUP = "19296"
HEADLESS = False

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN)$", re.I)
ROW_RE = re.compile(r"^(.+?)\s+(\d+)\+\s+Tackles?(?:\s+90\s*Mins)?$", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    return re.sub(r"[^a-z0-9]+", "_", clean(value).lower()).strip("_")


def load_match():
    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    for match in data.get("matches", []):
        if clean(match.get("match")) == MATCH_NAME:
            url = clean(match.get("source_url") or match.get("url"))
            if not url:
                raise SystemExit(f"{MATCH_NAME} exists but has no source URL.")
            return match, url.split("?", 1)[0]
    raise SystemExit(f"Could not find {MATCH_NAME} in {PROPS_PATH}")


def accept_cookies(page):
    for label in [
        "Accept All",
        "Accept all",
        "I Accept",
        "Accept",
        "Agree",
        "Allow all",
        "OK",
    ]:
        try:
            button = page.get_by_role("button", name=re.compile(f"^{re.escape(label)}$", re.I))
            if button.count():
                button.first.click(timeout=1500)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def click_player_tackles_if_needed(page):
    body = page.locator("body").inner_text(timeout=20000)
    if re.search(r"\d+\+\s+Tackles", body, re.I):
        return True

    for label in ["Player", "Player Tackles"]:
        try:
            locator = page.get_by_text(label, exact=True)
            if locator.count():
                locator.last.scroll_into_view_if_needed(timeout=2500)
                locator.last.click(timeout=3000)
                page.wait_for_timeout(1800)
        except Exception:
            pass

    body = page.locator("body").inner_text(timeout=20000)
    return bool(re.search(r"\d+\+\s+Tackles", body, re.I))


def scroll_all(page):
    previous_height = 0
    for _ in range(35):
        page.mouse.wheel(0, 750)
        page.wait_for_timeout(250)
        try:
            height = page.evaluate("document.body.scrollHeight")
        except Exception:
            height = previous_height
        if height == previous_height:
            page.wait_for_timeout(500)
        previous_height = height


def extract_dom_rows(page):
    return page.evaluate(
        """() => {
            const oddsRe = /^(?:\\d+\\/\\d+|EVS|EVENS|EVEN)$/i;
            const tackleRe = /^(.+?)\\s+(\\d+)\\+\\s+Tackles?(?:\\s+90\\s*Mins)?$/i;
            const rows = [];
            const seen = new Set();

            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_ELEMENT
            );

            while (walker.nextNode()) {
                const el = walker.currentNode;
                const own = (el.innerText || '').trim().replace(/\\s+/g, ' ');

                if (!tackleRe.test(own) || own.length > 120) continue;

                let node = el;
                let best = null;

                for (let depth = 0; depth < 9 && node; depth++, node = node.parentElement) {
                    const text = (node.innerText || '').trim();
                    const lines = text.split(/\\n+/).map(x => x.trim()).filter(Boolean);
                    const odds = lines.filter(x => oddsRe.test(x));

                    if (odds.length && text.length < 700) {
                        best = {
                            label: own,
                            odds: odds[0],
                            all_odds: odds,
                            block: text,
                            tag: node.tagName,
                            class_name: node.className || '',
                        };
                        break;
                    }
                }

                if (!best) continue;

                const key = best.label + '|' + best.odds;
                if (seen.has(key)) continue;
                seen.add(key);
                rows.push(best);
            }

            return rows;
        }"""
    )


def fallback_text_rows(body_text):
    lines = [clean(line) for line in body_text.splitlines() if clean(line)]
    rows = []

    for index, line in enumerate(lines):
        match = ROW_RE.fullmatch(line)
        if not match:
            continue

        odds = None
        for next_index in range(index + 1, min(index + 5, len(lines))):
            token = lines[next_index]
            if ROW_RE.fullmatch(token):
                break
            if ODDS_RE.fullmatch(token):
                odds = token.upper()
                break

        if odds:
            rows.append(
                {
                    "label": line,
                    "odds": odds,
                    "all_odds": [odds],
                    "block": "\n".join(lines[index:index + 5]),
                    "tag": "TEXT_FALLBACK",
                    "class_name": "",
                }
            )

    seen = set()
    unique = []
    for row in rows:
        key = (row["label"], row["odds"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    match, base_url = load_match()
    url = f"{base_url}?market_group={MARKET_GROUP}"

    print(f"Opening current BetVictor event:\n{url}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1050})

        page.goto(url, wait_until="domcontentloaded", timeout=70000)
        page.wait_for_timeout(6000)
        accept_cookies(page)

        page.wait_for_timeout(2000)
        scroll_all(page)
        opened = click_player_tackles_if_needed(page)
        scroll_all(page)

        body_text = page.locator("body").inner_text(timeout=25000)
        current_title = page.title()
        current_url = page.url

        rows = extract_dom_rows(page)
        if not rows:
            rows = fallback_text_rows(body_text)

        screenshot_path = DEBUG_DIR / "argentina-v-austria-tackles.png"
        page.screenshot(path=str(screenshot_path), full_page=True)

        browser.close()

    parsed = []
    for row in rows:
        match_row = ROW_RE.fullmatch(clean(row.get("label")))
        if not match_row:
            continue
        player = clean(match_row.group(1))
        threshold = f"{match_row.group(2)}+"
        odds = clean(row.get("odds")).upper()

        parsed.append(
            {
                "selection": f"{player} {threshold} Tackles",
                "normalized_selection": normalize(f"{player} {threshold} Tackles"),
                "player": player,
                "threshold": threshold,
                "odds": odds,
                "dom_block": row.get("block"),
            }
        )

    output = {
        "bookmaker": "BetVictor",
        "match": MATCH_NAME,
        "source_url": base_url,
        "probe_url": current_url,
        "page_title": current_title,
        "player_tackles_opened": opened,
        "selection_count": len(parsed),
        "selections": parsed,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (DEBUG_DIR / "body.txt").write_text(body_text, encoding="utf-8")

    print("\nCURRENT PAGE")
    print(f"Title: {current_title}")
    print(f"URL:   {current_url}")
    print(f"Rows:  {len(parsed)}")

    for item in parsed:
        print(
            f"{item['player']:<30} "
            f"{item['threshold']:<3} "
            f"{item['odds']}"
        )

    print(f"\nSaved JSON:       {OUT_PATH}")
    print(f"Saved body text:  {DEBUG_DIR / 'body.txt'}")
    print(f"Saved screenshot: {screenshot_path}")
    print("\nThe main BetVictor props JSON was NOT changed.")


if __name__ == "__main__":
    main()
