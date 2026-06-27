#!/usr/bin/env python3
"""
fetch_ladbrokes_shots_props_PROD15_COMPONENTS.py

Production Ladbrokes aggregate-shots component merge.

Targets:
  - Total Shots On Target Over / Under
  - Home Shots On Target Over / Under
  - Away Shots On Target Over / Under
  - Total Shots Over / Under
  - Home Shots Over / Under
  - Away Shots Over / Under

Reads:
  football/data/ladbrokes_worldcup_props.json

Creates a timestamped backup, merges currently available aggregate
shots markets into football/data/ladbrokes_worldcup_props.json, validates a
temporary file, and atomically replaces production.
"""

import importlib.util
import json
import os
import re
import shutil
import time
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]

PRODUCTION_PATH = (
    ROOT
    / "football"
    / "data"
    / "ladbrokes_worldcup_props.json"
)

TEMP_OUT_PATH = (
    ROOT
    / "football"
    / "data"
    / "ladbrokes_worldcup_props_shots_prod15.tmp.json"
)

BACKUP_DIR = (
    ROOT
    / "football"
    / "data"
    / "backups"
)

SCRAPER_PATH = (
    ROOT
    / "scripts"
    / "Football"
    / "fetch_ladbrokes_worldcup_props.py"
)

DEBUG_DIR = (
    ROOT
    / "football"
    / "debug"
    / "ladbrokes_shots_prod15_components"
)

MAX_MATCHES = 15
HEADLESS = False

MIN_SELECTIONS_PER_MARKET = 2


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def normalize(value):
    value = clean(value).replace(
        "&",
        "and",
    )
    value = unicodedata.normalize(
        "NFKD",
        value,
    )
    value = "".join(
        character
        for character in value
        if not unicodedata.combining(
            character
        )
    ).lower()

    return re.sub(
        r"[^a-z0-9]+",
        "_",
        value,
    ).strip("_")


def load_scraper_module():
    spec = importlib.util.spec_from_file_location(
        "ladbrokes_production_scraper",
        SCRAPER_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load {SCRAPER_PATH}"
        )

    module = importlib.util.module_from_spec(
        spec
    )
    spec.loader.exec_module(module)
    return module


def write_debug(
    match_name,
    label,
    content,
):
    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        match_name.lower(),
    ).strip("-")
    label_slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        label.lower(),
    ).strip("-")

    path = (
        DEBUG_DIR
        / f"{slug}_{label_slug}.txt"
    )
    path.write_text(
        str(content or ""),
        encoding="utf-8",
    )


def collect_market_titles_while_scrolling(
    page,
    scraper,
    steps=24,
):
    """
    Ladbrokes virtualizes the all-markets page, so not every market component
    exists in the DOM at the same time. Collect titles while scrolling through
    the page instead of reading only the final viewport.
    """
    titles = []
    seen = set()

    page.keyboard.press("Control+Home")
    page.wait_for_timeout(450)

    for _ in range(steps):
        for title in scraper.list_market_titles(
            page
        ):
            key = normalize(title)

            if not key or key in seen:
                continue

            seen.add(key)
            titles.append(title)

        page.mouse.wheel(0, 750)
        page.wait_for_timeout(180)

    return titles


def ensure_market_visible(
    page,
    scraper,
    title,
    steps=28,
):
    """
    Scroll until an exact component title is mounted in the current DOM.
    """
    wanted = normalize(title)

    page.keyboard.press("Control+Home")
    page.wait_for_timeout(350)

    for _ in range(steps):
        current = (
            scraper.list_market_titles(page)
        )

        if any(
            normalize(item) == wanted
            for item in current
        ):
            return True

        page.mouse.wheel(0, 700)
        page.wait_for_timeout(180)

    return False


def classify_aggregate_shot_titles(
    titles,
):
    """
    Discover Ladbrokes title variations instead of requiring one exact phrase.
    Player props are explicitly excluded.
    """
    found = {
        "shots_on_target": "",
        "shots": "",
    }

    for title in titles:
        low = clean(title).lower()

        if (
            "shot" not in low
            or "player" in low
        ):
            continue

        if (
            "shots on target" in low
            or "shot on target" in low
        ):
            if not found["shots_on_target"]:
                found["shots_on_target"] = title
            continue

        if "shots" in low or "shot" in low:
            if not found["shots"]:
                found["shots"] = title

    return found


def component_title(
    titles,
    wanted,
):
    wanted_norm = normalize(wanted)

    for title in titles:
        if normalize(title) == wanted_norm:
            return title

    return ""


