#!/usr/bin/env python3
"""
fetch_unibet_worldcup_props.py
Deep Unibet World Cup props scraper for BeatTheBooks / Odds Board.

Targets ONLY the markets we want on site:

MATCH / TEAM
  - Match Betting
  - Total Goals Over / Under
  - Team Total Goals Over / Under
  - Both Teams To Score
  - Double Chance
  - Half Time Result
  - Total Cards Over / Under
  - Total Corners Over / Under / Team Corners if available
  - Match Shots / Match Shots On Target if available
  - Team Shots / Team Shots On Target if available

PLAYER
  - Anytime Goalscorer
  - First Goalscorer
  - Player Shots 1+/2+/3+/4+
  - Player Shots On Target 1+/2+/3+/4+
  - Player Cards 1+
  - Player Fouls Committed / Won if available
  - Player Tackles if available
  - Player Assists if available

Explicitly ignores things like Correct Score, Goal Range, Draw No Bet, HT/FT,
handicaps, result combos, etc.

Output:
  football/data/unibet_worldcup_props.json
Debug snapshots:
  football/debug/unibet_worldcup_props/*.txt
"""

import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "football" / "data" / "unibet_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "unibet_worldcup_props"
LIST_URL = "https://www.unibet.ie/betting/odds/football/fifa-world-cup/group-matches"

MAX_MATCHES = 4
HEADLESS = False

DECIMAL_RE = re.compile(r"^\d+(?:\.\d+)?$")
LINE_RE = re.compile(r"^\d+(?:\.5)?$")
THRESHOLD_RE = re.compile(r"^\d\+$")

WORLD_CUP_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic", "Czechia",
    "Canada", "Bosnia & Herzegovina", "Bosnia and Herzegovina", "Bosnia",
    "USA", "United States", "Paraguay", "Qatar", "Switzerland", "Brazil", "Morocco",
    "Haiti", "Scotland", "Australia", "Turkey", "Turkiye", "Türkiye",
    "Germany", "Curacao", "Curaçao", "Netherlands", "Japan",
    "Ivory Coast", "Côte d'Ivoire", "Ecuador", "Sweden", "Tunisia", "Spain",
    "Cape Verde", "Belgium", "Egypt", "Saudi Arabia", "Uruguay", "Iran",
    "New Zealand", "France", "Senegal", "Iraq", "Norway", "Argentina",
    "Algeria", "Austria", "Jordan", "Portugal", "DR Congo", "England",
    "Croatia", "Ghana", "Panama", "Colombia", "Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
    "United States": "USA",
    "Côte d'Ivoire": "Ivory Coast",
}

IGNORE_MARKET_KEYWORDS = [
    "correct score", "goal range", "draw no bet", "asian handicap", "3-way handicap",
    "3 way handicap", "halftime/fulltime", "half time/full time", "ht/ft",
    "cashout", "early payout", "power sub", "bet builder",
]

WANTED_MARKET_HEADINGS = [
    "Full Time Result",
    "Total Goals",
    "Both Teams to Score",
    "Double Chance",
    "Half Time Result",
    "Total Cards",
    "Total Corners",
    "Team Total Corners",
    "Total Goals by",
    "Player Shots on Target",
    "Player Shots",
    "Player Total Cards",
    "Player Assists",
    "Player Fouls Committed",
    "Player Fouls Won",
    "Player Tackles",
    "Anytime Scorer",
    "Anytime Goalscorer",
    "First Goalscorer",
    "Goalscorer",
    "Match Shots on Target",
    "Match Shots",
    "Team Shots on Target",
    "Team Shots",
]


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


def selection_obj(selection, odds, extra=None):
    obj = {
        "selection": clean(selection),
        "normalized_selection": normalize(selection),
        "odds": decimal_to_fractional(odds),
        "decimal_odds": float(odds),
    }
    if extra:
        obj.update(extra)
    return obj


def market_obj(name, selections):
    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(selections),
        "selections": selections,
    }


