#!/usr/bin/env python3
"""
fetch_unibet_worldcup_shots_cards.py
Dedicated Unibet World Cup player props scraper for BeatTheBooks.

Purpose:
  Fix Unibet player grid markets by parsing DOM rows, not flattened body text.

Targets:
  - Player Shots On Target
  - Player Shots
  - Player Cards
  - Player Assists

Output:
  football/data/unibet_worldcup_shots_cards.json
Debug:
  football/debug/unibet_shots_cards/*.json

Run from repo root:
  python scripts/Football/fetch_unibet_worldcup_shots_cards.py
"""

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "football" / "data" / "unibet_worldcup_shots_cards.json"
DEBUG_DIR = ROOT / "football" / "debug" / "unibet_shots_cards"
LIST_URL = "https://www.unibet.ie/betting/odds/football/fifa-world-cup/group-matches"
MAIN_PROPS_PATH = ROOT / "football" / "data" / "unibet_worldcup_props.json"
MONEYLINES_PATH = ROOT / "football" / "data" / "unibet_worldcup_moneylines.json"

MAX_MATCHES = 15
HEADLESS = False

DECIMAL_RE = re.compile(r"^\d+(?:\.\d+)?$")
THRESHOLD_RE = re.compile(r"^\d\+$")

TEAM_ALIASES = {
    "Curaçao": "Curacao",
    "Côte d'Ivoire": "Ivory Coast",
    "United States": "USA",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Czech Republic": "Czechia",
}

MARKETS = [
    {
        "heading": "Player Shots on Target (Incl. Extra Time)",
        "short_heading": "Player Shots on Target",
        "market": "Player Shots On Target",
        "prop_type": "player_shots_on_target",
        "thresholds": {"1+", "2+", "3+"},
    },
    {
        "heading": "Player Shots (Incl. Extra Time)",
        "short_heading": "Player Shots",
        "market": "Player Shots",
        "prop_type": "player_shots",
        "thresholds": {"1+", "2+", "3+", "4+", "5+"},
    },
    {
        "heading": "Player Total Cards (Incl. Extra Time)",
        "short_heading": "Player Total Cards",
        "market": "Player Cards",
        "prop_type": "player_cards",
        "thresholds": {"1+"},
    },
    {
        "heading": "Player Assists (Incl. Extra Time)",
        "short_heading": "Player Assists",
        "market": "Player Assists",
        "prop_type": "player_assists",
        "thresholds": {"1+", "2+"},
    },
]

STOP_HEADINGS = {
    "Full Time Result", "Total Goals", "Double Chance", "Both Teams to Score",
    "Total Corners", "Total Cards", "Asian Handicap", "Correct Score",
    "Draw No Bet", "Winning Margin", "1st Goal", "Result & Both Teams to Score",
    "Anytime Scorer - Power Sub", "Player Shots on Target (Incl. Extra Time)",
    "Player Shots (Incl. Extra Time)", "Player Total Cards (Incl. Extra Time)",
    "Player Assists (Incl. Extra Time)", "Player Fouls Committed", "Player Fouls Won",
    "Player Tackles",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    s = clean(s)
    return TEAM_ALIASES.get(s, s)


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def slugify(s):
    return normalize(s).replace("_", "-")


def is_decimal_odds(s):
    s = clean(s)
    if not DECIMAL_RE.match(s):
        return False
    try:
        v = float(s)
        return 1.001 <= v <= 501
    except Exception:
        return False


def decimal_to_fractional(decimal_value):
    try:
        dec = float(decimal_value)
    except Exception:
        return str(decimal_value)
    frac = dec - 1.0
    common_denoms = [1, 2, 3, 4, 5, 6, 8, 10, 11, 20, 25, 50, 100]
    best_num, best_den, best_err = 0, 1, 999
    for den in common_denoms:
        num = round(frac * den)
        if num <= 0:
            continue
        err = abs((num / den) - frac)
        if err < best_err:
            best_num, best_den, best_err = num, den, err
    g = math.gcd(best_num, best_den) or 1
    best_num //= g
    best_den //= g
    if best_num == best_den:
        return "EVS"
    return f"{best_num}/{best_den}"


def threshold_to_line(th):
    try:
        n = int(str(th).replace("+", ""))
        return f"{n - 0.5:.1f}"
    except Exception:
        return str(th)


def selection_obj(player, threshold, odds, market_name, prop_type):
    return {
        "selection": f"{player} {threshold} {market_name}",
        "normalized_selection": normalize(f"{player} {threshold} {market_name}"),
        "odds": decimal_to_fractional(odds),
        "decimal_odds": float(odds),
        "player": player,
        "threshold": threshold,
        "line": threshold_to_line(threshold),
        "prop_type": prop_type,
    }


def market_obj(name, selections):
    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(selections),
        "selections": selections,
    }


