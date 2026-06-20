#!/usr/bin/env python3
"""
fetch_betvictor_player_tackles.py

Scrapes BetVictor Player Tackles using exact DOM rows.

Test mode:
- TARGET_SUCCESSFUL_MATCHES = 3
- Prioritises Argentina v Austria
- Skips finished/unavailable events instead of treating them as success

Output:
    football/data/betvictor_player_tackles.json

This script does NOT modify betvictor_worldcup_props.json.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_player_tackles.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_player_tackles"

MARKET_GROUP = "19296"
TARGET_SUCCESSFUL_MATCHES = 3
MAX_FIXTURES_TO_SCAN = 15
HEADLESS = False

PRIORITY_MATCHES = ["Argentina v Austria"]

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN)$", re.I)
ROW_RE = re.compile(
    r"^(.+?)\s+(\d+)\+\s+Tackles?(?:\s+90\s*Mins)?$",
    re.I,
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def slugify(value):
    return normalize(value).replace("_", "-")


def load_fixtures():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing: {PROPS_PATH}")

    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    fixtures = []

    for match in data.get("matches", []):
        name = clean(match.get("match"))
        home = clean(match.get("home_team"))
        away = clean(match.get("away_team"))
        url = clean(match.get("source_url") or match.get("url"))

        if not name and home and away:
            name = f"{home} v {away}"

        if not name or "/events/" not in url:
            continue

        fixtures.append(
            {
                "match": name,
                "home_team": home,
                "away_team": away,
                "source_url": url.split("?", 1)[0],
            }
        )

    by_name = {fixture["match"]: fixture for fixture in fixtures}
    ordered = []

    for name in PRIORITY_MATCHES:
        fixture = by_name.get(name)
        if fixture and fixture not in ordered:
            ordered.append(fixture)

    for fixture in fixtures:
        if fixture not in ordered:
            ordered.append(fixture)

    return ordered[:MAX_FIXTURES_TO_SCAN], data.get("generated_at")


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


def scroll_all(page):
    previous_height = 0

    for _ in range(35):
        page.mouse.wheel(0, 750)
        page.wait_for_timeout(220)

        try:
            height = page.evaluate("document.body.scrollHeight")
        except Exception:
            height = previous_height

        if height == previous_height:
            page.wait_for_timeout(350)

        previous_height = height


def click_player_tackles_if_needed(page):
    try:
        body = page.locator("body").inner_text(timeout=20000)
    except Exception:
        body = ""

    if re.search(r"\d+\+\s+Tackles", body, re.I):
        return True

    for label in ["Player", "Player Tackles"]:
        try:
            locator = page.get_by_text(label, exact=True)
            if locator.count():
                item = locator.last
                item.scroll_into_view_if_needed(timeout=2500)
                item.click(timeout=3000)
                page.wait_for_timeout(1800)
        except Exception:
            pass

    try:
        body = page.locator("body").inner_text(timeout=20000)
    except Exception:
        body = ""

    return bool(re.search(r"\d+\+\s+Tackles", body, re.I))


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

                for (
                    let depth = 0;
                    depth < 9 && node;
                    depth++, node = node.parentElement
                ) {
                    const text = (node.innerText || '').trim();
                    const lines = text
                        .split(/\\n+/)
                        .map(x => x.trim())
                        .filter(Boolean);
                    const odds = lines.filter(x => oddsRe.test(x));

                    if (odds.length && text.length < 700) {
                        best = {
                            label: own,
                            odds: odds[0],
                            all_odds: odds,
                            block: text,
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


def parse_rows(rows):
    selections = []
    seen = set()

    for row in rows:
        label = clean(row.get("label"))
        match = ROW_RE.fullmatch(label)
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
                "selection": f"{player} {threshold} Tackles",
                "normalized_selection": normalize(
                    f"{player} {threshold} Tackles"
                ),
                "odds": odds,
                "player": player,
                "threshold": threshold,
                "prop_type": "tackles",
            }
        )

    selections.sort(
        key=lambda item: (
            normalize(item["player"]),
            int(item["threshold"].rstrip("+")),
        )
    )
    return selections


def scrape_fixture(browser, fixture):
    context = browser.new_context(viewport={"width": 1700, "height": 1050})
    page = context.new_page()
    debug_dir = DEBUG_ROOT / slugify(fixture["match"])
    debug_dir.mkdir(parents=True, exist_ok=True)

    url = f"{fixture['source_url']}?market_group={MARKET_GROUP}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=70000)
        page.wait_for_timeout(6000)
        accept_cookies(page)
        page.wait_for_timeout(1500)

        scroll_all(page)
        opened = click_player_tackles_if_needed(page)
        scroll_all(page)

        body = page.locator("body").inner_text(timeout=25000)
        title = page.title()
        current_url = page.url

        rows = extract_dom_rows(page)
        selections = parse_rows(rows)

        page.screenshot(
            path=str(debug_dir / "player-tackles.png"),
            full_page=True,
        )
        (debug_dir / "body.txt").write_text(
            body,
            encoding="utf-8",
        )

        return {
            "match": fixture["match"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "source_url": fixture["source_url"],
            "probe_url": current_url,
            "page_title": title,
            "player_tackles_opened": opened,
            "market_count": 1 if selections else 0,
            "markets": [
                {
                    "market": "Player Tackles",
                    "normalized_market": "player_tackles",
                    "selection_count": len(selections),
                    "selections": selections,
                }
            ] if selections else [],
        }

    except KeyboardInterrupt:
        raise
    except Exception as exc:
        return {
            "match": fixture["match"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "source_url": fixture["source_url"],
            "market_count": 0,
            "markets": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        context.close()


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_ROOT.mkdir(parents=True, exist_ok=True)

    fixtures, source_generated_at = load_fixtures()

    print("BETVICTOR PLAYER TACKLES")
    print("=" * 72)
    print(
        f"Scanning up to {len(fixtures)} fixtures for "
        f"{TARGET_SUCCESSFUL_MATCHES} successful tackle markets."
    )

    results = []
    skipped = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)

        for index, fixture in enumerate(fixtures, 1):
            if len(results) >= TARGET_SUCCESSFUL_MATCHES:
                break

            print(f"\n[{index}/{len(fixtures)}] {fixture['match']}")
            result = scrape_fixture(browser, fixture)

            if result.get("market_count"):
                market = result["markets"][0]
                print(
                    f"  SUCCESS: {market['selection_count']} "
                    f"exact tackle selections"
                )
                for item in market["selections"]:
                    print(
                        f"    {item['player']:<30} "
                        f"{item['threshold']:<3} {item['odds']}"
                    )
                results.append(result)
            else:
                reason = result.get("error") or "market unavailable / finished"
                print(f"  SKIPPED: {reason}")
                skipped.append(
                    {
                        "match": fixture["match"],
                        "source_url": fixture["source_url"],
                        "reason": reason,
                    }
                )

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BetVictor",
        "market_type": "player_tackles",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_props_generated_at": source_generated_at,
        "target_successful_matches": TARGET_SUCCESSFUL_MATCHES,
        "successful_match_count": len(results),
        "scanned_fixture_count": len(results) + len(skipped),
        "matches": results,
        "skipped": skipped,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print(f"Saved: {OUT_PATH}")
    print(
        f"Successful tackle markets: "
        f"{len(results)}/{TARGET_SUCCESSFUL_MATCHES}"
    )


if __name__ == "__main__":
    main()
