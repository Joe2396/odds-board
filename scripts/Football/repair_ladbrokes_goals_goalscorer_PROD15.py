#!/usr/bin/env python3
"""
repair_ladbrokes_goals_goalscorer_PROD15.py

Production Ladbrokes repair pass for:
  - Total Goals Over / Under
  - 1st Half Goals Over / Under
  - full Player to Score

Loads the current production Ladbrokes props JSON but writes only to:
  football/data/ladbrokes_worldcup_props_repair_run3.json

Production JSON is never modified.
"""

import importlib.util
import json
import os
import shutil
import time
from datetime import datetime, timezone
from copy import deepcopy
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
    / "ladbrokes_worldcup_props_repair_prod15.tmp.json"
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

MAX_MATCHES = 15
HEADLESS = False
MIN_GOALSCORER_SELECTIONS = 60
MIN_TOTAL_GOALS_SELECTIONS = 6
MIN_FIRST_HALF_GOALS_SELECTIONS = 4
MIN_TEAM_GOALS_SELECTIONS = 4


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


def clean(value):
    import re

    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def replace_if_quality(
    match,
    new_market,
    minimum_selections,
):
    """
    Replace/add a market only when the new capture meets its quality floor
    and improves on what is already stored.
    """
    if not new_market:
        return False, "no market"

    new_count = len(
        new_market.get("selections", [])
    )

    if new_count < minimum_selections:
        return (
            False,
            f"below quality floor "
            f"({new_count} < {minimum_selections})",
        )

    key = new_market["normalized_market"]
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

        if new_count > old_count:
            markets[index] = new_market
            return (
                True,
                f"improved {old_count} -> {new_count}",
            )

        return (
            False,
            f"existing is equal/better "
            f"({old_count} >= {new_count})",
        )

    markets.append(new_market)
    return (
        True,
        f"added {new_count}",
    )


def wait_for_component_rows(
    page,
    scraper,
    title,
    minimum_rows=1,
    timeout_seconds=10,
):
    deadline = (
        time.perf_counter()
        + timeout_seconds
    )
    best = None
    best_count = 0

    while time.perf_counter() < deadline:
        scraper.expand_market_component(
            page,
            title,
            show_all=True,
        )
        data = scraper.extract_market_component(
            page,
            title,
        )
        count = len(
            scraper.structured_rows(data)
        )

        if count > best_count:
            best = data
            best_count = count

        if count >= minimum_rows:
            # Require one stable recheck so React has finished appending rows.
            page.wait_for_timeout(700)
            stable = (
                scraper.extract_market_component(
                    page,
                    title,
                )
            )
            stable_count = len(
                scraper.structured_rows(
                    stable
                )
            )

            if stable_count >= count:
                return stable

        page.wait_for_timeout(400)

    return best


def repair_goals_page(
    page,
    scraper,
    match,
):
    home = match.get("home_team", "")
    away = match.get("away_team", "")
    base = (
        match.get("url", "")
        .replace("/main-markets", "")
        .rstrip("/")
    )

    page.goto(
        f"{base}/goals",
        wait_until="domcontentloaded",
        timeout=40000,
    )
    scraper.wait_for_any_text(
        page,
        ["Over/Under Total Goals"],
        timeout=12000,
    )
    page.wait_for_timeout(1800)
    scraper.scroll_page(page, 8)

    title = "Over/Under Total Goals"
    titles = scraper.list_market_titles(page)

    print(
        "    goals page titles: "
        + (
            " | ".join(titles)
            if titles
            else "none"
        )
    )

    if title not in titles:
        return {
            "total": None,
            "first_half": None,
            "home": None,
            "away": None,
        }

    scraper.expand_market_component(
        page,
        title,
        show_all=True,
    )

    clicked_90 = (
        scraper.click_market_switcher(
            page,
            title,
            "90 Mins",
        )
    )
    page.wait_for_timeout(900)

    total_data = wait_for_component_rows(
        page,
        scraper,
        title,
        minimum_rows=3,
        timeout_seconds=10,
    )
    total_market = scraper.parse_ou_component(
        total_data,
        "Total Goals Over / Under",
        max_line=6.5,
    )

    clicked_half = (
        scraper.click_market_switcher(
            page,
            title,
            "1st Half",
        )
    )
    page.wait_for_timeout(900)

    half_data = wait_for_component_rows(
        page,
        scraper,
        title,
        minimum_rows=2,
        timeout_seconds=10,
    )
    half_market = scraper.parse_ou_component(
        half_data,
        "1st Half Goals Over / Under",
        max_line=3.5,
    )

    team_markets = {}

    for team in (home, away):
        team_title = (
            f"Over/Under Goals {team}"
        )
        scraper.expand_market_component(
            page,
            team_title,
            show_all=True,
        )
        team_data = wait_for_component_rows(
            page,
            scraper,
            team_title,
            minimum_rows=2,
            timeout_seconds=6,
        )
        team_markets[team] = (
            scraper.parse_ou_component(
                team_data,
                f"{team} Goals Over / Under",
                selection_prefix=team,
                max_line=5.5,
            )
        )

    print(
        f"    goals repair: "
        f"90_clicked={clicked_90} | "
        f"total={total_market['selection_count']} | "
        f"half_clicked={clicked_half} | "
        f"first_half="
        f"{half_market['selection_count']}"
    )

    return {
        "total": total_market,
        "first_half": half_market,
        "home": team_markets.get(home),
        "away": team_markets.get(away),
    }


