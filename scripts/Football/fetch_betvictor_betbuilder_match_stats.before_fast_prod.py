#!/usr/bin/env python3
"""
fetch_betvictor_betbuilder_match_stats.py

BetVictor Bet Builder Match/Team Shots scraper.

Keeps:
- Match Shots On Target
- Match Shots
- Home/Away Shots On Target
- Home/Away Shots

Key reliability fixes:
- MAX_MATCHES = 15
- retries zero-market fixtures up to 3 times
- uses a fresh browser context for each retry
- verifies the event page and Match Stats tab actually loaded
- supports Turkey / Turkiye / Türkiye row labels
- overwrites the stats JSON from the CURRENT main props fixture list
- records each attempt in the debug folder
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_worldcup_betbuilder_stats.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_betbuilder_stats"

MAX_MATCHES = 15
MAX_ATTEMPTS = 3
HEADLESS = False
BETBUILDER_GROUP = "12536"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
PLUS_RE = re.compile(r"^\d+\+$")

TEAM_ALIASES = {
    "United States": "USA",
    "USA": "USA",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Türkiye": "Türkiye",
    "Czech Republic": "Czechia",
    "Bosnia and Herzegovina": "Bosnia",
    "Bosnia & Herzegovina": "Bosnia",
    "Curaçao": "Curacao",
}

TEAM_ROW_ALIASES = {
    "USA": ["USA", "United States", "United States of America"],
    "Türkiye": ["Türkiye", "Turkey", "Turkiye"],
    "Czechia": ["Czechia", "Czech Republic"],
    "Bosnia": ["Bosnia", "Bosnia and Herzegovina", "Bosnia & Herzegovina"],
    "Curacao": ["Curacao", "Curaçao"],
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_team(value):
    value = clean(value)
    return TEAM_ALIASES.get(value, value)


def normalize(value):
    value = clean(value).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def is_odds(value):
    return bool(ODDS_RE.match(clean(value)))


def is_plus(value):
    return bool(PLUS_RE.match(clean(value)))


def base_event_url(url):
    return str(url or "").split("?", 1)[0]


def group_url(event_url):
    return f"{base_event_url(event_url)}?market_group={BETBUILDER_GROUP}"


def lines_from_text(text):
    return [clean(line) for line in text.splitlines() if clean(line)]


def row_team_aliases(team):
    values = TEAM_ROW_ALIASES.get(team, [team])
    result = []
    for value in values:
        value = clean(value)
        if value and value not in result:
            result.append(value)
    return result


def row_title_candidates(team, stat_label):
    return [f"{name} {stat_label}" for name in row_team_aliases(team)]


def selection(name, odds, **extra):
    item = {
        "selection": clean(name),
        "normalized_selection": normalize(name),
        "odds": clean(odds).upper(),
    }
    item.update({key: value for key, value in extra.items() if value is not None})
    return item


def market(name, selections):
    seen = set()
    output = []

    for item in selections:
        key = (
            item.get("selection"),
            item.get("odds"),
            item.get("side"),
            item.get("line"),
            item.get("team"),
            item.get("stat"),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)

    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(output),
        "selections": output,
    }


def load_fixtures():
    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    fixtures = []

    for match_data in data.get("matches", []):
        url = match_data.get("source_url", "")
        if "/events/" not in url:
            continue

        home = canonical_team(match_data.get("home_team", ""))
        away = canonical_team(match_data.get("away_team", ""))
        match_name = clean(match_data.get("match") or f"{home} v {away}")

        if (not home or not away) and " v " in match_name:
            home, away = [canonical_team(part) for part in match_name.split(" v ", 1)]

        if not home or not away:
            continue

        fixtures.append(
            {
                "match": match_name,
                "home": home,
                "away": away,
                "source_url": base_event_url(url),
            }
        )

    seen = set()
    output = []

    for fixture in fixtures:
        key = (normalize(fixture["match"]), fixture["source_url"])
        if key in seen:
            continue
        seen.add(key)
        output.append(fixture)

    return output[:MAX_MATCHES], data.get("generated_at")


def accept_cookies(page):
    labels = [
        "Accept All",
        "Accept all",
        "I Accept",
        "Accept",
        "Agree",
        "Allow all",
        "OK",
        "I have read the above",
        "Dismiss",
    ]

    for label in labels:
        try:
            locator = page.get_by_role("button", name=re.compile(f"^{re.escape(label)}$", re.I))
            if locator.count():
                locator.first.click(timeout=1500)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def body_text(page):
    try:
        return page.locator("body").inner_text(timeout=20000)
    except Exception:
        return ""


def click_show_more(page):
    for label in ["Show More", "Show more", "View More", "View more", "Show All", "Show all"]:
        try:
            locator = page.get_by_text(label, exact=True)
            for index in range(min(locator.count(), 10)):
                try:
                    locator.nth(index).click(timeout=900)
                    page.wait_for_timeout(250)
                except Exception:
                    pass
        except Exception:
            pass


def wait_for_event_page(page, fixture, timeout_ms=18000):
    deadline = datetime.now().timestamp() + timeout_ms / 1000

    while datetime.now().timestamp() < deadline:
        text = body_text(page)
        low = text.lower()

        has_team = (
            fixture["home"].lower() in low
            or fixture["away"].lower() in low
            or any(alias.lower() in low for alias in row_team_aliases(fixture["home"]))
            or any(alias.lower() in low for alias in row_team_aliases(fixture["away"]))
        )
        has_event_ui = "bet builder" in low or "match stats" in low or "popular" in low

        if has_team and has_event_ui:
            return True

        page.wait_for_timeout(750)

    return False


def click_locator(page, locator):
    try:
        locator.scroll_into_view_if_needed(timeout=2500)
    except Exception:
        pass

    try:
        locator.click(timeout=2500)
        page.wait_for_timeout(1400)
        return True
    except Exception:
        pass

    try:
        locator.evaluate("(el) => el.click()")
        page.wait_for_timeout(1400)
        return True
    except Exception:
        pass

    try:
        box = locator.bounding_box()
        if box:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(1400)
            return True
    except Exception:
        pass

    return False


def match_stats_active(page):
    low = body_text(page).lower()
    return "match shots on target" in low and "match shots" in low


def click_match_stats_tab(page):
    if match_stats_active(page):
        return True

    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    page.wait_for_timeout(500)

    locators = []

    try:
        locators.append(page.get_by_role("tab", name=re.compile(r"^Match Stats$", re.I)))
    except Exception:
        pass

    try:
        locators.append(page.get_by_role("button", name=re.compile(r"^Match Stats$", re.I)))
    except Exception:
        pass

    try:
        locators.append(page.get_by_text("Match Stats", exact=True))
    except Exception:
        pass

    for locator in locators:
        try:
            for index in range(min(locator.count(), 12)):
                if click_locator(page, locator.nth(index)) and match_stats_active(page):
                    return True
        except Exception:
            pass

    return match_stats_active(page)


def find_exact_text(page, labels: Iterable[str]):
    for label in labels:
        try:
            locator = page.get_by_text(label, exact=True)
            for index in range(min(locator.count(), 10)):
                item = locator.nth(index)
                try:
                    box = item.bounding_box()
                except Exception:
                    box = None
                if box and box["width"] > 4 and box["height"] > 4:
                    return label, item
        except Exception:
            pass

    return None, None


def click_row_chevron(page, labels):
    label, item = find_exact_text(page, labels)
    if not item:
        return None

    try:
        item.scroll_into_view_if_needed(timeout=2500)
    except Exception:
        pass
    page.wait_for_timeout(250)

    before = body_text(page)

    # Find a wide, row-like ancestor and click its far-right chevron area.
    try:
        rect = item.evaluate(
            """(el) => {
                let node = el;
                while (node) {
                    const r = node.getBoundingClientRect();
                    if (r.width >= 420 && r.height >= 24 && r.height <= 130) {
                        return {x: r.x, y: r.y, width: r.width, height: r.height};
                    }
                    node = node.parentElement;
                }
                const r = el.getBoundingClientRect();
                return {x: r.x, y: r.y, width: r.width, height: r.height};
            }"""
        )
        x = min(rect["x"] + rect["width"] - 24, 1650)
        y = rect["y"] + rect["height"] / 2
        page.mouse.click(x, y)
        page.wait_for_timeout(1000)
    except Exception:
        click_locator(page, item)

    after = body_text(page)

    # Even if the body text did not change, the row may already have been open.
    return label if label else None


def write_hits(text, debug_dir, filename="HITS.txt"):
    words = ["Match Shots", "Shots on Target", "Shots", "Over", "Under"]
    lines = text.splitlines()
    hits = []

    for index, line in enumerate(lines):
        if any(word.lower() in line.lower() for word in words):
            hits.append(f"{index:04d}: {line}")
            for next_index in range(index + 1, min(index + 16, len(lines))):
                if lines[next_index].strip():
                    hits.append(f"      {next_index:04d}: {lines[next_index]}")
            hits.append("")

    (debug_dir / filename).write_text("\n".join(hits), encoding="utf-8")


def capture_match_stats_page(page, fixture, debug_dir, attempt):
    chunks = []

    def capture(label):
        click_show_more(page)
        text = body_text(page)
        chunks.append(f"=== {label} ===\n{text}")

    tab_ok = click_match_stats_tab(page)
    print(f"      Match Stats active: {tab_ok}")
    capture(f"MATCH_STATS_TAB active={tab_ok}")

    row_specs = [
        ("Match Shots on Target", ["Match Shots on Target"]),
        ("Match Shots", ["Match Shots"]),
        (
            f"{fixture['home']} Shots on Target",
            row_title_candidates(fixture["home"], "Shots on Target"),
        ),
        (
            f"{fixture['home']} Shots",
            row_title_candidates(fixture["home"], "Shots"),
        ),
        (
            f"{fixture['away']} Shots on Target",
            row_title_candidates(fixture["away"], "Shots on Target"),
        ),
        (
            f"{fixture['away']} Shots",
            row_title_candidates(fixture["away"], "Shots"),
        ),
    ]

    found_titles = {}

    for canonical_title, candidates in row_specs:
        actual_title = click_row_chevron(page, candidates)
        found_titles[canonical_title] = actual_title
        capture(f"ROW {canonical_title} actual={actual_title!r}")

    all_text = "\n\n".join(chunks)

    attempt_all = debug_dir / f"ALL_attempt_{attempt}.txt"
    attempt_hits = f"HITS_attempt_{attempt}.txt"
    attempt_all.write_text(all_text, encoding="utf-8")
    write_hits(all_text, debug_dir, attempt_hits)

    # Keep the latest attempt under the familiar filenames too.
    (debug_dir / "ALL.txt").write_text(all_text, encoding="utf-8")
    write_hits(all_text, debug_dir, "HITS.txt")

    return all_text, found_titles, tab_ok


def split_title_block(lines, title, all_titles):
    title_norm = normalize(title)
    indexes = [index for index, value in enumerate(lines) if normalize(value) == title_norm]
    if not indexes:
        return []

    best = []
    best_score = -1

    for index in indexes:
        block = []

        for next_index in range(index + 1, min(index + 90, len(lines))):
            token = clean(lines[next_index])
            if not token:
                continue
            if normalize(token) != title_norm and normalize(token) in all_titles:
                break
            if token in {"Add to Betslip", "Save to Betslip and build a Multiple"}:
                break
            block.append(token)

        score = sum(1 for token in block if is_odds(token))
        if score > best_score:
            best = block
            best_score = score

    return best


def parse_threshold_market(lines, title, market_name, stat, team=None):
    all_titles = {
        normalize("To Have the Most"),
        normalize("Match Shots on Target"),
        normalize("Match Shots"),
    }

    for value in lines:
        low = clean(value).lower()
        if low.endswith("shots on target") or low.endswith("shots"):
            all_titles.add(normalize(value))

    block = split_title_block(lines, title, all_titles)
    if not block:
        return market(market_name, [])

    thresholds = [value for value in block if is_plus(value)]
    odds = [value for value in block if is_odds(value)]

    count = min(len(thresholds), len(odds))
    selections = []

    for threshold, odd in zip(thresholds[:count], odds[:count]):
        selections.append(
            selection(
                f"{market_name} {threshold}",
                odd,
                team=team,
                stat=stat,
                threshold=threshold,
            )
        )

    return market(market_name, selections)


def parse_first_market(lines, titles, market_name, stat, team=None):
    for title in titles:
        parsed = parse_threshold_market(lines, title, market_name, stat, team=team)
        if parsed["selection_count"] > 0:
            return parsed
    return market(market_name, [])


def parse_markets(text, fixture):
    lines = lines_from_text(text)
    home = fixture["home"]
    away = fixture["away"]

    candidates = [
        parse_first_market(
            lines,
            ["Match Shots on Target"],
            "Match Shots On Target",
            "shots_on_target",
        ),
        parse_first_market(lines, ["Match Shots"], "Match Shots", "shots"),
        parse_first_market(
            lines,
            row_title_candidates(home, "Shots on Target"),
            f"{home} Shots On Target",
            "shots_on_target",
            team=home,
        ),
        parse_first_market(
            lines,
            row_title_candidates(home, "Shots"),
            f"{home} Shots",
            "shots",
            team=home,
        ),
        parse_first_market(
            lines,
            row_title_candidates(away, "Shots on Target"),
            f"{away} Shots On Target",
            "shots_on_target",
            team=away,
        ),
        parse_first_market(
            lines,
            row_title_candidates(away, "Shots"),
            f"{away} Shots",
            "shots",
            team=away,
        ),
    ]

    return [candidate for candidate in candidates if candidate["selection_count"] > 0]


def empty_result(fixture, **extra):
    result = {
        "match": fixture["match"],
        "home_team": fixture["home"],
        "away_team": fixture["away"],
        "source_url": fixture["source_url"],
        "market_count": 0,
        "markets": [],
    }
    result.update(extra)
    return result


def scrape_fixture(browser, fixture):
    debug_dir = DEBUG_ROOT / slugify(fixture["match"])
    debug_dir.mkdir(parents=True, exist_ok=True)

    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        context = browser.new_context(viewport={"width": 1700, "height": 1000})
        page = context.new_page()
        url = group_url(fixture["source_url"])

        try:
            print(f"\n{fixture['match']} — attempt {attempt}/{MAX_ATTEMPTS}")
            print(f"  {url}")

            page.goto(url, wait_until="domcontentloaded", timeout=70000)
            page.wait_for_timeout(5500)
            accept_cookies(page)

            ready = wait_for_event_page(page, fixture)
            print(f"      Event page ready: {ready}")

            if not ready:
                last_error = "event_page_not_ready"
                continue

            page_text = body_text(page)
            if "There are currently no markets available" in page_text:
                return empty_result(
                    fixture,
                    note="bet_builder_unavailable",
                    attempts=attempt,
                )

            text, found_titles, tab_ok = capture_match_stats_page(
                page,
                fixture,
                debug_dir,
                attempt,
            )
            markets = parse_markets(text, fixture)

            print(f"  markets: {len(markets)}")
            for parsed_market in markets:
                print(
                    f"    {parsed_market['market']:<35} "
                    f"{parsed_market['selection_count']} selections"
                )

            if markets:
                return {
                    "match": fixture["match"],
                    "home_team": fixture["home"],
                    "away_team": fixture["away"],
                    "source_url": fixture["source_url"],
                    "market_count": len(markets),
                    "markets": markets,
                    "attempts": attempt,
                    "match_stats_active": tab_ok,
                    "found_row_titles": found_titles,
                }

            last_error = "zero_markets_after_parse"
            print("      Zero markets parsed; retrying with a fresh context.")

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(f"      Attempt error: {last_error}")
        finally:
            try:
                context.close()
            except Exception:
                pass

    return empty_result(
        fixture,
        error=last_error or "zero_markets",
        attempts=MAX_ATTEMPTS,
    )


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_ROOT.mkdir(parents=True, exist_ok=True)

    fixtures, source_generated_at = load_fixtures()

    print(f"Loaded {len(fixtures)} CURRENT BetVictor event URLs from main props JSON")
    for index, fixture in enumerate(fixtures, 1):
        print(f"  {index:02d}. {fixture['match']}")
    print(f"MAX_MATCHES = {MAX_MATCHES}")

    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)

        for index, fixture in enumerate(fixtures, 1):
            print("\n" + "=" * 72)
            print(f"[{index}/{len(fixtures)}]")
            results.append(scrape_fixture(browser, fixture))

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BetVictor",
        "market_type": "bet_builder_match_stats",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_props_generated_at": source_generated_at,
        "max_matches": MAX_MATCHES,
        "match_count": len(results),
        "matches_with_markets": len(
            [result for result in results if result.get("market_count", 0) > 0]
        ),
        "matches": results,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nSaved:")
    print(OUT_PATH)
    print(
        f"Matches with markets: "
        f"{output['matches_with_markets']}/{output['match_count']}"
    )


if __name__ == "__main__":
    main()