def dedupe_selections(selections):
    out, seen = [], set()
    for s in selections:
        key = (s.get("prop_type"), s.get("player"), s.get("threshold"))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def is_probably_player_name(x):
    x = clean(x)
    if not x or len(x) > 60:
        return False
    low = x.lower()
    bad = {
        "all", "spain", "cape verde", "players", "player", "view less", "view more",
        "all spain cape verde", "over", "under", "yes", "no", "draw",
    }
    if low in bad:
        return False
    if is_decimal_odds(x) or THRESHOLD_RE.match(x):
        return False
    if any(h.lower() == low for h in STOP_HEADINGS):
        return False
    return bool(re.search(r"[A-Za-zÀ-ž]", x))


def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "Got it"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=2500)
                page.wait_for_timeout(800)
                return
        except Exception:
            pass


def title_from_slug(url):
    tail = url.rstrip("/").split("/")[-1]
    prev = url.rstrip("/").split("/")[-2]
    part = prev if re.match(r"^[a-f0-9]{16,}$", tail) else tail
    if "-vs-" not in part:
        return ""
    home, away = part.split("-vs-", 1)
    def nice(x):
        return " ".join(w.capitalize() for w in x.split("-"))
    return f"{canonical_team(nice(home))} v {canonical_team(nice(away))}"


def split_teams(match_name):
    if re.search(r"\s+v\s+", match_name, re.I):
        home, away = re.split(r"\s+v\s+", match_name, maxsplit=1, flags=re.I)
        return canonical_team(home), canonical_team(away)
    return "", ""



def load_saved_match_links():
    """Fallback when Unibet's list page returns no anchors.

    Reads match URLs already discovered by the main Unibet scrapers so this
    focused shots/cards scraper can still run reliably.
    """
    out, seen = [], set()

    for path in [MAIN_PROPS_PATH, MONEYLINES_PATH]:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        for m in data.get("matches", []):
            url = clean(m.get("source_url") or m.get("url") or "")
            if not url:
                continue
            if "/betting/odds/football/fifa-world-cup/group-matches/" not in url:
                continue
            if "-vs-" not in url:
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append({"url": url, "text": clean(m.get("match") or f"{m.get('home','')} v {m.get('away','')}")})
            if len(out) >= MAX_MATCHES:
                return out

    return out

def collect_match_links(page):
    print(f"Opening Unibet World Cup page: {LIST_URL}")
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    accept_cookies(page)

    for i in range(14):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(500)

    links = page.evaluate("""
        () => Array.from(document.querySelectorAll('a'))
          .map(a => ({ href: a.href, text: a.innerText }))
          .filter(x =>
            x.href &&
            x.href.includes('/betting/odds/football/fifa-world-cup/group-matches/') &&
            x.href.includes('-vs-')
          )
    """)

    out, seen = [], set()
    for item in links:
        href = clean(item.get("href"))
        if not href or href in seen:
            continue
        seen.add(href)
        out.append({"url": href, "text": clean(item.get("text"))})

    if not out:
        print("Found 0 possible Unibet match links from list page")
        saved = load_saved_match_links()
        print(f"Fallback loaded {len(saved)} saved Unibet match links")
        return saved[:MAX_MATCHES]

    print(f"Found {len(out)} possible Unibet match links")
    return out[:MAX_MATCHES]


def click_main_markets(page):
    for label in ["Main Markets", "All"]:
        try:
            loc = page.get_by_text(label, exact=True)
            if loc.count():
                loc.first.click(timeout=4000)
                page.wait_for_timeout(1500)
                return True
        except Exception:
            pass
    return False