def lines_from_text(text):
    return [clean(x) for x in text.splitlines() if clean(x)]


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


def collect_match_links(page):
    print(f"Opening Unibet World Cup page: {LIST_URL}")
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    accept_cookies(page)

    for i in range(14):
        print(f"Scrolling list page {i + 1}/14...")
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(600)

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
        text = clean(item.get("text"))
        if not href or href in seen:
            continue
        seen.add(href)
        out.append({"url": href, "text": text})

    print(f"Found {len(out)} possible Unibet match links")
    return out[:MAX_MATCHES]


def title_from_slug(url):
    part = url.rstrip("/").split("/")[-2] if re.match(r"^[a-f0-9]{16,}$", url.rstrip("/").split("/")[-1]) else url.rstrip("/").split("/")[-1]
    part = part.split("?")[0]
    if "-vs-" not in part:
        return ""
    home, away = part.split("-vs-", 1)
    def nice(x):
        return " ".join(w.capitalize() for w in x.split("-"))
    return f"{nice(home)} v {nice(away)}"


def get_match_name_from_page(text, url, fallback_text=""):
    lines = lines_from_text(text)
    for line in lines:
        if " - " in line and len(line) < 90:
            a, b = [clean(x) for x in line.split(" - ", 1)]
            if a and b and not any(x.lower() in a.lower() for x in ["world cup", "football"]):
                return f"{canonical_team(a)} v {canonical_team(b)}"
    if fallback_text and "\n" in fallback_text:
        parts = [clean(x) for x in fallback_text.splitlines() if clean(x)]
        teams = [p for p in parts if p in WORLD_CUP_TEAMS]
        if len(teams) >= 2:
            return f"{canonical_team(teams[0])} v {canonical_team(teams[1])}"
    return title_from_slug(url)


def split_teams(match_name):
    if re.search(r"\s+v\s+", match_name, re.I):
        home, away = re.split(r"\s+v\s+", match_name, maxsplit=1, flags=re.I)
        return canonical_team(home), canonical_team(away)
    return "", ""


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


def expand_all_view_more(page, max_clicks=80):
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


def should_stop_at_heading(line):
    l = line.lower()
    if any(bad in l for bad in IGNORE_MARKET_KEYWORDS):
        return True
    for h in WANTED_MARKET_HEADINGS:
        if l == h.lower() or l.startswith(h.lower()):
            return True
    return False


def next_heading_index(lines, start):
    for i in range(start + 1, len(lines)):
        if should_stop_at_heading(lines[i]):
            return i
    return len(lines)


def parse_two_way_ou(lines, idx, market_name, end_idx=None, team=None, prop_hint=None):
    selections = []
    end = end_idx or next_heading_index(lines, idx)
    for i in range(idx + 1, end - 2):
        line = lines[i]
        if LINE_RE.match(line) and is_decimal_odds(lines[i + 1]) and is_decimal_odds(lines[i + 2]):
            selections.append(selection_obj(f"Over {line}", lines[i + 1], {
                "side": "over", "line": line, **({"team": team} if team else {}), **({"prop_type": prop_hint} if prop_hint else {})
            }))
            selections.append(selection_obj(f"Under {line}", lines[i + 2], {
                "side": "under", "line": line, **({"team": team} if team else {}), **({"prop_type": prop_hint} if prop_hint else {})
            }))
    return market_obj(market_name, selections) if selections else None


