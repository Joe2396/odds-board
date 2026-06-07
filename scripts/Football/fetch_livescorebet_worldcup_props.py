#!/usr/bin/env python3
"""
fetch_livescorebet_worldcup_props.py

Scrapes World Cup props from LiveScoreBet.
Hits each match page twice:
  1. Base URL → standard markets (BTTS, Goals, Correct Score, HT/FT etc)
  2. ?marketGroupId=757 → player markets (shots, cards, assists, goalscorers)
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH  = ROOT / "football" / "data" / "livescorebet_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "livescorebet_worldcup_props"

COUPON_URL     = "https://www.livescorebet.com/ie/coupon/21127/"
PLAYER_GRP_ID  = "757"
MAX_MATCHES    = 15

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens|\d+/\d+)$", re.I)

WORLD_CUP_TEAMS = {
    "Mexico","South Africa","South Korea","Czech Republic","Czechia",
    "Canada","Bosnia & Herzegovina","Bosnia","USA","Paraguay","Qatar",
    "Switzerland","Brazil","Morocco","Haiti","Scotland","Australia",
    "Turkey","Türkiye","Germany","Curacao","Netherlands","Japan",
    "Ivory Coast","Ecuador","Sweden","Tunisia","Spain","Cape Verde",
    "Belgium","Egypt","Saudi Arabia","Uruguay","Iran","New Zealand",
    "France","Senegal","Iraq","Norway","Argentina","Algeria","Austria",
    "Jordan","Portugal","DR Congo","England","Croatia","Ghana",
    "Panama","Colombia","Uzbekistan",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def normalize(s):
    s = clean(s).lower()
    s = s.replace("&", "and")
    s = s.replace("?", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def slugify(s):
    return normalize(s).replace("_", "-")


def sel(name, odds, extra=None):
    obj = {"selection": clean(name), "normalized_selection": normalize(name), "odds": clean(odds).upper()}
    if extra:
        obj.update(extra)
    return obj


def mkt(name, selections):
    return {"market": name, "normalized_market": normalize(name), "selection_count": len(selections), "selections": selections}


# ── Standard market parsers ────────────────────────────────────────────────────

def parse_match_result(lines, home, away):
    selections = []
    for i in range(len(lines) - 6):
        if (clean(lines[i]) == "Full Time" and
            clean(lines[i+1]) == home and
            clean(lines[i+2]) == "Draw" and
            clean(lines[i+3]) == away and
            is_odds(lines[i+4]) and is_odds(lines[i+5]) and is_odds(lines[i+6])):
            selections = [
                sel(home,   lines[i+4], {"side": "home"}),
                sel("Draw", lines[i+5], {"side": "draw"}),
                sel(away,   lines[i+6], {"side": "away"}),
            ]
            break
    return mkt("Match Betting", selections)


def parse_btts(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Both Teams to Score"), -1)
    if idx == -1:
        return mkt("Both Teams To Score", selections)
    block = lines[idx:idx+20]
    i = 0
    while i < len(block):
        label = clean(block[i])
        period_map = {
            "Full time":  "Both Teams To Score",
            "Full Time":  "Both Teams To Score",
            "1st Half":   "Both Teams To Score in the First Half",
            "2nd Half":   "Both Teams To Score in the Second Half",
        }
        if label in period_map and i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
            base = period_map[label]
            selections.append(sel(f"{base} - Yes", block[i+1], {"side": "yes"}))
            selections.append(sel(f"{base} - No",  block[i+2], {"side": "no"}))
            i += 3
        else:
            i += 1
    return mkt("Both Teams To Score", selections)


def parse_total_goals(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Total Goals"), -1)
    if idx == -1:
        return mkt("Total Goals Over / Under", selections)
    block = lines[idx:idx+40]
    in_match = False
    for i, line in enumerate(block):
        label = clean(line)
        if label == "Both Teams Combined":
            in_match = True
            continue
        if in_match and label in WORLD_CUP_TEAMS:
            break
        if not in_match:
            continue
        if re.match(r'^\d+\.?\d*$', label) and i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
            selections.append(sel(f"Over {label}",  block[i+1], {"side": "over",  "line": label}))
            selections.append(sel(f"Under {label}", block[i+2], {"side": "under", "line": label}))
    return mkt("Total Goals Over / Under", selections)


def parse_correct_score(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Correct Score"), -1)
    if idx == -1:
        return mkt("Correct Score", selections)
    block = lines[idx:idx+80]
    for i, line in enumerate(block):
        label = clean(line)
        if re.match(r'^\d+\s*[-:]\s*\d+$', label) and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label.replace(":", "-"), block[i+1]))
    return mkt("Correct Score", selections)


def parse_double_chance(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Double Chance"), -1)
    if idx == -1:
        return mkt("Double Chance", selections)
    block = lines[idx:idx+15]
    label_map = {"1X": "Home or Draw", "X2": "Away or Draw", "12": "Home or Away"}
    labels = [clean(l) for l in block if clean(l) in label_map]
    odds   = [clean(l) for l in block if is_odds(l)]
    for i, label in enumerate(labels):
        if i < len(odds):
            selections.append(sel(label_map[label], odds[i]))
    return mkt("Double Chance", selections)


def parse_ht_ft(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Half Time/Full Time"), -1)
    if idx == -1:
        return mkt("Half Time / Full Time", selections)
    block = lines[idx:idx+30]
    for i, line in enumerate(block):
        label = clean(line)
        if "/" in label and not is_odds(label) and i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(label, block[i+1]))
    return mkt("Half Time / Full Time", selections)


def parse_goalscorers(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) in {"Goalscorer", "Player to Score"}), -1)
    if idx == -1:
        return mkt("Player to Score", selections)
    skip = {"Goalscorer","Player to Score","First","Anytime","View more",
            "SUB","PAYOUT","applies to these markets","Goal Method"} | WORLD_CUP_TEAMS
    block = lines[idx:idx+200]
    i = 0
    while i < len(block):
        player = clean(block[i])
        if not player or player in skip or is_odds(player) or len(player) > 50:
            i += 1
            continue
        if i+2 < len(block) and is_odds(block[i+1]) and is_odds(block[i+2]):
            selections.append(sel(f"{player} First Goalscorer",   block[i+1], {"player": player, "prop_type": "first_goalscorer"}))
            selections.append(sel(f"{player} Anytime Goalscorer", block[i+2], {"player": player, "prop_type": "anytime_goalscorer"}))
            i += 3
        else:
            i += 1
    return mkt("Player to Score", selections)


# ── Player stat parsers (marketGroupId=757) ────────────────────────────────────

def parse_player_shots_on_target(lines):
    """Player's shots on target — Over 0.5 / 1.5 / 2.5 per player."""
    return _parse_player_over_market(lines, "Player's shots on target", "Shots On Target")


