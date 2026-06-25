#!/usr/bin/env python3
"""
collect_ladbrokes_complete_props_diagnostic.py

Collects one Ladbrokes fixture's exact text, HTML and screenshots for every
market area needed to finish the complete props scraper.

Production JSON files are never read or modified.

Output:
  football/debug/ladbrokes_complete_props_diagnostic.zip
"""

import json
import re
import shutil
import time
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
COMPETITION_URL = (
    "https://www.ladbrokes.com/en/sports/competitions/"
    "football/international/world-cup-2026"
)

WORK_DIR = (
    ROOT
    / "football"
    / "debug"
    / "ladbrokes_complete_props_diagnostic"
)
ZIP_PATH = (
    ROOT
    / "football"
    / "debug"
    / "ladbrokes_complete_props_diagnostic.zip"
)

HEADLESS = False
MAX_FIXTURES = 1


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value):
    value = clean(value).lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def accept_cookies(page):
    labels = [
        "Accept All",
        "Accept all",
        "I Accept",
        "Accept",
        "Agree",
        "Allow all",
        "Got it",
    ]

    for label in labels:
        try:
            button = page.get_by_role(
                "button",
                name=re.compile(
                    rf"^{re.escape(label)}$",
                    re.I,
                ),
            )

            if button.count():
                button.first.click(timeout=2500)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass


def scroll_page(page, steps=8):
    for _ in range(steps):
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(180)


def safe_body_text(page):
    try:
        return page.locator("body").inner_text(
            timeout=15000
        )
    except Exception:
        return ""


def safe_body_html(page):
    try:
        return page.locator("body").inner_html(
            timeout=15000
        )
    except Exception:
        return ""