def parse_match_markets(text, home, away):
    lines = lines_from_text(text)
    markets = []

    # Match Betting / Full Time Result
    for name in ["Full Time Result"]:
        try:
            idx = next(i for i, x in enumerate(lines) if x == name)
            block = lines[idx: min(len(lines), idx + 28)]
            odds = [x for x in block if is_decimal_odds(x)]
            if len(odds) >= 3:
                markets.append(market_obj("Match Betting", [
                    selection_obj(home, odds[0], {"side": "home"}),
                    selection_obj("Draw", odds[1], {"side": "draw"}),
                    selection_obj(away, odds[2], {"side": "away"}),
                ]))
        except Exception:
            pass

    # Total Goals, Total Cards, Total Corners, Match Shots/SOT
    simple_ou = [
        ("Total Goals", "Total Goals Over / Under", None),
        ("Total Cards", "Total Cards Over / Under", "cards"),
        ("Total Corners", "Total Corners Over / Under", "corners"),
        ("Match Shots on Target", "Match Shots On Target", "match_shots_on_target"),
        ("Match Shots", "Match Shots", "match_shots"),
    ]
    for heading, mname, hint in simple_ou:
        for idx, line in enumerate(lines):
            if line == heading:
                m = parse_two_way_ou(lines, idx, mname, prop_hint=hint)
                if m:
                    markets.append(m)
                break

    # Team total goals / corners / shots. Heading usually: Total Goals by Germany
    for idx, line in enumerate(lines):
        low = line.lower()
        for prefix, out_name, hint in [
            ("total goals by ", "Team Total Goals Over / Under", "team_total_goals"),
            ("total corners by ", "Team Total Corners Over / Under", "team_total_corners"),
            ("team shots on target by ", "Team Shots On Target", "team_shots_on_target"),
            ("team shots by ", "Team Shots", "team_shots"),
            ("shots on target by ", "Team Shots On Target", "team_shots_on_target"),
            ("shots by ", "Team Shots", "team_shots"),
        ]:
            if low.startswith(prefix):
                team = canonical_team(line[len(prefix):])
                m = parse_two_way_ou(lines, idx, out_name, team=team, prop_hint=hint)
                if m:
                    markets.append(m)

    # BTTS
    try:
        idx = next(i for i, x in enumerate(lines) if x == "Both Teams to Score")
        end = next_heading_index(lines, idx)
        block = lines[idx:end]
        selections = []
        for i, x in enumerate(block):
            if x.lower() == "yes" and i + 1 < len(block) and is_decimal_odds(block[i + 1]):
                selections.append(selection_obj("Both Teams To Score - Yes", block[i + 1], {"side": "yes"}))
            if x.lower() == "no" and i + 1 < len(block) and is_decimal_odds(block[i + 1]):
                selections.append(selection_obj("Both Teams To Score - No", block[i + 1], {"side": "no"}))
        if selections:
            markets.append(market_obj("Both Teams To Score", selections))
    except Exception:
        pass

    # Double Chance
    try:
        idx = next(i for i, x in enumerate(lines) if x == "Double Chance")
        end = next_heading_index(lines, idx)
        block = lines[idx:end]
        odds = [x for x in block if is_decimal_odds(x)]
        if len(odds) >= 3:
            markets.append(market_obj("Double Chance", [
                selection_obj(f"{home} or Draw", odds[0]),
                selection_obj(f"{home} or {away}", odds[1]),
                selection_obj(f"Draw or {away}", odds[2]),
            ]))
    except Exception:
        pass

    # Half Time Result only, NOT HT/FT.
    try:
        idx = next(i for i, x in enumerate(lines) if x == "Half Time Result")
        end = next_heading_index(lines, idx)
        block = lines[idx:end]
        odds = [x for x in block if is_decimal_odds(x)]
        if len(odds) >= 3:
            markets.append(market_obj("Half Time Result", [
                selection_obj(f"{home} Half Time", odds[0], {"side": "home"}),
                selection_obj("Draw Half Time", odds[1], {"side": "draw"}),
                selection_obj(f"{away} Half Time", odds[2], {"side": "away"}),
            ]))
    except Exception:
        pass

    return dedupe_markets(markets)


