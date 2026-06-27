#!/usr/bin/env python3
"""
fetch_unibet_worldcup_props_UNIFIED_PROD15_CLEAN_V2.py

Production unified Unibet World Cup props scraper.

Each fixture is opened and expanded once. The same rendered page supplies:
  - supported match/team markets and Anytime Goalscorer via the current
    validated text parser;
  - Player Shots On Target, Player Shots, Player Cards and Player Assists via
    the corrected positioned-DOM parser.

Production scope:
  Match Betting
  Total Goals Over / Under
  Team Total Goals Over / Under
  Both Teams To Score
  Double Chance
  Total Cards Over / Under
  Total Corners Over / Under
  Anytime Goalscorer
  Player Shots On Target
  Player Shots
  Player Cards
  Player Assists

Player markets are optional. Markets not currently published by Unibet are not
treated as scraper failures.

Creates a timestamped backup, validates a temporary JSON, then atomically
replaces football/data/unibet_worldcup_props.json.
"""

import importlib.util
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]

MAIN_SCRIPT = (
    ROOT
    / "scripts"
    / "Football"
    / "fetch_unibet_worldcup_props.py"
)

DOM_SCRIPT = (
    ROOT
    / "scripts"
    / "Football"
    / "fetch_unibet_worldcup_shots_cards.py"
)

OUT_PATH = (
    ROOT
    / "football"
    / "data"
    / "unibet_worldcup_props.json"
)

TEMP_OUT_PATH = (
    ROOT
    / "football"
    / "data"
    / "unibet_worldcup_props_unified.tmp.json"
)

BACKUP_DIR = (
    ROOT
    / "football"
    / "data"
    / "backups"
)

DEBUG_DIR = (
    ROOT
    / "football"
    / "debug"
    / "unibet_worldcup_props_unified"
)

MAX_MATCHES = 15
CANDIDATE_LIMIT = 15
HEADLESS = False

CORRECTED_MARKETS = {
    "Player Shots On Target",
    "Player Shots",
    "Player Cards",
    "Player Assists",
}


SUPPORTED_MARKETS = {
    "Match Betting",
    "Total Goals Over / Under",
    "Team Total Goals Over / Under",
    "Both Teams To Score",
    "Double Chance",
    "Total Cards Over / Under",
    "Total Corners Over / Under",
    "Anytime Goalscorer",
    "Player Shots On Target",
    "Player Shots",
    "Player Cards",
    "Player Assists",
}

PLAYER_THRESHOLDS = {
    "Player Shots On Target": {"1+", "2+", "3+"},
    "Player Shots": {"1+", "2+", "3+", "4+", "5+"},
    "Player Cards": {"1+"},
    "Player Assists": {"1+", "2+"},
}

OU_MARKETS = {
    "Total Goals Over / Under",
    "Team Total Goals Over / Under",
    "Total Cards Over / Under",
    "Total Corners Over / Under",
}


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def slugify(value):
    value = clean(value).lower()
    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    )
    return value.strip("-") or "unknown-match"


def load_module(name, path):
    if not path.exists():
        raise FileNotFoundError(
            f"Missing required repo script: {path}"
        )

    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not import {path}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for_match_ready(page, timeout_ms=12000):
    """
    Replace most of the unconditional initial sleep with a bounded readiness
    wait. A short settling delay remains after useful market text appears.
    """
    useful = re.compile(
        r"Full Time Result|Total Goals|"
        r"Both Teams to Score|Player Shots|"
        r"Anytime Scorer",
        re.I,
    )
    deadline = time.perf_counter() + (
        timeout_ms / 1000
    )

    while time.perf_counter() < deadline:
        try:
            text = page.locator("body").inner_text(
                timeout=1800
            )
        except Exception:
            text = ""

        if useful.search(text):
            page.wait_for_timeout(700)
            return True

        page.wait_for_timeout(300)

    return False


def expand_all_view_more_fast(
    page,
    max_clicks=80,
):
    """
    Same conservative one-at-a-time strategy as the production scrapers, but
    with a shorter post-click settle. It avoids batch JavaScript clicking, so
    React can remount the next button safely between clicks.
    """
    clicks = 0
    idle_rounds = 0

    while clicks < max_clicks and idle_rounds < 5:
        try:
            loc = page.get_by_text(
                "View more",
                exact=True,
            )
            count = loc.count()
        except Exception:
            count = 0

        clicked = False

        for index in range(min(count, 12)):
            try:
                target = loc.nth(index)

                if not target.is_visible(
                    timeout=350
                ):
                    continue

                target.scroll_into_view_if_needed(
                    timeout=1200
                )
                page.wait_for_timeout(80)
                target.click(timeout=1800)
                page.wait_for_timeout(350)

                clicks += 1
                clicked = True
                idle_rounds = 0
                break
            except Exception:
                continue

        if clicked:
            continue

        idle_rounds += 1
        page.mouse.wheel(0, 850)
        page.wait_for_timeout(220)

    print(
        f"Clicked View more {clicks} times "
        "(unified pass)"
    )
    return clicks