def parse_player_shots(lines):
    """Player's shots — Over 0.5 through 5.5 per player."""
    return _parse_player_over_market(lines, "Player's shots", "Shots")


def parse_player_assists(lines):
    """To give an assist — single odds per player."""
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "To give an assist"), -1)
    if idx == -1:
        return mkt("Player To Assist", selections)
    skip = {"To give an assist", "View more", "Mexico", "South Africa"} | WORLD_CUP_TEAMS
    block = lines[idx:idx+60]
    i = 0
    while i < len(block):
        player = clean(block[i])
        if not player or player in skip or is_odds(player) or len(player) > 50:
            i += 1
            continue
        if i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(f"{player} To Assist", block[i+1], {"player": player}))
            i += 2
        else:
            i += 1
    return mkt("Player To Assist", selections)


def parse_player_cards(lines):
    """To Get a Card — single odds per player."""
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "To Get a Card"), -1)
    if idx == -1:
        return mkt("Player To Get A Card", selections)
    skip = {"To Get a Card", "View more"} | WORLD_CUP_TEAMS
    block = lines[idx:idx+60]
    i = 0
    while i < len(block):
        player = clean(block[i])
        if not player or player in skip or is_odds(player) or len(player) > 50:
            i += 1
            continue
        if i+1 < len(block) and is_odds(block[i+1]):
            selections.append(sel(f"{player} To Get A Card", block[i+1], {"player": player}))
            i += 2
        else:
            i += 1
    return mkt("Player To Get A Card", selections)