def actual_switcher_label(
    switchers,
    wanted,
):
    """
    Resolve team aliases/capitalisation against the actual labels Ladbrokes
    rendered in the component.
    """
    wanted_norm = normalize(wanted)

    aliases = {
        "usa": {
            "usa",
            "united_states",
            "united_states_of_america",
        },
        "turkiye": {
            "turkiye",
            "turkey",
        },
        "dr_congo": {
            "dr_congo",
            "d_r_congo",
            "democratic_republic_of_congo",
        },
        "ivory_coast": {
            "ivory_coast",
            "cote_d_ivoire",
        },
        "curacao": {
            "curacao",
            "curaçao",
        },
    }

    wanted_aliases = aliases.get(
        wanted_norm,
        {wanted_norm},
    )

    for label in switchers:
        label_norm = normalize(label)

        if label_norm == wanted_norm:
            return label

        if label_norm in wanted_aliases:
            return label

        for alias_key, alias_values in aliases.items():
            if (
                wanted_norm in alias_values
                and label_norm in alias_values
            ):
                return label

    return ""


def wait_for_rows_stable(
    page,
    scraper,
    title,
    previous_signature="",
    minimum_rows=1,
    timeout_seconds=8,
):
    """
    Poll one component until it has usable rows and the tab content has either
    changed from the previous tab or stabilised.
    """
    deadline = (
        time.perf_counter()
        + timeout_seconds
    )
    best = None
    best_rows = 0
    best_signature = ""

    while time.perf_counter() < deadline:
        data = scraper.extract_market_component(
            page,
            title,
        )
        rows = scraper.structured_rows(
            data
        )
        signature = clean(
            data.get("text", "")
            if data
            else ""
        )

        if len(rows) > best_rows:
            best = data
            best_rows = len(rows)
            best_signature = signature

        content_changed = (
            not previous_signature
            or (
                signature
                and signature
                != previous_signature
            )
        )

        if (
            len(rows) >= minimum_rows
            and content_changed
        ):
            page.wait_for_timeout(550)
            stable = (
                scraper.extract_market_component(
                    page,
                    title,
                )
            )
            stable_rows = (
                scraper.structured_rows(
                    stable
                )
            )

            if len(stable_rows) >= len(rows):
                return (
                    stable,
                    clean(
                        stable.get("text", "")
                    ),
                )

        page.wait_for_timeout(300)

    return best, best_signature


def parse_tab_market(
    scraper,
    data,
    market_name,
    team="",
    max_line=50.5,
):
    market = scraper.parse_ou_component(
        data,
        market_name,
        selection_prefix=team,
        max_line=max_line,
    )

    if (
        market.get("selection_count", 0)
        < MIN_SELECTIONS_PER_MARKET
    ):
        return scraper.mkt(
            market_name,
            [],
        )

    return market


def replace_latest_valid(
    match,
    market,
):
    """
    Replace an existing aggregate-shots market with the latest valid capture.
    If Ladbrokes does not currently publish a market, no replacement is made.
    """
    if (
        market.get("selection_count", 0)
        < MIN_SELECTIONS_PER_MARKET
    ):
        return False, "below quality floor"

    key = market["normalized_market"]
    markets = match.setdefault(
        "markets",
        [],
    )

    for index, existing in enumerate(markets):
        if (
            existing.get("normalized_market")
            != key
        ):
            continue

        old_count = len(
            existing.get("selections", [])
        )
        new_count = len(
            market.get("selections", [])
        )
        markets[index] = market

        return (
            True,
            f"refreshed {old_count} -> {new_count}",
        )

    markets.append(market)
    return (
        True,
        f"added {market['selection_count']}",
    )