def expand_all_view_more(page, max_clicks=100):
    clicks = 0
    for _ in range(max_clicks):
        try:
            loc = page.get_by_text("View more", exact=True)
            count = loc.count()
            if count <= 0:
                break
            clicked = False
            for i in range(min(count, 10)):
                try:
                    target = loc.nth(i)
                    if target.is_visible(timeout=500):
                        target.scroll_into_view_if_needed(timeout=1500)
                        page.wait_for_timeout(150)
                        target.click(timeout=2000)
                        page.wait_for_timeout(650)
                        clicks += 1
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                page.mouse.wheel(0, 800)
                page.wait_for_timeout(350)
        except Exception:
            break
    print(f"Clicked View more {clicks} times")
    return clicks


def collect_rows(page):
    """Collect visible/loaded DOM leaf text grouped by y-position.

    This intentionally returns positioned rows because Unibet's body.innerText
    loses empty cells and breaks player grid alignment.
    """
    return page.evaluate("""
    () => {
      const els = Array.from(document.querySelectorAll('body *'));
      const cells = [];
      for (const e of els) {
        const txt = (e.innerText || e.textContent || '').trim().replace(/\\s+/g, ' ');
        if (!txt) continue;
        const r = e.getBoundingClientRect();
        if (!Number.isFinite(r.x) || !Number.isFinite(r.y) || r.width <= 0 || r.height <= 0) continue;
        // keep useful small/medium elements and market row containers
        if (txt.length > 90) continue;
        cells.push({
          text: txt,
          tag: e.tagName,
          cls: String(e.className || ''),
          x: r.x, y: r.y, w: r.width, h: r.height,
          cx: r.x + r.width / 2,
          cy: r.y + r.height / 2
        });
      }
      cells.sort((a,b) => (a.cy - b.cy) || (a.x - b.x));
      const rows = [];
      for (const c of cells) {
        let row = rows.find(r => Math.abs(r.y - c.cy) < 7);
        if (!row) {
          row = { y: c.cy, cells: [] };
          rows.push(row);
        }
        if (!row.cells.some(x => x.text === c.text && Math.abs(x.x - c.x) < 3)) {
          row.cells.push(c);
        }
      }
      for (const r of rows) {
        r.cells.sort((a,b) => a.x - b.x || a.w - b.w);
      }
      rows.sort((a,b) => a.y - b.y);
      return rows;
    }
    """)



def unique_cells(cells, x_tol=4):
    """Deduplicate nested Unibet DOM cells while preserving left-to-right order."""
    out = []
    for c in sorted(cells, key=lambda z: (z.get("x", 0), z.get("w", 0))):
        t = clean(c.get("text"))
        if not t:
            continue
        # Ignore huge combined strings for grid parsing; simple-card parser can
        # still use compact strings like "Player 1+ 4.00".
        if any(t == clean(o.get("text")) and abs(c.get("x", 0) - o.get("x", 0)) < x_tol for o in out):
            continue
        out.append(c)
    return out


def row_cells_in_col(row, col_min=None, col_max=None):
    cells = row.get("cells", [])
    if col_min is not None and col_max is not None:
        cells = [c for c in cells if col_min <= c.get("cx", 0) <= col_max]
    return unique_cells(cells)


def row_texts(row, col_min=None, col_max=None):
    texts = []
    for c in row_cells_in_col(row, col_min, col_max):
        t = clean(c.get("text"))
        if t and t not in texts:
            texts.append(t)
    return texts


def find_heading_positions(rows, heading):
    """Return (row_index, heading_cell, col_min, col_max) for exact heading cells."""
    out = []
    for i, r in enumerate(rows):
        for c in r.get("cells", []):
            if clean(c.get("text")) != heading:
                continue
            # Prefer the market-card/header container width where available.
            x = float(c.get("x", 0))
            w = float(c.get("w", 0))
            if w < 120:
                continue
            out.append((i, c, x - 12, x + w + 12))
    # If only small heading cells existed, fall back to any exact heading.
    if not out:
        for i, r in enumerate(rows):
            for c in r.get("cells", []):
                if clean(c.get("text")) == heading:
                    x = float(c.get("x", 0))
                    w = float(c.get("w", 488)) or 488
                    out.append((i, c, x - 12, x + w + 12))
    return out