def _parse_player_over_market(lines, header, market_name):
    """Generic parser for player Over X.X markets laid out as:
       Header / Home / Away / Over 0.5 / Over 1.5 ... / Player / odds / odds ...
    """
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == header), -1)
    if idx == -1:
        return mkt(market_name, selections)

    block = lines[idx:idx+200]

    # Find the over thresholds line
    thresholds = []
    threshold_idx = -1
    for i, line in enumerate(block[:20]):
        if re.match(r'^Over \d+\.?\d*$', clean(line)):
            if threshold_idx == -1:
                threshold_idx = i
            thresholds.append(clean(line).replace("Over ", ""))

    if not thresholds:
        return mkt(market_name, selections)

    skip = {header, "View more", "Mexico", "South Africa"} | WORLD_CUP_TEAMS
    n = len(thresholds)

    i = threshold_idx + n  # start after the threshold headers
    while i < len(block):
        player = clean(block[i])
        if not player or player in skip or len(player) > 50:
            # Check if we've hit a new section
            if i > threshold_idx + n + 2 and player in WORLD_CUP_TEAMS:
                break
            i += 1
            continue

        # Collect the next n odds
        odds_found = []
        for j in range(1, n + 1):
            if i + j < len(block):
                o = clean(block[i+j])
                if is_odds(o):
                    odds_found.append(o)
                else:
                    break

        if len(odds_found) == n:
            for k, threshold in enumerate(thresholds):
                selections.append(sel(
                    f"{player} Over {threshold} {market_name}",
                    odds_found[k],
                    {"player": player, "line": threshold, "side": "over"}
                ))
            i += n + 1
        else:
            i += 1

    return mkt(market_name, selections)


def parse_standard_props(text, home, away):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    markets = []
    for parser, args in [
        (parse_match_result,  (lines, home, away)),
        (parse_btts,          (lines,)),
        (parse_total_goals,   (lines,)),
        (parse_correct_score, (lines,)),
        (parse_double_chance, (lines,)),
        (parse_ht_ft,         (lines,)),
        (parse_goalscorers,   (lines,)),
    ]:
        try:
            m = parser(*args)
            if m["selections"]:
                markets.append(m)
        except Exception as e:
            print(f"    Parser error ({parser.__name__}): {e}")
    return markets


def parse_player_props(text):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    markets = []
    for parser in [
        parse_goalscorers,
        parse_player_shots_on_target,
        parse_player_shots,
        parse_player_assists,
        parse_player_cards,
    ]:
        try:
            m = parser(lines) if parser != parse_goalscorers else parse_goalscorers(lines)
            if m["selections"]:
                markets.append(m)
        except Exception as e:
            print(f"    Parser error ({parser.__name__}): {e}")
    return markets


# ── Browser helpers ────────────────────────────────────────────────────────────

def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "Got it"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


def expand_view_more(page):
    try:
        buttons = page.get_by_text("View more", exact=True)
        count = buttons.count()
        if count:
            print(f"    Expanding {count} 'View more' button(s)...")
            for i in range(count):
                try:
                    buttons.nth(i).scroll_into_view_if_needed(timeout=2000)
                    buttons.nth(i).click(timeout=3000)
                    page.wait_for_timeout(600)
                except Exception:
                    pass
    except Exception:
        pass


def get_page_text(page, url, scroll_steps=18):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookies(page)
    for _ in range(scroll_steps):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(300)
    expand_view_more(page)
    page.keyboard.press("Control+Home")
    page.wait_for_timeout(500)
    return page.locator("body").inner_text(timeout=30000)