def scrape_component_tabs(
    page,
    scraper,
    match_name,
    title,
    home,
    away,
    base_market_name,
    max_line,
):
    result = []
    diagnostics = []

    visible = ensure_market_visible(
        page,
        scraper,
        title,
    )

    if not visible:
        return result, [
            f"{title}: component not visible "
            "after full-page scan"
        ]

    expanded = scraper.expand_market_component(
        page,
        title,
        show_all=True,
    )

    if not expanded.get("found"):
        return result, [
            f"{title}: component not found"
        ]

    initial = scraper.extract_market_component(
        page,
        title,
    )
    switchers = (
        initial.get("switchers", [])
        if initial
        else []
    )

    diagnostics.append(
        f"{title}: switchers={switchers}"
    )

    tab_specs = [
        (
            "Match",
            "Match",
            f"Total {base_market_name} "
            "Over / Under",
            "",
        ),
        (
            home,
            actual_switcher_label(
                switchers,
                home,
            ),
            f"{home} {base_market_name} "
            "Over / Under",
            home,
        ),
        (
            away,
            actual_switcher_label(
                switchers,
                away,
            ),
            f"{away} {base_market_name} "
            "Over / Under",
            away,
        ),
    ]

    previous_signature = ""

    for (
        display_tab,
        actual_tab,
        market_name,
        team_prefix,
    ) in tab_specs:
        if display_tab == "Match":
            actual_tab = actual_switcher_label(
                switchers,
                "Match",
            ) or "Match"

        if not actual_tab:
            diagnostics.append(
                f"{title}/{display_tab}: "
                "tab label not found"
            )
            continue

        clicked = (
            scraper.click_market_switcher(
                page,
                title,
                actual_tab,
            )
        )

        data, signature = wait_for_rows_stable(
            page,
            scraper,
            title,
            previous_signature=
                previous_signature,
            minimum_rows=1,
            timeout_seconds=8,
        )

        rows = scraper.structured_rows(
            data
        )
        market = parse_tab_market(
            scraper,
            data,
            market_name,
            team=team_prefix,
            max_line=max_line,
        )

        diagnostics.append(
            f"{title}/{display_tab}: "
            f"actual={actual_tab} | "
            f"clicked={clicked} | "
            f"rows={len(rows)} | "
            f"captured="
            f"{market['selection_count']}"
        )

        if market["selections"]:
            result.append(market)

        previous_signature = (
            signature
            or previous_signature
        )

    if len(result) < 3:
        write_debug(
            match_name,
            normalize(title),
            (
                initial.get("text", "")
                if initial
                else "component missing"
            ),
        )

    return result, diagnostics


