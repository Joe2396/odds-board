#!/usr/bin/env python3
# BETVICTOR_ALL_PROPS_FAST_TEST3_V1
"""
fetch_betvictor_worldcup_props_NEXT15.py

BetVictor combined props scraper — isolated three-match speed test.

What this does:
- Loads football/data/betvictor_worldcup_moneylines.json.
- Sorts fixtures by kickoff.
- Skips old/live-ish fixtures.
- Takes the NEXT 15 fixtures only.
- Opens each fixture from the BetVictor World Cup list with strict row matching.
- Verifies the event header contains the expected teams before scraping.
- Opens known BetVictor market_group URLs directly:
    popular/default
    goals       19293
    corners     19294
    cards       19295
    player      19296
    bet_builder 12536
- Parses:
    Match Betting
    Total Goals O/U
    BTTS
    Double Chance
    Half Time Result
    Total Corners O/U
    Total Cards O/U
    First/Anytime/Last Goalscorer
    First Player Card
    Player Cards
    Player Shots On Target
    Player Shots
    Player Assists
    Player Tackles
    Player Fouls
    To Have The Most Match Stats

Outputs:
  football/data/betvictor_worldcup_all_fast_test.json
  football/data/betvictor_worldcup_all_fast_audit.json

This test never writes betvictor_worldcup_props.json or any specialist
production BetVictor JSON.

Debug:
  football/debug/betvictor_worldcup_props/<match>/ALL_GROUPS.txt
  football/debug/betvictor_worldcup_props/<match>/HITS.txt
"""

import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

MONEYLINES_PATH = ROOT / "football" / "data" / "betvictor_worldcup_moneylines.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_worldcup_all_fast_test.json"
AUDIT_PATH = ROOT / "football" / "data" / "betvictor_worldcup_all_fast_audit.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_worldcup_all_fast_test"

LIST_URL = "https://www.betvictor.com/en-ie/sports/240/sections/custom-list/7199/group/world-cup-matches/item/matches"

MAX_MATCHES = 3
HEADLESS = False

# This core scraper deliberately excludes Bet Builder. Match/team statistics
# are collected by fetch_betvictor_betbuilder_match_stats.py and merged later.
GROUPS = {
    "popular": None,
    "goals": "19293",
    "corners": "19294",
    "cards": "19295",
    "player": "19296",
    "bet_builder": "12536",
}

# Only open accordions needed by this core pass. Shots, SOT, fouls and tackles
# have dedicated exact scrapers later in the BetVictor pipeline.
FAST_EXPANDS_BY_GROUP = {
    "popular": [
        "Match Betting",
        "Match Result",
        "Both Teams To Score",
        "Double Chance",
        "Double Chance Betting",
        "Double Chance (1X2)",
    ],
    "goals": [
        "Goalscorers",
    ],
    "corners": [],
    "cards": [
        "Player Cards",
        "Player To Be Carded",
        "Player to Be Carded",
    ],
    "player": [
        "Goalscorers",
        "Player Assists",
        "Player To Assist",
        "Player to Assist",
        "To Assist",
        "Player Shots on Target",
        "Player Shots On Target",
        "Player Shots",
        "Player Fouls",
        "Player Fouls Committed",
        "Player Tackles",
    ],
    "bet_builder": [],
}

EXPAND_TITLES = [
    # player group
    "Goalscorers",
    "Player to Score",
    "Player Shots on Target",
    "Player Shots",
    "Player Assists",
    "Player Tackles",
    "Player Fouls",
    "Player Cards",
    "Multi Scorers",
    # cards/corners/goals/match stats
    "Total Corners Over/Under",
    "Total Cards Over/Under",
    "Total Goals Over/Under",
    "Match Shots on Target",
    "Match Shots",
    "Match Tackles",
    "Match Offsides",
    "To Have the Most",
    # popular page
    "Both Teams To Score",
    "Match Betting",
    "Double Chance",
]

BET_BUILDER_SUBTABS = [
    "Match Stats",
    "Player Stats",
    "Popular",
    "Result",
    "Goals",
    "Corners",
    "Cards",
    "Odd/Even",
]

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)

THRESH_RE = re.compile(r"^\d\+$")

EXACT_PLAYER_MARKETS = {
    "player_shots_on_target": {
        "market": "Player Shots On Target",
        "headings": [
            "Player Shots on Target",
            "Player Shots On Target",
        ],
        "row_pattern": (
            r"^(.+?)\s+(\d+)\+\s+"
            r"Shots?\s+On\s+Target(?:\s+90\s*Mins)?$"
        ),
        "prop_type": "shots_on_target",
    },
    "player_shots": {
        "market": "Player Shots",
        "headings": ["Player Shots"],
        "row_pattern": (
            r"^(.+?)\s+(\d+)\+\s+Shots?"
            r"(?:\s+90\s*Mins)?$"
        ),
        "prop_type": "shots",
    },
    "player_fouls_committed": {
        "market": "Player Fouls Committed",
        "headings": [
            "Player Fouls",
            "Player Fouls Committed",
        ],
        "row_pattern": (
            r"^(.+?)\s+(\d+)\+\s+Fouls?"
            r"(?:\s+Committed)?(?:\s+90\s*Mins)?$"
        ),
        "prop_type": "fouls_committed",
    },
    "player_tackles": {
        "market": "Player Tackles",
        "headings": ["Player Tackles"],
        "row_pattern": (
            r"^(.+?)\s+(\d+)\+\s+Tackles?"
            r"(?:\s+90\s*Mins)?$"
        ),
        "prop_type": "tackles",
    },
}

CORE_REQUIREMENTS = {
    "match_betting": 3,
    "total_goals_over_under": 2,
    "both_teams_to_score": 2,
    "double_chance": 3,
    "total_corners_over_under": 2,
    "total_cards_over_under": 2,
    "anytime_goalscorer": 1,
    "player_cards": 1,
}

PLAYER_REQUIREMENTS = {
    "player_assists": 1,
    "player_shots_on_target": 1,
    "player_shots": 1,
    "player_fouls_committed": 1,
    "player_tackles": 1,
}

TEAM_ALIASES = {
    "United States": "USA",
    "USA": "USA",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Türkiye": "Türkiye",
    "Czech Republic": "Czechia",
    "Czechia": "Czechia",
    "Bosnia and Herzegovina": "Bosnia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia": "Bosnia",
    "Curaçao": "Curacao",
    "Curacao": "Curacao",
}

TEAM_ALT = {
    "USA": ["USA", "United States"],
    "Türkiye": ["Türkiye", "Turkey", "Turkiye"],
    "Czechia": ["Czechia", "Czech Republic"],
    "Bosnia": ["Bosnia", "Bosnia and Herzegovina", "Bosnia & Herzegovina"],
    "Curacao": ["Curacao", "Curaçao"],
}

WORLD_CUP_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic", "Czechia",
    "Canada", "Bosnia and Herzegovina", "Bosnia & Herzegovina", "Bosnia",
    "USA", "United States", "Paraguay", "Qatar", "Switzerland", "Brazil", "Morocco",
    "Haiti", "Scotland", "Australia", "Turkey", "Turkiye", "Türkiye", "Germany",
    "Curacao", "Curaçao", "Netherlands", "Japan", "Ivory Coast", "Ecuador", "Sweden",
    "Tunisia", "Spain", "Cape Verde", "Belgium", "Egypt", "Saudi Arabia", "Uruguay",
    "Iran", "New Zealand", "France", "Senegal", "Iraq", "Norway", "Argentina",
    "Algeria", "Austria", "Jordan", "Portugal", "DR Congo", "England", "Croatia",
    "Ghana", "Panama", "Colombia", "Uzbekistan",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    s = clean(s)
    return TEAM_ALIASES.get(s, s)


def team_alts(s):
    c = canonical_team(s)
    return TEAM_ALT.get(c, [c])


def norm(s):
    s = canonical_team(s).lower().replace("&", "and").replace("türkiye", "turkiye")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_threshold(s):
    return bool(THRESH_RE.match(clean(s)))


def lines_from_text(text):
    return [clean(x) for x in text.splitlines() if clean(x)]


