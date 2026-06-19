#!/usr/bin/env python3
"""
fetch_williamhill_worldcup_match_stats.py (V14 topmost position grid cards/corners fix)

Separate William Hill World Cup match/team stats scraper — TEST VERSION — V14 topmost position grid cards/corners fix.

MAX_MATCHES = 15 while testing.

This targets the bottom of the Popular/default event page, especially:
  - Team Performance
  - Total Match Shots
  - Total Team Match Shots
  - Total Match Shots On Target
  - Total Team Match Shots On Target

It also attempts:
  - Total Corners / Match Corners
  - Total Cards / Match Cards

Output:
  football/data/williamhill_worldcup_match_stats.json

Debug:
  football/debug/williamhill_worldcup_match_stats/<match>.txt
  football/debug/williamhill_worldcup_match_stats/<match>_hits.txt

Run moneylines first so fixture targets are fresh:
  python scripts/Football/fetch_williamhill_worldcup_moneylines.py
  python scripts/Football/fetch_williamhill_worldcup_match_stats.py (V14 topmost position grid cards/corners fix)
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "williamhill_worldcup_match_stats.json"
DEBUG_DIR = ROOT / "football" / "debug" / "williamhill_worldcup_match_stats"
MONEYLINES_PATH = ROOT / "football" / "data" / "williamhill_worldcup_moneylines.json"

COMPETITION_URL = "https://sports.williamhill.com/betting/en-gb/football/competitions/OB_TY52321/world-cup-2026/matches"

MAX_MATCHES = 15
HEADLESS = False

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
    "Cape Verde Islands": "Cape Verde",
    "Congo DR": "DR Congo",
}

TEAM_SEARCH_ALIASES = {
    "DR Congo": ["DR Congo", "Congo DR", "Democratic Republic Of Congo", "Democratic Republic of Congo"],
    "Bosnia": ["Bosnia", "Bosnia & Herzegovina", "Bosnia and Herzegovina"],
    "Türkiye": ["Türkiye", "Turkey", "Turkiye"],
    "Czechia": ["Czechia", "Czech Republic"],
    "Curacao": ["Curacao", "Curaçao"],
    "Cape Verde": ["Cape Verde", "Cape Verde Islands"],
    "USA": ["USA", "United States", "United States Of America", "United States of America"],
}

STAT_TARGETS = [
    # heading variants, market name, prop_type, team market?
    (["Total Match Shots", "Match Shots", "Total Shots"], "Match Shots", "match_shots", False),
    (["Total Match Shots On Target", "Match Shots On Target", "Total Shots On Target"], "Match Shots On Target", "match_shots_on_target", False),

    (["Total Team Match Shots", "Team Match Shots", "Team Shots", "Total Team Shots"], None, "team_shots", True),
    (["Total Team Match Shots On Target", "Team Match Shots On Target", "Team Shots On Target", "Total Team Shots On Target"], None, "team_shots_on_target", True),

    (["Match Over/Under Corners", "Total Corners", "Match Corners", "Total Match Corners", "Corners Over/Under", "Total Corners Over/Under", "Match Over/Under Corner"], "Total Corners", "corners", False),
    (["Match Over/Under Cards", "Total Cards", "Match Cards", "Total Match Cards", "Cards Over/Under", "Total Cards Over/Under", "Match Over/Under Card", "Total Booking Points", "Booking Points"], "Total Cards", "cards", False),
]

ALL_STAT_HEADINGS = []
for variants, _, _, _ in STAT_TARGETS:
    ALL_STAT_HEADINGS.extend(variants)


# ── Helpers ──────────────────────────────────────────────────────────────────

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def slugify(s):
    return normalize(s).replace("_", "-")


def canonical_team(s):
    return TEAM_ALIASES.get(clean(s), clean(s))


def team_search_terms(team):
    team = canonical_team(team)
    terms = [team]
    terms.extend(TEAM_SEARCH_ALIASES.get(team, []))

    for canonical, variants in TEAM_SEARCH_ALIASES.items():
        if team == canonical or team in variants:
            terms.append(canonical)
            terms.extend(variants)

    out, seen = [], set()
    for t in terms:
        t = clean(t)
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def is_valid_kickoff_time(t):
    t = clean(t)
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if not m:
        return False
    hh = int(m.group(1))
    mm = int(m.group(2))
    return 0 <= hh <= 23 and 0 <= mm <= 59


def lines_from_text(text):
    return [clean(x) for x in text.splitlines() if clean(x)]


def sel(name, odds, extra=None):
    obj = {
        "selection": clean(name),
        "normalized_selection": normalize(name),
        "odds": clean(odds).upper(),
    }
    if extra:
        obj.update(extra)
    return obj


def mkt(name, selections):
    seen, out = set(), []
    for s in selections:
        key = (
            s.get("selection"),
            s.get("odds"),
            s.get("team"),
            s.get("side"),
            s.get("line"),
            s.get("threshold"),
            s.get("prop_type"),
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


def threshold_to_line(th):
    th = clean(th)
    m = re.match(r"^(\d+)\+$", th)
    if m:
        return str(float(int(m.group(1)) - 0.5)).rstrip("0").rstrip(".")
    m = re.match(r"^Over\s+(\d+(?:\.\d+)?)$", th, re.I)
    if m:
        return m.group(1)
    m = re.match(r"^(\d+(?:\.\d+)?)$", th)
    if m:
        return m.group(1)
    return th


def heading_matches(line, heading):
    return normalize(line) == normalize(heading)


def any_heading_matches(line, headings):
    return any(heading_matches(line, h) for h in headings)


def team_match_token(tok, team):
    tok_l = clean(tok).lower()
    return tok_l in {t.lower() for t in team_search_terms(team)}


# ── Fixture loading / row-click discovery ────────────────────────────────────

def load_moneyline_targets():
    if not MONEYLINES_PATH.exists():
        return []

    try:
        data = json.loads(MONEYLINES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    targets = []
    seen = set()

    for m in data.get("matches", []):
        time_label = clean(m.get("time", ""))

        # Skip live clocks like 61:02.
        if not is_valid_kickoff_time(time_label):
            continue

        home = clean(m.get("home_team") or "")
        away = clean(m.get("away_team") or "")
        match = clean(m.get("match") or "")

        if not home or not away:
            if " v " in match:
                home, away = [clean(x) for x in match.split(" v ", 1)]

        if not home or not away:
            continue

        home = canonical_team(home)
        away = canonical_team(away)
        key = normalize(f"{home} v {away}")

        if key in seen:
            continue

        seen.add(key)
        targets.append({
            "home": home,
            "away": away,
            "name": f"{home} v {away}",
            "date_label": clean(m.get("date_label", "")),
            "time": time_label,
        })

    return targets


def page_has_fixture(page, home, away):
    try:
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body = ""
    lo = clean(body).lower()
    return (
        any(t.lower() in lo for t in team_search_terms(home)) and
        any(t.lower() in lo for t in team_search_terms(away))
    )


def get_visible_fixture_click_candidates(page, home, away):
    home_terms = team_search_terms(home)
    away_terms = team_search_terms(away)

    js = r"""
        ({homeTerms, awayTerms}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const H = homeTerms.map(norm).filter(Boolean);
            const A = awayTerms.map(norm).filter(Boolean);

            const hasAny = (txt, arr) => arr.some(v => txt.includes(v));
            const eqAny = (txt, arr) => arr.some(v => txt === v);

            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 4 && r.height > 4 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.visibility !== 'hidden' && st.display !== 'none';
            };

            const textOf = el => norm(el.innerText || el.textContent || '');

            const nodes = Array.from(document.querySelectorAll('a, button, [role=button], span, div, li, article, section'))
                .filter(visible);

            const candidates = [];

            for (const el of nodes) {
                const t = textOf(el);

                if (!eqAny(t, H)) continue;

                let row = el;
                for (let depth = 0; depth < 9 && row && row !== document.body; depth++, row = row.parentElement) {
                    if (!visible(row)) continue;

                    const rt = textOf(row);
                    if (!hasAny(rt, H) || !hasAny(rt, A)) continue;

                    const r = row.getBoundingClientRect();

                    if (r.height > 280 || r.width > 1450 || rt.length > 950) continue;

                    const er = el.getBoundingClientRect();

                    candidates.push({
                        x: Math.max(8, Math.min(er.left + er.width / 2, window.innerWidth - 8)),
                        y: Math.max(8, Math.min(er.top + er.height / 2, window.innerHeight - 8)),
                        row_x: Math.max(8, Math.min(r.left + Math.min(r.width * 0.30, 320), window.innerWidth - 8)),
                        row_y: Math.max(8, Math.min(r.top + r.height / 2, window.innerHeight - 8)),
                        score: (r.width * r.height) + (rt.length * 20),
                        text: rt.slice(0, 180)
                    });
                    break;
                }
            }

            candidates.sort((a, b) => a.score - b.score);
            return candidates.slice(0, 8);
        }
    """
    try:
        return page.evaluate(js, {"homeTerms": home_terms, "awayTerms": away_terms}) or []
    except Exception:
        return []


def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "Got it", "OK"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(900)
                return
        except Exception:
            pass


def click_tab(page, tab_name):
    try:
        page.evaluate("window.scrollTo(0, 0); document.scrollingElement.scrollTop = 0")
    except Exception:
        pass
    page.wait_for_timeout(350)

    for role in ["link", "button", "tab"]:
        try:
            loc = page.get_by_role(role, name=re.compile(f"^{re.escape(tab_name)}$", re.I))
            if loc.count():
                loc.first.click(timeout=3500)
                page.wait_for_timeout(1800)
                return True
        except Exception:
            pass

    try:
        loc = page.get_by_text(tab_name, exact=True)
        for i in range(min(loc.count(), 8)):
            try:
                item = loc.nth(i)
                item.scroll_into_view_if_needed(timeout=1200)
                box = item.bounding_box()
                if not box or box["width"] <= 4 or box["height"] <= 4 or box["width"] > 280:
                    continue
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.wait_for_timeout(1800)
                return True
            except Exception:
                pass
    except Exception:
        pass

    return False


def close_login_popups(page):
    """Close William Hill login modal if an odds click accidentally opens it."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    except Exception:
        pass

    for pattern in [r"^Close$", r"close", r"×", r"✕", r"X"]:
        try:
            loc = page.get_by_role("button", name=re.compile(pattern, re.I))
            if loc.count():
                loc.first.click(timeout=900)
                page.wait_for_timeout(500)
                return True
        except Exception:
            pass

    js = r"""
        () => {
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 10 && r.height > 10 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.visibility !== 'hidden' && st.display !== 'none';
            };

            const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();

            const nodes = Array.from(document.querySelectorAll('div, section, aside, form'))
                .filter(visible)
                .map(el => ({el, r: el.getBoundingClientRect(), t: text(el)}))
                .filter(x =>
                    x.t.includes('Username') &&
                    x.t.includes('Password') &&
                    (x.t.includes('Log In') || x.t.includes('Login'))
                )
                .sort((a,b) => (a.r.width*a.r.height) - (b.r.width*b.r.height));

            if (!nodes.length) return null;

            const box = nodes[0].r;

            const clickables = Array.from(document.querySelectorAll('button, [role=button], svg, span, div'))
                .filter(visible)
                .map(el => ({el, r: el.getBoundingClientRect(), t: text(el)}))
                .filter(x =>
                    x.r.left >= box.left &&
                    x.r.right <= box.right &&
                    x.r.top >= box.top &&
                    x.r.top <= box.top + Math.min(120, box.height * 0.35) &&
                    x.r.left >= box.left + box.width * 0.65 &&
                    x.r.width <= 90 &&
                    x.r.height <= 90
                )
                .sort((a,b) => (b.r.left + b.r.top) - (a.r.left + a.r.top));

            if (clickables.length) {
                const r = clickables[0].r;
                return {x: r.left + r.width / 2, y: r.top + r.height / 2};
            }

            return {x: box.right - 32, y: box.top + 30};
        }
    """
    try:
        pos = page.evaluate(js)
        if pos:
            page.mouse.click(float(pos["x"]), float(pos["y"]))
            page.wait_for_timeout(700)
            return True
    except Exception:
        pass

    return False