def is_probably_player_name(x, home="", away=""):
    x = clean(x)
    if not x or len(x) > 45:
        return False
    low = x.lower()
    bad = {
        "players", "player", "all", "germany", "curacao", "over", "under", "view more",
        "main markets", "player specials", "match specials", "cards", "full time", "half time",
        "1+", "2+", "3+", "4+", "yes", "no", "draw"
    }
    if low in bad or x in {home, away}:
        return False
    if is_decimal_odds(x) or LINE_RE.match(x) or THRESHOLD_RE.match(x):
        return False
    if "/" in x or "(" in x or ")" in x:
        return False
    # names normally have at least one letter and not too many digits
    return bool(re.search(r"[A-Za-zÀ-ž]", x))


def parse_goalscorers(lines, home, away):
    markets = []
    selections_anytime, selections_first = [], []

    # Unibet often has a single Goalscorer table with columns Anytime / 1st / Last.
    # The old scraper's main issue was accidentally reading threshold rows as players.
    for idx, line in enumerate(lines):
        if line not in {"Goalscorer", "Anytime Scorer", "Anytime Goalscorer", "First Goalscorer"}:
            continue
        end = next_heading_index(lines, idx)
        block = lines[idx:end]
        for i in range(1, len(block) - 2):
            player = block[i]
            if not is_probably_player_name(player, home, away):
                continue
            if is_decimal_odds(block[i + 1]):
                # if row has two odds after player, odds1=anytime, odds2=first scorer.
                selections_anytime.append(selection_obj(f"{player} Anytime Goalscorer", block[i + 1], {
                    "player": player,
                    "prop_type": "anytime_goalscorer",
                }))
                if i + 2 < len(block) and is_decimal_odds(block[i + 2]):
                    selections_first.append(selection_obj(f"{player} First Goalscorer", block[i + 2], {
                        "player": player,
                        "prop_type": "first_goalscorer",
                    }))
        break

    if selections_anytime:
        markets.append(market_obj("Anytime Goalscorer", dedupe_selections(selections_anytime)))
    if selections_first:
        markets.append(market_obj("First Goalscorer", dedupe_selections(selections_first)))
    return markets


def parse_player_grid(lines, heading, market_name, prop_type, home, away, allowed_thresholds=None):
    markets = []
    allowed_thresholds = allowed_thresholds or {"1+", "2+", "3+", "4+"}
    for idx, line in enumerate(lines):
        if not line.startswith(heading):
            continue
        end = next_heading_index(lines, idx)
        block = lines[idx:end]

        # find header thresholds visible before rows
        thresholds = []
        for x in block[:25]:
            if x in allowed_thresholds and x not in thresholds:
                thresholds.append(x)
        if not thresholds:
            thresholds = ["1+"] if "Cards" in heading else ["1+", "2+", "3+", "4+"]

        selections = []
        i = 1
        while i < len(block):
            player = block[i]
            if not is_probably_player_name(player, home, away):
                i += 1
                continue
            odds = []
            j = i + 1
            while j < len(block) and len(odds) < len(thresholds):
                if is_decimal_odds(block[j]):
                    odds.append(block[j])
                    j += 1
                    continue
                # If another player/heading starts, stop this row.
                if is_probably_player_name(block[j], home, away) or should_stop_at_heading(block[j]):
                    break
                j += 1

            for th, odd in zip(thresholds, odds):
                if th not in allowed_thresholds:
                    continue
                selections.append(selection_obj(f"{player} {th} {market_name}", odd, {
                    "player": player,
                    "threshold": th,
                    "line": threshold_to_line(th),
                    "prop_type": prop_type,
                }))
            i = max(j, i + 1)

        if selections:
            markets.append(market_obj(market_name, dedupe_selections(selections)))
    return markets


def threshold_to_line(th):
    try:
        n = int(str(th).replace("+", ""))
        return f"{n - 0.5:.1f}"
    except Exception:
        return str(th)


