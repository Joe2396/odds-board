#!/usr/bin/env python3
"""
PaddyPower World Cup Props Scraper
Markets: Over/Under Goals, BTTS, Double Chance, Half Time Result,
         Match Shots, Match Shots On Target, Home Shots On Target,
         Away Shots, First/Anytime Goalscorer, Player Shots On Target,
         Player Fouls Committed, Player Fouls Won, Total Cards O/U,
         Total Corners O/U, Home/Away Total Corners
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT     = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "football" / "data" / "paddypower_worldcup_props.json"
DBG_DIR  = ROOT / "football" / "debug" / "paddypower_worldcup_props"

LIST_URL    = "https://www.paddypower.com/fifa-world-cup"
MAX_MATCHES = 1  # change to 15 when happy

TABS = {
    "":                 ["Double Chance", "Half Time"],
    "?tab=goals":       ["Over/Under Goals Markets", "Player to Score", "Both Teams to Score Markets"],
    "?tab=shots":       ["Player Shots On Target Including Woodwork", "Match Shots", "Match Shots On Target", "Team Shots On Target", "Team Shots"],
    "?tab=cards-fouls": ["Player Shown a Card", "Player To Commit A Foul", "Player To Be Fouled", "Cards Over/Under Markets"],
    "?tab=corners":     ["Corner Over/Under Markets", "Home Total Corners", "Away Total Corners"],
}

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|Evens)$", re.IGNORECASE)

def clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()

def is_odds(s) -> bool:
    return bool(ODDS_RE.match(clean(s)))

def normalize(s) -> str:
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")

def slugify(s) -> str:
    return re.sub(r"[^a-z0-9_-]", "-", normalize(s)).strip("-")

def safe_label(tab_param: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", (tab_param or "main").lstrip("?"))

def build_sel(selection, odds, extra=None) -> dict:
    obj = {"selection": clean(selection), "normalized_selection": normalize(selection), "odds": clean(odds).upper()}
    if extra:
        obj.update(extra)
    return obj

def build_market(name, selections) -> dict:
    return {"market": name, "normalized_market": normalize(name), "selection_count": len(selections), "selections": selections}

def dedupe(market) -> dict:
    seen, out = set(), []
    for s in market.get("selections", []):
        key = (s.get("normalized_selection"), s.get("odds"), s.get("line"), s.get("threshold"), s.get("player"), s.get("team"), s.get("prop_type"))
        if key not in seen:
            seen.add(key)
            out.append(s)
    market["selections"] = out
    market["selection_count"] = len(out)
    return market

def find_line(lines, title) -> int:
    want = clean(title).lower()
    for i, line in enumerate(lines):
        if clean(line).lower() == want:
            return i
    return -1

def get_block(lines, title, stops=None) -> list:
    start = find_line(lines, title)
    if start == -1:
        return []
    stop_set = {clean(t).lower() for t in (stops or []) if clean(t).lower() != clean(title).lower()}
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if clean(lines[i]).lower() in stop_set:
            end = i
            break
    return lines[start:end]

def get_first_block(lines, titles, stops=None) -> list:
    for title in titles:
        b = get_block(lines, title, stops)
        if b:
            return b
    return []

_JUNK_NAMES = {
    "super sub", "show all selections", "show all", "show more", "show less",
    "show less selections", "over", "under", "1+", "2+", "3+", "4+",
    "first", "anytime", "yes", "no", "draw", "the draw", "win more", "no goalscorer",
}
_JUNK_SUBSTRINGS = [
    "you're betting", "means you win", "means you lose", "only cards shown",
    "going in the book", "stats below", "extra time", "penalty shootout",
    "tournament avg", "a free-kick", "a foul won", "cards awarded",
    "sports betting", "football betting", "popular events", "match odds",
    "both teams", "team with most", "over/under", "correct score",
    "bet builder", "corner ", "corners over/under",
    "own goals don", "shots that hit the woodwork", "no clean sheet", "to score or assist",
]

def is_junk_player(name) -> bool:
    n = clean(name).lower()
    if not n or is_odds(n) or n in _JUNK_NAMES:
        return True
    if any(x in n for x in _JUNK_SUBSTRINGS):
        return True
    if re.match(r"^\d", n):
        return True
    if len(n) > 45:
        return True
    return False

def _parse_player_threshold(block, market_name, prop_type, label_tpl, max_t=3) -> dict:
    sels = []
    seen: dict = {}
    for i, line in enumerate(block):
        player = clean(line)
        if is_junk_player(player) or re.match(r"^Tournament Avg:", player, re.I):
            continue
        odds_found = []
        j = i + 1
        while j < min(i + max_t * 3, len(block)):
            tok = clean(block[j])
            if is_odds(tok):
                odds_found.append(tok)
                if len(odds_found) == max_t:
                    break
            elif re.match(r"^Tournament Avg:", tok, re.I):
                pass
            elif odds_found:
                break
            j += 1
        if not odds_found:
            continue
        key = player.lower()
        seen.setdefault(key, {"name": player, "odds": {}})
        for k, odd in enumerate(odds_found):
            t = f"{k + 1}+"
            seen[key]["odds"].setdefault(t, odd)
    for _, pd in seen.items():
        for k in range(max_t):
            t = f"{k + 1}+"
            if t in pd["odds"]:
                sels.append(build_sel(label_tpl.format(player=pd["name"], threshold=t), pd["odds"][t],
                                      {"player": pd["name"], "prop_type": prop_type, "threshold": t}))
    return dedupe(build_market(market_name, sels))

# ---------------------------------------------------------------------------
# GOALS TAB
# ---------------------------------------------------------------------------

def parse_goals_ou(lines) -> dict:
    block = get_block(lines, "Over/Under Goals Markets", [
        "Home Team Over/Under Goals Markets", "Away Team Over/Under Goals Markets",
        "Player to Score", "Both Teams to Score Markets",
    ])
    sels = []
    for i, line in enumerate(block):
        m = re.match(r"Over/Under\s+([\d.]+)\s+Goals?$", clean(line), re.I)
        if not m:
            continue
        threshold = m.group(1)
        try:
            if float(threshold) > 5.5:
                continue
        except ValueError:
            pass
        odds = []
        for j in range(i + 1, min(i + 6, len(block))):
            tok = clean(block[j])
            if is_odds(tok):
                odds.append(tok)
            if len(odds) == 2:
                break
        if len(odds) == 2:
            sels.append(build_sel(f"Over {threshold}",  odds[0], {"side": "over",  "line": threshold}))
            sels.append(build_sel(f"Under {threshold}", odds[1], {"side": "under", "line": threshold}))
    return dedupe(build_market("Over/Under Goals", sels))

def parse_btts(lines) -> dict:
    block = get_first_block(lines, ["Both Teams to Score Markets", "Both Teams To Score Markets"],
                            ["Result & Both to Score", "Match Odds", "1st Half Over/Under Goals"])
    sels = []
    for i, line in enumerate(block):
        label = clean(line)
        if "both teams" not in label.lower() and "both team" not in label.lower():
            continue
        if i + 2 >= len(block):
            continue
        yes_odds, no_odds = clean(block[i + 1]), clean(block[i + 2])
        if not is_odds(yes_odds) or not is_odds(no_odds):
            continue
        base = re.sub(r"\?$", "", label).strip()
        sels.append(build_sel(f"{base} - Yes", yes_odds, {"side": "yes"}))
        sels.append(build_sel(f"{base} - No",  no_odds,  {"side": "no"}))
    return dedupe(build_market("Both Teams To Score", sels))

def parse_player_to_score(lines) -> tuple:
    block = get_block(lines, "Player to Score", [
        "Player to Score Multiple Goals", "To Score Or Assist",
        "Goals Range - Match", "Both Teams to Score Markets", "Both Teams To Score Markets",
    ])
    first_sels, anytime_sels = [], []
    col_start = -1
    for i, line in enumerate(block):
        if clean(line).lower() == "first":
            col_start = i
            break
    search_from = col_start + 2 if col_start >= 0 else 1
    for i in range(search_from, len(block)):
        player = clean(block[i])
        if is_junk_player(player) or i + 2 >= len(block):
            continue
        first_odds, anytime_odds = clean(block[i + 1]), clean(block[i + 2])
        if not is_odds(first_odds) or not is_odds(anytime_odds):
            continue
        first_sels.append(build_sel(f"{player} First Goalscorer", first_odds,
                                    {"player": player, "prop_type": "first_goalscorer"}))
        anytime_sels.append(build_sel(f"{player} Anytime Goalscorer", anytime_odds,
                                      {"player": player, "prop_type": "anytime_goalscorer"}))
    return dedupe(build_market("First Goalscorer", first_sels)), dedupe(build_market("Anytime Goalscorer", anytime_sels))

# ---------------------------------------------------------------------------
# MAIN TAB
# ---------------------------------------------------------------------------

def parse_double_chance(lines, home, away) -> dict:
    block = get_block(lines, "Double Chance", ["Player Foul Involvements", "Half Time", "Match Odds", "Team To Score the First Goal"])
    candidates = [
        (f"{home} And Draw", "home_draw"), (f"{away} And Draw", "away_draw"), (f"{home} And {away}", "home_away"),
        (f"{home} or Draw",  "home_draw"), (f"{away} or Draw",  "away_draw"), (f"{home} or {away}",  "home_away"),
    ]
    sels = []
    for i, line in enumerate(block):
        label = clean(line)
        for sel_name, side in candidates:
            if label.lower() == sel_name.lower() and i + 1 < len(block):
                odds = clean(block[i + 1])
                if is_odds(odds):
                    sels.append(build_sel(sel_name, odds, {"side": side}))
    return dedupe(build_market("Double Chance", sels))

def parse_half_time_result(lines, home, away) -> dict:
    block = get_first_block(lines, ["Half Time", "Half Time Result"],
                            ["Sports Betting", "Football Betting", "Match Odds", "Double Chance", "Player Foul Involvements"])
    name_map = {home: "home", "The Draw": "draw", "Draw": "draw", away: "away"}
    names_found, odds_found = [], []
    for line in block:
        label = clean(line)
        if label in name_map and label not in ("Half Time", "Half Time Result"):
            display = "Draw" if label in ("The Draw", "Draw") else label
            if not any(d == display for d, _ in names_found):
                names_found.append((display, name_map[label]))
        elif is_odds(label):
            odds_found.append(label)
    sels = []
    for (display, side), odds in zip(names_found, odds_found):
        sels.append(build_sel(display, odds, {"side": side}))
    return dedupe(build_market("Half Time Result", sels))

# ---------------------------------------------------------------------------
# SHOTS TAB
# ---------------------------------------------------------------------------

def parse_player_shots_on_target(lines) -> dict:
    """
    Scan for player name followed by 2-3 consecutive odds between the
    section heading and the first team/match shots heading.
    Avoids stop-list issues by scanning directly.
    """
    # Find start and end boundaries
    start = find_line(lines, "Player Shots On Target Including Woodwork")
    if start == -1:
        return build_market("Player Shots On Target", [])

    # End at first line that signals we are past player data
    end_markers = {
        "player to have 4 or more shots on target including woodwork",
        "team shots on target",
        "player shown a card", "player to commit a foul",
    }
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if clean(lines[i]).lower() in end_markers:
            end = i
            break

    block = lines[start:end]

    sels = []
    seen: dict = {}
    i = 0
    while i < len(block):
        player = clean(block[i])
        if is_junk_player(player):
            i += 1
            continue
        # Collect consecutive odds immediately after player name
        odds_found = []
        j = i + 1
        while j < len(block) and len(odds_found) < 3:
            tok = clean(block[j])
            if is_odds(tok):
                odds_found.append(tok)
                j += 1
            else:
                break
        if not odds_found:
            i += 1
            continue
        key = player.lower()
        seen.setdefault(key, {"name": player, "odds": []})
        if not seen[key]["odds"]:
            seen[key]["odds"] = odds_found
        i = j  # jump past the odds we consumed

    for _, pd in seen.items():
        thresholds = ["1+", "2+", "3+"]
        for k, odd in enumerate(pd["odds"][:2]):  # only 1+ and 2+
            t = thresholds[k]
            sels.append(build_sel(
                f"{pd['name']} {t} Shots On Target", odd,
                {"player": pd["name"], "prop_type": "shots_on_target", "threshold": t},
            ))

    return dedupe(build_market("Player Shots On Target", sels))

def parse_xor_more(lines, section_title, market_name, stops, team=None) -> dict:
    block = get_block(lines, section_title, stops)
    sels = []
    for i, line in enumerate(block):
        label = clean(line)
        if not re.search(r"\d+\s+or\s+more", label, re.I):
            continue
        if i + 1 >= len(block):
            continue
        odds = clean(block[i + 1])
        if not is_odds(odds):
            continue
        display = f"{team} {label}" if team else label
        extra = {"side": "over"}
        if team:
            extra["team"] = team
        m = re.search(r"([\d]+(?:\.\d+)?)", label)
        if m:
            extra["line"] = m.group(1)
        sels.append(build_sel(display, odds, extra))
    return dedupe(build_market(market_name, sels))

def parse_shots_markets(lines, home, away) -> list:
    markets = []
    def add(m):
        if m["selection_count"]:
            markets.append(m)
    add(parse_player_shots_on_target(lines))
    add(parse_xor_more(lines, "Match Shots", "Match Shots",
                       ["Match Shots On Target", "Player To Have 1 or More Shots on Target in Each Half"]))
    add(parse_xor_more(lines, "Match Shots On Target", "Match Shots On Target",
                       ["Player To Have 1 or More Shots on Target in Each Half",
                        "Player Shots In The 1st Half", "Home Team Shots on Target in Each Half"]))
    add(parse_xor_more(lines, "Team Shots On Target", "Home Shots On Target",
                       ["Team Shots", "Match Shots"], team=home))
    add(parse_xor_more(lines, "Team Shots", "Away Shots",
                       ["Match Shots", "Match Shots On Target"], team=away))
    return markets

# ---------------------------------------------------------------------------
# CARDS/FOULS TAB
# ---------------------------------------------------------------------------

def parse_player_card(lines) -> dict:
    block = get_first_block(lines, ["Player Shown a Card", "Player To Be Carded", "Player Cards"],
                            ["Player To Commit A Foul", "Player To Be Fouled", "Cards Over/Under Markets"])
    sels, seen = [], set()
    for i, line in enumerate(block):
        player = clean(line)
        if is_junk_player(player) or i + 1 >= len(block):
            continue
        odds = clean(block[i + 1])
        if not is_odds(odds):
            continue
        key = player.lower()
        if key in seen:
            continue
        seen.add(key)
        sels.append(build_sel(f"{player} To Be Carded", odds, {"player": player, "prop_type": "player_card"}))
    return dedupe(build_market("Player Cards", sels))

def parse_player_fouls_committed(lines) -> dict:
    block = get_block(lines, "Player To Commit A Foul",
                      ["Player To Commit 1 Or More Fouls In First Half", "Player To Be Fouled", "Cards Over/Under Markets"])
    return _parse_player_threshold(block, "Player Fouls Committed", "fouls_committed", "{player} {threshold} Fouls Committed")

def parse_player_fouls_won(lines) -> dict:
    block = get_block(lines, "Player To Be Fouled", ["Player Foul Involvements", "Cards Over/Under Markets"])
    return _parse_player_threshold(block, "Player Fouls Won", "fouls_won", "{player} {threshold} Fouls Won")

def parse_cards_ou(lines) -> dict:
    block = get_block(lines, "Cards Over/Under Markets", ["Corner Over/Under Markets", "Home Total Corners", "Away Total Corners"])
    sels = []
    for i, line in enumerate(block):
        label = clean(line)
        m = re.match(r"Cards\s+Over/Under\s+([\d.]+)", label, re.I)
        if not m or i + 2 >= len(block):
            continue
        threshold = m.group(1)
        try:
            if float(threshold) > 7.5:
                continue
        except ValueError:
            pass
        over_odds, under_odds = clean(block[i + 1]), clean(block[i + 2])
        if is_odds(over_odds) and is_odds(under_odds):
            sels.append(build_sel(f"Over {threshold}",  over_odds,  {"side": "over",  "line": threshold}))
            sels.append(build_sel(f"Under {threshold}", under_odds, {"side": "under", "line": threshold}))
    return dedupe(build_market("Total Cards Over/Under", sels))

# ---------------------------------------------------------------------------
# CORNERS TAB
# ---------------------------------------------------------------------------

def parse_corners_ou(lines) -> dict:
    block = get_block(lines, "Corner Over/Under Markets", ["Home Total Corners", "Away Total Corners"])
    sels = []
    for i, line in enumerate(block):
        label = clean(line)
        m = re.match(r"Corners?\s+Over/Under\s+([\d.]+)", label, re.I)
        if not m or i + 2 >= len(block):
            continue
        threshold = m.group(1)
        try:
            if float(threshold) > 15.5:
                continue
        except ValueError:
            pass
        over_odds, under_odds = clean(block[i + 1]), clean(block[i + 2])
        if is_odds(over_odds) and is_odds(under_odds):
            sels.append(build_sel(f"Over {threshold} Corners",  over_odds,  {"side": "over",  "line": threshold}))
            sels.append(build_sel(f"Under {threshold} Corners", under_odds, {"side": "under", "line": threshold}))
    return dedupe(build_market("Total Corners Over/Under", sels))

def parse_team_corners_ou(lines, title, market_name, stops, team) -> dict:
    block = get_block(lines, title, stops)
    sels = []
    pat = re.compile(r"(?:Home|Away)\s+Total\s+Corners\s+([\d.]+)$", re.I)
    for i, line in enumerate(block):
        m = pat.match(clean(line))
        if not m or i + 2 >= len(block):
            continue
        threshold = m.group(1)
        over_odds, under_odds = clean(block[i + 1]), clean(block[i + 2])
        if not is_odds(over_odds) or not is_odds(under_odds):
            continue
        sels.append(build_sel(f"{team} Over {threshold}",  over_odds,  {"side": "over",  "line": threshold, "team": team}))
        sels.append(build_sel(f"{team} Under {threshold}", under_odds, {"side": "under", "line": threshold, "team": team}))
    return dedupe(build_market(market_name, sels))

# ---------------------------------------------------------------------------
# Master parser
# ---------------------------------------------------------------------------

def parse_tab(tab_param, lines, home, away) -> list:
    markets = []
    def add(m):
        if m.get("selection_count", 0) > 0:
            markets.append(m)

    if tab_param == "?tab=goals":
        add(parse_goals_ou(lines))
        first_gs, anytime_gs = parse_player_to_score(lines)
        add(first_gs)
        add(anytime_gs)
        add(parse_btts(lines))
    elif tab_param == "":
        add(parse_double_chance(lines, home, away))
        add(parse_half_time_result(lines, home, away))
    elif tab_param == "?tab=shots":
        for m in parse_shots_markets(lines, home, away):
            markets.append(m)
    elif tab_param == "?tab=cards-fouls":
        add(parse_player_card(lines))
        add(parse_player_fouls_committed(lines))
        add(parse_player_fouls_won(lines))
        add(parse_cards_ou(lines))
    elif tab_param == "?tab=corners":
        add(parse_corners_ou(lines))
        add(parse_team_corners_ou(lines, "Home Total Corners", "Home Total Corners", ["Away Total Corners"], home))
        add(parse_team_corners_ou(lines, "Away Total Corners", "Away Total Corners", [], away))

    return markets

# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def accept_cookies(page) -> None:
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass

def click_show_all(page) -> None:
    for text in ["Show all selections", "Show all", "Show more", "Show More"]:
        try:
            buttons = page.get_by_text(text, exact=True)
            for i in range(min(buttons.count(), 6)):
                try:
                    buttons.nth(i).click(timeout=700)
                    page.wait_for_timeout(300)
                except Exception:
                    pass
        except Exception:
            pass

def expand_section(page, heading) -> None:
    try:
        loc = page.get_by_text(heading, exact=True)
        if not loc.count():
            return
        el = loc.first
        el.scroll_into_view_if_needed(timeout=2000)
        page.wait_for_timeout(200)
        try:
            already_open = page.evaluate("""(h) => {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    if (node.textContent.trim() === h) {
                        let el = node.parentElement;
                        for (let i = 0; i < 6; i++) {
                            if (!el) break;
                            if (el.getAttribute('aria-expanded') === 'true') return true;
                            el = el.parentElement;
                        }
                        return false;
                    }
                }
                return false;
            }""", heading)
            if already_open:
                return
        except Exception:
            pass
        el.click(timeout=2000)
        page.wait_for_timeout(900)
        click_show_all(page)
    except Exception:
        pass

def get_body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""

# ---------------------------------------------------------------------------
# Match-link collection
# ---------------------------------------------------------------------------

def collect_match_links(page) -> list:
    print(f"Loading list page: {LIST_URL}")
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookies(page)
    for _ in range(25):
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(250)
    links = page.evaluate("""
        () => Array.from(document.querySelectorAll('a'))
            .map(a => ({ href: a.href, text: a.innerText }))
            .filter(x => x.href && x.href.includes('/football/fifa-world-cup/') && x.href.includes('-v-'))
    """)
    seen, out = set(), []
    for item in links:
        href = clean(item.get("href", "")).split("?")[0]
        if not href or href in seen:
            continue
        seen.add(href)
        out.append({"url": href, "text": clean(item.get("text", ""))})
    print(f"Found {len(out)} match links")
    return out

# ---------------------------------------------------------------------------
# Per-match scraper
# ---------------------------------------------------------------------------

def get_match_name(text) -> str:
    for line in [clean(x) for x in text.splitlines() if clean(x)]:
        if " v " in line and 5 < len(line) < 60:
            return line
    return ""

def scrape_match(page, url, fallback_text="") -> dict:
    base_url    = url.split("?")[0]
    all_markets = []
    tab_texts   = {}
    match_name  = ""

    for tab_param, headings in TABS.items():
        label = safe_label(tab_param)
        try:
            print(f"    tab={label}", end=" ... ", flush=True)
            page.goto(base_url + tab_param, wait_until="domcontentloaded", timeout=30000)
            wait_ms = 4000 if tab_param == "?tab=goals" else 2500
            page.wait_for_timeout(wait_ms)
            accept_cookies(page)
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(500)
            click_show_all(page)
            for heading in headings:
                expand_section(page, heading)
            page.wait_for_timeout(500)
            click_show_all(page)
            tab_text = get_body_text(page)
            tab_texts[label] = tab_text
            if not match_name:
                match_name = get_match_name(tab_text)
            print("ok")
        except PWTimeout:
            print("timeout")
            tab_texts[label] = ""
        except Exception as e:
            print(f"error: {e}")
            tab_texts[label] = ""

    match_name = match_name or fallback_text
    if " v " in match_name:
        home, away = [clean(x) for x in match_name.split(" v ", 1)]
    else:
        home, away = "", ""

    if home and away:
        for tab_param in TABS:
            label     = safe_label(tab_param)
            tab_lines = [clean(x) for x in tab_texts.get(label, "").splitlines() if clean(x)]
            try:
                all_markets.extend(parse_tab(tab_param, tab_lines, home, away))
            except Exception as e:
                import traceback
                print(f"    parse error ({label}): {e}")
                traceback.print_exc()

    slug     = slugify(match_name or url[-30:])
    combined = "\n\n".join(f"=== {safe_label(t)} ===\n{tab_texts.get(safe_label(t), '')}" for t in TABS)
    (DBG_DIR / f"{slug}_combined.txt").write_text(combined, encoding="utf-8")
    for lbl, text in tab_texts.items():
        (DBG_DIR / f"{slug}_{lbl}.txt").write_text(text, encoding="utf-8")

    return {
        "match":        match_name,
        "home_team":    home,
        "away_team":    away,
        "source_url":   url,
        "market_count": len(all_markets),
        "markets":      all_markets,
    }

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DBG_DIR.mkdir(parents=True, exist_ok=True)
    matches, errors = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page    = browser.new_page(viewport={"width": 1280, "height": 900})
        links   = collect_match_links(page)[:MAX_MATCHES]

        for idx, item in enumerate(links, 1):
            print(f"\n=== [{idx}/{len(links)}] {item.get('text') or item['url']} ===")
            try:
                result = scrape_match(page, item["url"], item.get("text", ""))
                matches.append(result)
                print(f"  → {result['match']} | {result['market_count']} markets")
                for m in result["markets"]:
                    print(f"      {m['market']:50s} {m['selection_count']} selections")
            except Exception as e:
                print(f"  ERROR: {e}")
                errors.append({"url": item["url"], "error": str(e)})

        browser.close()

    good   = [m for m in matches if m.get("market_count", 0) > 0]
    output = {
        "sport": "football", "competition": "FIFA World Cup", "bookmaker": "PaddyPower",
        "market_type": "props", "source_url": LIST_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(matches), "matches_with_markets": len(good),
        "error_count": len(errors), "errors": errors, "matches": matches,
    }
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅  Done — {len(good)}/{len(matches)} matches with markets → {OUT_PATH}")

if __name__ == "__main__":
    main()