def compact_market_rows(rows, start_idx, col_min=None, col_max=None, max_rows=140):
    """Rows from a market heading until View less in the same column/card."""
    out = []
    for r in rows[start_idx:start_idx + max_rows]:
        texts = row_texts(r, col_min, col_max)
        if not texts:
            continue
        out.append(r)
        # Important: only stop when View less is inside THIS market column.
        if any(t == "View less" for t in texts) and len(out) > 3:
            break
    return out


def dedupe_position_cells(cells, x_tol=8):
    out = []
    for c in sorted(cells, key=lambda z: z.get("cx", 0)):
        t = clean(c.get("text"))
        if not t:
            continue
        if any(t == clean(o.get("text")) and abs(c.get("cx", 0) - o.get("cx", 0)) < x_tol for o in out):
            continue
        out.append(c)
    return out


def nearest_threshold(odd_cell, threshold_cells):
    if not threshold_cells:
        return None
    ocx = odd_cell.get("cx", 0)
    best = min(threshold_cells, key=lambda c: abs(c.get("cx", 0) - ocx))
    return clean(best.get("text"))


def parse_simple_cards_block(block, col_min, col_max, market_name, prop_type):
    """Parse Unibet's Player Total Cards rows, e.g. 'Mikel Merino 1+ 4.75'."""
    selections = []
    seen = set()
    card_pat = re.compile(r"^(.+?)\s+1\+\s+(\d+(?:\.\d+)?)$")

    for r in block[1:]:
        cells = row_cells_in_col(r, col_min, col_max)
        texts = [clean(c.get("text")) for c in cells if clean(c.get("text"))]
        if not texts:
            continue

        parsed_this_row = False

        # Best case: one compact cell contains player + threshold + odds.
        for t in texts:
            m = card_pat.match(t)
            if not m:
                continue
            player, odd = clean(m.group(1)), clean(m.group(2))
            if is_probably_player_name(player) and is_decimal_odds(odd):
                key = (player, "1+")
                if key not in seen:
                    selections.append(selection_obj(player, "1+", odd, market_name, prop_type))
                    seen.add(key)
                parsed_this_row = True
                break

        if not parsed_this_row:
            # Fallback: a cell says 'Player 1+' and another cell has odds.
            player = None
            for t in texts:
                if t.endswith(" 1+"):
                    player = clean(t[:-3])
                    break
            odds = [t for t in texts if is_decimal_odds(t)]
            if player and odds and is_probably_player_name(player):
                key = (player, "1+")
                if key not in seen:
                    selections.append(selection_obj(player, "1+", odds[0], market_name, prop_type))
                    seen.add(key)

        # Stop only when the current column/card itself has View less.
        if any(t == "View less" for t in texts):
            break

    return selections


def parse_grid_block(block, col_min, col_max, config):
    """Parse player grid markets from positioned rows.

    The key fix: map each odds button to the nearest threshold header by x-position.
    This handles Unibet blank cells correctly:
      Players | 1+ | 2+ | 3+ | 4+
      Lamine Yamal                 1.27
    becomes 4+ = 1.27, not 1+ = 1.27.
    """
    market_name = config["market"]
    prop_type = config["prop_type"]
    allowed = config["thresholds"]

    header_i = None
    threshold_cells = []

    for bi, r in enumerate(block):
        cells = row_cells_in_col(r, col_min, col_max)
        texts = [clean(c.get("text")) for c in cells]
        if "Players" not in texts:
            continue
        th_cells = [c for c in cells if THRESHOLD_RE.match(clean(c.get("text")))]
        th_cells = dedupe_position_cells(th_cells)
        if th_cells:
            header_i = bi
            threshold_cells = th_cells
            break

    if header_i is None or not threshold_cells:
        return []

    selections = []
    seen = set()

    for r in block[header_i + 1:]:
        cells = row_cells_in_col(r, col_min, col_max)
        texts = [clean(c.get("text")) for c in cells if clean(c.get("text"))]
        if not texts:
            continue
        if any(t == "View less" for t in texts):
            break
        if any(clean(cfg["heading"]) in texts for cfg in MARKETS):
            break

        # Ignore summary/overlay rows like '6+ 26.00 21.00 ...'.
        if THRESHOLD_RE.match(texts[0]) or re.match(r"^\d\+\s+", texts[0]):
            continue

        player_candidates = [t for t in texts if is_probably_player_name(t) and not re.search(r"\d+(?:\.\d+)?", t)]
        if not player_candidates:
            continue
        player = player_candidates[0]

        odds_cells = [c for c in cells if is_decimal_odds(clean(c.get("text")))]
        odds_cells = dedupe_position_cells(odds_cells)

        for oc in odds_cells:
            odd = clean(oc.get("text"))
            th = nearest_threshold(oc, threshold_cells)
            if not th or th not in allowed:
                continue
            key = (player, th)
            if key in seen:
                continue
            selections.append(selection_obj(player, th, odd, market_name, prop_type))
            seen.add(key)

    return selections