def sel(selection, odds, **extra):
    out = {
        "selection": clean(selection),
        "normalized_selection": normalize(selection),
        "odds": clean(odds).upper(),
    }
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def market(name, selections):
    seen, out = set(), []
    for s in selections:
        key = (
            s.get("selection"),
            s.get("odds"),
            s.get("player"),
            s.get("threshold"),
            s.get("side"),
            s.get("line"),
            s.get("stat"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(out),
        "selections": out,
    }


def parse_kickoff(date_label, time_label):
    raw = f"{clean(date_label)} {clean(time_label)}"
    for fmt in ("%a %d %B %Y %H:%M", "%A %d %B %Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            pass
    return None


def load_next_15_fixtures():
    data = json.loads(MONEYLINES_PATH.read_text(encoding="utf-8"))
    rows = data.get("matches") or []

    fixtures = []
    seen = set()

    for m in rows:
        home = canonical_team(m.get("home_team") or "")
        away = canonical_team(m.get("away_team") or "")
        date_label = clean(m.get("date_label") or "")
        time_label = clean(m.get("time") or "")
        if not home or not away or not date_label or not time_label:
            continue

        kickoff = parse_kickoff(date_label, time_label)
        if not kickoff:
            continue

        key = (kickoff.isoformat(), norm(home), norm(away))
        if key in seen:
            continue
        seen.add(key)

        fixtures.append({
            "match": f"{home} v {away}",
            "home": home,
            "away": away,
            "date": date_label,
            "time": time_label,
            "kickoff": kickoff,
            "source_url": clean(
                m.get("source_url")
                or m.get("url")
                or ""
            ),
        })

    fixtures.sort(key=lambda x: x["kickoff"])

    # Skip games that are clearly old. Keep a small grace window because the PC clock/page times
    # can be a little off and upcoming pages may be tested close to kickoff.
    now = datetime.now()
    upcoming = [f for f in fixtures if f["kickoff"] >= now - timedelta(hours=2)]

    if len(upcoming) < MAX_MATCHES:
        # fallback if PC date is off
        upcoming = fixtures

    return upcoming[:MAX_MATCHES]


def block_heavy_resources(route):
    """Keep JS/XHR/HTML but skip assets that do not affect market parsing."""
    if route.request.resource_type in {"image", "media", "font"}:
        route.abort()
    else:
        route.continue_()


def new_fast_page(browser):
    page = browser.new_page(
        viewport={"width": 1700, "height": 1000}
    )
    try:
        page.route("**/*", block_heavy_resources)
    except Exception:
        pass
    return page


def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "OK", "I have read the above"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def scroll_all(page, passes=4):
    for _ in range(passes):
        try:
            page.evaluate(
                """() => {
                    window.scrollBy(0, 850);
                    const els = Array.from(document.querySelectorAll('body *'));
                    for (const el of els) {
                        const st = getComputedStyle(el);
                        if (el.scrollHeight > el.clientHeight + 80 && ['auto','scroll','overlay'].includes(st.overflowY)) {
                            el.scrollTop = Math.min(el.scrollTop + 850, el.scrollHeight);
                        }
                    }
                }"""
            )
        except Exception:
            page.mouse.wheel(0, 850)
        page.wait_for_timeout(250)


def click_show_more(page):
    for label in ["Show More", "Show more", "View More", "View more", "Show All", "Show all"]:
        try:
            loc = page.get_by_text(label, exact=True)
            for i in range(min(loc.count(), 10)):
                try:
                    loc.nth(i).scroll_into_view_if_needed(timeout=1000)
                    loc.nth(i).click(timeout=1000)
                    page.wait_for_timeout(350)
                except Exception:
                    pass
        except Exception:
            pass


def click_exact_text(page, label):
    try:
        loc = page.get_by_text(label, exact=True)
        if loc.count():
            loc.first.scroll_into_view_if_needed(timeout=1500)
            page.wait_for_timeout(150)
            loc.first.click(timeout=1500)
            page.wait_for_timeout(900)
            return True
    except Exception:
        pass

    try:
        return bool(page.evaluate(
            r"""(label) => {
                const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                const nodes = Array.from(document.querySelectorAll('button, [role=button], a, div, span'))
                  .filter(el => clean(el.innerText || el.textContent || '') === label);
                for (const node of nodes) {
                    let el = node;
                    for (let i=0; i<5 && el; i++, el=el.parentElement) {
                        const txt = clean(el.innerText || el.textContent || '');
                        if (txt.length > 140) continue;
                        el.scrollIntoView({block:'center'});
                        el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                        el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                        el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                        el.click();
                        return true;
                    }
                }
                return false;
            }""",
            label,
        ))
    except Exception:
        return False


def click_betbuilder_subtab(page, label):
    """Click Bet Builder second-row sub-tabs such as Match Stats / Player Stats.

    This is stricter than click_exact_text because the main page can contain repeated labels.
    It prefers short clickable nodes near the Build Your Own Bet area.
    """
    try:
        return bool(page.evaluate(
            r"""(label) => {
                const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                const nodes = Array.from(document.querySelectorAll('button, [role=button], a, div, span'))
                    .filter(el => clean(el.innerText || el.textContent || '') === label);

                // Prefer visible, short nodes.
                const visible = nodes.filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 10 && r.height > 10 && r.y > 0 && r.y < window.innerHeight + 400;
                });

                const ordered = (visible.length ? visible : nodes).sort((a, b) => {
                    const ar = a.getBoundingClientRect();
                    const br = b.getBoundingClientRect();
                    return Math.abs(ar.y - 430) - Math.abs(br.y - 430);
                });

                for (const node of ordered) {
                    let el = node;
                    for (let i = 0; i < 5 && el; i++, el = el.parentElement) {
                        const txt = clean(el.innerText || el.textContent || '');
                        if (!txt || txt.length > 100) continue;
                        el.scrollIntoView({block:'center'});
                        el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                        el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                        el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                        el.click();
                        return true;
                    }
                }
                return false;
            }""",
            label,
        ))
    except Exception:
        return False


def expand_market_accordion(page, label):
    """Expand a specific market accordion by exact heading text.

    Works for BetVictor rows like:
      Match Shots on Target
      France Shots
      Senegal Tackles
    """
    try:
        return bool(page.evaluate(
            r"""(label) => {
                const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                const nodes = Array.from(document.querySelectorAll('body *'))
                    .filter(el => clean(el.innerText || el.textContent || '') === label);

                for (const node of nodes) {
                    let el = node;
                    for (let depth = 0; depth < 7 && el; depth++, el = el.parentElement) {
                        const txt = clean(el.innerText || el.textContent || '');
                        if (!txt || txt.length > 180) continue;

                        // Prefer row/header containers, but click whichever small ancestor is clickable.
                        el.scrollIntoView({block:'center'});
                        el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                        el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                        el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                        el.click();
                        return true;
                    }
                }
                return false;
            }""",
            label,
        ))
    except Exception:
        return False


def open_date_header(page, date_label):
    if not date_label:
        return False

    try:
        loc = page.get_by_text(date_label, exact=True)
        if loc.count():
            loc.first.scroll_into_view_if_needed(timeout=2500)
            page.wait_for_timeout(200)
            loc.first.click(timeout=2500)
            page.wait_for_timeout(900)
            return True
    except Exception:
        pass

    try:
        return bool(page.evaluate(
            r"""(dateLabel) => {
                const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                const nodes = Array.from(document.querySelectorAll('body *'))
                  .filter(el => clean(el.innerText || el.textContent || '') === dateLabel);
                for (const node of nodes) {
                    let el = node;
                    for (let i=0; i<6 && el; i++, el=el.parentElement) {
                        const txt = clean(el.innerText || el.textContent || '');
                        if (txt.length > 220) continue;
                        el.scrollIntoView({block:'center'});
                        el.click();
                        return true;
                    }
                }
                return false;
            }""",
            date_label,
        ))
    except Exception:
        return False


def body_has_fixture(page, fixture):
    try:
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        return False
    lo = body.lower()
    return any(x.lower() in lo for x in team_alts(fixture["home"])) and any(x.lower() in lo for x in team_alts(fixture["away"]))


def click_fixture_more_strict(page, fixture):
    """Click More from the smallest exact fixture row only."""
    home_names = team_alts(fixture["home"])
    away_names = team_alts(fixture["away"])
    return bool(page.evaluate(
        r"""({homeNames, awayNames, timeLabel, allTeams}) => {
            const clean = s => (s || '').replace(/\s+/g, ' ').trim();
            const hasAny = (txt, arr) => arr.some(x => txt.toLowerCase().includes(String(x).toLowerCase()));
            const time = String(timeLabel).toLowerCase();

            function teamCount(txt) {
                const low = txt.toLowerCase();
                let c = 0;
                for (const t of allTeams) {
                    if (low.includes(String(t).toLowerCase())) c++;
                }
                return c;
            }

            const all = Array.from(document.querySelectorAll('body *'));
            let candidates = [];

            // Start from exact home text nodes/elements to avoid broad date containers.
            for (const el of all) {
                const own = clean(el.innerText || el.textContent || '');
                if (!own) continue;
                const low = own.toLowerCase();

                const maybeHomeNode = homeNames.some(h => low === String(h).toLowerCase() || low.includes(String(h).toLowerCase()));
                if (!maybeHomeNode) continue;

                let p = el;
                for (let depth = 0; depth < 8 && p; depth++, p = p.parentElement) {
                    const txt = clean(p.innerText || p.textContent || '');
                    if (!txt || txt.length > 650) continue;
                    const lower = txt.toLowerCase();

                    if (!hasAny(txt, homeNames) || !hasAny(txt, awayNames) || !lower.includes(time)) continue;
                    if (!/\bmore\b/i.test(txt)) continue;

                    const tc = teamCount(txt);
                    // Exact fixture row usually has 2 teams. Allow 3 because aliases/labels can duplicate.
                    if (tc > 4) continue;

                    candidates.push({el: p, txt, len: txt.length, teamCount: tc});
                }
            }

            candidates.sort((a,b) => {
                if (a.teamCount !== b.teamCount) return a.teamCount - b.teamCount;
                return a.len - b.len;
            });

            for (const c of candidates.slice(0, 8)) {
                const root = c.el;
                const descendants = Array.from(root.querySelectorAll('a, button, [role=button], span, div'));
                let more = descendants.find(d => /^more\s*>?$/i.test(clean(d.innerText || d.textContent || '')))
                        || descendants.find(d => /\bmore\b/i.test(clean(d.innerText || d.textContent || '')));
                if (!more) continue;

                more.scrollIntoView({block:'center'});
                more.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                more.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                more.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                more.click();
                return true;
            }

            return false;
        }""",
        {
            "homeNames": home_names,
            "awayNames": away_names,
            "timeLabel": fixture["time"],
            "allTeams": list(WORLD_CUP_TEAMS),
        },
    ))


def verify_event(page, fixture):
    """Confirm both expected teams without stacked fixed waits."""
    if "/events/" not in page.url:
        return False

    home_names = [name.lower() for name in team_alts(fixture["home"])]
    away_names = [name.lower() for name in team_alts(fixture["away"])]

    deadline = time.perf_counter() + 7.0

    while time.perf_counter() < deadline:
        title = ""
        body = ""

        try:
            title = clean(page.title()).lower()
        except Exception:
            pass

        try:
            body = clean(
                page.locator("body").inner_text(timeout=2500)
            ).lower()
        except Exception:
            pass

        combined = f"{title} {body}"

        if (
            any(name in combined for name in home_names)
            and any(name in combined for name in away_names)
        ):
            return True

        page.wait_for_timeout(350)

    return False

def open_event_from_list(browser, fixture):
    """Fallback only when the moneyline JSON has no usable event URL."""
    page = new_fast_page(browser)

    try:
        page.goto(
            LIST_URL,
            wait_until="domcontentloaded",
            timeout=45000,
        )

        try:
            page.wait_for_function(
                "() => document.body && document.body.innerText.length > 500",
                timeout=8000,
            )
        except Exception:
            pass

        accept_cookies(page)
        page.keyboard.press("Home")

        for _ in range(20):
            if (
                fixture["date"] in page.locator("body").inner_text(
                    timeout=5000
                )
                or body_has_fixture(page, fixture)
            ):
                break
            scroll_all(page, passes=1)

        if not body_has_fixture(page, fixture):
            open_date_header(page, fixture["date"])
            page.wait_for_timeout(500)

        for _ in range(24):
            if (
                body_has_fixture(page, fixture)
                and click_fixture_more_strict(page, fixture)
            ):
                if verify_event(page, fixture):
                    return page, page.url
                break

            scroll_all(page, passes=1)

        page.close()
        return None, None

    except Exception:
        try:
            page.close()
        except Exception:
            pass
        raise


def open_event_fast(browser, fixture):
    """
    Use the event URL saved by the BetVictor moneyline scraper.

    Falling back to the competition list remains available for old JSON files.
    """
    source_url = clean(fixture.get("source_url"))
    direct_url = source_url.split("?", 1)[0]

    if "/events/" in direct_url:
        page = new_fast_page(browser)

        try:
            page.goto(
                direct_url,
                wait_until="domcontentloaded",
                timeout=45000,
            )
            accept_cookies(page)

            if verify_event(page, fixture):
                print("    opened directly from moneyline event URL")
                return page, page.url

            print("    direct event verification failed; using list fallback")
        except Exception as error:
            print(
                "    direct event load failed; using list fallback: "
                f"{type(error).__name__}"
            )

        try:
            page.close()
        except Exception:
            pass

    return open_event_from_list(browser, fixture)

def base_event_url(url):
    return str(url).split("?", 1)[0]


def group_url(event_url, group_id):
    base = base_event_url(event_url)
    if not group_id:
        return base
    return f"{base}?market_group={group_id}"


def capture_group(
    page,
    event_url,
    group_name,
    group_id,
    debug_dir,
    fixture=None,
):
    """
    Capture one BetVictor market group while reusing the same page.

    Bet Builder receives special handling because Match Stats sits behind a
    second-row tab and its individual rows must be expanded.
    """
    started = time.perf_counter()
    url = group_url(event_url, group_id)
    print(f"    group {group_name} ...")

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=45000,
    )

    try:
        page.wait_for_function(
            r"""() => {
                const text = document.body
                    ? document.body.innerText
                    : "";
                return (
                    /\d+\/\d+/.test(text)
                    || /EVS|EVENS|EVEN/i.test(text)
                    || /no markets available/i.test(text)
                );
            }""",
            timeout=9000,
        )
    except Exception:
        pass

    accept_cookies(page)

    try:
        initial_body = page.locator("body").inner_text(timeout=7000)
    except Exception:
        initial_body = ""

    if "There are currently no markets available" in initial_body:
        captured = (
            f"=== GROUP {group_name} NO MARKETS ===\n"
            + initial_body
        )
        (debug_dir / f"{group_name}.txt").write_text(
            captured,
            encoding="utf-8",
        )
        print(
            f"      {group_name}: no markets "
            f"({time.perf_counter() - started:.1f}s)"
        )
        return captured

    chunks = []

    def capture(label, passes=1):
        click_show_more(page)
        scroll_all(page, passes=passes)

        try:
            body = page.locator("body").inner_text(timeout=8000)
        except Exception:
            body = ""

        if body:
            chunks.append(
                f"=== GROUP {group_name} {label} ===\n{body}"
            )

    capture("DEFAULT", passes=2)

    if group_name == "bet_builder":
        try:
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass

        page.wait_for_timeout(350)
        tab_clicked = click_betbuilder_subtab(page, "Match Stats")
        page.wait_for_timeout(1200)
        capture(
            f"MATCH_STATS_TAB clicked={tab_clicked}",
            passes=2,
        )

        home = fixture.get("home", "") if fixture else ""
        away = fixture.get("away", "") if fixture else ""

        row_titles = [
            "To Have the Most",
            "To Have The Most",
            "Match Shots on Target",
            "Match Shots On Target",
            "Match Shots",
            f"{home} Shots on Target",
            f"{home} Shots On Target",
            f"{home} Shots",
            f"{away} Shots on Target",
            f"{away} Shots On Target",
            f"{away} Shots",
        ]

        seen_titles = set()

        for title in row_titles:
            title_key = clean(title).lower()

            if not title or title_key in seen_titles:
                continue

            seen_titles.add(title_key)

            try:
                if expand_market_accordion(page, title):
                    page.wait_for_timeout(500)
                    capture(
                        f"EXPANDED {title}",
                        passes=1,
                    )
            except Exception:
                continue
    else:
        for title in FAST_EXPANDS_BY_GROUP.get(group_name, []):
            try:
                if expand_market_accordion(page, title):
                    page.wait_for_timeout(350)
                    capture(
                        f"EXPANDED {title}",
                        passes=1,
                    )
            except Exception:
                continue

    captured = "\n\n".join(chunks)

    (debug_dir / f"{group_name}.txt").write_text(
        captured,
        encoding="utf-8",
    )

    print(
        f"      {group_name}: "
        f"{time.perf_counter() - started:.1f}s"
    )

    return captured


def extract_visible_exact_rows(page, pattern_source):
    """Read only currently mounted rows matching one exact player market."""
    return page.evaluate(
        r"""({patternSource}) => {
            const oddsRe =
                /^(?:\d+\/\d+|EVS|EVENS|EVEN)$/i;
            const rowRe = new RegExp(patternSource, "i");
            const rows = [];
            const seen = new Set();

            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_ELEMENT
            );

            while (walker.nextNode()) {
                const element = walker.currentNode;
                const label = (element.innerText || "")
                    .trim()
                    .replace(/\s+/g, " ");

                if (
                    !rowRe.test(label)
                    || label.length > 150
                ) {
                    continue;
                }

                let node = element;
                let result = null;

                for (
                    let depth = 0;
                    depth < 10 && node;
                    depth += 1, node = node.parentElement
                ) {
                    const block = (node.innerText || "").trim();

                    if (!block || block.length > 850) {
                        continue;
                    }

                    const lines = block
                        .split(/\n+/)
                        .map(value => value.trim())
                        .filter(Boolean);

                    const odds = lines.filter(
                        value => oddsRe.test(value)
                    );

                    if (odds.length) {
                        result = {
                            label,
                            odds: odds[0],
                            block,
                        };
                        break;
                    }
                }

                if (!result) {
                    continue;
                }

                const key = result.label + "|" + result.odds;

                if (seen.has(key)) {
                    continue;
                }

                seen.add(key);
                rows.push(result);
            }

            return rows;
        }""",
        {"patternSource": pattern_source},
    )


def mark_likely_scroll_containers(page):
    """Mark the largest visible vertical scroll containers."""
    try:
        return page.evaluate(
            r"""() => {
                document
                    .querySelectorAll(
                        "[data-bv-all-fast-scroll-id]"
                    )
                    .forEach(
                        element => element.removeAttribute(
                            "data-bv-all-fast-scroll-id"
                        )
                    );

                const candidates = [];

                for (
                    const element
                    of document.querySelectorAll("*")
                ) {
                    const rect =
                        element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    const range =
                        element.scrollHeight
                        - element.clientHeight;

                    if (
                        rect.width < 260
                        || rect.height < 160
                        || range < 100
                    ) {
                        continue;
                    }

                    if (
                        style.overflowY !== "auto"
                        && style.overflowY !== "scroll"
                        && style.overflowY !== "overlay"
                    ) {
                        continue;
                    }

                    candidates.push({
                        element,
                        range,
                        score: range * rect.width,
                        height: rect.height,
                    });
                }

                candidates.sort(
                    (left, right) =>
                        right.score - left.score
                );

                return candidates
                    .slice(0, 10)
                    .map((item, index) => {
                        item.element.setAttribute(
                            "data-bv-all-fast-scroll-id",
                            String(index)
                        );

                        return {
                            id: index,
                            range: item.range,
                            height: item.height,
                        };
                    });
            }"""
        )
    except Exception:
        return []


def add_exact_rows(store, rows):
    before = len(store)

    for row in rows:
        label = clean(row.get("label"))
        odds = clean(row.get("odds")).upper()

        if not label or not is_odds(odds):
            continue

        store[f"{label}|{odds}"] = {
            "label": label,
            "odds": odds,
            "block": clean(row.get("block")),
        }

    return len(store) - before


def harvest_exact_rows(page, pattern_source):
    """
    Harvest a virtualised player market from the window and inner containers.
    """
    harvested = {}

    for pass_number in range(1, 4):
        before = len(harvested)

        try:
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass

        page.wait_for_timeout(250)

        try:
            total_height = int(
                page.evaluate(
                    "Math.max("
                    "document.body.scrollHeight,"
                    "document.documentElement.scrollHeight"
                    ")"
                )
            )
            viewport = int(
                page.evaluate(
                    "window.innerHeight || 900"
                )
            )
        except Exception:
            total_height = 5000
            viewport = 900

        step = max(220, min(360, viewport // 3))
        position = 0

        while position <= total_height:
            try:
                page.evaluate(
                    "(value) => window.scrollTo(0, value)",
                    position,
                )
                page.wait_for_timeout(180)
                add_exact_rows(
                    harvested,
                    extract_visible_exact_rows(
                        page,
                        pattern_source,
                    ),
                )
            except Exception:
                pass

            position += step

        for info in mark_likely_scroll_containers(page):
            locator = page.locator(
                "[data-bv-all-fast-scroll-id="
                f'"{info["id"]}"]'
            )

            if not locator.count():
                continue

            container_step = max(
                180,
                int(info.get("height", 600)) // 3,
            )
            container_position = 0

            while container_position <= int(
                info.get("range", 0)
            ):
                try:
                    locator.evaluate(
                        "(element, value) => "
                        "{ element.scrollTop = value; }",
                        container_position,
                    )
                    page.wait_for_timeout(220)
                    add_exact_rows(
                        harvested,
                        extract_visible_exact_rows(
                            page,
                            pattern_source,
                        ),
                    )
                except Exception:
                    break

                container_position += container_step

        if len(harvested) == before and pass_number > 1:
            break

        click_show_more(page)

    return list(harvested.values())


def exact_player_market_from_rows(config, rows):
    row_re = re.compile(config["row_pattern"], re.I)
    selections = []

    for row in rows:
        match = row_re.fullmatch(
            clean(row.get("label"))
        )

        if not match:
            continue

        player = clean(match.group(1))
        threshold = f"{match.group(2)}+"
        odds = clean(row.get("odds")).upper()

        if not player or not is_odds(odds):
            continue

        selections.append(
            sel(
                (
                    f"{player} {threshold} "
                    f"{config['market'].replace('Player ', '')}"
                ),
                odds,
                player=player,
                threshold=threshold,
                prop_type=config["prop_type"],
            )
        )

    selections.sort(
        key=lambda item: (
            normalize(item.get("player")),
            int(
                clean(item.get("threshold"))
                .rstrip("+")
                or 0
            ),
        )
    )

    return market(config["market"], selections)


def capture_exact_player_markets(
    page,
    fixture,
    debug_dir,
):
    """
    Capture Shots, SOT, Fouls and Tackles before leaving the Player group.

    This reuses the current fixture page and avoids launching the four
    specialist BetVictor browser jobs.
    """
    print("      exact player stats ...")
    started = time.perf_counter()
    results = []
    diagnostics = {}

    try:
        click_exact_text(page, "Player")
    except Exception:
        pass

    for key, config in EXACT_PLAYER_MARKETS.items():
        clicked_heading = None

        # Do not click an already-open row unless no matching selections exist.
        body = ""
        try:
            body = page.locator("body").inner_text(
                timeout=5000
            )
        except Exception:
            pass

        row_re = re.compile(config["row_pattern"], re.I)
        already_visible = any(
            row_re.fullmatch(clean(line))
            for line in body.splitlines()
        )

        if not already_visible:
            for heading in config["headings"]:
                try:
                    if expand_market_accordion(
                        page,
                        heading,
                    ):
                        clicked_heading = heading
                        page.wait_for_timeout(700)
                        break
                except Exception:
                    continue

        click_show_more(page)
        rows = harvest_exact_rows(
            page,
            config["row_pattern"],
        )
        parsed = exact_player_market_from_rows(
            config,
            rows,
        )

        diagnostics[key] = {
            "market": config["market"],
            "heading_clicked": clicked_heading,
            "raw_rows": len(rows),
            "selection_count": parsed[
                "selection_count"
            ],
        }

        (debug_dir / f"exact_{key}.json").write_text(
            json.dumps(
                {
                    "fixture": fixture["match"],
                    "diagnostics": diagnostics[key],
                    "rows": rows,
                    "market": parsed,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if parsed["selection_count"] > 0:
            results.append(parsed)

        print(
            f"        {config['market']:<27} "
            f"{parsed['selection_count']} selections"
        )

    print(
        "      exact player stats: "
        f"{time.perf_counter() - started:.1f}s"
    )

    return results, diagnostics


def parse_stat_over_under(
    lines,
    titles,
    market_name,
    stat,
    team=None,
):
    parsed = None

    for title in titles:
        candidate = parse_over_under(
            lines,
            title,
            market_name,
        )

        if candidate.get("selection_count", 0) > 0:
            parsed = candidate
            break

    if parsed is None:
        parsed = market(market_name, [])

    for selection in parsed.get("selections", []):
        selection["stat"] = stat

        if team:
            selection["team"] = team

    return parsed


def find_market(markets, normalized_market):
    for market_data in markets:
        if (
            market_data.get("normalized_market")
            == normalized_market
        ):
            return market_data

    return None


def build_match_audit(fixture, markets, exact_diagnostics):
    by_key = {
        market_data.get("normalized_market"): market_data
        for market_data in markets
    }

    expected_stats = {
        "match_shots_on_target_over_under":
            "Match Shots On Target Over / Under",
        "match_shots_over_under":
            "Match Shots Over / Under",
        normalize(
            f"{fixture['home']} Shots On Target "
            "Over / Under"
        ):
            f"{fixture['home']} Shots On Target Over / Under",
        normalize(
            f"{fixture['home']} Shots Over / Under"
        ):
            f"{fixture['home']} Shots Over / Under",
        normalize(
            f"{fixture['away']} Shots On Target "
            "Over / Under"
        ):
            f"{fixture['away']} Shots On Target Over / Under",
        normalize(
            f"{fixture['away']} Shots Over / Under"
        ):
            f"{fixture['away']} Shots Over / Under",
    }

    requirements = []

    for key, minimum in CORE_REQUIREMENTS.items():
        requirements.append(
            {
                "section": "core",
                "normalized_market": key,
                "minimum_selections": minimum,
            }
        )

    for key, minimum in PLAYER_REQUIREMENTS.items():
        requirements.append(
            {
                "section": "player",
                "normalized_market": key,
                "minimum_selections": minimum,
            }
        )

    for key, label in expected_stats.items():
        requirements.append(
            {
                "section": "match_team_stats",
                "normalized_market": key,
                "label": label,
                "minimum_selections": 1,
            }
        )

    rows = []
    missing = []

    for requirement in requirements:
        key = requirement["normalized_market"]
        market_data = by_key.get(key)
        count = (
            market_data.get("selection_count", 0)
            if market_data
            else 0
        )
        minimum = requirement["minimum_selections"]
        status = (
            "FOUND"
            if count >= minimum
            else "MISSING_OR_NOT_OFFERED"
        )

        row = {
            **requirement,
            "market": (
                market_data.get("market")
                if market_data
                else requirement.get("label", key)
            ),
            "selection_count": count,
            "status": status,
        }
        rows.append(row)

        if status != "FOUND":
            missing.append(key)

    core_complete = all(
        row["status"] == "FOUND"
        for row in rows
        if row["section"] == "core"
    )

    return {
        "match": fixture["match"],
        "core_complete": core_complete,
        "market_count": len(markets),
        "missing_or_not_offered": missing,
        "requirements": rows,
        "exact_player_diagnostics": exact_diagnostics,
    }


def print_match_audit(audit):
    print("    coverage audit:")

    for row in audit["requirements"]:
        status = (
            "OK"
            if row["status"] == "FOUND"
            else "MISS"
        )
        print(
            f"      [{status:<4}] "
            f"{row['market']:<40} "
            f"{row['selection_count']} selections"
        )

    if audit["core_complete"]:
        print("    CORE COVERAGE: complete")
    else:
        core_missing = [
            row["normalized_market"]
            for row in audit["requirements"]
            if (
                row["section"] == "core"
                and row["status"] != "FOUND"
            )
        ]
        print(
            "    MISSING CORE: "
            + ", ".join(core_missing)
        )


def find_block(lines, title, max_len=260):
    indices = [i for i, x in enumerate(lines) if clean(x).lower() == clean(title).lower()]
    if not indices:
        return []
    best, score = [], -1
    for idx in indices:
        block = lines[idx:idx + max_len]
        sc = sum(1 for x in block if is_odds(x))
        if sc > score:
            best, score = block, sc
    return best


def bad_player(x, home, away):
    x = clean(x)
    junk = {
        "Search", "Show More", "Show Less", "First", "Anytime", "Last", "Over", "Under", "Yes", "No",
        "Goalscorers", "Player Shots on Target", "Player Shots", "Player Assists", "Player Tackles", "Player Fouls", "Player Cards",
        home, away, "Draw", "Popular", "Bet Builder", "Specials", "Bet Boost", "Early Payout", "Goals", "Corners", "Cards", "Player", "Half", "Asian Lines", "Other",
    }
    if not x or x in junk or is_odds(x) or is_threshold(x):
        return True
    if len(x) > 55:
        return True
    if re.match(r"^\d", x):
        return True
    if any(t in x.lower() for t in ["responsible", "terms", "privacy", "world cup", "kick off", "match betting"]):
        return True
    return False


def parse_over_under(lines, title, market_name):
    block = find_block(lines, title, 120)

    if not block:
        idxs = [
            i for i, x in enumerate(lines)
            if clean(title).lower() in clean(x).lower()
        ]
        if idxs:
            block = lines[idxs[0]:idxs[0] + 120]

    out = []
    seen = set()

    def add(side, line, odds):
        side = clean(side).lower()
        line = clean(line)
        odds = clean(odds)

        if side not in {"over", "under"}:
            return
        if not re.fullmatch(r"\d+(?:\.\d+)?", line):
            return
        if not is_odds(odds):
            return

        key = (side, line)
        if key in seen:
            return
        seen.add(key)

        out.append(
            sel(
                f"{side.title()} {line}",
                odds,
                side=side,
                line=line,
            )
        )

    # Parse explicit BetVictor rows first:
    # O 1.5
    # 1/6
    # U 1.5
    # 4/1
    explicit_started = False
    misses_after_start = 0
    i = 0

    while i < len(block):
        token = clean(block[i])
        explicit = re.fullmatch(
            r"(O|U|Over|Under)\s*(\d+(?:\.\d+)?)",
            token,
            re.I,
        )

        if explicit and i + 1 < len(block) and is_odds(block[i + 1]):
            side_token = explicit.group(1).lower()
            side = "over" if side_token in {"o", "over"} else "under"
            add(side, explicit.group(2), block[i + 1])
            explicit_started = True
            misses_after_start = 0
            i += 2
            continue

        if explicit_started:
            if token not in {"Show More", "Show Less", "Over", "Under"} and not is_odds(token):
                misses_after_start += 1
                if misses_after_start >= 2:
                    break

        i += 1

    if out:
        return market(market_name, out)

    # Fallback for a genuine two-column layout.
    first_line_idx = next(
        (
            i for i, token in enumerate(block)
            if re.fullmatch(r"\d+(?:\.\d+)?", clean(token))
        ),
        -1,
    )
    over_header_idx = next(
        (i for i, token in enumerate(block) if clean(token).lower() == "over"),
        -1,
    )
    under_header_idx = next(
        (i for i, token in enumerate(block) if clean(token).lower() == "under"),
        -1,
    )

    if (
        first_line_idx >= 0
        and over_header_idx >= 0
        and under_header_idx >= 0
        and over_header_idx < first_line_idx
        and under_header_idx < first_line_idx
    ):
        i = first_line_idx
        while i < len(block):
            token = clean(block[i])

            if not re.fullmatch(r"\d+(?:\.\d+)?", token):
                i += 1
                continue

            odds = []
            j = i + 1
            while j < min(i + 7, len(block)):
                nxt = clean(block[j])

                if re.fullmatch(r"\d+(?:\.\d+)?", nxt):
                    break
                if is_odds(nxt):
                    odds.append(nxt)
                    if len(odds) == 2:
                        break
                j += 1

            if len(odds) == 2:
                add("over", token, odds[0])
                add("under", token, odds[1])
                i = j + 1
            else:
                i += 1

        if out:
            return market(market_name, out)

    # Final fallback for separate Over and Under blocks.
    mode = None
    i = 0
    while i < len(block):
        token = clean(block[i])
        lower = token.lower()

        if lower == "over":
            mode = "over"
            i += 1
            continue
        if lower == "under":
            mode = "under"
            i += 1
            continue

        if (
            mode
            and re.fullmatch(r"\d+(?:\.\d+)?", token)
            and i + 1 < len(block)
            and is_odds(block[i + 1])
        ):
            add(mode, token, block[i + 1])
            i += 2
            continue

        i += 1

    return market(market_name, out)

def find_first_block(lines, titles, max_len=260):
    """Find the strongest exact-title block across title aliases."""
    best = []
    best_score = -1

    for title in titles:
        block = find_block(lines, title, max_len)

        if not block:
            continue

        score = sum(1 for token in block if is_odds(token))

        if score > best_score:
            best = block
            best_score = score

    return best


def next_odds(lines, index, lookahead=4):
    for offset in range(1, lookahead + 1):
        target = index + offset

        if target >= len(lines):
            break

        token = clean(lines[target])

        if is_odds(token):
            return token

        if offset > 1 and token and token not in {
            "Home",
            "Draw",
            "Away",
            "Yes",
            "No",
            "First",
            "Anytime",
            "Last",
        }:
            break

    return ""


def token_matches_team(token, team):
    token_key = norm(token)

    return any(
        token_key == norm(alias)
        for alias in team_alts(team)
    )


def classify_double_chance_label(token, home, away):
    raw = clean(token)
    compact = re.sub(r"[^A-Za-z0-9]+", "", raw).upper()

    if compact in {"1X", "X1"}:
        return "home_draw"
    if compact in {"X2", "2X"}:
        return "away_draw"
    if compact in {"12", "21"}:
        return "home_away"

    key = normalize(raw)
    words = set(key.split("_"))

    home_present = any(
        normalize(alias) in key
        for alias in team_alts(home)
    ) or "home" in words

    away_present = any(
        normalize(alias) in key
        for alias in team_alts(away)
    ) or "away" in words

    draw_present = (
        "draw" in words
        or "tie" in words
        or key in {"home_or_draw", "away_or_draw"}
    )

    if home_present and draw_present and not away_present:
        return "home_draw"

    if away_present and draw_present and not home_present:
        return "away_draw"

    if home_present and away_present and not draw_present:
        return "home_away"

    return None


def parse_simple_player_aliases(
    lines,
    titles,
    market_name,
    prop_type,
    home,
    away,
):
    block = find_first_block(lines, titles, 280)
    title_keys = {normalize(title) for title in titles}
    out = []
    seen = set()

    for i, raw_player in enumerate(block):
        player = clean(raw_player)

        if normalize(player) in title_keys:
            continue

        if bad_player(player, home, away):
            continue

        odds = next_odds(block, i, lookahead=2)

        if not odds:
            continue

        key = (player, odds)

        if key in seen:
            continue

        seen.add(key)
        out.append(
            sel(
                f"{player} {market_name.replace('Player ', '')}",
                odds,
                player=player,
                prop_type=prop_type,
            )
        )

    return market(market_name, out)


def parse_player_cards_anytime(lines, home, away):
    """
    Keep only the ordinary card price.

    BetVictor can display First and Anytime card columns together. When two or
    three prices follow a player, the ordinary/Anytime card price is the second
    column. A one-price row is treated as the ordinary card market.
    """
    titles = [
        "Player Cards",
        "Player To Be Carded",
        "Player to Be Carded",
    ]
    block = find_first_block(lines, titles, 320)
    title_keys = {normalize(title) for title in titles}

    out = []
    seen = set()

    for i, raw_player in enumerate(block):
        player = clean(raw_player)

        if normalize(player) in title_keys:
            continue

        if bad_player(player, home, away):
            continue

        odds = []
        j = i + 1

        while j < min(i + 7, len(block)) and len(odds) < 3:
            token = clean(block[j])

            if is_odds(token):
                odds.append(token)
            elif odds:
                break

            j += 1

        if not odds:
            continue

        ordinary_odds = odds[1] if len(odds) >= 2 else odds[0]
        key = (player, ordinary_odds)

        if key in seen:
            continue

        seen.add(key)
        out.append(
            sel(
                f"{player} To Get A Card",
                ordinary_odds,
                player=player,
                prop_type="player_card",
            )
        )

    return market("Player Cards", out)


def parse_match_betting(lines, home, away):
    block = find_first_block(
        lines,
        [
            "Match Betting",
            "Match Result",
            "1X2",
            "Match Odds",
        ],
        70,
    )

    outcomes = {}

    for i, raw_token in enumerate(block):
        token = clean(raw_token)
        odds = next_odds(block, i, lookahead=3)

        if not odds:
            continue

        if token_matches_team(token, home):
            outcomes.setdefault(
                "home",
                sel(home, odds, side="home"),
            )
            continue

        if token.lower() in {"draw", "the draw", "tie"}:
            outcomes.setdefault(
                "draw",
                sel("Draw", odds, side="draw"),
            )
            continue

        if token_matches_team(token, away):
            outcomes.setdefault(
                "away",
                sel(away, odds, side="away"),
            )

    if set(outcomes) != {"home", "draw", "away"}:
        return market("Match Betting", [])

    return market(
        "Match Betting",
        [
            outcomes["home"],
            outcomes["draw"],
            outcomes["away"],
        ],
    )

def parse_btts(lines):
    # Handles blocks where the title is exact or combined with Total Goals in Popular.
    indices = [i for i, x in enumerate(lines) if "both teams to score" in clean(x).lower()]
    out = []
    for idx in indices[:3]:
        block = lines[idx:idx + 50]
        for i, tok in enumerate(block):
            if tok in {"Yes", "No"} and i + 1 < len(block) and is_odds(block[i + 1]):
                out.append(sel(f"Both Teams To Score - {tok}", block[i + 1], side=tok.lower()))
    return market("Both Teams To Score", out)


def parse_double_chance(lines, home, away):
    block = find_first_block(
        lines,
        [
            "Double Chance",
            "Double Chance Betting",
            "Double Chance (1X2)",
        ],
        80,
    )

    labels = {
        "home_draw": f"{home} or Draw",
        "away_draw": f"{away} or Draw",
        "home_away": f"{home} or {away}",
    }

    outcomes = {}

    for i, raw_token in enumerate(block):
        outcome = classify_double_chance_label(
            raw_token,
            home,
            away,
        )

        if not outcome:
            continue

        odds = next_odds(block, i, lookahead=3)

        if not odds:
            continue

        outcomes.setdefault(
            outcome,
            sel(
                labels[outcome],
                odds,
                side=outcome,
            ),
        )

    if set(outcomes) != {
        "home_draw",
        "away_draw",
        "home_away",
    }:
        return market("Double Chance", [])

    return market(
        "Double Chance",
        [
            outcomes["home_draw"],
            outcomes["away_draw"],
            outcomes["home_away"],
        ],
    )

def parse_half_time(lines, home, away):
    block = find_block(lines, "Half Time", 70) or find_block(lines, "Half-Time Result", 70)
    out = []
    for label, side in [(home, "home"), ("Draw", "draw"), (away, "away")]:
        for i, tok in enumerate(block):
            if clean(tok) == label and i + 1 < len(block) and is_odds(block[i + 1]):
                out.append(sel(label, block[i + 1], side=side))
                break
    return market("Half Time Result", out)


def parse_two_or_three_col_player(lines, title, market_names, home, away):
    block = find_block(lines, title, 460)
    first, anytime, last = [], [], []

    for i, player in enumerate(block):
        player = clean(player)
        if bad_player(player, home, away):
            continue
        odds = []
        j = i + 1
        while j < min(i + 8, len(block)) and len(odds) < 3:
            if is_odds(block[j]):
                odds.append(block[j])
            elif odds:
                break
            j += 1
        if not odds:
            continue
        if len(odds) >= 3:
            first.append(sel(f"{player} First", odds[0], player=player, prop_type="first"))
            anytime.append(sel(f"{player} Anytime", odds[1], player=player, prop_type="anytime"))
            last.append(sel(f"{player} Last", odds[2], player=player, prop_type="last"))
        elif len(odds) == 2:
            first.append(sel(f"{player} First", odds[0], player=player, prop_type="first"))
            anytime.append(sel(f"{player} Anytime", odds[1], player=player, prop_type="anytime"))
        elif len(odds) == 1:
            anytime.append(sel(f"{player} Anytime", odds[0], player=player, prop_type="anytime"))

    markets = []
    if first:
        markets.append(market(market_names[0], first))
    if anytime:
        markets.append(market(market_names[1], anytime))
    if len(market_names) > 2 and last:
        markets.append(market(market_names[2], last))
    return markets


def parse_threshold_player(lines, title, market_name, prop_type, max_thresholds, home, away):
    block = find_block(lines, title, 580)
    out = []
    if not block:
        return market(market_name, out)

    headers = [x for x in block[:50] if is_threshold(x)]
    if not headers:
        headers = [f"{i}+" for i in range(1, max_thresholds + 1)]
    headers = headers[:max_thresholds]

    for i, player in enumerate(block):
        player = clean(player)
        if bad_player(player, home, away):
            continue
        odds = []
        j = i + 1
        while j < min(i + 14, len(block)) and len(odds) < len(headers):
            if is_odds(block[j]):
                odds.append(block[j])
            elif odds and not is_threshold(block[j]):
                break
            j += 1
        if not odds:
            continue
        for idx, odd in enumerate(odds):
            th = headers[idx] if idx < len(headers) else f"{idx+1}+"
            out.append(sel(
                f"{player} {th} {market_name.replace('Player ', '')}",
                odd,
                player=player,
                threshold=th,
                prop_type=prop_type,
            ))
    return market(market_name, out)


def parse_simple_player(lines, title, market_name, prop_type, home, away):
    block = find_block(lines, title, 420)
    out = []
    for i, player in enumerate(block):
        player = clean(player)
        if bad_player(player, home, away):
            continue
        if i + 1 < len(block) and is_odds(block[i + 1]):
            out.append(sel(f"{player} {market_name.replace('Player ', '')}", block[i + 1], player=player, prop_type=prop_type))
    return market(market_name, out)


def parse_match_stats(lines, home, away):
    # Bet Builder > Match Stats:
    # To Have the Most
    # Home | Draw | Away
    # Shots
    # 1/8 | 16/1 | 19/4
    # Shots On Target
    # ...
    block = find_block(lines, "To Have the Most", 180)

    if not block:
        # Fallback: line may include extra whitespace or section label.
        idxs = [i for i, x in enumerate(lines) if "to have the most" in clean(x).lower()]
        if idxs:
            block = lines[idxs[0]:idxs[0] + 180]

    stat_names = {"Shots", "Shots On Target", "Tackles", "Offsides"}
    out = []

    for i, stat in enumerate(block):
        stat = clean(stat)
        if stat not in stat_names:
            continue

        odds = []
        j = i + 1
        while j < min(i + 10, len(block)) and len(odds) < 3:
            if is_odds(block[j]):
                odds.append(block[j])
            j += 1

        if len(odds) >= 3:
            out.append(sel(f"{home} Most {stat}", odds[0], side="home", stat=stat))
            out.append(sel(f"Draw Most {stat}", odds[1], side="draw", stat=stat))
            out.append(sel(f"{away} Most {stat}", odds[2], side="away", stat=stat))

    return market("To Have The Most Match Stats", out)


def parse_all(
    group_texts,
    home,
    away,
    exact_player_markets=None,
):
    """
    Parse and merge every BetVictor props family in memory.
    """
    popular_lines = lines_from_text(
        group_texts.get("popular", "")
    )
    goals_lines = lines_from_text(
        group_texts.get("goals", "")
    )
    corners_lines = lines_from_text(
        group_texts.get("corners", "")
    )
    cards_lines = lines_from_text(
        group_texts.get("cards", "")
    )
    player_lines = lines_from_text(
        group_texts.get("player", "")
    )
    bet_builder_lines = lines_from_text(
        group_texts.get("bet_builder", "")
    )

    markets = []

    def add(candidate):
        if isinstance(candidate, list):
            for market_data in candidate:
                if market_data.get(
                    "selection_count",
                    0,
                ) > 0:
                    markets.append(market_data)
            return

        if candidate.get("selection_count", 0) > 0:
            markets.append(candidate)

    add(parse_match_betting(popular_lines, home, away))
    add(parse_btts(popular_lines))
    add(parse_double_chance(popular_lines, home, away))
    add(parse_half_time(popular_lines, home, away))

    add(
        parse_over_under(
            goals_lines,
            "Total Goals Over/Under",
            "Total Goals Over / Under",
        )
    )

    add(
        parse_over_under(
            corners_lines,
            "Total Corners Over/Under",
            "Total Corners Over / Under",
        )
    )

    total_cards = parse_over_under(
        cards_lines,
        "Total Cards Over/Under",
        "Total Cards Over / Under",
    )

    if not total_cards.get("selection_count"):
        total_cards = parse_over_under(
            cards_lines,
            "Total Cards",
            "Total Cards Over / Under",
        )

    add(total_cards)

    scorer_lines = goals_lines + player_lines
    add(
        parse_two_or_three_col_player(
            scorer_lines,
            "Goalscorers",
            [
                "First Goalscorer",
                "Anytime Goalscorer",
                "Last Goalscorer",
            ],
            home,
            away,
        )
    )

    # Ordinary card market only.
    add(parse_player_cards_anytime(
        cards_lines,
        home,
        away,
    ))

    add(
        parse_simple_player_aliases(
            player_lines,
            [
                "Player Assists",
                "Player To Assist",
                "Player to Assist",
                "To Assist",
            ],
            "Player Assists",
            "assist",
            home,
            away,
        )
    )

    # Exact virtual-list markets have priority over generic text parsing.
    add(exact_player_markets or [])

    exact_keys = {
        market_data.get("normalized_market")
        for market_data in (exact_player_markets or [])
    }

    if "player_shots_on_target" not in exact_keys:
        add(
            parse_threshold_player(
                player_lines,
                "Player Shots on Target",
                "Player Shots On Target",
                "shots_on_target",
                4,
                home,
                away,
            )
        )

    if "player_shots" not in exact_keys:
        add(
            parse_threshold_player(
                player_lines,
                "Player Shots",
                "Player Shots",
                "shots",
                4,
                home,
                away,
            )
        )

    if "player_fouls_committed" not in exact_keys:
        fouls = parse_threshold_player(
            player_lines,
            "Player Fouls",
            "Player Fouls Committed",
            "fouls_committed",
            4,
            home,
            away,
        )

        if not fouls.get("selection_count"):
            fouls = parse_threshold_player(
                player_lines,
                "Player Fouls Committed",
                "Player Fouls Committed",
                "fouls_committed",
                4,
                home,
                away,
            )

        add(fouls)

    if "player_tackles" not in exact_keys:
        add(
            parse_threshold_player(
                player_lines,
                "Player Tackles",
                "Player Tackles",
                "tackles",
                4,
                home,
                away,
            )
        )

    add(parse_match_stats(
        bet_builder_lines,
        home,
        away,
    ))

    add(
        parse_stat_over_under(
            bet_builder_lines,
            [
                "Match Shots on Target",
                "Match Shots On Target",
            ],
            "Match Shots On Target Over / Under",
            "shots_on_target",
        )
    )

    add(
        parse_stat_over_under(
            bet_builder_lines,
            ["Match Shots"],
            "Match Shots Over / Under",
            "shots",
        )
    )

    add(
        parse_stat_over_under(
            bet_builder_lines,
            [
                f"{home} Shots on Target",
                f"{home} Shots On Target",
            ],
            f"{home} Shots On Target Over / Under",
            "shots_on_target",
            team=home,
        )
    )

    add(
        parse_stat_over_under(
            bet_builder_lines,
            [f"{home} Shots"],
            f"{home} Shots Over / Under",
            "shots",
            team=home,
        )
    )

    add(
        parse_stat_over_under(
            bet_builder_lines,
            [
                f"{away} Shots on Target",
                f"{away} Shots On Target",
            ],
            f"{away} Shots On Target Over / Under",
            "shots_on_target",
            team=away,
        )
    )

    add(
        parse_stat_over_under(
            bet_builder_lines,
            [f"{away} Shots"],
            f"{away} Shots Over / Under",
            "shots",
            team=away,
        )
    )

    drop_markets = {
        "first_goalscorer",
        "last_goalscorer",
        "first_player_card",
    }

    # Later exact/specialist markets replace earlier generic versions.
    by_market = {}

    for market_data in markets:
        key = market_data["normalized_market"]

        if key in drop_markets:
            continue

        by_market[key] = market_data

    return list(by_market.values())

def write_hits(text, debug_dir, home, away):
    words = [
        "Player Shots", "Shots on Target", "Player Cards", "Player Assists", "Player Tackles",
        "Player Fouls", "Total Corners", "Total Cards", "To Have the Most", "Match Shots",
        "Match Shots on Target", "Match Tackles", "Match Offsides",
        f"{home} Shots", f"{away} Shots", f"{home} Tackles", f"{away} Tackles",
    ]
    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if any(w.lower() in line.lower() for w in words):
            hits.append(f"{i:04d}: {line}")
            for j in range(i + 1, min(i + 14, len(lines))):
                if lines[j].strip():
                    hits.append(f"      {j:04d}: {lines[j]}")
            hits.append("")
    (debug_dir / "HITS.txt").write_text("\n".join(hits), encoding="utf-8")


def scrape_fixture(browser, fixture):
    fixture_started = time.perf_counter()

    print(
        f"\n{fixture['match']} | "
        f"{fixture['date']} {fixture['time']}"
    )

    page, event_url = open_event_fast(
        browser,
        fixture,
    )

    if not page or not event_url:
        print("    could not open exact event")

        failure_audit = {
            "match": fixture["match"],
            "core_complete": False,
            "market_count": 0,
            "missing_or_not_offered": [
                *CORE_REQUIREMENTS,
                *PLAYER_REQUIREMENTS,
            ],
            "requirements": [],
            "exact_player_diagnostics": {},
            "error": "could_not_open_exact_event",
        }

        return (
            {
                "match": fixture["match"],
                "home_team": fixture["home"],
                "away_team": fixture["away"],
                "kickoff": fixture[
                    "kickoff"
                ].isoformat(),
                "source_url": LIST_URL,
                "market_count": 0,
                "markets": [],
                "error": "could_not_open_exact_event",
            },
            failure_audit,
        )

    print(
        "    opened exact event: "
        f"{base_event_url(event_url)}"
    )

    debug_dir = (
        DEBUG_ROOT
        / slugify(fixture["match"])
    )
    debug_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    chunks = []
    group_texts = {}
    exact_player_markets = []
    exact_diagnostics = {}

    try:
        for group_name, group_id in GROUPS.items():
            group_text = capture_group(
                page,
                event_url,
                group_name,
                group_id,
                debug_dir,
                fixture,
            )
            group_texts[group_name] = group_text
            chunks.append(
                f"\n\n##### "
                f"{group_name.upper()} #####\n"
                f"{group_text}"
            )

            # Reuse the already-open Player page before navigating away.
            if group_name == "player":
                (
                    exact_player_markets,
                    exact_diagnostics,
                ) = capture_exact_player_markets(
                    page,
                    fixture,
                    debug_dir,
                )
    finally:
        try:
            page.close()
        except Exception:
            pass

    all_text = "\n".join(chunks)

    (debug_dir / "ALL_GROUPS.txt").write_text(
        all_text,
        encoding="utf-8",
    )

    write_hits(
        all_text,
        debug_dir,
        fixture["home"],
        fixture["away"],
    )

    markets = parse_all(
        group_texts,
        fixture["home"],
        fixture["away"],
        exact_player_markets,
    )

    print(f"    markets: {len(markets)}")

    for market_data in markets:
        print(
            f"      {market_data['market']:<40} "
            f"{market_data['selection_count']} "
            "selections"
        )

    audit = build_match_audit(
        fixture,
        markets,
        exact_diagnostics,
    )
    print_match_audit(audit)

    elapsed = round(
        time.perf_counter() - fixture_started,
        2,
    )

    result = {
        "match": fixture["match"],
        "home_team": fixture["home"],
        "away_team": fixture["away"],
        "kickoff": fixture[
            "kickoff"
        ].isoformat(),
        "source_url": base_event_url(event_url),
        "market_count": len(markets),
        "markets": markets,
        "elapsed_seconds": elapsed,
    }

    audit["elapsed_seconds"] = elapsed

    return result, audit

def main():
    total_started = time.perf_counter()

    OUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    DEBUG_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    fixtures = load_next_15_fixtures()

    print(
        f"Selected next {len(fixtures)} "
        "BetVictor fixtures:"
    )

    for index, fixture in enumerate(fixtures, 1):
        print(
            f"  {index:02d}. "
            f"{fixture['date']} "
            f"{fixture['time']} | "
            f"{fixture['match']}"
        )

    results = []
    audits = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS,
        )

        for index, fixture in enumerate(
            fixtures,
            1,
        ):
            print("\n" + "=" * 70)
            print(f"[{index}/{len(fixtures)}]")

            try:
                result, audit = scrape_fixture(
                    browser,
                    fixture,
                )
                results.append(result)
                audits.append(audit)
            except KeyboardInterrupt:
                raise
            except Exception as error:
                print(
                    "    ERROR: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                results.append(
                    {
                        "match": fixture["match"],
                        "home_team": fixture["home"],
                        "away_team": fixture["away"],
                        "kickoff": fixture[
                            "kickoff"
                        ].isoformat(),
                        "source_url": LIST_URL,
                        "market_count": 0,
                        "markets": [],
                        "error": str(error),
                    }
                )

                audits.append(
                    {
                        "match": fixture["match"],
                        "core_complete": False,
                        "market_count": 0,
                        "missing_or_not_offered": [
                            *CORE_REQUIREMENTS,
                            *PLAYER_REQUIREMENTS,
                        ],
                        "requirements": [],
                        "exact_player_diagnostics": {},
                        "error": str(error),
                    }
                )

        browser.close()

    elapsed = round(
        time.perf_counter() - total_started,
        2,
    )

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BetVictor",
        "market_type": "combined_props_test",
        "source_url": LIST_URL,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "test_mode": True,
        "max_matches": MAX_MATCHES,
        "production_files_modified": False,
        "match_count": len(results),
        "matches_with_markets": len(
            [
                result
                for result in results
                if result.get("market_count", 0) > 0
            ]
        ),
        "elapsed_seconds": elapsed,
        "matches": results,
    }

    audit_output = {
        "bookmaker": "BetVictor",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "test_mode": True,
        "max_matches": MAX_MATCHES,
        "production_files_modified": False,
        "elapsed_seconds": elapsed,
        "match_count": len(audits),
        "core_complete_matches": len(
            [
                audit
                for audit in audits
                if audit.get("core_complete")
            ]
        ),
        "matches": audits,
    }

    output_temp = OUT_PATH.with_suffix(
        OUT_PATH.suffix + ".tmp"
    )
    output_temp.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_temp.replace(OUT_PATH)

    audit_temp = AUDIT_PATH.with_suffix(
        AUDIT_PATH.suffix + ".tmp"
    )
    audit_temp.write_text(
        json.dumps(
            audit_output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    audit_temp.replace(AUDIT_PATH)

    print("\nSaved COMBINED TEST outputs:")
    print(OUT_PATH)
    print(AUDIT_PATH)
    print(
        "Matches with markets: "
        f"{output['matches_with_markets']}/"
        f"{output['match_count']}"
    )
    print(
        "Core-complete matches: "
        f"{audit_output['core_complete_matches']}/"
        f"{audit_output['match_count']}"
    )
    print(f"Total elapsed: {elapsed:.1f}s")
    print("Production BetVictor files modified: NO")


if __name__ == "__main__":
    main()