def get_match_links(page):
    print(f"Opening coupon page: {COUPON_URL}")
    page.goto(COUPON_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)
    accept_cookies(page)
    for _ in range(20):
        page.mouse.wheel(0, 750)
        page.wait_for_timeout(400)

    links = page.evaluate("""
        () => [...new Set(
            Array.from(document.querySelectorAll('a'))
                .map(a => a.href)
                .filter(h => h && h.includes('/world-cup-2026/') && h.includes('/SBTE_'))
        )]
    """)

    fixtures = []
    seen = set()
    for url in links:
        # Strip any query params
        base_url = url.split("?")[0]
        if base_url in seen:
            continue
        seen.add(base_url)
        slug = base_url.split("/world-cup-2026/")[-1].split("/")[0]
        name = slug.replace("-", " ").title()
        fixtures.append({"url": base_url, "name": name})

    print(f"Found {len(fixtures)} match links")
    return fixtures[:MAX_MATCHES]


def detect_teams(text, fallback_slug=""):
    """Extract home/away team names from page text."""
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    for i, line in enumerate(lines):
        if line in WORLD_CUP_TEAMS and i+2 < len(lines):
            if clean(lines[i+1]) == "Draw" and clean(lines[i+2]) in WORLD_CUP_TEAMS:
                return line, lines[i+2]
    return "", ""


def scrape_match(page, fixture):
    url  = fixture["url"]
    name = fixture["name"]
    print(f"\n  [{name}]")

    # ── Pass 1: standard markets ──
    print(f"    Pass 1: standard markets")
    text1 = get_page_text(page, url, scroll_steps=20)
    debug1 = DEBUG_DIR / f"{slugify(name)}_standard.txt"
    debug1.write_text(text1, encoding="utf-8")

    home, away = detect_teams(text1)
    if not home:
        # Fallback from slug
        slug = url.split("/world-cup-2026/")[-1].split("/")[0]
        home = slug.split("-")[0].title()
        away = " ".join(slug.split("-")[1:]).title()

    standard_markets = parse_standard_props(text1, home, away)
    print(f"    Standard markets: {len(standard_markets)} — {[m['market'] for m in standard_markets]}")

    # ── Pass 2: player stat markets ──
    player_url = f"{url}?marketGroupId={PLAYER_GRP_ID}"
    print(f"    Pass 2: player markets")
    text2 = get_page_text(page, player_url, scroll_steps=25)
    debug2 = DEBUG_DIR / f"{slugify(name)}_player.txt"
    debug2.write_text(text2, encoding="utf-8")

    player_markets = parse_player_props(text2)
    print(f"    Player markets: {len(player_markets)} — {[m['market'] for m in player_markets]}")

    # Merge — dedupe by market name
    seen_markets = set()
    all_markets = []
    for m in standard_markets + player_markets:
        key = m["normalized_market"]
        if key not in seen_markets:
            seen_markets.add(key)
            all_markets.append(m)

    return {
        "match":      f"{home} v {away}",
        "home_team":  home,
        "away_team":  away,
        "url":        url,
        "markets":    all_markets,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LiveScoreBet World Cup Props Scraper")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        fixtures = get_match_links(page)

        results = []
        for i, fixture in enumerate(fixtures):
            print(f"\n[{i+1}/{len(fixtures)}]")
            try:
                result = scrape_match(page, fixture)
                results.append(result)
            except Exception as e:
                print(f"  ⚠ Error: {e}")
                results.append({
                    "match": fixture["name"], "home_team": "", "away_team": "",
                    "url": fixture["url"], "markets": []
                })

        browser.close()

    output = {
        "sport":        "football",
        "competition":  "FIFA World Cup",
        "bookmaker":    "LiveScoreBet",
        "source_url":   COUPON_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count":  len(results),
        "matches":      results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved → {OUT_PATH}")
    print("\n── Summary ─────────────────────────────────────────────")
    for r in results:
        print(f"  {r['match']:<40} {len(r['markets'])} markets")
    print("─" * 60)


if __name__ == "__main__":
    main()