def capture_goalscorer_once(
    page,
    scraper,
    match,
):
    home = match.get("home_team", "")
    away = match.get("away_team", "")
    base = (
        match.get("url", "")
        .replace("/main-markets", "")
        .rstrip("/")
    )

    page.goto(
        f"{base}/goalscorer",
        wait_until="domcontentloaded",
        timeout=40000,
    )
    scraper.wait_for_any_text(
        page,
        [
            "Popular Goalscorer Markets",
            "Goalscorer",
            "Player To Score",
        ],
        timeout=12000,
    )
    page.wait_for_timeout(1800)
    scraper.scroll_page(page, 8)

    titles = scraper.list_market_titles(page)
    title = next(
        (
            candidate
            for candidate in titles
            if candidate.lower()
            in {
                "popular goalscorer markets",
                "goalscorer",
                "goalscorers",
                "player to score",
            }
        ),
        "",
    )

    print(
        "    goalscorer title: "
        f"{title or 'not found'}"
    )

    combined = scraper.mkt(
        "Player to Score",
        [],
    )

    if not title:
        return combined

    for team in (home, away):
        scraper.expand_market_component(
            page,
            title,
            show_all=False,
        )
        clicked = (
            scraper.click_market_switcher(
                page,
                title,
                team,
            )
        )
        page.wait_for_timeout(900)

        data = wait_for_component_rows(
            page,
            scraper,
            title,
            minimum_rows=15,
            timeout_seconds=12,
        )
        team_market = (
            scraper.parse_goalscorer_component(
                data
            )
        )
        scraper.merge_market_selections(
            combined,
            team_market,
        )

        print(
            f"    goalscorer/{team}: "
            f"clicked={clicked} | "
            f"rows="
            f"{len(scraper.structured_rows(data))} | "
            f"captured="
            f"{team_market['selection_count']}"
        )

    return combined