def scrape_match(
    page,
    scraper,
    match,
):
    started = time.perf_counter()

    home = clean(
        match.get("home_team", "")
    )
    away = clean(
        match.get("away_team", "")
    )
    name = clean(
        match.get("match", "")
    )
    url = clean(
        match.get("url", "")
    )

    if not home or not away or not url:
        return None

    base = url.replace(
        "/main-markets",
        "",
    ).rstrip("/")
    main_url = f"{base}/main-markets"
    all_url = f"{base}/all-markets"

    # The main page has the reliable scoreboard/in-play marker.
    page.goto(
        main_url,
        wait_until="domcontentloaded",
        timeout=45000,
    )
    page.wait_for_timeout(2600)
    scraper.accept_cookies(page)

    if scraper.event_is_live(page):
        print(
            "    SKIP: live/started"
        )
        return {
            "status": "live",
            "markets": [],
            "missing": [],
            "seconds": round(
                time.perf_counter()
                - started,
                3,
            ),
        }

    page.goto(
        all_url,
        wait_until="domcontentloaded",
        timeout=45000,
    )
    scraper.wait_for_any_text(
        page,
        [
            "Over/Under Total Shots",
            "Over/Under Total Shots On Target",
            "Player Total Shots",
        ],
        timeout=12000,
    )
    page.wait_for_timeout(1600)
    scraper.accept_cookies(page)

    titles = collect_market_titles_while_scrolling(
        page,
        scraper,
    )
    print(
        "    shots page titles: "
        + (
            " | ".join(
                title
                for title in titles
                if "shot" in title.lower()
            )
            or "none"
        )
    )

    discovered = classify_aggregate_shot_titles(
        titles
    )

    print(
        "    discovered aggregate titles: "
        f"SOT={discovered['shots_on_target'] or 'missing'} | "
        f"Shots={discovered['shots'] or 'missing'}"
    )

    specs = [
        (
            discovered["shots_on_target"],
            "Shots On Target",
            30.5,
        ),
        (
            discovered["shots"],
            "Shots",
            60.5,
        ),
    ]

    markets = []
    diagnostics = []

    for title, base_name, max_line in specs:
        if not title:
            diagnostics.append(
                f"aggregate {base_name}: title missing"
            )
            continue

        component_markets, component_log = (
            scrape_component_tabs(
                page,
                scraper,
                name,
                title,
                home,
                away,
                base_name,
                max_line,
            )
        )
        markets.extend(
            component_markets
        )
        diagnostics.extend(
            component_log
        )

    for line in diagnostics:
        print(f"    {line}")

    expected = {
        normalize(
            "Total Shots On Target "
            "Over / Under"
        ),
        normalize(
            f"{home} Shots On Target "
            "Over / Under"
        ),
        normalize(
            f"{away} Shots On Target "
            "Over / Under"
        ),
        normalize(
            "Total Shots Over / Under"
        ),
        normalize(
            f"{home} Shots Over / Under"
        ),
        normalize(
            f"{away} Shots Over / Under"
        ),
    }

    captured = {
        market["normalized_market"]
        for market in markets
    }
    missing = sorted(
        expected - captured
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    return {
        "status": (
            "available"
            if markets
            else "unavailable"
        ),
        "markets": markets,
        "missing": missing,
        "seconds": round(
            elapsed,
            3,
        ),
    }


def main():
    started = time.perf_counter()

    if not PRODUCTION_PATH.exists():
        raise FileNotFoundError(
            f"Missing {PRODUCTION_PATH}"
        )

    if not SCRAPER_PATH.exists():
        raise FileNotFoundError(
            f"Missing {SCRAPER_PATH}"
        )

    scraper = load_scraper_module()

    production_data = json.loads(
        PRODUCTION_PATH.read_text(
            encoding="utf-8"
        )
    )
    matches = production_data.get(
        "matches",
        [],
    )

    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")
    backup_path = (
        BACKUP_DIR
        / (
            "ladbrokes_worldcup_props_"
            f"before_shots_merge_{timestamp}.json"
        )
    )
    shutil.copy2(
        PRODUCTION_PATH,
        backup_path,
    )

    print("=" * 68)
    print(
        "Ladbrokes Aggregate Shots "
        "PROD15 COMPONENTS"
    )
    print("=" * 68)
    print(
        f"Loaded {len(matches)} matches"
    )
    print(f"Backup: {backup_path}")

    scanned = 0
    available = 0
    changed_matches = 0
    skipped_live = 0
    unavailable = 0
    full_six = 0

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

        for candidate_index, match in enumerate(
            matches,
            start=1,
        ):
            if scanned >= MAX_MATCHES:
                break

            scanned += 1
            name = match.get(
                "match",
                "Unknown fixture",
            )

            print(
                f"\n[{scanned}/{min(MAX_MATCHES, len(matches))}] "
                f"{name}"
            )

            result = scrape_match(
                page,
                scraper,
                match,
            )

            if result.get("status") == "live":
                skipped_live += 1
                continue

            if not result.get("markets"):
                unavailable += 1
                print(
                    "    availability: no aggregate "
                    "Shots/SOT market published"
                )
                print(
                    f"    elapsed: "
                    f"{result['seconds']:.2f}s"
                )
                continue

            available += 1
            accepted = []

            for market in result["markets"]:
                was_changed, reason = (
                    replace_latest_valid(
                        match,
                        market,
                    )
                )

                if was_changed:
                    accepted.append(
                        f"{market['market']} "
                        f"({reason})"
                    )

            if accepted:
                changed_matches += 1

            if not result["missing"]:
                full_six += 1

            match["market_count"] = len(
                match.get("markets", [])
            )

            print(
                "    accepted: "
                + (
                    " | ".join(accepted)
                    if accepted
                    else "none"
                )
            )
            print(
                "    aggregate-shots audit: "
                + (
                    ", ".join(
                        result["missing"]
                    )
                    if result["missing"]
                    else "none"
                )
            )
            print(
                f"    elapsed: "
                f"{result['seconds']:.2f}s"
            )

        browser.close()

    production_data["generated_at"] = datetime.now(
        timezone.utc
    ).isoformat()
    production_data[
        "ladbrokes_aggregate_shots"
    ] = {
        "type":
            "aggregate_shots_prod15_components",
        "completed_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "fixtures_scanned": scanned,
        "fixtures_with_markets": available,
        "fixtures_with_all_six": full_six,
        "matches_changed": changed_matches,
        "skipped_live": skipped_live,
        "markets_unavailable": unavailable,
        "backup_path": str(backup_path),
    }

    TEMP_OUT_PATH.write_text(
        json.dumps(
            production_data,
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

    if not isinstance(
        validated.get("matches"),
        list,
    ):
        raise RuntimeError(
            "Temporary JSON validation failed: "
            "matches is not a list"
        )

    if len(
        validated["matches"]
    ) != len(matches):
        raise RuntimeError(
            "Temporary JSON validation failed: "
            "match count changed"
        )

    os.replace(
        TEMP_OUT_PATH,
        PRODUCTION_PATH,
    )

    print("")
    print("=" * 68)
    print(f"Fixtures scanned: {scanned}")
    print(
        "Fixtures with aggregate markets: "
        f"{available}"
    )
    print(
        "Fixtures with all six markets: "
        f"{full_six}"
    )
    print(
        f"Changed matches: {changed_matches}"
    )
    print(
        f"Unavailable: {unavailable}"
    )
    print(
        f"Skipped live: {skipped_live}"
    )
    print(
        f"Elapsed: "
        f"{time.perf_counter() - started:.2f}s"
    )
    print(
        f"Production output: "
        f"{PRODUCTION_PATH}"
    )
    print(f"Backup: {backup_path}")
    print(
        "Production JSON modified: YES"
    )
    print("=" * 68)


if __name__ == "__main__":
    main()
