#!/usr/bin/env python3
"""
fetch_williamhill_worldcup_cards_corners.py

William Hill World Cup cards/corners scraper.

This is separate on purpose:
  - Corners and Cards live in their own William Hill top tabs.
  - We only scrape:
      Corners -> Match Over/Under Corners
      Cards   -> Match Over/Under Cards

Test mode:
  MAX_MATCHES = 7

Temporary:
  TEMP_SKIP_MATCHES includes Czechia v South Africa because it is currently in-play.
  Remove it later if needed.

Output:
  football/data/williamhill_worldcup_cards_corners.json

Debug:
  football/debug/williamhill_cards_corners/<match>_corners.txt
  football/debug/williamhill_cards_corners/<match>_cards.txt
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

MONEYLINES_PATH = ROOT / "football" / "data" / "williamhill_worldcup_moneylines.json"
OUT_PATH = ROOT / "football" / "data" / "williamhill_worldcup_cards_corners.json"
DEBUG_DIR = ROOT / "football" / "debug" / "williamhill_cards_corners"

MATCHES_LIST_URL = "https://sports.williamhill.com/betting/en-gb/football/competitions/OB_TY52321/world-cup-2026/matches"

MAX_MATCHES = 7
HEADLESS = False

# Keep this while Czechia v South Africa is in-play/live.
TEMP_SKIP_MATCHES = {"Czechia v South Africa"}

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def normalize(s):
    s = clean(s).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def slugify(s):
    return normalize(s).replace("_", "-")


TEAM_ALIASES = {
    "bosnia": "bosnia_and_herzegovina",
    "bosnia_herzegovina": "bosnia_and_herzegovina",
    "bosnia_and_herzegovina": "bosnia_and_herzegovina",
    "czech_republic": "czechia",
    "czechia": "czechia",
    "turkey": "turkiye",
    "türkiye": "turkiye",
    "congo_dr": "dr_congo",
    "dr_congo": "dr_congo",
    "united_states": "usa",
    "usa": "usa",
    "south_korea": "south_korea",
    "south_africa": "south_africa",
}


def norm_team(s):
    n = normalize(s)
    return TEAM_ALIASES.get(n, n)


def match_key_from_names(home, away):
    return f"{norm_team(home)}_v_{norm_team(away)}"


def get_field(obj, *names):
    for n in names:
        v = obj.get(n)
        if v:
            return v
    return ""


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_label(s):
    return bool(re.match(r"^(Over|Under)\s+\d+(?:\.\d+)?$", clean(s), re.I))


def sel(name, odds, side, line, prop_type):
    return {
        "selection": clean(name),
        "normalized_selection": normalize(name),
        "odds": clean(odds).upper(),
        "side": side,
        "line": clean(line),
        "prop_type": prop_type,
    }


def market(name, selections):
    out, seen = [], set()
    for s in selections:
        k = (s["selection"], s["odds"], s["side"], s["line"], s["prop_type"])
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(out),
        "selections": out,
    }


def load_fixtures():
    if not MONEYLINES_PATH.exists():
        raise SystemExit(
            f"Missing moneylines file: {MONEYLINES_PATH}\n"
            "Run: python scripts\\Football\\fetch_williamhill_worldcup_moneylines.py"
        )

    data = json.loads(MONEYLINES_PATH.read_text(encoding="utf-8"))
    rows = data.get("matches", data if isinstance(data, list) else [])

    fixtures = []
    seen = set()

    for m in rows:
        home = get_field(m, "home_team", "home", "home_name")
        away = get_field(m, "away_team", "away", "away_name")
        name = get_field(m, "match", "name", "event_name")

        if not home or not away:
            if " v " in name:
                home, away = [clean(x) for x in name.split(" v ", 1)]
            elif " vs " in name:
                home, away = [clean(x) for x in name.split(" vs ", 1)]

        if not home or not away:
            continue

        match_name = f"{home} v {away}"

        if match_name in TEMP_SKIP_MATCHES:
            continue

        key = match_key_from_names(home, away)
        if key in seen:
            continue
        seen.add(key)

        url = get_field(m, "url", "event_url", "match_url", "href", "source_url")

        fixtures.append({
            "match": match_name,
            "home_team": home,
            "away_team": away,
            "url": url,
        })

        if len(fixtures) >= MAX_MATCHES:
            break

    return fixtures


def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "Got it", "OK"]:
        try:
            loc = page.get_by_role("button", name=re.compile(label, re.I))
            if loc.count():
                loc.first.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def close_popups(page):
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


def click_target_row_from_list(page, fixture):
    home = fixture["home_team"]
    away = fixture["away_team"]

    page.goto(MATCHES_LIST_URL, wait_until="domcontentloaded", timeout=70000)
    page.wait_for_timeout(6000)
    accept_cookies(page)
    close_popups(page)

    js = r"""
        ({home, away}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();

            const alias = s => {
                s = norm(s);
                s = s.replace('bosnia and herzegovina', 'bosnia');
                s = s.replace('bosnia & herzegovina', 'bosnia');
                s = s.replace('czech republic', 'czechia');
                s = s.replace('congo dr', 'dr congo');
                return s;
            };

            const h = alias(home);
            const a = alias(away);

            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 20 && r.height > 15 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.display !== 'none' && st.visibility !== 'hidden';
            };

            const clickable = el => el.closest('a, button, [role=button]') || el;

            const all = Array.from(document.querySelectorAll('a, button, [role=button], div, article, section, li'));
            const cands = [];

            for (const el of all) {
                if (!visible(el)) continue;

                const txt = alias(el.innerText || el.textContent || '');
                if (!txt.includes(h) || !txt.includes(a)) continue;

                const r = el.getBoundingClientRect();
                if (r.height > 260 || r.width > 1400) continue;

                const c = clickable(el);
                const cr = c.getBoundingClientRect();
                if (cr.width < 20 || cr.height < 15) continue;

                cands.push({
                    x: cr.left + Math.min(cr.width * 0.55, cr.width - 8),
                    y: cr.top + cr.height / 2,
                    top: cr.top,
                    height: cr.height,
                    text: (el.innerText || el.textContent || '').slice(0, 250)
                });
            }

            cands.sort((x, y) => x.top - y.top || x.height - y.height);
            return cands[0] || null;
        }
    """

    for scroll_y in [0, 500, 1000, 1500, 2200, 3000, 3800, 4600]:
        page.evaluate("(y) => window.scrollTo(0, y)", scroll_y)
        page.wait_for_timeout(700)

        pt = page.evaluate(js, {"home": home, "away": away})
        if not pt:
            continue

        before = page.url
        page.mouse.click(float(pt["x"]), float(pt["y"]))
        page.wait_for_timeout(3500)

        if page.url != before and "/OB_EV" in page.url:
            return page.url

        if "/OB_EV" in page.url:
            return page.url

    raise RuntimeError(f"Could not row-click target from WH list: {fixture['match']}")


def resolve_event_url(page, fixture):
    url = fixture.get("url", "")

    if url and "/OB_EV" in url:
        return url

    return click_target_row_from_list(page, fixture)


def setup_event(page, event_url):
    page.goto(event_url, wait_until="domcontentloaded", timeout=70000)
    page.wait_for_timeout(5000)
    accept_cookies(page)
    close_popups(page)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)


def click_top_tab(page, tab):
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)

    js = r"""
        ({tab}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();
            const shown = el => {
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 5 && r.height > 5 &&
                       r.bottom > 0 && r.top < window.innerHeight &&
                       st.display !== 'none' && st.visibility !== 'hidden';
            };

            const nodes = Array.from(document.querySelectorAll('button, [role=tab], [role=button], a, div, span'));
            const cands = [];

            for (const el of nodes) {
                if (!shown(el)) continue;

                const txt = norm(el.innerText || el.textContent || '');
                if (txt !== tab) continue;

                const r = el.getBoundingClientRect();
                if (r.top < 180 || r.top > 500) continue;

                cands.push({x:r.left+r.width/2, y:r.top+r.height/2, top:r.top, left:r.left, width:r.width});
            }

            cands.sort((a,b) => (a.top - b.top) || (b.width - a.width));
            return cands[0] || null;
        }
    """

    pt = page.evaluate(js, {"tab": tab})
    if not pt:
        try:
            loc = page.get_by_text(tab, exact=True)
            if loc.count():
                loc.first.click(timeout=2500)
                page.wait_for_timeout(1500)
                close_popups(page)
                return True
        except Exception:
            return False
        return False

    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_timeout(1500)
    close_popups(page)
    return True


def click_exact_heading(page, heading):
    locate_js = r"""
        ({heading}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();
            const styleVisible = el => {
                if (!el) return false;
                const st = getComputedStyle(el);
                return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
            };

            const nodes = Array.from(document.querySelectorAll('button, [role=button], div, span, p'));
            const cands = [];

            for (const el of nodes) {
                if (!styleVisible(el)) continue;

                const txt = norm(el.innerText || el.textContent || '');
                if (txt !== heading) continue;

                let row = el.closest('button, [role=button], [data-testid], div') || el;

                let cur = el;
                for (let i = 0; i < 6 && cur; i++) {
                    const r = cur.getBoundingClientRect();
                    if (r.width > 700 && r.height > 30 && r.height < 90) {
                        row = cur;
                        break;
                    }
                    cur = cur.parentElement;
                }

                const r = row.getBoundingClientRect();
                if (r.width < 300 || r.height < 20) continue;

                cands.push({
                    top: r.top + window.scrollY,
                    bottom: r.bottom + window.scrollY,
                    left: r.left + window.scrollX,
                    right: r.right + window.scrollX,
                    width: r.width,
                    height: r.height,
                    vxLeft: r.left,
                    vxRight: r.right,
                    vy: r.top + r.height / 2
                });
            }

            cands.sort((a,b) => a.top - b.top);
            return cands[0] || null;
        }
    """

    verify_js = r"""
        ({heading}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();
            const styleVisible = el => {
                if (!el) return false;
                const st = getComputedStyle(el);
                return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
            };

            const nodes = Array.from(document.querySelectorAll('div, span, button, [role=button], [role=tab], p'));
            const rows = [];

            const isMarketHeading = txt => {
                const l = txt.toLowerCase();
                if (!txt || txt.length > 90 || txt.includes('\n')) return false;
                if (txt === heading) return true;
                return (
                    l.includes('over/under') ||
                    l.includes('shown a card') ||
                    l.includes('race to') ||
                    l.includes('total') ||
                    l.includes('corners') ||
                    l.includes('cards')
                ) && !/^(over|under)\s+\d/.test(l);
            };

            for (const el of nodes) {
                if (!styleVisible(el)) continue;

                const txt = norm(el.innerText || el.textContent || '');
                if (!isMarketHeading(txt)) continue;

                const r = el.getBoundingClientRect();
                if (r.width < 10 || r.height < 8) continue;

                rows.push({
                    text: txt,
                    top: r.top + window.scrollY,
                    bottom: r.bottom + window.scrollY
                });
            }

            rows.sort((a,b) => a.top - b.top);

            const idx = rows.findIndex(x => x.text === heading);
            if (idx < 0) return {opened:false, gap:0, rows};

            const h = rows[idx];
            const next = rows.slice(idx + 1).find(x => x.top > h.bottom + 2);
            const gap = next ? (next.top - h.bottom) : 999;

            return {opened: gap > 160, gap, heading:h, next, rows};
        }
    """

    row = page.evaluate(locate_js, {"heading": heading})
    if not row:
        return False

    page.evaluate("(y) => window.scrollTo(0, Math.max(0, y - 150))", row["top"])
    page.wait_for_timeout(600)

    row = page.evaluate(locate_js, {"heading": heading})
    if not row:
        return False

    click_points = [
        (row["vxRight"] - 30, row["vy"]),
        (row["vxLeft"] + 45, row["vy"]),
        ((row["vxLeft"] + row["vxRight"]) / 2, row["vy"]),
    ]

    for x, y in click_points:
        try:
            page.mouse.click(float(x), float(y))
            page.wait_for_timeout(1200)
            close_popups(page)

            state = page.evaluate(verify_js, {"heading": heading})
            if state and state.get("opened"):
                return True
        except Exception:
            pass

    try:
        state = page.evaluate(verify_js, {"heading": heading})
        return bool(state and state.get("opened"))
    except Exception:
        return False


def click_inner_match_near_heading(page, heading):
    js = r"""
        ({heading}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();
            const styleVisible = el => {
                if (!el) return false;
                const st = getComputedStyle(el);
                return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
            };

            const nodes = Array.from(document.querySelectorAll('div, span, button, [role=button], [role=tab], p'));
            const heads = [];

            for (const el of nodes) {
                if (!styleVisible(el)) continue;

                const txt = norm(el.innerText || el.textContent || '');
                if (txt !== heading) continue;

                const r = el.getBoundingClientRect();
                if (r.width < 10 || r.height < 8) continue;

                heads.push({top:r.top+window.scrollY, bottom:r.bottom+window.scrollY, left:r.left+window.scrollX});
            }

            heads.sort((a,b) => a.top - b.top);
            const h = heads[0];
            if (!h) return null;

            const matches = [];
            for (const el of nodes) {
                if (!styleVisible(el)) continue;

                const txt = norm(el.innerText || el.textContent || '');
                if (txt !== 'Match') continue;

                let clickEl = el.closest('button, [role=tab], [role=button]') || el;
                const r = clickEl.getBoundingClientRect();
                const top = r.top + window.scrollY;
                const left = r.left + window.scrollX;

                if (top < h.bottom || top > h.bottom + 180) continue;
                if (r.width < 30 || r.height < 10) continue;

                matches.push({
                    x: left + r.width / 2 - window.scrollX,
                    y: top + r.height / 2 - window.scrollY,
                    top: top,
                    left: left,
                    width: r.width
                });
            }

            matches.sort((a,b) => (a.top - b.top) || (b.left - a.left));
            return matches[0] || null;
        }
    """

    pt = page.evaluate(js, {"heading": heading})
    if not pt:
        return False

    page.mouse.click(float(pt["x"]), float(pt["y"]))
    page.wait_for_timeout(1000)
    close_popups(page)
    return True


def token_data_between_heading_and_next_market(page, heading):
    js = r"""
        ({heading}) => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();

            const styleVisible = el => {
                if (!el) return false;
                const st = getComputedStyle(el);
                return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
            };

            const nodes = Array.from(document.querySelectorAll('div, span, button, [role=button], [role=tab], p'));

            const headingCandidates = [];
            const marketHeadingCandidates = [];

            const isMarketHeading = txt => {
                const l = txt.toLowerCase();
                if (!txt || txt.length > 90) return false;
                if (txt === heading) return true;
                return (
                    l.includes('over/under') ||
                    l.includes('shown a card') ||
                    l.includes('race to') ||
                    l.includes('total') ||
                    l.includes('team') ||
                    l.includes('corners') ||
                    l.includes('cards')
                ) && !/^(over|under)\s+\d/.test(l);
            };

            for (const el of nodes) {
                if (!styleVisible(el)) continue;

                const txt = norm(el.innerText || el.textContent || '');
                if (!txt || txt.includes('\n')) continue;

                const r = el.getBoundingClientRect();
                if (r.width < 10 || r.height < 8) continue;

                const item = {
                    text: txt,
                    top: r.top + window.scrollY,
                    bottom: r.bottom + window.scrollY,
                    left: r.left + window.scrollX,
                    width: r.width
                };

                if (txt === heading) headingCandidates.push(item);
                if (isMarketHeading(txt)) marketHeadingCandidates.push(item);
            }

            headingCandidates.sort((a,b) => a.top - b.top);
            const h = headingCandidates[0];
            if (!h) return {heading: null, nextHeading: null, tokens: []};

            const after = marketHeadingCandidates
                .filter(x => x.top > h.bottom + 8 && x.text !== heading)
                .sort((a,b) => a.top - b.top);

            const next = after[0] || {top: h.bottom + 900, text: 'END'};

            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            const tokens = [];
            let node;

            while ((node = walker.nextNode())) {
                const txt = norm(node.nodeValue || '');
                if (!txt || txt.length > 80) continue;

                const parent = node.parentElement;
                if (!styleVisible(parent)) continue;

                const range = document.createRange();
                range.selectNodeContents(node);
                const rects = Array.from(range.getClientRects());
                range.detach();

                for (const r of rects) {
                    if (r.width <= 1 || r.height <= 1) continue;

                    const top = r.top + window.scrollY;
                    const left = r.left + window.scrollX;

                    if (top < h.bottom - 2) continue;
                    if (top >= next.top - 4) continue;

                    tokens.push({
                        text: txt,
                        left: left,
                        top: top,
                        right: r.right + window.scrollX,
                        bottom: r.bottom + window.scrollY,
                        width: r.width,
                        height: r.height,
                        cx: left + r.width / 2,
                        cy: top + r.height / 2
                    });
                }
            }

            const seen = new Set();
            const final = [];
            for (const t of tokens) {
                const key = [
                    t.text.toLowerCase(),
                    Math.round(t.left / 3),
                    Math.round(t.top / 3)
                ].join('|');
                if (seen.has(key)) continue;
                seen.add(key);
                final.push(t);
            }

            final.sort((a,b) => (a.top - b.top) || (a.left - b.left));
            return {heading: h, nextHeading: next, tokens: final};
        }
    """
    return page.evaluate(js, {"heading": heading}) or {"heading": None, "nextHeading": None, "tokens": []}


def parse_tokens(tokens, market_name, prop_type, min_line):
    labels = []
    odds = []

    for t in tokens:
        txt = clean(t["text"])
        if is_label(txt):
            m = re.match(r"^(Over|Under)\s+(\d+(?:\.\d+)?)$", txt, re.I)
            line = m.group(2)
            if float(line) < min_line:
                continue
            labels.append({**t, "side": m.group(1).lower(), "line": line})
        elif is_odds(txt):
            odds.append(t)

    out = []
    used = set()

    for lab in labels:
        best = None
        best_score = None

        for idx, od in enumerate(odds):
            if idx in used:
                continue

            dy = od["cy"] - lab["cy"]
            dx = abs(od["cx"] - lab["cx"])

            if dy <= 3 or dy > 80:
                continue
            if dx > 230:
                continue

            score = dy + dx * 0.55
            if best is None or score < best_score:
                best = (idx, od)
                best_score = score

        if best is None:
            continue

        idx, od = best
        used.add(idx)

        side = lab["side"]
        line = lab["line"]
        out.append(sel(f"{side.title()} {line}", od["text"], side, line, prop_type))

    return market(market_name, out), labels, odds


def scrape_one_tab(page, event_url, fixture, tab, heading, market_name, prop_type, min_line):
    setup_event(page, event_url)

    print(f"      {tab} tab:", click_top_tab(page, tab))
    print(f"      {heading}:", click_exact_heading(page, heading))
    print("      inner Match:", click_inner_match_near_heading(page, heading))

    data = token_data_between_heading_and_next_market(page, heading)
    tokens = data.get("tokens", [])
    m, labels, odds = parse_tokens(tokens, market_name, prop_type, min_line)

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    debug_file = DEBUG_DIR / f"{slugify(fixture['match'])}_{tab.lower()}.txt"
    debug_file.write_text(
        "HEADING:\n" + json.dumps(data.get("heading"), indent=2) +
        "\n\nNEXT HEADING:\n" + json.dumps(data.get("nextHeading"), indent=2) +
        "\n\nPARSED:\n" +
        "\n".join(f"{s['selection']} {s['odds']}" for s in m["selections"]) +
        "\n\nLABELS:\n" +
        "\n".join(f"{x['text']:<12} top={x['top']:.1f} left={x['left']:.1f} cx={x['cx']:.1f}" for x in labels) +
        "\n\nODDS:\n" +
        "\n".join(f"{x['text']:<8} top={x['top']:.1f} left={x['left']:.1f} cx={x['cx']:.1f}" for x in odds) +
        "\n\nALL TOKENS:\n" +
        "\n".join(f"{x['text']:<40} top={x['top']:.1f} left={x['left']:.1f} cx={x['cx']:.1f}" for x in tokens),
        encoding="utf-8",
    )

    return m


def scrape_fixture(page, fixture):
    print("\n" + "=" * 60)
    print(f"Scraping cards/corners: {fixture['match']}")

    event_url = resolve_event_url(page, fixture)
    fixture["url"] = event_url
    print(f"URL: {event_url}")

    corners = scrape_one_tab(
        page,
        event_url,
        fixture,
        "Corners",
        "Match Over/Under Corners",
        "Total Corners",
        "corners",
        4.5,
    )

    cards = scrape_one_tab(
        page,
        event_url,
        fixture,
        "Cards",
        "Match Over/Under Cards",
        "Total Cards",
        "cards",
        1.5,
    )

    markets = [m for m in [corners, cards] if m["selection_count"] > 0]

    print(f"✓ {fixture['match']} — {len(markets)} cards/corners markets")
    for m in markets:
        print(f"  {m['market']:<20} {m['selection_count']} selections")
        for s in m["selections"][:10]:
            print(f"    {s['selection']:<12} {s['odds']}")

    return {
        "match": fixture["match"],
        "home_team": fixture["home_team"],
        "away_team": fixture["away_team"],
        "url": event_url,
        "market_count": len(markets),
        "markets": markets,
    }


def main():
    print("William Hill Cards/Corners Scraper")
    print(f"MAX_MATCHES = {MAX_MATCHES}")
    print(f"TEMP_SKIP_MATCHES = {sorted(TEMP_SKIP_MATCHES)}")

    fixtures = load_fixtures()

    if not fixtures:
        raise SystemExit("No fixtures found.")

    print("\nTargets:")
    for f in fixtures:
        print(" -", f["match"])

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=40)
        page = browser.new_page(viewport={"width": 1500, "height": 950})

        for fixture in fixtures:
            try:
                results.append(scrape_fixture(page, fixture))
            except Exception as e:
                print(f"  !! failed {fixture['match']}: {e}")
                results.append({
                    "match": fixture["match"],
                    "home_team": fixture["home_team"],
                    "away_team": fixture["away_team"],
                    "url": fixture.get("url", ""),
                    "market_count": 0,
                    "markets": [],
                    "error": str(e),
                })

        browser.close()

    out = {
        "bookmaker": "WilliamHill",
        "source": "cards_corners",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches_with_markets": len([m for m in results if m.get("market_count", 0) > 0]),
        "matches": results,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved → {OUT_PATH}")
    print("\nSummary:")
    for r in results:
        print(f"  {r['match']:<40} {r.get('market_count', 0)} cards/corners markets")


if __name__ == "__main__":
    main()