def save_snapshot(
    page,
    folder,
    label,
    extra=None,
):
    folder.mkdir(parents=True, exist_ok=True)
    stem = slugify(label)

    (folder / f"{stem}.txt").write_text(
        safe_body_text(page),
        encoding="utf-8",
    )
    (folder / f"{stem}.html").write_text(
        safe_body_html(page),
        encoding="utf-8",
    )

    if extra is not None:
        (folder / f"{stem}.json").write_text(
            json.dumps(
                extra,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    try:
        page.screenshot(
            path=str(folder / f"{stem}.png"),
            full_page=True,
        )
    except Exception:
        pass


def click_exact(page, label, root_selector=""):
    """
    Click the smallest visible element whose text exactly matches label.
    Optionally restrict the search to a CSS root selector.
    """
    try:
        return bool(
            page.evaluate(
                r"""
                ({label, rootSelector}) => {
                    const clean = value =>
                        (value || "")
                            .replace(/\s+/g, " ")
                            .trim();

                    const visible = element => {
                        const rect =
                            element.getBoundingClientRect();
                        const style =
                            getComputedStyle(element);

                        return (
                            rect.width > 0
                            && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                        );
                    };

                    const root = rootSelector
                        ? document.querySelector(rootSelector)
                        : document;

                    if (!root) {
                        return false;
                    }

                    const candidates = Array.from(
                        root.querySelectorAll(
                            "button, a, [role='button'], "
                            + "[role='tab'], h1, h2, h3, h4, "
                            + "span, div, p"
                        )
                    ).filter(
                        element =>
                            visible(element)
                            && clean(element.innerText)
                                === label
                    );

                    candidates.sort(
                        (a, b) => {
                            const ar =
                                a.getBoundingClientRect();
                            const br =
                                b.getBoundingClientRect();

                            return (
                                ar.width * ar.height
                                - br.width * br.height
                            );
                        }
                    );

                    const target = candidates[0];

                    if (!target) {
                        return false;
                    }

                    target.scrollIntoView({
                        block: "center",
                        inline: "center",
                        behavior: "instant",
                    });
                    target.click();
                    return true;
                }
                """,
                {
                    "label": label,
                    "rootSelector": root_selector,
                },
            )
        )
    except Exception:
        return False


def click_all_show_all(page, root_selector=""):
    clicked = 0

    for _ in range(8):
        if not click_exact(
            page,
            "Show All",
            root_selector,
        ):
            break

        clicked += 1
        page.wait_for_timeout(600)

    return clicked


def mark_card(
    page,
    headings,
    marker,
    required_labels=None,
):
    """
    Mark the smallest visible ancestor containing the requested heading and
    optional labels. The marker is then used for card-only snapshots/clicks.
    """
    if isinstance(headings, str):
        headings = [headings]

    required_labels = required_labels or []

    try:
        return bool(
            page.evaluate(
                r"""
                ({headings, marker, requiredLabels}) => {
                    const clean = value =>
                        (value || "")
                            .replace(/\s+/g, " ")
                            .trim();

                    const visible = element => {
                        const rect =
                            element.getBoundingClientRect();
                        const style =
                            getComputedStyle(element);

                        return (
                            rect.width > 0
                            && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                        );
                    };

                    document.querySelectorAll(
                        `[data-lad-diagnostic="${marker}"]`
                    ).forEach(
                        element =>
                            element.removeAttribute(
                                "data-lad-diagnostic"
                            )
                    );

                    const candidates = [];

                    for (const heading of headings) {
                        const exactNodes = Array.from(
                            document.querySelectorAll(
                                "h1, h2, h3, h4, h5, button, "
                                + "[role='button'], span, div, p"
                            )
                        ).filter(
                            element =>
                                visible(element)
                                && clean(element.innerText)
                                    === heading
                        );

                        for (const exactNode of exactNodes) {
                            let node = exactNode;

                            for (
                                let depth = 0;
                                node && depth < 12;
                                depth += 1,
                                node = node.parentElement
                            ) {
                                const rect =
                                    node.getBoundingClientRect();
                                const text =
                                    clean(node.innerText);

                                if (
                                    rect.width < 250
                                    || rect.height < 40
                                    || rect.height > 2200
                                ) {
                                    continue;
                                }

                                if (
                                    !text.includes(heading)
                                    || !requiredLabels.every(
                                        label =>
                                            text.includes(label)
                                    )
                                ) {
                                    continue;
                                }

                                candidates.push({
                                    node,
                                    area:
                                        rect.width
                                        * rect.height,
                                });
                            }
                        }
                    }

                    candidates.sort(
                        (a, b) => a.area - b.area
                    );

                    const best = candidates[0];

                    if (!best) {
                        return false;
                    }

                    best.node.setAttribute(
                        "data-lad-diagnostic",
                        marker
                    );
                    return true;
                }
                """,
                {
                    "headings": headings,
                    "marker": marker,
                    "requiredLabels": required_labels,
                },
            )
        )
    except Exception:
        return False


def save_card_snapshot(
    page,
    folder,
    label,
    marker,
):
    folder.mkdir(parents=True, exist_ok=True)
    stem = slugify(label)
    selector = (
        f'[data-lad-diagnostic="{marker}"]'
    )

    try:
        locator = page.locator(selector)

        if not locator.count():
            (folder / f"{stem}_missing.txt").write_text(
                "CARD NOT FOUND",
                encoding="utf-8",
            )
            return

        (folder / f"{stem}.txt").write_text(
            locator.first.inner_text(
                timeout=8000
            ),
            encoding="utf-8",
        )
        (folder / f"{stem}.html").write_text(
            locator.first.evaluate(
                "element => element.outerHTML"
            ),
            encoding="utf-8",
        )

        try:
            locator.first.screenshot(
                path=str(folder / f"{stem}.png")
            )
        except Exception:
            pass
    except Exception as error:
        (folder / f"{stem}_error.txt").write_text(
            repr(error),
            encoding="utf-8",
        )


def get_match_links(page):
    page.goto(
        COMPETITION_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )
    page.wait_for_timeout(4500)
    accept_cookies(page)

    for _ in range(12):
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(220)

    links = page.evaluate(
        r"""
        () => [...new Set(
            Array.from(
                document.querySelectorAll(
                    'a[href*="/sports/event/football/'
                    + 'international/world-cup-2026/"]'
                )
            )
                .map(anchor => anchor.href)
                .filter(href => {
                    const path =
                        href.split(
                            "/world-cup-2026/"
                        )[1] || "";

                    return (
                        path.includes("-v-")
                        && !href.includes("outright")
                        && !href.includes(
                            "top-goalscorer"
                        )
                    );
                })
        )]
        """
    )

    fixtures = []
    seen = set()

    for url in links:
        base = url.split("?")[0]

        if not base.endswith("/main-markets"):
            base = (
                base.rstrip("/")
                + "/main-markets"
            )

        if base in seen:
            continue

        seen.add(base)

        slug = (
            base
            .split("/world-cup-2026/")[-1]
            .split("/")[0]
        )
        name = (
            slug.replace("-v-", " v ")
            .replace("-", " ")
            .title()
        )
        fixtures.append(
            {
                "url": base,
                "name": name,
                "slug": slug,
            }
        )

    return fixtures[:MAX_FIXTURES]


def fixture_teams(fixture):
    slug = fixture.get("slug", "")

    if "-v-" not in slug:
        return "", ""

    home_slug, away_slug = slug.split(
        "-v-",
        1,
    )

    return (
        home_slug.replace("-", " ").title(),
        away_slug.replace("-", " ").title(),
    )


def visit(page, url, wait_labels=None):
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )
    page.wait_for_timeout(1800)
    accept_cookies(page)

    if wait_labels:
        try:
            page.wait_for_function(
                r"""
                labels => {
                    const text =
                        document.body?.innerText || "";

                    return labels.some(
                        label => text.includes(label)
                    );
                }
                """,
                wait_labels,
                timeout=8000,
            )
        except Exception:
            pass


def collect_fixture(page, fixture):
    home, away = fixture_teams(fixture)
    base = fixture["url"].replace(
        "/main-markets",
        "",
    )
    folder = WORK_DIR / slugify(
        fixture["name"]
    )
    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    metadata = {
        "fixture": fixture,
        "home": home,
        "away": away,
        "collected_at_unix": time.time(),
    }
    (folder / "metadata.json").write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        f"Collecting {home} v {away}"
    )

    # Main markets.
    visit(
        page,
        fixture["url"],
        [
            "Match Betting",
            "Double Chance",
        ],
    )
    scroll_page(page, 8)
    save_snapshot(
        page,
        folder,
        "main_before_clicks",
    )

    for heading in (
        "Both Teams To Score",
        "Double Chance",
    ):
        clicked = click_exact(
            page,
            heading,
        )
        page.wait_for_timeout(900)
        save_snapshot(
            page,
            folder,
            f"main_after_{heading}",
            {
                "clicked": clicked,
            },
        )

    # Goals.
    visit(
        page,
        f"{base}/goals",
        ["Total Goals"],
    )
    scroll_page(page, 8)
    clicked_half = click_exact(
        page,
        "1st Half",
    )
    page.wait_for_timeout(700)
    show_all_goals = click_all_show_all(page)
    save_snapshot(
        page,
        folder,
        "goals",
        {
            "clicked_1st_half": clicked_half,
            "show_all_clicks": show_all_goals,
        },
    )

    # Goalscorer.
    visit(
        page,
        f"{base}/goalscorer",
        [
            "Goalscorer",
            "Player To Score",
        ],
    )
    scroll_page(page, 10)
    show_all_goalscorer = (
        click_all_show_all(page)
    )
    save_snapshot(
        page,
        folder,
        "goalscorer",
        {
            "show_all_clicks":
                show_all_goalscorer,
        },
    )

    # Half.
    visit(
        page,
        f"{base}/half",
        ["Both Teams To Score"],
    )
    scroll_page(page, 6)
    save_snapshot(
        page,
        folder,
        "half",
    )

    # Corners and cards.
    visit(
        page,
        f"{base}/corners-and-cards",
        [
            "Over/Under Total Corners",
            "Over/Under Total Cards",
        ],
    )
    scroll_page(page, 10)
    save_snapshot(
        page,
        folder,
        "corners_cards_initial",
    )

    for heading, marker in (
        (
            "Over/Under Total Corners",
            "corners",
        ),
        (
            "Over/Under Total Cards",
            "cards",
        ),
    ):
        marked = mark_card(
            page,
            heading,
            marker,
        )

        if marked:
            selector = (
                f'[data-lad-diagnostic="{marker}"]'
            )
            clicked = click_exact(
                page,
                heading,
                selector,
            )
            page.wait_for_timeout(800)
            mark_card(
                page,
                heading,
                marker,
            )
            save_card_snapshot(
                page,
                folder,
                f"{marker}_after_heading_click",
                marker,
            )

            if marker == "corners":
                for tab in (
                    "Match",
                    home,
                    away,
                ):
                    mark_card(
                        page,
                        heading,
                        marker,
                    )
                    clicked_tab = click_exact(
                        page,
                        tab,
                        selector,
                    )
                    page.wait_for_timeout(800)
                    mark_card(
                        page,
                        heading,
                        marker,
                    )
                    save_card_snapshot(
                        page,
                        folder,
                        f"corners_tab_{tab}",
                        marker,
                    )
                    (folder / (
                        f"corners_tab_"
                        f"{slugify(tab)}_click.json"
                    )).write_text(
                        json.dumps(
                            {
                                "clicked":
                                    clicked_tab,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
        else:
            (folder / (
                f"{marker}_card_not_found.txt"
            )).write_text(
                heading,
                encoding="utf-8",
            )

    save_snapshot(
        page,
        folder,
        "corners_cards_final",
    )

    # Player stats.
    visit(
        page,
        f"{base}/player-stats",
        [
            "Player Total Tackles",
            "Bet Builder Player Markets",
        ],
    )
    scroll_page(page, 8)
    save_snapshot(
        page,
        folder,
        "player_stats_initial",
    )

    player_marked = mark_card(
        page,
        "Bet Builder Player Markets",
        "player-markets",
        [
            "PLAYERS",
            "SoT",
            "Carded",
            "Fouls",
            "Shots",
            "Assists",
        ],
    )
    tackles_marked = mark_card(
        page,
        "Player Total Tackles",
        "tackles",
        [
            "PLAYERS",
            "1+",
            "2+",
            "3+",
            "4+",
        ],
    )

    print(
        "  player cards: "
        f"player={player_marked}, "
        f"tackles={tackles_marked}"
    )

    if player_marked:
        for tab in (
            "SoT",
            "Shots",
            "Carded",
            "Fouls",
            "Assists",
        ):
            mark_card(
                page,
                "Bet Builder Player Markets",
                "player-markets",
                [
                    "PLAYERS",
                    "SoT",
                    "Carded",
                    "Fouls",
                    "Shots",
                    "Assists",
                ],
            )
            selector = (
                '[data-lad-diagnostic='
                '"player-markets"]'
            )
            clicked_tab = click_exact(
                page,
                tab,
                selector,
            )
            page.wait_for_timeout(900)

            mark_card(
                page,
                "Bet Builder Player Markets",
                "player-markets",
                [
                    "PLAYERS",
                    "SoT",
                    "Carded",
                    "Fouls",
                    "Shots",
                    "Assists",
                ],
            )
            show_all_clicks = click_all_show_all(
                page,
                selector,
            )
            page.wait_for_timeout(600)

            mark_card(
                page,
                "Bet Builder Player Markets",
                "player-markets",
                [
                    "PLAYERS",
                    "SoT",
                    "Carded",
                    "Fouls",
                    "Shots",
                    "Assists",
                ],
            )
            save_card_snapshot(
                page,
                folder,
                f"player_{tab}",
                "player-markets",
            )
            (folder / (
                f"player_{slugify(tab)}_click.json"
            )).write_text(
                json.dumps(
                    {
                        "clicked_tab":
                            clicked_tab,
                        "show_all_clicks":
                            show_all_clicks,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    if tackles_marked:
        for team in (
            home,
            away,
        ):
            mark_card(
                page,
                "Player Total Tackles",
                "tackles",
                [
                    "PLAYERS",
                    "1+",
                    "2+",
                    "3+",
                    "4+",
                ],
            )
            selector = (
                '[data-lad-diagnostic="tackles"]'
            )
            clicked_team = click_exact(
                page,
                team,
                selector,
            )
            page.wait_for_timeout(900)

            mark_card(
                page,
                "Player Total Tackles",
                "tackles",
                [
                    "PLAYERS",
                    "1+",
                    "2+",
                    "3+",
                    "4+",
                ],
            )
            show_all_clicks = click_all_show_all(
                page,
                selector,
            )
            page.wait_for_timeout(600)

            mark_card(
                page,
                "Player Total Tackles",
                "tackles",
                [
                    "PLAYERS",
                    "1+",
                    "2+",
                    "3+",
                    "4+",
                ],
            )
            save_card_snapshot(
                page,
                folder,
                f"tackles_{team}",
                "tackles",
            )
            (folder / (
                f"tackles_{slugify(team)}_click.json"
            )).write_text(
                json.dumps(
                    {
                        "clicked_team":
                            clicked_team,
                        "show_all_clicks":
                            show_all_clicks,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    save_snapshot(
        page,
        folder,
        "player_stats_final",
    )


def create_zip():
    ZIP_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(
        ZIP_PATH,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in WORK_DIR.rglob("*"):
            if not path.is_file():
                continue

            archive.write(
                path,
                path.relative_to(
                    WORK_DIR.parent
                ),
            )


def main():
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)

    WORK_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    started = time.perf_counter()

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

        fixtures = get_match_links(page)
        print(
            f"Found {len(fixtures)} diagnostic fixture(s)"
        )

        if not fixtures:
            browser.close()
            raise RuntimeError(
                "No Ladbrokes World Cup fixtures found"
            )

        for fixture in fixtures:
            collect_fixture(
                page,
                fixture,
            )

        browser.close()

    create_zip()

    elapsed = time.perf_counter() - started

    print("")
    print("=" * 64)
    print("Ladbrokes complete-props diagnostic finished")
    print(f"Elapsed: {elapsed:.2f}s")
    print(f"ZIP: {ZIP_PATH}")
    print("Production JSON modified: NO")
    print("=" * 64)


if __name__ == "__main__":
    main()