def load_saved_links(
    main_module,
    dom_module,
):
    """
    Prefer links already stored by the current Unibet files when the list page
    does not expose anchors. This mirrors the dedicated DOM scraper fallback.
    """
    try:
        dom_module.MAX_MATCHES = CANDIDATE_LIMIT
        links = dom_module.load_saved_match_links()
    except Exception:
        links = []

    if links:
        return links[:CANDIDATE_LIMIT]

    paths = [
        ROOT
        / "football"
        / "data"
        / "unibet_worldcup_props.json",
        ROOT
        / "football"
        / "data"
        / "unibet_worldcup_moneylines.json",
    ]

    output = []
    seen = set()

    for path in paths:
        if not path.exists():
            continue

        try:
            data = json.loads(
                path.read_text(encoding="utf-8")
            )
        except Exception:
            continue

        for match in data.get("matches", []):
            url = clean(
                match.get("source_url")
                or match.get("url")
            )

            if (
                not url
                or "-vs-" not in url
                or url in seen
            ):
                continue

            seen.add(url)
            output.append(
                {
                    "url": url,
                    "text": clean(
                        match.get("match", "")
                    ),
                }
            )

            if len(output) >= CANDIDATE_LIMIT:
                return output

    return output


def collect_links(
    page,
    main_module,
    dom_module,
):
    main_module.MAX_MATCHES = CANDIDATE_LIMIT
    dom_module.MAX_MATCHES = CANDIDATE_LIMIT

    links = main_module.collect_match_links(
        page
    )

    if links:
        return links[:CANDIDATE_LIMIT]

    print(
        "List page returned no links; "
        "using saved Unibet URLs."
    )

    saved = load_saved_links(
        main_module,
        dom_module,
    )
    return saved[:CANDIDATE_LIMIT]


def corrected_dom_markets(
    rows,
    dom_module,
):
    markets = []

    for config in dom_module.MARKETS:
        market = dom_module.parse_row_market(
            rows,
            config,
        )

        if market and market.get("selections"):
            markets.append(market)

    return markets


def replace_corrected_markets(
    main_markets,
    corrected,
    main_module,
):
    """
    Mimic the existing correction merge policy inside the same browser pass:
    remove all four flattened-text versions and append only the positioned-DOM
    versions that were successfully parsed.
    """
    kept = [
        market
        for market in main_markets
        if market.get("market")
        not in CORRECTED_MARKETS
    ]

    corrected_by_name = {
        market.get("market"): market
        for market in corrected
        if market.get("market")
        in CORRECTED_MARKETS
    }

    for name in [
        "Player Shots On Target",
        "Player Shots",
        "Player Cards",
        "Player Assists",
    ]:
        market = corrected_by_name.get(name)

        if market:
            kept.append(market)

    cleaned = main_module.dedupe_markets(
        kept
    )

    return [
        market
        for market in cleaned
        if market.get("market")
        in SUPPORTED_MARKETS
    ]