def try_click_candidate(page, cand, home, away, list_url, y):
    click_points = [
        (cand.get("x"), cand.get("y")),
        (cand.get("row_x"), cand.get("row_y")),
    ]

    for x, y_click in click_points:
        if x is None or y_click is None:
            continue

        try:
            page.mouse.click(float(x), float(y_click))
            page.wait_for_timeout(1600)

            if "OB_EV" not in page.url:
                page.mouse.click(float(x), float(y_click))
                page.wait_for_url("**/OB_EV**", timeout=6500)

            page.wait_for_timeout(2200)

            if "OB_EV" in page.url and page_has_fixture(page, home, away):
                return page.url.split("?", 1)[0]

        except Exception:
            pass

        try:
            page.goto(list_url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(1200)
            accept_cookies(page)
            page.evaluate("(y) => { window.scrollTo(0, y); document.scrollingElement.scrollTop = y; }", y)
            page.wait_for_timeout(350)
        except Exception:
            pass

    return ""


def discover_event_url_for_target(page, target):
    home, away = target["home"], target["away"]
    list_url = COMPETITION_URL

    page.goto(list_url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5500)
    accept_cookies(page)

    try:
        page.evaluate("window.scrollTo(0, 0); document.scrollingElement.scrollTop = 0")
        page.wait_for_timeout(700)
    except Exception:
        pass

    for pass_no in range(1, 4):
        try:
            scroll_height = int(page.evaluate("document.scrollingElement.scrollHeight"))
            client_height = int(page.evaluate("document.scrollingElement.clientHeight"))
            max_y = max(scroll_height - client_height, 0)
        except Exception:
            max_y = 10000

        positions = list(range(0, max_y + 1, 140))
        if max_y not in positions:
            positions.append(max_y)

        for y in positions:
            try:
                page.evaluate("(y) => { window.scrollTo(0, y); document.scrollingElement.scrollTop = y; }", y)
            except Exception:
                page.mouse.wheel(0, 650)
            page.wait_for_timeout(320)

            cands = get_visible_fixture_click_candidates(page, home, away)
            if not cands:
                continue

            print(f"    visible candidates for {home} v {away} at y={y}: {len(cands)}")
            for cand in cands:
                url = try_click_candidate(page, cand, home, away, list_url, y)
                if url:
                    print(f"  ✓ found {home} v {away}: {url}")
                    return url

    print(f"  - could not discover event URL for {home} v {away}")
    return ""


def get_match_links(page):
    print(f"Opening: {COMPETITION_URL}")

    targets = load_moneyline_targets()
    print(f"  valid moneyline targets loaded: {len(targets)}")

    if not targets:
        print("  No valid moneyline targets found. Run fetch_williamhill_worldcup_moneylines.py first.")
        return []

    fixtures = []
    seen_urls = set()

    for target in targets:
        if len(fixtures) >= MAX_MATCHES:
            break

        url = discover_event_url_for_target(page, target)
        if not url or url in seen_urls:
            continue

        seen_urls.add(url)
        fixtures.append({
            "url": url,
            "name": target["name"],
            "home": target["home"],
            "away": target["away"],
        })

    print(f"Found {len(fixtures)} fixtures")
    return fixtures[:MAX_MATCHES]


# ── Page interaction for stats area ──────────────────────────────────────────

def scroll_page(page, steps=10):
    for _ in range(steps):
        try:
            page.mouse.wheel(0, 700)
        except Exception:
            pass
        page.wait_for_timeout(250)


def click_all_show_more(page, max_clicks=20):
    for _ in range(max_clicks):
        clicked = False
        for label in ["Show More", "Show more", "See more", "View more"]:
            try:
                loc = page.get_by_text(label, exact=True)
                if loc.count() > 0:
                    item = loc.first
                    item.scroll_into_view_if_needed(timeout=1000)
                    item.click(timeout=1000)
                    page.wait_for_timeout(300)
                    clicked = True
                    break
            except Exception:
                pass
        if not clicked:
            break


def click_tab(page, tab_name):
    try:
        page.evaluate("window.scrollTo(0, 0); document.scrollingElement.scrollTop = 0")
    except Exception:
        pass
    page.wait_for_timeout(300)

    for role in ["link", "button", "tab"]:
        try:
            loc = page.get_by_role(role, name=re.compile(f"^{re.escape(tab_name)}$", re.I))
            if loc.count():
                loc.first.click(timeout=3500)
                page.wait_for_timeout(1600)
                return True
        except Exception:
            pass

    try:
        loc = page.get_by_text(tab_name, exact=True)
        for i in range(min(loc.count(), 8)):
            try:
                item = loc.nth(i)
                item.scroll_into_view_if_needed(timeout=1200)
                box = item.bounding_box()
                if not box or box["width"] <= 4 or box["height"] <= 4 or box["width"] > 280:
                    continue
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.wait_for_timeout(1600)
                return True
            except Exception:
                pass
    except Exception:
        pass

    return False


def scroll_heading_into_view(page, heading):
    js = r"""
        (heading) => {
            const target = (heading || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();
            const low = s => norm(s).toLowerCase();

            const all = Array.from(document.querySelectorAll('span, div, button, [role=button], h2, h3, p'));

            let matches = [];
            for (const el of all) {
                const txt = norm(el.innerText || el.textContent || '');
                const ltxt = txt.toLowerCase();

                if (!ltxt) continue;
                if (ltxt !== target && !ltxt.includes(target)) continue;
                if (txt.length > 260) continue;
                matches.push(el);
            }

            matches.sort((a, b) => {
                const at = low(a.innerText || a.textContent || '');
                const bt = low(b.innerText || b.textContent || '');
                const ae = at === target ? 0 : 1;
                const be = bt === target ? 0 : 1;
                if (ae !== be) return ae - be;
                return at.length - bt.length;
            });

            for (const el of matches.slice(0, 12)) {
                try { el.scrollIntoView({behavior:'instant', block:'center', inline:'nearest'}); }
                catch(e) { try { el.scrollIntoView(false); } catch(e2) {} }

                const r = el.getBoundingClientRect();
                if (r.bottom > 0 && r.top < window.innerHeight) {
                    return {found: true, y: window.scrollY, text: norm(el.innerText || el.textContent || '').slice(0, 160)};
                }
            }

            return {found:false, y: window.scrollY};
        }
    """
    try:
        res = page.evaluate(js, heading)
        page.wait_for_timeout(500)
        return bool(res and res.get("found"))
    except Exception:
        return False


def find_heading_clicks(page, heading):
    """Scroll heading into view then return candidate click points for the plus row."""
    js = r"""
        (heading) => {
            const target = (heading || '').replace(/\s+/g, ' ').trim().toLowerCase();

            const norm = s => (s || '').replace(/\s+/g, ' ').trim();

            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 4 && r.height > 4 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.visibility !== 'hidden' && st.display !== 'none';
            };

            const nodes = Array.from(document.querySelectorAll('span, div, button, [role=button], h2, h3, p'))
                .filter(visible);

            let rows = [];

            for (const el of nodes) {
                const txt = norm(el.innerText || el.textContent || '');
                const ltxt = txt.toLowerCase();

                if (!ltxt) continue;
                if (ltxt !== target && !ltxt.includes(target)) continue;
                if (txt.length > 260) continue;

                let row = el;
                for (let d = 0; d < 10 && row && row !== document.body; d++, row = row.parentElement) {
                    if (!visible(row)) continue;

                    const rt = norm(row.innerText || row.textContent || '');
                    const rlow = rt.toLowerCase();
                    const r = row.getBoundingClientRect();

                    if (!rlow.includes(target)) continue;
                    if (r.width < 350 || r.height < 22 || r.height > 130) continue;
                    if (rt.length > 280) continue;

                    rows.push({
                        x: Math.max(8, Math.min(r.right - 28, window.innerWidth - 8)),
                        y: Math.max(8, Math.min(r.top + r.height / 2, window.innerHeight - 8)),
                        x_left: Math.max(8, Math.min(r.left + 40, window.innerWidth - 8)),
                        y_left: Math.max(8, Math.min(r.top + r.height / 2, window.innerHeight - 8)),
                        score: r.width * r.height + rt.length,
                        text: rt.slice(0, 180)
                    });
                    break;
                }
            }

            rows.sort((a, b) => a.score - b.score);
            return rows.slice(0, 3);
        }
    """
    try:
        return page.evaluate(js, heading) or []
    except Exception:
        return []


def click_accordion_heading(page, heading):
    # First scroll the exact heading into view.
    scroll_heading_into_view(page, heading)

    for cand in find_heading_clicks(page, heading):
        for x_key, y_key in [("x", "y"), ("x_left", "y_left")]:
            try:
                page.mouse.click(float(cand[x_key]), float(cand[y_key]))
                page.wait_for_timeout(850)
                return True
            except Exception:
                pass
    return False


def get_section_bounds_for_heading(page, heading):
    """Find the visible accordion row for heading and estimate the opened content bounds."""
    js = r"""
        (heading) => {
            const target = (heading || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();

            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 4 && r.height > 4 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.visibility !== 'hidden' && st.display !== 'none';
            };

            const nodes = Array.from(document.querySelectorAll('span, div, button, [role=button], h2, h3, p'))
                .filter(visible);

            let best = null;

            for (const el of nodes) {
                const txt = norm(el.innerText || el.textContent || '');
                const ltxt = txt.toLowerCase();

                if (ltxt !== target && !ltxt.includes(target)) continue;
                if (txt.length > 260) continue;

                let row = el;
                for (let d = 0; d < 10 && row && row !== document.body; d++, row = row.parentElement) {
                    if (!visible(row)) continue;

                    const rt = norm(row.innerText || row.textContent || '');
                    const rlow = rt.toLowerCase();
                    const r = row.getBoundingClientRect();

                    if (!rlow.includes(target)) continue;
                    if (r.width < 350 || r.height < 22 || r.height > 130) continue;
                    if (rt.length > 280) continue;

                    const score = r.width * r.height + rt.length;
                    if (!best || score < best.score) {
                        best = {
                            left: r.left,
                            right: r.right,
                            top: r.top,
                            bottom: r.bottom,
                            width: r.width,
                            height: r.height,
                            score,
                            text: rt.slice(0, 160)
                        };
                    }
                    break;
                }
            }

            return best;
        }
    """
    try:
        return page.evaluate(js, heading)
    except Exception:
        return None


def click_visible_team_tab(page, team, heading=""):
    """Click a real visible team tab inside an opened team stat accordion.

    V7: no false-positive positional fallback. If the section did not actually
    open, this returns False so the caller can retry opening the accordion.
    """
    terms = team_search_terms(team)

    if heading:
        scroll_heading_into_view(page, heading)
        page.wait_for_timeout(250)

    js_textnode = r"""
        ({terms}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();
            const lows = terms.map(t => norm(t).toLowerCase());

            const visibleEl = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 8 && r.height > 8 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.visibility !== 'hidden' && st.display !== 'none';
            };

            const textEqualsTeam = txt => lows.some(t => norm(txt).toLowerCase() === t);

            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let n;
            const cands = [];

            while (n = walker.nextNode()) {
                const txt = norm(n.textContent || '');
                if (!textEqualsTeam(txt)) continue;

                let el = n.parentElement;
                if (!visibleEl(el)) continue;

                // Walk upward to the smallest clickable/team-tab area.
                let best = null;
                for (let d = 0; d < 8 && el && el !== document.body; d++, el = el.parentElement) {
                    if (!visibleEl(el)) continue;

                    const r = el.getBoundingClientRect();
                    const etxt = norm(el.innerText || el.textContent || '');

                    // Team tabs are in the opened accordion: wide-ish, shallow-ish.
                    if (r.width < 25 || r.height < 14 || r.height > 90) continue;
                    if (etxt.length > 140) continue;

                    const clickable = el.closest('button, [role=button]') || el;
                    const cr = clickable.getBoundingClientRect();

                    best = {
                        x: Math.max(8, Math.min(cr.left + cr.width / 2, window.innerWidth - 8)),
                        y: Math.max(8, Math.min(cr.top + cr.height / 2, window.innerHeight - 8)),
                        score: Math.abs(cr.top - window.innerHeight * 0.42) + cr.width * cr.height * 0.001,
                        text: etxt.slice(0, 120)
                    };
                    break;
                }

                if (best) cands.push(best);
            }

            cands.sort((a,b) => a.score - b.score);
            return cands.slice(0, 8);
        }
    """

    try:
        cands = page.evaluate(js_textnode, {"terms": terms}) or []
    except Exception:
        cands = []

    for cand in cands:
        try:
            page.mouse.click(float(cand["x"]), float(cand["y"]))
            page.wait_for_timeout(900)
            close_login_popups(page)
            return True
        except Exception:
            pass

    return False



def open_single_market(page, heading):
    """Open one accordion and leave it in view."""
    ok = click_accordion_heading(page, heading)
    close_login_popups(page)
    print(f"      {'clicked' if ok else 'missed '} {heading}")
    click_all_show_more(page, max_clicks=3)
    close_login_popups(page)
    return ok


def prepare_popular_page(page):
    if click_tab(page, "Popular"):
        print("      ✓ Popular tab")
    else:
        print("      - Popular tab not found/default assumed")

    # Important: scroll headings into view by exact DOM node, not body text.
    scroll_heading_into_view(page, "Team Performance")

# ── Parsing ──────────────────────────────────────────────────────────────────

def text_after_heading_lines(text, headings, max_lines=120):
    """Return the best expanded block after a heading.

    William Hill can include the same heading text more than once in body text
    after accordion clicks. The earlier version used the first occurrence, which
    could be the collapsed/no-rows copy. This version checks every occurrence and
    returns the block with the most odds, which is usually the opened/active tab.
    """
    lines = lines_from_text(text)

    candidates = []

    for idx, line in enumerate(lines):
        if not any_heading_matches(line, headings):
            continue

        block = []
        for j in range(idx + 1, min(idx + max_lines, len(lines))):
            tok = clean(lines[j])
            if not tok:
                continue

            # Stop at the next stat heading, but allow the current heading to
            # repeat once due WH duplicate DOM text.
            if j > idx + 2 and any_heading_matches(tok, ALL_STAT_HEADINGS):
                if not any_heading_matches(tok, headings):
                    break

            if tok in {"Football Betting at William Hill", "Betting with William Hill", "Back To Top"}:
                break

            block.append(tok)

        odds_count = sum(1 for x in block if is_odds(x))
        over_count = sum(1 for x in block if clean(x).lower().startswith("over "))
        candidates.append((odds_count, over_count, len(block), block))

    if not candidates:
        return []

    candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return candidates[0][3]



def parse_ou_block(block, market_name, prop_type, team=None, side=None):
    selections = []
    i = 0

    while i < len(block):
        label = clean(block[i])

        # Ignore team tab labels.
        if team and team_match_token(label, team):
            i += 1
            continue

        # Standard WH labels and extended labels:
        #   Over 8
        #   Over 8.5
        #   Over 8 Corners
        #   Over 3.5 Cards
        #   Under 8.5 Total Corners
        over_match = re.match(r"^Over\s+(\d+(?:\.\d+)?)(?:\s+.*)?$", label, re.I)
        under_match = re.match(r"^Under\s+(\d+(?:\.\d+)?)(?:\s+.*)?$", label, re.I)

        # Two-column WH grid:
        #   Over 4.5
        #   Under 4.5
        #   1/33
        #   10/1
        if over_match and i + 3 < len(block):
            next_under = re.match(r"^Under\s+(\d+(?:\.\d+)?)(?:\s+.*)?$", clean(block[i + 1]), re.I)
            if next_under and next_under.group(1) == over_match.group(1):
                if is_odds(block[i + 2]) and is_odds(block[i + 3]):
                    line = over_match.group(1)
                    extra_o = {"side": "over", "line": line, "prop_type": prop_type}
                    extra_u = {"side": "under", "line": line, "prop_type": prop_type}
                    if team:
                        extra_o.update({"team": team, "team_side": side})
                        extra_u.update({"team": team, "team_side": side})
                    selections.append(sel(f"{team + ' ' if team else ''}Over {line}", block[i + 2], extra_o))
                    selections.append(sel(f"{team + ' ' if team else ''}Under {line}", block[i + 3], extra_u))
                    i += 4
                    continue

        if over_match and i + 1 < len(block) and is_odds(block[i + 1]):
            line = over_match.group(1)
            extra = {"side": "over", "line": line, "prop_type": prop_type}
            if team:
                extra.update({"team": team, "team_side": side})
            selections.append(sel(f"{team + ' ' if team else ''}Over {line}", block[i + 1], extra))
            i += 2
            continue

        if under_match and i + 1 < len(block) and is_odds(block[i + 1]):
            line = under_match.group(1)
            extra = {"side": "under", "line": line, "prop_type": prop_type}
            if team:
                extra.update({"team": team, "team_side": side})
            selections.append(sel(f"{team + ' ' if team else ''}Under {line}", block[i + 1], extra))
            i += 2
            continue

        # Threshold ladder: 10+ then odds.
        if re.match(r"^\d+\+$", label) and i + 1 < len(block) and is_odds(block[i + 1]):
            extra = {"threshold": label, "line": threshold_to_line(label), "prop_type": prop_type}
            if team:
                extra.update({"team": team, "team_side": side})
            selections.append(sel(f"{team + ' ' if team else ''}{label}", block[i + 1], extra))
            i += 2
            continue

        # Numeric line + one odds: 8, 8/15 => Over 8.
        if re.match(r"^\d+(?:\.\d+)?$", label) and i + 1 < len(block) and is_odds(block[i + 1]):
            line = label
            extra = {"side": "over", "line": line, "prop_type": prop_type}
            if team:
                extra.update({"team": team, "team_side": side})
            selections.append(sel(f"{team + ' ' if team else ''}Over {line}", block[i + 1], extra))
            i += 2
            continue

        # Over/Under table fallback:
        #   8.5
        #   Over
        #   Under
        #   5/6
        #   5/6
        if re.match(r"^\d+(?:\.\d+)?$", label) and i + 4 < len(block):
            if clean(block[i + 1]).lower() == "over" and clean(block[i + 2]).lower() == "under":
                if is_odds(block[i + 3]) and is_odds(block[i + 4]):
                    line = label
                    extra_o = {"side": "over", "line": line, "prop_type": prop_type}
                    extra_u = {"side": "under", "line": line, "prop_type": prop_type}
                    if team:
                        extra_o.update({"team": team, "team_side": side})
                        extra_u.update({"team": team, "team_side": side})
                    selections.append(sel(f"{team + ' ' if team else ''}Over {line}", block[i + 3], extra_o))
                    selections.append(sel(f"{team + ' ' if team else ''}Under {line}", block[i + 4], extra_u))
                    i += 5
                    continue

        i += 1

    return selections


def parse_market_from_text(text, headings, market_name, prop_type, team=None, side=None):
    block = text_after_heading_lines(text, headings, max_lines=140)
    sels = parse_ou_block(block, market_name, prop_type, team=team, side=side)

    # Extra fallback for team SOT/shot sections: sometimes the active rows are
    # captured slightly after the first best block. Scan every matching heading
    # and keep the largest parsed result.
    if not sels:
        lines = lines_from_text(text)
        best = []
        for idx, line in enumerate(lines):
            if not any_heading_matches(line, headings):
                continue
            b = []
            for j in range(idx + 1, min(idx + 140, len(lines))):
                tok = clean(lines[j])
                if not tok:
                    continue
                if j > idx + 2 and any_heading_matches(tok, ALL_STAT_HEADINGS):
                    if not any_heading_matches(tok, headings):
                        break
                b.append(tok)
            cand = parse_ou_block(b, market_name, prop_type, team=team, side=side)
            if len(cand) > len(best):
                best = cand
        sels = best

    return mkt(market_name, sels)


def save_hits(debug_file, text):
    hit_file = debug_file.with_name(debug_file.stem + "_hits.txt")
    words = [
        "Team Performance",
        "Total Match Shots",
        "Total Team Match Shots",
        "Total Match Shots On Target",
        "Total Team Match Shots On Target",
        "Total Corners",
        "Match Corners",
        "Total Cards",
        "Match Cards",
        "Shots On Target",
        "Shots",
        "Corners",
        "Cards",
        "Over",
        "Under",
    ]

    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if any(w.lower() in line.lower() for w in words):
            hits.append(f"{i + 1}: {line}")
            for j in range(i + 1, min(i + 20, len(lines))):
                if clean(lines[j]):
                    hits.append(f"    {j + 1}: {lines[j]}")
            hits.append("")

    hit_file.write_text("\n".join(hits), encoding="utf-8")

# ── Scrape one match ─────────────────────────────────────────────────────────



def click_inner_match_subtab(page):
    """Force the opened Corners/Cards accordion onto the inner 'Match' sub-tab.

    WH keeps Match / 1st Half / 2nd Half inside the market. If we don't force
    Match, the body text can include or prefer half-market rows, causing lines
    like corners 0.5/1.5 or cards 0.5 with wrong odds.
    """
    js = r"""
        () => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();

            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 25 && r.height > 12 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.visibility !== 'hidden' && st.display !== 'none';
            };

            const nodes = Array.from(document.querySelectorAll('button, [role=tab], [role=button], div, span'))
                .filter(visible);

            const cands = [];

            for (const el of nodes) {
                const txt = norm(el.innerText || el.textContent || '');
                if (txt !== 'Match') continue;

                let clickEl = el.closest('button, [role=tab], [role=button]') || el;
                if (!visible(clickEl)) continue;

                const r = clickEl.getBoundingClientRect();

                // Avoid breadcrumb / fixture title / top nav. The inner sub-tab is
                // normally in the white opened market area around the middle of viewport.
                if (r.top < 250) continue;
                if (r.width < 40 || r.width > 700) continue;
                if (r.height < 18 || r.height > 80) continue;

                cands.push({
                    x: Math.max(8, Math.min(r.left + r.width / 2, window.innerWidth - 8)),
                    y: Math.max(8, Math.min(r.top + r.height / 2, window.innerHeight - 8)),
                    score: Math.abs(r.top - window.innerHeight * 0.55) + r.width * 0.002,
                    text: txt,
                    top: r.top,
                    width: r.width
                });
            }

            cands.sort((a, b) => a.score - b.score);
            return cands.slice(0, 6);
        }
    """

    try:
        cands = page.evaluate(js) or []
    except Exception:
        cands = []

    for cand in cands:
        try:
            page.mouse.click(float(cand["x"]), float(cand["y"]))
            page.wait_for_timeout(900)
            close_login_popups(page)
            return True
        except Exception:
            pass

    return False


def min_full_match_line(prop_type):
    if prop_type == "corners":
        return 4.5
    if prop_type == "cards":
        return 1.5
    return None


def parse_tab_ou_market_from_text(text, headings, market_name, prop_type):
    """Special parser for WH top Corners/Cards tabs.

    We choose the candidate heading block that looks like the FULL MATCH tab,
    not 1st half / 2nd half. This avoids incorrect rows such as:
      corners Over 0.5 / 1.5
      cards Over 0.5
    """
    lines = lines_from_text(text)
    min_line = min_full_match_line(prop_type)

    candidates = []

    for idx, line in enumerate(lines):
        if not any_heading_matches(line, headings):
            continue

        block = []
        for j in range(idx + 1, min(idx + 110, len(lines))):
            tok = clean(lines[j])
            if not tok:
                continue

            # Stop at another major market heading.
            if j > idx + 8 and any_heading_matches(tok, ALL_STAT_HEADINGS):
                if not any_heading_matches(tok, headings):
                    break

            if tok in {"Football Betting at William Hill", "Betting with William Hill", "Back To Top"}:
                break

            block.append(tok)

        sels = parse_ou_block(block, market_name, prop_type)
        if not sels:
            continue

        kept = []
        low_count = 0

        for s in sels:
            try:
                line_val = float(clean(s.get("line", "")))
            except Exception:
                kept.append(s)
                continue

            if min_line is not None and line_val < min_line:
                low_count += 1
                continue

            kept.append(s)

        if not kept:
            continue

        # Prefer blocks with no half-market low lines, then more useful rows.
        candidates.append({
            "score": (1 if low_count == 0 else 0, len(kept), -low_count, -len(block)),
            "sels": kept,
            "block": block,
            "low_count": low_count,
        })

    if not candidates:
        return parse_market_from_text(text, headings, market_name, prop_type)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return mkt(market_name, candidates[0]["sels"])






def click_inner_match_by_heading_position(page, heading_candidates):
    """Click the inner Match sub-tab by coordinates relative to the open market heading."""
    js = r"""
        ({headings}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();
            const shown = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 5 && r.height > 5 &&
                       st.visibility !== 'hidden' &&
                       st.display !== 'none' &&
                       st.opacity !== '0' &&
                       r.bottom > 0 && r.top < window.innerHeight;
            };

            const hNorms = (headings || []).map(h => norm(h).toLowerCase());
            const all = Array.from(document.querySelectorAll('button, [role=button], [role=tab], div, span, p'));

            const hs = [];
            for (const el of all) {
                if (!shown(el)) continue;
                const txt = norm(el.innerText || el.textContent || '');
                if (!txt || txt.length > 80 || txt.includes('\n')) continue;
                if (!hNorms.includes(txt.toLowerCase())) continue;
                const r = el.getBoundingClientRect();
                hs.push({left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width, height:r.height});
            }

            if (!hs.length) return null;

            hs.sort((a,b) => b.top - a.top);
            const h = hs[0];

            // Inner Match tab is normally 45-80px under the heading and in the
            // left third of the white market panel.
            return {
                x: Math.max(10, Math.min(h.left + 260, window.innerWidth - 10)),
                y: Math.max(10, Math.min(h.bottom + 50, window.innerHeight - 10)),
                headingTop: h.top,
                headingBottom: h.bottom
            };
        }
    """
    try:
        pt = page.evaluate(js, {"headings": heading_candidates})
    except Exception:
        pt = None

    if not pt:
        return False

    try:
        page.mouse.click(float(pt["x"]), float(pt["y"]))
        page.wait_for_timeout(1000)
        close_login_popups(page)
        return True
    except Exception:
        return False

def extract_visible_ou_grid_by_position(page, heading_candidates, market_name, prop_type):
    """Parse WH Cards/Corners by screen position instead of body text order.

    WH lays out these markets as two columns. Body inner_text can return labels
    and odds in a weird order, which swaps/duplicates the prices. Bounding boxes
    let us pair each Over/Under label with the odds directly underneath it in the
    same column.
    """
    min_line = min_full_match_line(prop_type)

    js = r"""
        ({headings}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();

            const topMost = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const x = Math.max(2, Math.min(r.left + r.width / 2, window.innerWidth - 2));
                const y = Math.max(2, Math.min(r.top + r.height / 2, window.innerHeight - 2));
                const hit = document.elementFromPoint(x, y);
                return hit && (hit === el || el.contains(hit) || hit.contains(el));
            };

            const shown = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 8 && r.height > 6 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.visibility !== 'hidden' &&
                       st.display !== 'none' &&
                       st.opacity !== '0' &&
                       topMost(el);
            };

            const all = Array.from(document.querySelectorAll('button, [role=button], [role=tab], div, span, p'));

            // Find the opened target heading. Prefer exact/small text nodes, not giant parent containers.
            let headingTop = 0;
            let headingBottom = 0;
            const hNorms = (headings || []).map(h => norm(h).toLowerCase());

            const headingEls = [];
            for (const el of all) {
                if (!shown(el)) continue;
                const txt = norm(el.innerText || el.textContent || '');
                if (!txt || txt.length > 80 || txt.includes('\n')) continue;
                if (hNorms.includes(txt.toLowerCase())) {
                    const r = el.getBoundingClientRect();
                    headingEls.push({top: r.top, bottom: r.bottom, width: r.width, height: r.height, txt});
                }
            }

            if (headingEls.length) {
                // Prefer the lower matching heading if duplicate collapsed/opened headings exist.
                headingEls.sort((a, b) => b.top - a.top);
                headingTop = headingEls[0].top;
                headingBottom = headingEls[0].bottom;
            }

            const items = [];
            for (const el of all) {
                if (!shown(el)) continue;

                const txt = norm(el.innerText || el.textContent || '');
                if (!txt || txt.length > 30 || txt.includes('\n')) continue;

                const isLabel = /^(Over|Under)\s+\d+(?:\.\d+)?(?:\s+.*)?$/i.test(txt);
                const isOdd = /^(?:\d+\/\d+|EVS|EVENS|EVEN|Evens)$/i.test(txt);
                if (!isLabel && !isOdd) continue;

                const r = el.getBoundingClientRect();

                // Restrict to rows after target heading. Allow off-screen rows too.
                if (headingBottom && r.top < headingBottom - 2) continue;
                if (headingBottom && r.top > headingBottom + 1800) continue;

                // Remove giant wrappers/containers.
                if (r.width > 900 || r.height > 90) continue;

                items.push({
                    text: txt,
                    type: isLabel ? 'label' : 'odds',
                    left: r.left,
                    right: r.right,
                    top: r.top,
                    bottom: r.bottom,
                    width: r.width,
                    height: r.height,
                    cx: r.left + r.width / 2,
                    cy: r.top + r.height / 2
                });
            }

            // Dedupe near-identical text boxes.
            const seen = new Set();
            const deduped = [];
            for (const it of items) {
                const key = [
                    it.text.toLowerCase(),
                    Math.round(it.left / 4),
                    Math.round(it.top / 4),
                    it.type
                ].join('|');
                if (seen.has(key)) continue;
                seen.add(key);
                deduped.push(it);
            }

            return deduped;
        }
    """

    try:
        items = page.evaluate(js, {"headings": heading_candidates}) or []
    except Exception:
        items = []

    labels = []
    odds = []

    for it in items:
        txt = clean(it.get("text", ""))
        if re.match(r"^(Over|Under)\s+\d+(?:\.\d+)?", txt, re.I):
            m = re.match(r"^(Over|Under)\s+(\d+(?:\.\d+)?)", txt, re.I)
            if not m:
                continue
            side = m.group(1).lower()
            line = m.group(2)
            try:
                line_val = float(line)
            except Exception:
                continue

            if min_line is not None and line_val < min_line:
                continue

            labels.append({
                **it,
                "side": side,
                "line": line,
                "line_val": line_val,
            })
        elif is_odds(txt):
            odds.append(it)

    if not labels or not odds:
        return mkt(market_name, [])

    selections = []
    used_odds = set()

    labels.sort(key=lambda x: (float(x["top"]), float(x["left"])))

    for lab in labels:
        best = None
        best_score = None

        for oi, od in enumerate(odds):
            # Allow the same odds text to appear elsewhere, but don't use the exact same box twice.
            if oi in used_odds:
                continue

            dy = float(od["cy"]) - float(lab["cy"])
            if dy <= 3 or dy > 95:
                continue

            dx = abs(float(od["cx"]) - float(lab["cx"]))
            if dx > 180:
                continue

            # Strongly prefer same column and nearest row below.
            score = dy + dx * 0.55

            if best is None or score < best_score:
                best = (oi, od)
                best_score = score

        if best is None:
            continue

        oi, od = best
        used_odds.add(oi)

        line = clean(lab["line"])
        side = clean(lab["side"])

        selections.append(sel(
            f"{side.title()} {line}",
            od["text"],
            {"side": side, "line": line, "prop_type": prop_type}
        ))

    # Some WH pages render duplicate label/odds boxes from sticky/virtualized DOM.
    # Keep the shortest sensible list by unique side+line. If duplicates remain,
    # keep the first positional pair.
    final = []
    seen_lines = set()
    for s in selections:
        k = (s.get("side"), s.get("line"))
        if k in seen_lines:
            continue
        seen_lines.add(k)
        final.append(s)

    return mkt(market_name, final)


def scrape_tab_market(page, tab_name, heading_candidates, market_name, prop_type, debug_chunks):
    """Click a top WH tab, open target market, force inner Match tab, and parse by DOM position."""
    clicked_tab = click_tab(page, tab_name)
    print(f"      {'✓' if clicked_tab else '-'} {tab_name} tab")

    if not clicked_tab:
        return None

    close_login_popups(page)

    for heading in heading_candidates:
        ok = open_single_market(page, heading)
        if not ok:
            continue

        close_login_popups(page)

        if click_inner_match_by_heading_position(page, heading_candidates):
            print(f"        clicked inner Match tab by position for {heading}")
        elif click_inner_match_subtab(page):
            print(f"        clicked inner Match tab for {heading}")

        # Position-based parser first. This fixes WH two-column text-order issues
        # where body.inner_text swaps Over/Under odds.
        m_pos = extract_visible_ou_grid_by_position(page, heading_candidates, market_name, prop_type)

        try:
            text = page.locator("body").inner_text(timeout=18000)
        except Exception:
            text = ""

        debug_chunks.append(f"\n\n=== TAB {tab_name} / {heading} / INNER MATCH ===\n{text}")

        if m_pos["selection_count"] > 0:
            return m_pos

        # Do not text-fallback for Cards/Corners because WH text order includes
        # hidden/half-tab rows and causes wrong odds. Better to miss than publish bad prices.
        if prop_type not in {"cards", "corners"}:
            m = parse_tab_ou_market_from_text(text, heading_candidates, market_name, prop_type)
            if m["selection_count"] > 0:
                return m

    return None


def scrape_match_stats(page, fixture):
    url = fixture["url"]
    name = fixture["name"]
    home = fixture.get("home") or ""
    away = fixture.get("away") or ""

    if not home or not away:
        if " v " in name:
            home, away = [canonical_team(x) for x in name.split(" v ", 1)]

    print(f"  Scraping stats: {name}")
    print(f"  URL: {url}")

    page.goto(url, wait_until="domcontentloaded", timeout=70000)
    page.wait_for_timeout(5500)
    accept_cookies(page)
    close_login_popups(page)

    prepare_popular_page(page)

    markets = []
    debug_chunks = []

    # Match-level sections.
    match_sections = [
        ("Total Match Shots", ["Total Match Shots", "Match Shots", "Total Shots"], "Match Shots", "match_shots"),
        ("Total Match Shots On Target", ["Total Match Shots On Target", "Match Shots On Target", "Total Shots On Target"], "Match Shots On Target", "match_shots_on_target"),
    ]

    for heading, variants, market_name, prop_type in match_sections:
        ok = open_single_market(page, heading)
        try:
            text = page.locator("body").inner_text(timeout=18000)
        except Exception:
            text = ""
        debug_chunks.append(f"\n\n=== {heading} ===\n{text}")

        if ok:
            m = parse_market_from_text(text, variants, market_name, prop_type)
            if m["selection_count"] > 0:
                markets.append(m)

    # Corners/Cards live on their own top tabs, not the lower Popular stat area.
    corners_market = scrape_tab_market(
        page,
        "Corners",
        ["Match Over/Under Corners", "Total Corners", "Match Corners", "Total Match Corners", "Corners Over/Under", "Total Corners Over/Under"],
        "Total Corners",
        "corners",
        debug_chunks,
    )
    if corners_market and corners_market["selection_count"] > 0:
        markets.append(corners_market)

    cards_market = scrape_tab_market(
        page,
        "Cards",
        ["Match Over/Under Cards", "Total Cards", "Match Cards", "Total Match Cards", "Cards Over/Under", "Total Cards Over/Under", "Total Booking Points", "Booking Points"],
        "Total Cards",
        "cards",
        debug_chunks,
    )
    if cards_market and cards_market["selection_count"] > 0:
        markets.append(cards_market)

    # Return to Popular before team sections.
    click_tab(page, "Popular")
    close_login_popups(page)

    # Team sections: open once, then click across both team tabs and parse active rows.
    team_sections = [
        (
            "Total Team Match Shots",
            ["Total Team Match Shots", "Team Match Shots", "Team Shots", "Total Team Shots"],
            "Shots",
            "team_shots",
        ),
        (
            "Total Team Match Shots On Target",
            ["Total Team Match Shots On Target", "Team Match Shots On Target", "Team Shots On Target", "Total Team Shots On Target"],
            "Shots On Target",
            "team_shots_on_target",
        ),
    ]

    for heading, variants, base_name, prop_type in team_sections:
        ok = open_single_market(page, heading)
        if not ok:
            continue

        for team, side in [(home, "home"), (away, "away")]:
            market_name = f"{team} {base_name}"
            parsed_market = None
            tab_ok = False

            # Retry a few times because WH sometimes reports the heading in DOM
            # but does not actually open the team-tab panel on the first click.
            for attempt in range(1, 4):
                scroll_heading_into_view(page, heading)

                tab_ok = click_visible_team_tab(page, team, heading=heading)

                if not tab_ok:
                    # Section probably is not open yet. Click accordion again,
                    # then retry the team tab.
                    click_accordion_heading(page, heading)
                    close_login_popups(page)
                    page.wait_for_timeout(900)
                    scroll_heading_into_view(page, heading)
                    tab_ok = click_visible_team_tab(page, team, heading=heading)

                try:
                    text = page.locator("body").inner_text(timeout=18000)
                except Exception:
                    text = ""

                debug_chunks.append(f"\n\n=== {heading} / {team} / attempt {attempt} ===\n{text}")

                m = parse_market_from_text(text, variants, market_name, prop_type, team=team, side=side)

                if tab_ok and m["selection_count"] > 0:
                    parsed_market = m
                    break

                # One more click can open a collapsed SOT accordion without
                # losing the current scroll position.
                click_accordion_heading(page, heading)
                close_login_popups(page)
                page.wait_for_timeout(900)

            print(f"        {'clicked' if tab_ok else 'missed '} {team} tab for {heading}")

            if parsed_market and parsed_market["selection_count"] > 0:
                markets.append(parsed_market)

    # Dedupe by market.
    seen, unique = set(), []
    for m in markets:
        k = m["normalized_market"]
        if k not in seen:
            seen.add(k)
            unique.append(m)

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    full_debug = "\n".join(debug_chunks)
    debug_file.write_text(full_debug, encoding="utf-8")
    save_hits(debug_file, full_debug)

    print(f"  ✓ {home} v {away} — {len(unique)} stat markets")
    for m in unique:
        print(f"      {m['market']:<34} {m['selection_count']} selections")

    return {
        "match": f"{home} v {away}",
        "home_team": home,
        "away_team": away,
        "url": url,
        "market_count": len(unique),
        "markets": unique,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("William Hill World Cup Match/Team Stats Scraper")
    print("TEST MODE: MAX_MATCHES = 3")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        fixtures = get_match_links(page)

        results = []
        for i, fixture in enumerate(fixtures, 1):
            print("\n" + "=" * 60)
            print(f"[{i}/{len(fixtures)}]")
            try:
                results.append(scrape_match_stats(page, fixture))
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"  ⚠ Error: {type(e).__name__}: {e}")
                results.append({
                    "match": fixture.get("name", ""),
                    "home_team": fixture.get("home", ""),
                    "away_team": fixture.get("away", ""),
                    "url": fixture.get("url", ""),
                    "market_count": 0,
                    "markets": [],
                    "error": str(e),
                })

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "WilliamHill",
        "source_url": COMPETITION_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches_with_markets": len([r for r in results if r.get("market_count", 0) > 0]),
        "matches": results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved → {OUT_PATH}")
    print("\n── Summary ─────────────────────────────────────────────")
    for r in results:
        print(f"  {r['match']:<40} {r.get('market_count', 0)} stat markets")
    print("─" * 60)


if __name__ == "__main__":
    main()
