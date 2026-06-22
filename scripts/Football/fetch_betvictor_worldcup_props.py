#!/usr/bin/env python3
"""
fetch_betvictor_worldcup_props_NEXT15.py

BetVictor World Cup props scraper — production next-15 version.

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

Output:
  football/data/betvictor_worldcup_props.json

Debug:
  football/debug/betvictor_worldcup_props/<match>/ALL_GROUPS.txt
  football/debug/betvictor_worldcup_props/<match>/HITS.txt
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

MONEYLINES_PATH = ROOT / "football" / "data" / "betvictor_worldcup_moneylines.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_worldcup_props"

LIST_URL = "https://www.betvictor.com/en-ie/sports/240/sections/custom-list/7199/group/world-cup-matches/item/matches"

MAX_MATCHES = 15
HEADLESS = False

GROUPS = {
    "popular": None,
    "goals": "19293",
    "corners": "19294",
    "cards": "19295",
    "player": "19296",
    "bet_builder": "12536",
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
    """Verify that the opened BetVictor event is the expected fixture.

    BetVictor sometimes loads the correct event URL but the body text is not ready
    when we check it. Use title + body + a second wait before rejecting.
    """
    if "/events/" not in page.url:
        return False

    def has_fixture_text(txt):
        lo = clean(txt).lower()
        home_ok = any(x.lower() in lo for x in team_alts(fixture["home"]))
        away_ok = any(x.lower() in lo for x in team_alts(fixture["away"]))
        return home_ok and away_ok

    for wait_ms in (1500, 3500, 5500):
        try:
            page.wait_for_timeout(wait_ms)
            title = ""
            try:
                title = page.title()
            except Exception:
                title = ""
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=15000)
            except Exception:
                body = ""

            if has_fixture_text(title) or has_fixture_text(body):
                return True
        except Exception:
            pass

    return False


def open_event_from_list(browser, fixture):
    page = browser.new_page(viewport={"width": 1700, "height": 1000})
    try:
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        accept_cookies(page)
        page.keyboard.press("Home")
        page.wait_for_timeout(500)

        # Get the date header or fixture into view.
        for _ in range(35):
            body = page.locator("body").inner_text(timeout=16000)
            if fixture["date"] in body or body_has_fixture(page, fixture):
                break
            scroll_all(page, passes=1)

        # If row is not visible, open its date accordion.
        if not body_has_fixture(page, fixture):
            open_date_header(page, fixture["date"])
            page.wait_for_timeout(1000)

        for attempt in range(45):
            if body_has_fixture(page, fixture):
                if click_fixture_more_strict(page, fixture):
                    page.wait_for_timeout(4500)
                    if verify_event(page, fixture):
                        return page, page.url
                    else:
                        print(f"    verify failed after waits: {page.url}")
                        page.close()
                        return None, None
            scroll_all(page, passes=1)

        page.close()
        return None, None

    except Exception:
        try:
            page.close()
        except Exception:
            pass
        raise


def base_event_url(url):
    return str(url).split("?", 1)[0]


def group_url(event_url, group_id):
    base = base_event_url(event_url)
    if not group_id:
        return base
    return f"{base}?market_group={group_id}"


def capture_group(page, event_url, group_name, group_id, debug_dir, fixture=None):
    url = group_url(event_url, group_id)
    print(f"    group {group_name} ...")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4500)
    # Wait until fractional odds are actually rendered on the page.
    # Betting SPAs render via JS after domcontentloaded, so a fixed
    # timeout is unreliable. This is especially needed for corners/cards
    # groups where the accordion is already expanded by default.
    try:
        page.wait_for_function(
            r"() => /\d+\/\d+/.test(document.body.innerText)",
            timeout=10000
        )
    except Exception:
        pass
    accept_cookies(page)

    # Some BetVictor events have a valid event URL but a specific group, usually
    # Bet Builder, says "There are currently no markets available".
    # That is not a wrong event; just skip that group cleanly.
    try:
        initial_body = page.locator("body").inner_text(timeout=20000)
        if "There are currently no markets available" in initial_body:
            txt = f"=== GROUP {group_name} NO MARKETS ===\n" + initial_body
            (debug_dir / f"{group_name}.txt").write_text(txt, encoding="utf-8")
            print(f"      {group_name}: no markets available, skipped")
            return txt
    except Exception:
        pass

    chunks = []

    def capture(label, passes=4):
        click_show_more(page)
        scroll_all(page, passes=passes)
        try:
            chunks.append(f"=== GROUP {group_name} {label} ===\n" + page.locator("body").inner_text(timeout=25000))
        except Exception:
            pass

    capture("DEFAULT", passes=4)

    # Bet Builder has a second-row menu. The required match/team stat markets are inside:
    # Bet Builder -> Match Stats
    if group_name == "bet_builder":
        home = fixture.get("home", "") if fixture else ""
        away = fixture.get("away", "") if fixture else ""

        match_stat_titles = [
            "To Have the Most",
            "Match Shots on Target",
            "Match Shots",
            "Match Tackles",
            "Match Offsides",
            f"{home} Shots on Target",
            f"{home} Shots",
            f"{home} Tackles",
            f"{home} Offsides",
            f"{away} Shots on Target",
            f"{away} Shots",
            f"{away} Tackles",
            f"{away} Offsides",
        ]

        # Reset near the top of the Bet Builder page so the sub-tabs are clickable.
        try:
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass
        page.wait_for_timeout(500)

        clicked_ms = click_betbuilder_subtab(page, "Match Stats")
        page.wait_for_timeout(1800)
        capture(f"SUBTAB Match Stats clicked={clicked_ms}", passes=5)

        # Expand the market rows on Match Stats. This is the bit missing before.
        for title in match_stat_titles:
            try:
                clicked = expand_market_accordion(page, title)
                page.wait_for_timeout(900)
                capture(f"MATCH_STATS EXPANDED {title} clicked={clicked}", passes=2)
            except Exception:
                pass

        # Also capture Player Stats for safety, but player markets are mainly from market_group=19296.
        try:
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass
        page.wait_for_timeout(500)
        clicked_ps = click_betbuilder_subtab(page, "Player Stats")
        page.wait_for_timeout(1800)
        capture(f"SUBTAB Player Stats clicked={clicked_ps}", passes=4)

    # Normal group expansion for non-betbuilder pages.
    # Skip titles that are the primary market on their dedicated group page
    # (already expanded by default) — clicking would collapse them.
    SKIP_EXPAND_ON_GROUP = {
        "corners": {"Total Corners Over/Under"},
        "cards":   {"Total Cards Over/Under", "Total Cards"},
        "goals":   {"Total Goals Over/Under"},
    }
    skip_on_this_group = SKIP_EXPAND_ON_GROUP.get(group_name, set())
    for title in EXPAND_TITLES:
        if title in skip_on_this_group:
            continue
        try:
            if expand_market_accordion(page, title):
                capture(f"EXPANDED {title}", passes=3)
        except Exception:
            pass

    text = "\n\n".join(chunks)
    (debug_dir / f"{group_name}.txt").write_text(text, encoding="utf-8")
    return text


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

def parse_match_betting(lines, home, away):
    block = (find_block(lines, "Match Betting", 50) or
             find_block(lines, "Match Result", 50) or
             find_block(lines, "1X2", 50) or
             find_block(lines, "Match Odds", 50))
    out = []
    wanted = [(home, "home"), ("Draw", "draw"), (away, "away")]
    for label, side in wanted:
        for i, tok in enumerate(block):
            if clean(tok) == label and i + 1 < len(block) and is_odds(block[i + 1]):
                out.append(sel(label, block[i + 1], side=side))
                break
    return market("Match Betting", out)


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


def parse_double_chance(lines):
    block = find_block(lines, "Double Chance", 45)
    out = []
    mapping = {"1/X": "Home or Draw", "1X": "Home or Draw", "1/2": "Home or Away", "12": "Home or Away", "X/2": "Away or Draw", "X2": "Away or Draw"}
    for i, tok in enumerate(block):
        tok = clean(tok)
        if tok in mapping and i + 1 < len(block) and is_odds(block[i + 1]):
            out.append(sel(mapping[tok], block[i + 1]))
    return market("Double Chance", out)


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


def parse_all(all_text, home, away):
    lines = lines_from_text(all_text)
    markets = []

    def add(m):
        if isinstance(m, list):
            for x in m:
                if x.get("selection_count", 0) > 0:
                    markets.append(x)
        elif m.get("selection_count", 0) > 0:
            markets.append(m)

    add(parse_match_betting(lines, home, away))
    add(parse_over_under(lines, "Total Goals Over/Under", "Total Goals Over / Under"))
    add(parse_btts(lines))
    add(parse_double_chance(lines))
    add(parse_half_time(lines, home, away))
    add(parse_over_under(lines, "Total Corners Over/Under", "Total Corners Over / Under"))
    _cards = parse_over_under(lines, "Total Cards Over/Under", "Total Cards Over / Under")
    if not _cards.get("selection_count"):
        _cards = parse_over_under(lines, "Total Cards", "Total Cards Over / Under")
    add(_cards)

    add(parse_two_or_three_col_player(lines, "Goalscorers", ["First Goalscorer", "Anytime Goalscorer", "Last Goalscorer"], home, away))
    add(parse_two_or_three_col_player(lines, "Player Cards", ["First Player Card", "Player Cards"], home, away))

    add(parse_threshold_player(lines, "Player Shots on Target", "Player Shots On Target", "shots_on_target", 3, home, away))
    add(parse_threshold_player(lines, "Player Shots", "Player Shots", "shots", 4, home, away))
    add(parse_simple_player(lines, "Player Assists", "Player Assists", "assist", home, away))
    add(parse_threshold_player(lines, "Player Tackles", "Player Tackles", "tackles", 4, home, away))
    add(parse_threshold_player(lines, "Player Fouls", "Player Fouls", "fouls", 4, home, away))

    # Bet Builder > Match Stats desired markets.
    add(parse_match_stats(lines, home, away))
    add(parse_over_under(lines, "Match Shots on Target", "Match Shots On Target Over / Under"))
    add(parse_over_under(lines, "Match Shots", "Match Shots Over / Under"))
    add(parse_over_under(lines, "Match Tackles", "Match Tackles Over / Under"))
    add(parse_over_under(lines, "Match Offsides", "Match Offsides Over / Under"))

    add(parse_over_under(lines, f"{home} Shots on Target", f"{home} Shots On Target Over / Under"))
    add(parse_over_under(lines, f"{home} Shots", f"{home} Shots Over / Under"))
    add(parse_over_under(lines, f"{home} Tackles", f"{home} Tackles Over / Under"))
    add(parse_over_under(lines, f"{home} Offsides", f"{home} Offsides Over / Under"))

    add(parse_over_under(lines, f"{away} Shots on Target", f"{away} Shots On Target Over / Under"))
    add(parse_over_under(lines, f"{away} Shots", f"{away} Shots Over / Under"))
    add(parse_over_under(lines, f"{away} Tackles", f"{away} Tackles Over / Under"))
    add(parse_over_under(lines, f"{away} Offsides", f"{away} Offsides Over / Under"))

    # We do NOT want First Goalscorer or Last Goalscorer on the site.
    # Keep Anytime Goalscorer only.
    DROP_MARKETS = {"first_goalscorer", "last_goalscorer"}

    seen, out = set(), []
    for m in markets:
        k = m["normalized_market"]
        if k in DROP_MARKETS:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(m)
    return out


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
    print(f"\n{fixture['match']} | {fixture['date']} {fixture['time']}")
    page, event_url = open_event_from_list(browser, fixture)

    if not page or not event_url:
        print("    could not open exact event")
        return {
            "match": fixture["match"],
            "home_team": fixture["home"],
            "away_team": fixture["away"],
            "kickoff": fixture["kickoff"].isoformat(),
            "source_url": LIST_URL,
            "market_count": 0,
            "markets": [],
            "error": "could_not_open_exact_event",
        }

    print(f"    opened exact event: {base_event_url(event_url)}")

    debug_dir = DEBUG_ROOT / slugify(fixture["match"])
    debug_dir.mkdir(parents=True, exist_ok=True)

    chunks = []
    try:
        for group_name, group_id in GROUPS.items():
            text = capture_group(page, event_url, group_name, group_id, debug_dir, fixture)
            chunks.append(f"\n\n##### {group_name.upper()} #####\n{text}")
    finally:
        try:
            page.close()
        except Exception:
            pass

    all_text = "\n".join(chunks)
    (debug_dir / "ALL_GROUPS.txt").write_text(all_text, encoding="utf-8")
    write_hits(all_text, debug_dir, fixture["home"], fixture["away"])

    markets = parse_all(all_text, fixture["home"], fixture["away"])
    print(f"    markets: {len(markets)}")
    for m in markets:
        print(f"      {m['market']:<35} {m['selection_count']} selections")

    return {
        "match": fixture["match"],
        "home_team": fixture["home"],
        "away_team": fixture["away"],
        "kickoff": fixture["kickoff"].isoformat(),
        "source_url": base_event_url(event_url),
        "market_count": len(markets),
        "markets": markets,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_ROOT.mkdir(parents=True, exist_ok=True)

    fixtures = load_next_15_fixtures()

    print(f"Selected next {len(fixtures)} BetVictor fixtures:")
    for i, f in enumerate(fixtures, 1):
        print(f"  {i:02d}. {f['date']} {f['time']} | {f['match']}")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        for i, fixture in enumerate(fixtures, 1):
            print("\n" + "=" * 70)
            print(f"[{i}/{len(fixtures)}]")
            try:
                results.append(scrape_fixture(browser, fixture))
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"    ERROR: {type(e).__name__}: {e}")
                results.append({
                    "match": fixture["match"],
                    "home_team": fixture["home"],
                    "away_team": fixture["away"],
                    "kickoff": fixture["kickoff"].isoformat(),
                    "source_url": LIST_URL,
                    "market_count": 0,
                    "markets": [],
                    "error": str(e),
                })

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BetVictor",
        "market_type": "props",
        "source_url": LIST_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches_with_markets": len([r for r in results if r.get("market_count", 0) > 0]),
        "matches": results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nSaved:")
    print(OUT_PATH)
    print(f"Matches with markets: {output['matches_with_markets']}/{output['match_count']}")


if __name__ == "__main__":
    main()