def save_debug(
    match_name,
    url,
    text,
    rows,
    dom_module,
):
    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    slug = slugify(match_name)

    (
        DEBUG_DIR
        / f"{slug}.txt"
    ).write_text(
        text,
        encoding="utf-8",
    )

    compact = {}

    for config in dom_module.MARKETS:
        heading = config["heading"]
        indices = [
            index
            for index, row in enumerate(rows)
            if any(
                heading
                == clean(cell.get("text"))
                for cell in row.get("cells", [])
            )
        ]

        if not indices:
            continue

        compact[config["market"]] = {
            "heading": heading,
            "rows": dom_module.compact_market_rows(
                rows,
                indices[0],
            ),
        }

    (
        DEBUG_DIR
        / f"{slug}_dom.json"
    ).write_text(
        json.dumps(
            {
                "match": match_name,
                "url": url,
                "markets": compact,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def scrape_match(
    page,
    item,
    main_module,
    dom_module,
):
    started = time.perf_counter()
    url = item["url"]
    fallback_text = item.get("text") or ""

    print(
        f"\nOpening Unibet match page: {url}"
    )

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    ready = wait_for_match_ready(page)
    main_module.accept_cookies(page)
    main_module.click_main_markets(page)
    wait_for_match_ready(
        page,
        timeout_ms=7000,
    )

    initial_text = page.locator(
        "body"
    ).inner_text(timeout=30000)

    match_name = (
        main_module.get_match_name_from_page(
            initial_text,
            url,
            fallback_text=fallback_text,
        )
    )
    home, away = main_module.split_teams(
        match_name
    )

    clicks = expand_all_view_more_fast(
        page,
        max_clicks=80,
    )
    page.wait_for_timeout(650)

    text = page.locator(
        "body"
    ).inner_text(timeout=30000)
    rows = dom_module.collect_rows(page)

    main_markets = []

    if home and away:
        main_markets.extend(
            main_module.parse_match_markets(
                text,
                home,
                away,
            )
        )
        main_markets.extend(
            main_module.parse_player_markets(
                text,
                home,
                away,
            )
        )

    main_markets = (
        main_module.dedupe_markets(
            main_markets
        )
    )
    corrected = corrected_dom_markets(
        rows,
        dom_module,
    )
    markets = replace_corrected_markets(
        main_markets,
        corrected,
        main_module,
    )

    save_debug(
        match_name,
        url,
        text,
        rows,
        dom_module,
    )

    corrected_counts = {
        market["market"]:
            market.get("selection_count", 0)
        for market in corrected
    }
    missing_corrected = [
        name
        for name in [
            "Player Shots On Target",
            "Player Shots",
            "Player Cards",
            "Player Assists",
        ]
        if name not in corrected_counts
    ]

    if len(corrected_counts) == 4:
        player_market_state = "complete"
    elif corrected_counts:
        player_market_state = "partial"
    else:
        player_market_state = "not published"

    elapsed = time.perf_counter() - started

    print(f"Detected match: {match_name}")
    print(f"Ready signal found: {ready}")
    print(
        f"Player-market state: "
        f"{player_market_state}"
    )
    print(
        "Corrected DOM markets: "
        + (
            " | ".join(
                f"{name}={count}"
                for name, count
                in corrected_counts.items()
            )
            or "none"
        )
    )
    print(
        "Corrected-market availability audit: "
        + (
            ", ".join(missing_corrected)
            if missing_corrected
            else "none"
        )
    )

    for market in markets:
        print(
            f"  - {market['market']}: "
            f"{market['selection_count']}"
        )

    print(
        f"Unified fixture elapsed: "
        f"{elapsed:.2f}s"
    )

    return {
        "match": match_name,
        "home_team": home,
        "away_team": away,
        "source_url": url,
        "market_count": len(markets),
        "markets": markets,
    }


def selection_key(selection):
    return (
        clean(
            selection.get(
                "normalized_selection",
                "",
            )
        ),
        clean(selection.get("player", "")),
        clean(selection.get("threshold", "")),
        clean(selection.get("side", "")),
        clean(selection.get("line", "")),
        clean(selection.get("team", "")),
    )


def validate_output(output, expected_count):
    matches = output.get("matches")

    if not isinstance(matches, list):
        raise RuntimeError(
            "Validation failed: matches is not a list"
        )

    if len(matches) != expected_count:
        raise RuntimeError(
            "Validation failed: match count "
            f"{len(matches)} != {expected_count}"
        )

    issues = []

    for match in matches:
        match_name = clean(match.get("match"))
        home = clean(match.get("home_team"))
        away = clean(match.get("away_team"))
        markets = match.get("markets")

        if not match_name or not home or not away:
            issues.append(
                f"Invalid match identity: {match_name!r}"
            )
            continue

        if not isinstance(markets, list):
            issues.append(
                f"{match_name}: markets is not a list"
            )
            continue

        seen_market_names = set()

        for market in markets:
            name = clean(market.get("market"))
            selections = market.get("selections")

            if name not in SUPPORTED_MARKETS:
                issues.append(
                    f"{match_name}: unsupported market {name}"
                )

            if name in seen_market_names:
                issues.append(
                    f"{match_name}: duplicate market {name}"
                )
            seen_market_names.add(name)

            if not isinstance(selections, list) or not selections:
                issues.append(
                    f"{match_name}/{name}: empty selections"
                )
                continue

            if market.get("selection_count") != len(selections):
                issues.append(
                    f"{match_name}/{name}: selection_count mismatch"
                )

            seen_selections = set()
            ou_groups = {}

            for selection in selections:
                key = selection_key(selection)

                if key in seen_selections:
                    issues.append(
                        f"{match_name}/{name}: duplicate selection {key}"
                    )
                seen_selections.add(key)

                try:
                    decimal_odds = float(
                        selection.get("decimal_odds")
                    )
                except Exception:
                    decimal_odds = 0

                if decimal_odds <= 1:
                    issues.append(
                        f"{match_name}/{name}: invalid decimal odds"
                    )

                if name in PLAYER_THRESHOLDS:
                    threshold = clean(
                        selection.get("threshold")
                    )
                    if threshold not in PLAYER_THRESHOLDS[name]:
                        issues.append(
                            f"{match_name}/{name}: "
                            f"invalid threshold {threshold}"
                        )

                if name in OU_MARKETS:
                    line = clean(selection.get("line"))
                    side = clean(
                        selection.get("side")
                    ).lower()
                    team = clean(selection.get("team"))

                    if not line or side not in {"over", "under"}:
                        issues.append(
                            f"{match_name}/{name}: invalid O/U selection"
                        )
                    else:
                        ou_groups.setdefault(
                            (team, line),
                            set(),
                        ).add(side)

            if name in OU_MARKETS:
                for group, sides in ou_groups.items():
                    if sides != {"over", "under"}:
                        issues.append(
                            f"{match_name}/{name}/{group}: "
                            f"incomplete O/U pair {sorted(sides)}"
                        )

        match["market_count"] = len(markets)

    if issues:
        preview = "\n".join(
            f"  - {issue}"
            for issue in issues[:30]
        )
        raise RuntimeError(
            "Unibet production validation failed:\n"
            + preview
        )


def main():
    started = time.perf_counter()

    OUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    main_module = load_module(
        "unibet_main_current",
        MAIN_SCRIPT,
    )
    dom_module = load_module(
        "unibet_dom_current",
        DOM_SCRIPT,
    )

    matches = []
    errors = []

    print("=" * 70)
    print(
        "UNIBET UNIFIED PROPS PROD15 CLEAN V2"
    )
    print("=" * 70)
    print(
        "One fixture load and one expansion pass"
    )
    print(
        "Unsupported markets are filtered out"
    )
    print(
        "Player markets are optional"
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS
        )
        page = browser.new_page(
            viewport={
                "width": 1700,
                "height": 1000,
            }
        )

        links = collect_links(
            page,
            main_module,
            dom_module,
        )[:MAX_MATCHES]

        if not links:
            browser.close()
            raise RuntimeError(
                "No Unibet fixture links found"
            )

        print(
            f"\nScraping {len(links)} fixtures"
        )

        for index, item in enumerate(
            links,
            start=1,
        ):
            print("")
            print("=" * 70)
            print(
                f"Unified Unibet "
                f"{index}/{len(links)}"
            )
            print("=" * 70)

            try:
                match = scrape_match(
                    page,
                    item,
                    main_module,
                    dom_module,
                )
                matches.append(match)
            except Exception as error:
                print(
                    f"ERROR scraping "
                    f"{item.get('url')}: "
                    f"{error}"
                )
                errors.append(
                    {
                        "url": item.get("url"),
                        "error": str(error),
                    }
                )

        browser.close()

    if errors:
        raise RuntimeError(
            "Unibet scrape completed with "
            f"{len(errors)} error(s); "
            "production was not modified"
        )

    elapsed = time.perf_counter() - started
    good_matches = [
        match
        for match in matches
        if match.get("market_count", 0) > 0
    ]

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "Unibet",
        "market_type": "props",
        "source_url": main_module.LIST_URL,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "match_count": len(matches),
        "matches_with_markets":
            len(good_matches),
        "error_count": 0,
        "errors": [],
        "supported_markets": sorted(
            SUPPORTED_MARKETS
        ),
        "player_markets_optional": True,
        "scraper":
            "unified_single_pass_clean_v2_multi_occurrence",
        "elapsed_seconds": round(
            elapsed,
            3,
        ),
        "matches": matches,
    }

    validate_output(
        output,
        expected_count=len(links),
    )

    TEMP_OUT_PATH.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    validated = json.loads(
        TEMP_OUT_PATH.read_text(
            encoding="utf-8"
        )
    )
    validate_output(
        validated,
        expected_count=len(links),
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")
    backup_path = (
        BACKUP_DIR
        / (
            "unibet_worldcup_props_"
            f"before_unified_{timestamp}.json"
        )
    )

    if OUT_PATH.exists():
        shutil.copy2(
            OUT_PATH,
            backup_path,
        )

    os.replace(
        TEMP_OUT_PATH,
        OUT_PATH,
    )

    print("")
    print("=" * 70)
    print(
        "UNIBET UNIFIED PROD15 CLEAN V2 COMPLETE"
    )
    print("=" * 70)
    print(f"Fixtures scraped: {len(matches)}")
    print(
        "Matches with markets: "
        f"{len(good_matches)}"
    )
    print("Errors: 0")
    print(
        f"Elapsed: {elapsed:.2f}s"
    )
    print(f"Wrote: {OUT_PATH}")
    if backup_path.exists():
        print(f"Backup: {backup_path}")
    print(
        "Validation: PASS"
    )
    print(
        "Production JSON modified: YES"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