def parse_player_markets(text, home, away):
    lines = lines_from_text(text)
    markets = []
    markets.extend(parse_goalscorers(lines, home, away))

    wanted_grids = [
        ("Player Shots on Target", "Player Shots On Target", "player_shots_on_target", {"1+", "2+", "3+", "4+"}),
        ("Player Shots", "Player Shots", "player_shots", {"1+", "2+", "3+", "4+"}),
        ("Player Total Cards", "Player Cards", "player_cards", {"1+"}),
        ("Player Assists", "Player Assists", "player_assists", {"1+", "2+"}),
        ("Player Fouls Committed", "Player Fouls Committed", "player_fouls_committed", {"1+", "2+", "3+", "4+"}),
        ("Player Fouls Won", "Player Fouls Won", "player_fouls_won", {"1+", "2+", "3+", "4+"}),
        ("Player Tackles", "Player Tackles", "player_tackles", {"1+", "2+", "3+", "4+"}),
    ]
    for heading, mname, ptype, thresholds in wanted_grids:
        markets.extend(parse_player_grid(lines, heading, mname, ptype, home, away, thresholds))

    return dedupe_markets(markets)


def dedupe_selections(selections):
    out, seen = [], set()
    for s in selections:
        key = (
            s.get("selection"), s.get("player"), s.get("threshold"),
            s.get("side"), s.get("line"), s.get("team"), s.get("decimal_odds")
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def dedupe_markets(markets):
    merged = {}
    order = []
    for m in markets:
        if not m or not m.get("selections"):
            continue
        name = m["market"]
        if name not in merged:
            merged[name] = {**m, "selections": []}
            order.append(name)
        merged[name]["selections"].extend(m.get("selections", []))

    out = []
    for name in order:
        m = merged[name]
        m["selections"] = dedupe_selections(m["selections"])
        m["selection_count"] = len(m["selections"])
        if m["selection_count"]:
            out.append(m)
    return out


def scrape_match(page, url, fallback_text=""):
    print(f"\nOpening Unibet match page: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5500)
    accept_cookies(page)
    click_main_markets(page)
    page.wait_for_timeout(1000)

    initial_text = page.locator("body").inner_text(timeout=30000)
    match_name = get_match_name_from_page(initial_text, url, fallback_text=fallback_text)
    home, away = split_teams(match_name)

    # Main page contains the useful props. Expand all visible View More rows.
    expand_all_view_more(page, max_clicks=100)
    page.wait_for_timeout(1000)

    text = page.locator("body").inner_text(timeout=30000)
    lines = lines_from_text(text)

    markets = []
    if home and away:
        markets.extend(parse_match_markets(text, home, away))
        markets.extend(parse_player_markets(text, home, away))
    markets = dedupe_markets(markets)

    debug_name = slugify(match_name or url[-40:]) or "unknown-match"
    debug_file = DEBUG_DIR / f"{debug_name}.txt"
    debug_file.write_text(text, encoding="utf-8")

    print(f"Detected match: {match_name}")
    for m in markets:
        print(f"  - {m['market']}: {m['selection_count']}")

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
        print(f"Limiting Unibet props scrape to first {len(links)} matches")
        print("==============================")

        for index, item in enumerate(links, start=1):
            print()
            print("==============================")
            print(f"Unibet props {index}/{len(links)}")
            print("==============================")
            try:
                match = scrape_match(page, item["url"], fallback_text=item.get("text") or "")
                matches.append(match)
                print(f"Saved match: {match['match']} | markets: {match['market_count']}")
            except Exception as e:
                print(f"ERROR scraping {item['url']}: {e}")
                errors.append({"url": item["url"], "error": str(e)})

        browser.close()

    good_matches = [m for m in matches if m.get("market_count", 0) > 0]
    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "Unibet",
        "market_type": "props",
        "source_url": LIST_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(matches),
        "matches_with_markets": len(good_matches),
        "error_count": len(errors),
        "errors": errors,
        "matches": matches,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("==============================")
    print("Unibet World Cup props complete")
    print("==============================")
    print(f"Match links scraped: {len(matches)}")
    print(f"Matches with markets: {len(good_matches)}")
    print(f"Errors: {len(errors)}")
    print(f"Wrote: {OUT_PATH}")


if __name__ == "__main__":
    main()