def repair_goalscorer_page(
    page,
    scraper,
    match,
):
    best = capture_goalscorer_once(
        page,
        scraper,
        match,
    )

    if (
        best["selection_count"]
        >= MIN_GOALSCORER_SELECTIONS
    ):
        return best

    print(
        "    goalscorer below quality target; "
        "retrying page once"
    )
    page.wait_for_timeout(1200)

    retry = capture_goalscorer_once(
        page,
        scraper,
        match,
    )

    if (
        retry["selection_count"]
        > best["selection_count"]
    ):
        return retry

    return best


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
            f"before_goals_repair_{timestamp}.json"
        )
    )
    shutil.copy2(
        PRODUCTION_PATH,
        backup_path,
    )

    print("=" * 68)
    print(
        "Ladbrokes Goals + Goalscorer "
        "REPAIR PROD15"
    )
    print("=" * 68)
    print(
        f"Loaded {len(matches)} production "
        "matches"
    )
    print(f"Backup: {backup_path}")
    print(
        "Quality floors: "
        f"Total Goals={MIN_TOTAL_GOALS_SELECTIONS}, "
        f"1st Half={MIN_FIRST_HALF_GOALS_SELECTIONS}, "
        f"Team Goals={MIN_TEAM_GOALS_SELECTIONS}, "
        f"Player to Score={MIN_GOALSCORER_SELECTIONS}"
    )

    processed = 0
    skipped_live = 0
    skipped_complete = 0
    changed_matches = 0
    quality_rejections = 0

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
            if processed >= MAX_MATCHES:
                break

            name = match.get(
                "match",
                "Unknown fixture",
            )
            url = match.get(
                "url",
                "",
            )

            if not url:
                print(
                    f"\n[{candidate_index}] {name}"
                )
                print(
                    "    SKIP: no fixture URL"
                )
                continue

            old_counts = {
                market.get(
                    "normalized_market"
                ): len(
                    market.get(
                        "selections",
                        [],
                    )
                )
                for market in match.get(
                    "markets",
                    [],
                )
            }

            total_ok = (
                old_counts.get(
                    "total_goals_over_under",
                    0,
                )
                >= MIN_TOTAL_GOALS_SELECTIONS
            )
            half_ok = (
                old_counts.get(
                    "1st_half_goals_over_under",
                    0,
                )
                >= MIN_FIRST_HALF_GOALS_SELECTIONS
            )
            scorer_ok = (
                old_counts.get(
                    "player_to_score",
                    0,
                )
                >= MIN_GOALSCORER_SELECTIONS
            )

            if total_ok and half_ok and scorer_ok:
                skipped_complete += 1
                print(
                    f"\n[{candidate_index}] {name}"
                )
                print(
                    "    SKIP: goals and "
                    "goalscorers already complete"
                )
                continue

            # Verify it is still a usable prematch event.
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=40000,
            )
            page.wait_for_timeout(3000)
            scraper.accept_cookies(page)

            if scraper.event_is_live(page):
                skipped_live += 1
                print(
                    f"\n[{candidate_index}] {name}"
                )
                print(
                    "    SKIP: live/started"
                )
                continue

            processed += 1
            print(
                f"\n[{processed}/{MAX_MATCHES}] "
                f"{name}"
            )

            goal_results = repair_goals_page(
                page,
                scraper,
                match,
            )
            scorer_market = (
                repair_goalscorer_page(
                    page,
                    scraper,
                    match,
                )
            )

            candidates = [
                (
                    goal_results.get("total"),
                    MIN_TOTAL_GOALS_SELECTIONS,
                ),
                (
                    goal_results.get(
                        "first_half"
                    ),
                    MIN_FIRST_HALF_GOALS_SELECTIONS,
                ),
                (
                    goal_results.get("home"),
                    MIN_TEAM_GOALS_SELECTIONS,
                ),
                (
                    goal_results.get("away"),
                    MIN_TEAM_GOALS_SELECTIONS,
                ),
                (
                    scorer_market,
                    MIN_GOALSCORER_SELECTIONS,
                ),
            ]

            changed = []
            rejected = []

            for market, minimum in candidates:
                if not market:
                    continue

                accepted, reason = (
                    replace_if_quality(
                        match,
                        market,
                        minimum,
                    )
                )

                if accepted:
                    changed.append(
                        f"{market['market']} "
                        f"({reason})"
                    )
                else:
                    rejected.append(
                        f"{market['market']}: "
                        f"{reason}"
                    )
                    if (
                        "below quality floor"
                        in reason
                    ):
                        quality_rejections += 1

            match["market_count"] = len(
                match.get("markets", [])
            )

            new_counts = {
                market.get(
                    "normalized_market"
                ): len(
                    market.get(
                        "selections",
                        [],
                    )
                )
                for market in match.get(
                    "markets",
                    [],
                )
            }

            if changed:
                changed_matches += 1

            print(
                "    accepted: "
                + (
                    " | ".join(changed)
                    if changed
                    else "none"
                )
            )

            if rejected:
                print(
                    "    retained/rejected: "
                    + " | ".join(rejected)
                )

            print(
                "    Total Goals: "
                f"{old_counts.get('total_goals_over_under', 0)}"
                " -> "
                f"{new_counts.get('total_goals_over_under', 0)}"
            )
            print(
                "    1st Half Goals: "
                f"{old_counts.get('1st_half_goals_over_under', 0)}"
                " -> "
                f"{new_counts.get('1st_half_goals_over_under', 0)}"
            )
            print(
                "    Player to Score: "
                f"{old_counts.get('player_to_score', 0)}"
                " -> "
                f"{new_counts.get('player_to_score', 0)}"
            )

        browser.close()

    production_data["generated_at"] = datetime.now(
        timezone.utc
    ).isoformat()
    production_data["ladbrokes_goals_repair"] = {
        "type": (
            "ladbrokes_goals_goalscorer_prod15"
        ),
        "completed_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "matches_processed": processed,
        "matches_changed": changed_matches,
        "skipped_live": skipped_live,
        "skipped_already_complete":
            skipped_complete,
        "quality_rejections":
            quality_rejections,
        "quality_floors": {
            "total_goals":
                MIN_TOTAL_GOALS_SELECTIONS,
            "first_half_goals":
                MIN_FIRST_HALF_GOALS_SELECTIONS,
            "team_goals":
                MIN_TEAM_GOALS_SELECTIONS,
            "player_to_score":
                MIN_GOALSCORER_SELECTIONS,
        },
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

    # Validate the complete temp JSON before replacing production.
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
            "Temporary repaired JSON failed "
            "validation: matches is not a list"
        )

    if len(
        validated["matches"]
    ) != len(matches):
        raise RuntimeError(
            "Temporary repaired JSON failed "
            "validation: match count changed"
        )

    os.replace(
        TEMP_OUT_PATH,
        PRODUCTION_PATH,
    )

    print("")
    print("=" * 68)
    print(
        f"Processed: {processed}"
    )
    print(
        f"Changed matches: {changed_matches}"
    )
    print(
        f"Skipped live: {skipped_live}"
    )
    print(
        "Skipped already complete: "
        f"{skipped_complete}"
    )
    print(
        "Quality-gate rejections: "
        f"{quality_rejections}"
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