def parse_row_market(rows, config):
    heading = config["heading"]
    market_name = config["market"]
    prop_type = config["prop_type"]

    selections = []

    for hidx, hcell, col_min, col_max in find_heading_positions(rows, heading):
        block = compact_market_rows(rows, hidx, col_min, col_max)

        if prop_type == "player_cards":
            selections.extend(parse_simple_cards_block(block, col_min, col_max, market_name, prop_type))
        else:
            selections.extend(parse_grid_block(block, col_min, col_max, config))

        # One good market/card is enough; avoid duplicate scrolled copies.
        if selections:
            break

    return market_obj(market_name, dedupe_selections(selections)) if selections else None

def scrape_match(page, url):
    print(f"\nOpening Unibet match page: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5500)
    accept_cookies(page)
    click_main_markets(page)
    page.wait_for_timeout(1000)

    match_name = title_from_slug(url)
    home, away = split_teams(match_name)

    expand_all_view_more(page, max_clicks=100)
    page.wait_for_timeout(1000)

    rows = collect_rows(page)
    markets = []
    debug_markets = {}

    for cfg in MARKETS:
        m = parse_row_market(rows, cfg)
        if m:
            markets.append(m)
            print(f"  - {m['market']}: {m['selection_count']}")
        # Save compact block around heading for debugging.
        idxs = [i for i, r in enumerate(rows) if any(cfg["heading"] == clean(c.get("text")) for c in r.get("cells", []))]
        if idxs:
            block = compact_market_rows(rows, idxs[0])
            debug_markets[cfg["market"]] = {
                "heading": cfg["heading"],
                "rows": block,
            }

    debug_name = slugify(match_name or url[-40:]) or "unknown-match"
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / f"{debug_name}.json").write_text(
        json.dumps({"match": match_name, "url": url, "markets": debug_markets}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return {
        "match": match_name,
        "home_team": home,
        "away_team": away,
        "source_url": url,
        "market_count": len(markets),
        "markets": markets,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    matches, errors = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        links = collect_match_links(page)
        print()
        print("==============================")
        print(f"Limiting Unibet shots/cards scrape to first {len(links)} matches")
        print("==============================")

        for index, item in enumerate(links, start=1):
            print()
            print("==============================")
            print(f"Unibet shots/cards {index}/{len(links)}")
            print("==============================")
            try:
                match = scrape_match(page, item["url"])
                matches.append(match)
            except Exception as e:
                print(f"ERROR scraping {item['url']}: {e}")
                errors.append({"url": item["url"], "error": str(e)})

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "Unibet",
        "market_type": "player_props_shots_cards",
        "source_url": LIST_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(matches),
        "matches_with_markets": len([m for m in matches if m.get("market_count", 0) > 0]),
        "error_count": len(errors),
        "errors": errors,
        "matches": matches,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("==============================")
    print("Unibet shots/cards complete")
    print("==============================")
    print(f"Wrote: {OUT_PATH}")
    print(f"Debug: {DEBUG_DIR}")


if __name__ == "__main__":
    main()
