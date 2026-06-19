#!/usr/bin/env python3
"""
fetch_betvictor_props_FRANCE_DIRECT_V5.py

BetVictor props direct test for France v Senegal.

Why this exists:
- The previous full scraper used the first fixture from betvictor_worldcup_moneylines.json
  and then mis-clicked a nearby fixture row.
- This version does NOT use the fixture list and does NOT click fixture rows.
- It opens the exact France v Senegal event URL from the browser screenshot and then
  visits the known BetVictor market_group URLs directly.

Output:
  football/data/betvictor_france_senegal_props_direct.json
Debug:
  football/debug/betvictor_france_senegal_direct/*.txt
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "football" / "data" / "betvictor_france_senegal_props_direct.json"
DEBUG_DIR = ROOT / "football" / "debug" / "betvictor_france_senegal_direct"

EVENT_URL = "https://www.betvictor.com/en-ie/sports/240/meetings/726764210/events/2654406500"
MATCH = "France v Senegal"
HOME = "France"
AWAY = "Senegal"
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
    "France Shots on Target",
    "France Shots",
    "France Tackles",
    "France Offsides",
    "Senegal Shots on Target",
    "Senegal Shots",
    "Senegal Tackles",
    "Senegal Offsides",
    "To Have the Most",
]

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
THRESH_RE = re.compile(r"^\d\+$")


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_threshold(s):
    return bool(THRESH_RE.match(clean(s)))


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")


def group_url(group_id):
    if not group_id:
        return EVENT_URL
    return f"{EVENT_URL}?market_group={group_id}"


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
        key = (s.get("selection"), s.get("odds"), s.get("player"), s.get("threshold"), s.get("side"), s.get("line"))
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


def scroll_all(page, passes=5):
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
            """(label) => {
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


def capture_group(page, group_name, group_id):
    url = group_url(group_id)
    print(f"  opening group {group_name}: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4500)
    accept_cookies(page)

    chunks = []
    click_show_more(page)
    scroll_all(page, passes=4)
    chunks.append(f"=== GROUP {group_name} DEFAULT ===\n" + page.locator("body").inner_text(timeout=25000))

    # Expand likely accordions/sections and capture after each successful click.
    for title in EXPAND_TITLES:
        try:
            if click_exact_text(page, title):
                click_show_more(page)
                scroll_all(page, passes=3)
                chunks.append(f"=== GROUP {group_name} EXPANDED {title} ===\n" + page.locator("body").inner_text(timeout=25000))
        except Exception:
            pass

    text = "\n\n".join(chunks)
    (DEBUG_DIR / f"{group_name}.txt").write_text(text, encoding="utf-8")
    return text


# ---------------- parsers ----------------

JUNK_PLAYERS = {
    "Search", "Show More", "Show Less", "First", "Anytime", "Last", "Over", "Under", "Yes", "No",
    "Goalscorers", "Player Shots on Target", "Player Shots", "Player Assists", "Player Tackles", "Player Fouls", "Player Cards",
    HOME, AWAY, "Draw", "Popular", "Bet Builder", "Specials", "Bet Boost", "Early Payout", "Goals", "Corners", "Cards", "Player", "Half", "Asian Lines", "Other",
}


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


def bad_player(x):
    x = clean(x)
    if not x or x in JUNK_PLAYERS or is_odds(x) or is_threshold(x):
        return True
    if len(x) > 55:
        return True
    if re.match(r"^\d", x):
        return True
    if any(t in x.lower() for t in ["responsible", "terms", "privacy", "world cup", "kick off", "match betting"]):
        return True
    return False


def parse_over_under(lines, title, market_name):
    block = find_block(lines, title, 140)
    out = []
    mode = None
    i = 0
    while i < len(block):
        tok = clean(block[i])
        if tok.lower() == "over":
            mode = "over"; i += 1; continue
        if tok.lower() == "under":
            mode = "under"; i += 1; continue
        m = re.match(r"^(?:O|U)?\s*(\d+(?:\.\d+)?)$", tok, re.I)
        if mode and m and i + 1 < len(block) and is_odds(block[i+1]):
            line = m.group(1)
            out.append(sel(f"{mode.title()} {line}", block[i+1], side=mode, line=line))
            i += 2
            continue
        i += 1
    return market(market_name, out)


def parse_two_or_three_col_player(lines, title, market_names):
    """For Goalscorers/cards: player + first/anytime[/last] odds."""
    block = find_block(lines, title, 420)
    first, anytime, last = [], [], []
    headers = []
    for h in ["First", "Anytime", "Last"]:
        if h in block:
            headers.append(h)
    if not headers:
        headers = ["Anytime"]

    for i, player in enumerate(block):
        player = clean(player)
        if bad_player(player):
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


def parse_threshold_player(lines, title, market_name, prop_type, max_thresholds=4):
    block = find_block(lines, title, 520)
    out = []
    if not block:
        return market(market_name, out)

    # Look for explicit headers 1+ 2+ 3+ etc. If absent, assume 1+,2+,3+,4+ left aligned.
    headers = [x for x in block[:40] if is_threshold(x)]
    if not headers:
        headers = [f"{i}+" for i in range(1, max_thresholds + 1)]
    headers = headers[:max_thresholds]

    for i, player in enumerate(block):
        player = clean(player)
        if bad_player(player):
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
            out.append(sel(f"{player} {th} {market_name.replace('Player ', '')}", odd, player=player, threshold=th, prop_type=prop_type))
    return market(market_name, out)


def parse_simple_player(lines, title, market_name, prop_type):
    block = find_block(lines, title, 360)
    out = []
    for i, player in enumerate(block):
        player = clean(player)
        if bad_player(player):
            continue
        if i + 1 < len(block) and is_odds(block[i + 1]):
            out.append(sel(f"{player} {market_name.replace('Player ', '')}", block[i + 1], player=player, prop_type=prop_type))
    return market(market_name, out)


def parse_match_stats(lines):
    out = []
    block = find_block(lines, "To Have the Most", 120)
    stat_names = {"Shots", "Shots On Target", "Tackles", "Offsides"}
    for i, stat in enumerate(block):
        stat = clean(stat)
        if stat not in stat_names:
            continue
        odds = []
        j = i + 1
        while j < min(i + 8, len(block)) and len(odds) < 3:
            if is_odds(block[j]):
                odds.append(block[j])
            j += 1
        if len(odds) >= 3:
            out.append(sel(f"{HOME} Most {stat}", odds[0], side="home", stat=stat))
            out.append(sel(f"Draw Most {stat}", odds[1], side="draw", stat=stat))
            out.append(sel(f"{AWAY} Most {stat}", odds[2], side="away", stat=stat))
    return market("To Have The Most Match Stats", out)


def parse_all(all_text):
    lines = lines_from_text(all_text)
    markets = []
    def add(m):
        if isinstance(m, list):
            for x in m:
                if x.get("selection_count", 0) > 0:
                    markets.append(x)
        elif m.get("selection_count", 0) > 0:
            markets.append(m)

    add(parse_over_under(lines, "Total Goals Over/Under", "Total Goals Over / Under"))
    add(parse_over_under(lines, "Total Corners Over/Under", "Total Corners Over / Under"))
    add(parse_over_under(lines, "Total Cards Over/Under", "Total Cards Over / Under"))

    add(parse_two_or_three_col_player(lines, "Goalscorers", ["First Goalscorer", "Anytime Goalscorer", "Last Goalscorer"]))
    add(parse_two_or_three_col_player(lines, "Player Cards", ["First Player Card", "Player Cards"]))

    add(parse_threshold_player(lines, "Player Shots on Target", "Player Shots On Target", "shots_on_target", 3))
    add(parse_threshold_player(lines, "Player Shots", "Player Shots", "shots", 4))
    add(parse_simple_player(lines, "Player Assists", "Player Assists", "assist"))
    add(parse_threshold_player(lines, "Player Tackles", "Player Tackles", "tackles", 4))
    add(parse_threshold_player(lines, "Player Fouls", "Player Fouls", "fouls", 4))
    add(parse_match_stats(lines))

    seen, out = set(), []
    for m in markets:
        k = m["normalized_market"]
        if k in seen:
            continue
        seen.add(k)
        out.append(m)
    return out


def write_hits(text):
    words = ["Player Shots", "Shots on Target", "Player Cards", "Player Assists", "Player Tackles", "Player Fouls", "Total Corners", "Total Cards", "To Have the Most", "Match Shots", "France Shots", "Senegal Shots"]
    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if any(w.lower() in line.lower() for w in words):
            hits.append(f"{i:04d}: {line}")
            for j in range(i + 1, min(i + 14, len(lines))):
                if lines[j].strip():
                    hits.append(f"      {j:04d}: {lines[j]}")
            hits.append("")
    (DEBUG_DIR / "HITS.txt").write_text("\n".join(hits), encoding="utf-8")


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    chunks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        print(f"Direct event test: {MATCH}")
        print(EVENT_URL)

        for group_name, group_id in GROUPS.items():
            text = capture_group(page, group_name, group_id)
            chunks.append(f"\n\n##### {group_name.upper()} #####\n{text}")

        browser.close()

    all_text = "\n".join(chunks)
    (DEBUG_DIR / "ALL_GROUPS.txt").write_text(all_text, encoding="utf-8")
    write_hits(all_text)

    markets = parse_all(all_text)
    result = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BetVictor",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": 1,
        "matches_with_markets": 1 if markets else 0,
        "matches": [{
            "match": MATCH,
            "home_team": HOME,
            "away_team": AWAY,
            "source_url": EVENT_URL,
            "market_count": len(markets),
            "markets": markets,
        }]
    }
    OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nSaved:")
    print(OUT_PATH)
    print(DEBUG_DIR / "ALL_GROUPS.txt")
    print(DEBUG_DIR / "HITS.txt")
    print(f"\nMarkets: {len(markets)}")
    for m in markets:
        print(f"  {m['market']:<35} {m['selection_count']} selections")


if __name__ == "__main__":
    main()
