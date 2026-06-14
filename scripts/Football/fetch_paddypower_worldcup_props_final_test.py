#!/usr/bin/env python3
"""
PaddyPower World Cup Props Scraper - final test: targeted shots + popular tackles/assists + robust cards

Scrapes:
- Match props: goals, BTTS, double chance, half time result, cards, corners
- Player props: first goalscorer, anytime goalscorer
- Player stats: shots, shots on target, tackles, assists, carded
- Team stats: team shots, team shots on target
- Match stats: match shots, match shots on target
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "football" / "data" / "paddypower_worldcup_props.json"
DBG_DIR = ROOT / "football" / "debug" / "paddypower_worldcup_props"

LIST_URL = "https://www.paddypower.com/fifa-world-cup"
MAX_MATCHES = 1  # change to 15 when happy

TABS = {
    "": ["Double Chance", "Half Time"],
    "?tab=popular": ["Player Tackles", "Player To Have 4 Or More Tackles", "Anytime Assist"],
    "?tab=goals": [
        "Over/Under Goals Markets",
        "Player to Score",
        "Both Teams to Score Markets",
        "Anytime Assist",
    ],
    "?tab=shots": [
        "Player Shots On Target Including Woodwork",
        "Player Shots 1 - 3",
        "Player Shots 4 - 6",
        "Player Tackles",
        "Player To Have 4 Or More Tackles",
        "Anytime Assist",
        "Team Shots On Target",
        "Team Shots",
        "Team To Have 5 Or More Shots",
        "Team To Have 6 Or More Shots",
        "Team To Have 7 Or More Shots",
        "Team To Have 8 Or More Shots",
        "Team To Have 9 Or More Shots",
        "Match Shots",
        "Match Shots On Target",
    ],
    "?tab=cards-fouls": [
        "Player Shown a Card",
        "Player To Commit A Foul",
        "Player To Be Fouled",
        "Cards Over/Under Markets",
    ],
    "?tab=corners": [
        "Corner Over/Under Markets",
        "Home Total Corners",
        "Away Total Corners",
    ],
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
    obj = {
        "selection": clean(selection),
        "normalized_selection": normalize(selection),
        "odds": clean(odds).upper(),
    }
    if extra:
        obj.update(extra)
    return obj


def build_market(name, selections) -> dict:
    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(selections),
        "selections": selections,
    }


def dedupe(market) -> dict:
    seen, out = set(), []
    for s in market.get("selections", []):
        key = (
            s.get("normalized_selection"),
            s.get("odds"),
            s.get("line"),
            s.get("threshold"),
            s.get("player"),
            s.get("team"),
            s.get("prop_type"),
            s.get("side"),
        )
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


def find_lines(lines, title) -> list:
    want = clean(title).lower()
    return [i for i, line in enumerate(lines) if clean(line).lower() == want]


def _candidate_block(lines, start, title, stops=None) -> list:
    stop_set = {clean(t).lower() for t in (stops or []) if clean(t).lower() != clean(title).lower()}
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if clean(lines[i]).lower() in stop_set:
            end = i
            break
    return lines[start:end]


def get_block(lines, title, stops=None) -> list:
    """
    Paddy pages often list market headings near the top and then repeat the
    real expanded market farther down with odds. The old version grabbed the
    first heading, which meant markets like Player SOT, Tackles and Assists
    sometimes returned the empty menu block instead of the real market block.

    This chooses the matching heading block with the most odds in it.
    """
    starts = find_lines(lines, title)
    if not starts:
        return []

    best_block = []
    best_score = -1

    for start in starts:
        block = _candidate_block(lines, start, title, stops)
        odds_count = sum(1 for x in block if is_odds(x))

        # Bonus if it looks like a proper table with threshold headers.
        threshold_count = sum(1 for x in block if clean(x).lower() in {"1+", "2+", "3+", "4+", "5+", "6+"})
        score = odds_count * 10 + threshold_count

        if score > best_score:
            best_score = score
            best_block = block

    return best_block


def get_first_block(lines, titles, stops=None) -> list:
    for title in titles:
        b = get_block(lines, title, stops)
        if b:
            return b
    return []


_JUNK_NAMES = {
    "super sub", "win more", "boosts", "show all selections", "show all", "show more",
    "show less", "show less selections", "over", "under", "1+", "2+", "3+", "4+", "5+", "6+",
    "first", "anytime", "yes", "no", "draw", "the draw", "no goalscorer",
}

_JUNK_SUBSTRINGS = [
    "you're betting", "means you win", "means you lose", "only cards shown",
    "going in the book", "stats below", "extra time", "penalty shootout",
    "tournament avg", "a free-kick", "a foul won", "cards awarded",
    "sports betting", "football betting", "popular events", "match odds",
    "both teams", "team with most", "over/under", "correct score",
    "bet builder", "corner ", "corners over/under", "own goals don",
    "shots that hit the woodwork", "no clean sheet", "have a pop",
    "opta guys", "what is and isn't", "applies to", "free bet", "t&cs",
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


def parse_player_threshold_section(lines, section_title, market_name, prop_type, label_tpl, stops, thresholds) -> dict:
    block = get_block(lines, section_title, stops)
    sels, seen = [], {}

    for i, line in enumerate(block):
        player = clean(line)
        if is_junk_player(player):
            continue

        odds_found = []
        j = i + 1
        while j < min(i + 14, len(block)) and len(odds_found) < len(thresholds):
            tok = clean(block[j])
            if is_odds(tok):
                odds_found.append(tok)
            elif tok.lower() in {"1+", "2+", "3+", "4+", "5+", "6+"} or re.match(r"^Tournament Avg:", tok, re.I):
                pass
            elif odds_found:
                break
            j += 1

        if not odds_found:
            continue

        key = player.lower()
        seen.setdefault(key, {"name": player, "odds": {}})
        for k, odd in enumerate(odds_found):
            if k < len(thresholds):
                seen[key]["odds"].setdefault(thresholds[k], odd)

    for _, pd in seen.items():
        for t in thresholds:
            if t in pd["odds"]:
                sels.append(build_sel(
                    label_tpl.format(player=pd["name"], threshold=t),
                    pd["odds"][t],
                    {"player": pd["name"], "prop_type": prop_type, "threshold": t},
                ))

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
            sels.append(build_sel(f"Over {threshold}", odds[0], {"side": "over", "line": threshold}))
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
        sels.append(build_sel(f"{base} - No", no_odds, {"side": "no"}))
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
        first_sels.append(build_sel(f"{player} First Goalscorer", first_odds, {"player": player, "prop_type": "first_goalscorer"}))
        anytime_sels.append(build_sel(f"{player} Anytime Goalscorer", anytime_odds, {"player": player, "prop_type": "anytime_goalscorer"}))

    return dedupe(build_market("First Goalscorer", first_sels)), dedupe(build_market("Anytime Goalscorer", anytime_sels))


def parse_anytime_assist(lines) -> dict:
    block = get_first_block(lines, ["Anytime Assist"], [
        "Player to Create Shots", "Player To Create 4 Or More Shots",
        "Player Shots 1 - 3", "Player Tackles", "To Score Or Assist",
        "Team Shots", "Match Shots",
    ])
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
        sels.append(build_sel(f"{player} Anytime Assist", odds, {"player": player, "prop_type": "anytime_assist"}))
    return dedupe(build_market("Anytime Assist", sels))


# ---------------------------------------------------------------------------
# MAIN TAB
# ---------------------------------------------------------------------------

def parse_double_chance(lines, home, away) -> dict:
    block = get_block(lines, "Double Chance", ["Player Foul Involvements", "Half Time", "Match Odds", "Team To Score the First Goal"])
    candidates = [
        (f"{home} And Draw", "home_draw"), (f"{away} And Draw", "away_draw"), (f"{home} And {away}", "home_away"),
        (f"{home} or Draw", "home_draw"), (f"{away} or Draw", "away_draw"), (f"{home} or {away}", "home_away"),
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
# SHOTS / STATS TAB
# ---------------------------------------------------------------------------

def parse_player_shots_on_target(lines) -> dict:
    return parse_player_threshold_section(
        lines, "Player Shots On Target Including Woodwork", "Player Shots On Target", "shots_on_target",
        "{player} {threshold} Shots On Target",
        ["Player To Have 4 Or More Shots On Target Including Woodwork", "Player Shots 1 - 3",
         "Player Shots 4 - 6", "Team Shots On Target", "Team Shots", "Match Shots"],
        ["1+", "2+", "3+"],
    )


def parse_player_shots_1_3(lines) -> dict:
    return parse_player_threshold_section(
        lines, "Player Shots 1 - 3", "Player Shots", "shots", "{player} {threshold} Shots",
        ["Player Shots 4 - 6", "Team Shots On Target", "Team Shots",
         "Team To Have 5 Or More Shots", "Match Shots", "Match Shots On Target"],
        ["1+", "2+", "3+"],
    )


def parse_player_shots_4_6(lines) -> dict:
    return parse_player_threshold_section(
        lines, "Player Shots 4 - 6", "Player Shots 4+", "shots", "{player} {threshold} Shots",
        ["Team Shots On Target", "Team Shots", "Team To Have 5 Or More Shots", "Match Shots", "Match Shots On Target"],
        ["4+", "5+", "6+"],
    )


def parse_player_tackles(lines) -> dict:
    return parse_player_threshold_section(
        lines, "Player Tackles", "Player Tackles", "tackles", "{player} {threshold} Tackles",
        ["Player To Have 4 Or More Tackles", "To Score Or Assist", "Anytime Assist",
         "Player to Create Shots", "Player Shots 1 - 3", "Team Shots"],
        ["1+", "2+", "3+"],
    )


def parse_player_tackles_4plus(lines) -> dict:
    return parse_player_threshold_section(
        lines, "Player To Have 4 Or More Tackles", "Player Tackles 4+", "tackles", "{player} 4+ Tackles",
        ["To Score Or Assist", "Anytime Assist", "Player to Create Shots", "Player Shots 1 - 3", "Team Shots"],
        ["4+"],
    )


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
            extra["threshold"] = f"{m.group(1)}+"
        sels.append(build_sel(display, odds, extra))
    return dedupe(build_market(market_name, sels))


def parse_team_market(lines, section_title, market_name, stops, home, away, prop_type) -> dict:
    block = get_block(lines, section_title, stops)
    sels = []
    current_team = None

    for i, line in enumerate(block):
        label = clean(line)
        if label.lower() == home.lower():
            current_team = home
            continue
        if label.lower() == away.lower():
            current_team = away
            continue

        m = re.search(r"(\d+)\s+or\s+more", label, re.I)
        if not m or i + 1 >= len(block):
            continue

        odds = clean(block[i + 1])
        if not is_odds(odds):
            continue

        line_no = m.group(1)
        team = current_team
        if not team:
            if home.lower() in label.lower():
                team = home
            elif away.lower() in label.lower():
                team = away

        sels.append(build_sel(
            f"{team + ' ' if team else ''}{line_no}+ {market_name}",
            odds,
            {"team": team, "side": "over", "line": line_no, "threshold": f"{line_no}+", "prop_type": prop_type},
        ))

    return dedupe(build_market(market_name, sels))


def parse_team_threshold_single_sections(lines, home, away) -> list:
    markets = []
    for n in range(5, 10):
        m = parse_team_market(
            lines, f"Team To Have {n} Or More Shots", "Team Shots",
            [f"Team To Have {n + 1} Or More Shots", "Match Shots", "Match Shots On Target"],
            home, away, "team_shots",
        )
        if m["selection_count"]:
            markets.append(m)
    return markets


def parse_shots_markets(lines, home, away) -> list:
    markets = []

    def add(m):
        if m.get("selection_count", 0):
            markets.append(m)

    add(parse_player_shots_on_target(lines))
    add(parse_player_shots_1_3(lines))
    add(parse_player_shots_4_6(lines))
    add(parse_player_tackles(lines))
    add(parse_player_tackles_4plus(lines))
    add(parse_anytime_assist(lines))

    add(parse_team_market(
        lines, "Team Shots On Target", "Team Shots On Target",
        ["Team Shots", "Team To Have 5 Or More Shots", "Match Shots", "Match Shots On Target"],
        home, away, "team_shots_on_target",
    ))
    add(parse_team_market(
        lines, "Team Shots", "Team Shots",
        ["Team To Have 5 Or More Shots", "Team To Have 6 Or More Shots", "Team To Have 7 Or More Shots",
         "Team To Have 8 Or More Shots", "Team To Have 9 Or More Shots", "Match Shots", "Match Shots On Target"],
        home, away, "team_shots",
    ))

    for m in parse_team_threshold_single_sections(lines, home, away):
        add(m)

    add(parse_xor_more(lines, "Match Shots", "Match Shots",
                       ["Match Shots On Target", "Player To Have 1 or More Shots on Target in Each Half"]))
    add(parse_xor_more(lines, "Match Shots On Target", "Match Shots On Target",
                       ["Player To Have 1 or More Shots on Target in Each Half", "Player Shots In The 1st Half",
                        "Home Team Shots on Target in Each Half", "Sports Betting"]))

    return markets


# ---------------------------------------------------------------------------
# CARDS / FOULS TAB
# ---------------------------------------------------------------------------

def parse_player_card(lines) -> dict:
    block = get_first_block(
        lines,
        ["Player Shown a Card", "Player To Be Carded", "Player Cards"],
        ["Player To Commit A Foul", "Player To Be Fouled", "Cards Over/Under Markets"],
    )

    sels, seen = [], set()

    # Paddy sometimes inserts helper text / Show More between the heading and players.
    # Scan for any clean player-looking line followed shortly by odds.
    for i, line in enumerate(block):
        player = clean(line)

        if is_junk_player(player):
            continue

        odds = ""
        for j in range(i + 1, min(i + 4, len(block))):
            tok = clean(block[j])
            if is_odds(tok):
                odds = tok
                break
            if tok and not is_junk_player(tok) and not re.match(r"^Tournament Avg:", tok, re.I):
                break

        if not odds:
            continue

        key = player.lower()
        if key in seen:
            continue

        seen.add(key)
        sels.append(
            build_sel(
                f"{player} To Be Carded",
                odds,
                {"player": player, "prop_type": "player_card"},
            )
        )

    return dedupe(build_market("Player Cards", sels))

def parse_player_fouls_committed(lines) -> dict:
    return parse_player_threshold_section(
        lines, "Player To Commit A Foul", "Player Fouls Committed", "fouls_committed",
        "{player} {threshold} Fouls Committed",
        ["Player To Commit 1 Or More Fouls In First Half", "Player To Be Fouled", "Cards Over/Under Markets"],
        ["1+", "2+", "3+"],
    )


def parse_player_fouls_won(lines) -> dict:
    return parse_player_threshold_section(
        lines, "Player To Be Fouled", "Player Fouls Won", "fouls_won",
        "{player} {threshold} Fouls Won",
        ["Player Foul Involvements", "Cards Over/Under Markets"],
        ["1+", "2+", "3+"],
    )


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
            sels.append(build_sel(f"Over {threshold}", over_odds, {"side": "over", "line": threshold}))
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
            sels.append(build_sel(f"Over {threshold} Corners", over_odds, {"side": "over", "line": threshold}))
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
        sels.append(build_sel(f"{team} Over {threshold}", over_odds, {"side": "over", "line": threshold, "team": team}))
        sels.append(build_sel(f"{team} Under {threshold}", under_odds, {"side": "under", "line": threshold, "team": team}))
    return dedupe(build_market(market_name, sels))


# ---------------------------------------------------------------------------
# MASTER PARSER
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
        add(parse_anytime_assist(lines))
    elif tab_param == "":
        add(parse_double_chance(lines, home, away))
        add(parse_half_time_result(lines, home, away))
    elif tab_param == "?tab=popular":
        add(parse_player_tackles(lines))
        add(parse_player_tackles_4plus(lines))
        add(parse_anytime_assist(lines))
    elif tab_param == "?tab=shots":
        for m in parse_shots_markets(lines, home, away):
            add(m)
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
# BROWSER HELPERS - QUICKER VERSION
# ---------------------------------------------------------------------------

def accept_cookies(page) -> None:
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=2500)
                page.wait_for_timeout(600)
                return
        except Exception:
            pass


def click_show_all(page) -> None:
    for text in ["Show all selections", "Show all", "Show more", "Show More"]:
        try:
            buttons = page.get_by_text(text, exact=True)
            for i in range(min(buttons.count(), 5)):
                try:
                    buttons.nth(i).click(timeout=600)
                    page.wait_for_timeout(180)
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
        el.scroll_into_view_if_needed(timeout=1500)
        page.wait_for_timeout(120)

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

        el.click(timeout=1500)
        page.wait_for_timeout(450)

    except Exception:
        pass


def quick_expand_tab(page, headings, tab_param=None) -> None:
    # One normal pass, then a tiny targeted pass for the markets that Paddy
    # tends to leave collapsed. This avoids the slow full double-pass.
    click_show_all(page)
    for heading in headings:
        expand_section(page, heading)
    click_show_all(page)

    targeted = []
    if tab_param == "?tab=shots":
        targeted = [
            "Player Shots On Target Including Woodwork",
            "Player Shots 1 - 3",
            "Player Shots 4 - 6",
        ]
    elif tab_param == "?tab=popular":
        targeted = [
            "Player Tackles",
            "Player To Have 4 Or More Tackles",
            "Anytime Assist",
        ]
    elif tab_param == "?tab=goals":
        targeted = ["Anytime Assist"]

    for heading in targeted:
        expand_section(page, heading)
        click_show_all(page)


def get_body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=9000)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# MATCH LINK COLLECTION
# ---------------------------------------------------------------------------

def collect_match_links(page) -> list:
    print(f"Loading list page: {LIST_URL}")
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4500)
    accept_cookies(page)

    for _ in range(20):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(180)

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
# PER MATCH SCRAPER
# ---------------------------------------------------------------------------

def get_match_name(text) -> str:
    for line in [clean(x) for x in text.splitlines() if clean(x)]:
        if " v " in line and 5 < len(line) < 60:
            return line
    return ""


def scrape_match(page, url, fallback_text="") -> dict:
    base_url = url.split("?")[0]
    all_markets = []
    tab_texts = {}
    match_name = ""

    for tab_param, headings in TABS.items():
        label = safe_label(tab_param)
        try:
            print(f"    tab={label}", end=" ... ", flush=True)

            page.goto(base_url + tab_param, wait_until="domcontentloaded", timeout=30000)
            wait_ms = 3000 if tab_param in ("?tab=goals", "?tab=shots", "?tab=popular") else 2200
            page.wait_for_timeout(wait_ms)

            accept_cookies(page)

            # one scroll to load content, one quick expansion pass, no double pass
            page.mouse.wheel(0, 3200)
            page.wait_for_timeout(350)

            quick_expand_tab(page, headings, tab_param)

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
            label = safe_label(tab_param)
            tab_lines = [clean(x) for x in tab_texts.get(label, "").splitlines() if clean(x)]
            try:
                all_markets.extend(parse_tab(tab_param, tab_lines, home, away))
            except Exception as e:
                import traceback
                print(f"    parse error ({label}): {e}")
                traceback.print_exc()

    slug = slugify(match_name or url[-30:])
    combined = "\n\n".join(f"=== {safe_label(t)} ===\n{tab_texts.get(safe_label(t), '')}" for t in TABS)
    (DBG_DIR / f"{slug}_combined.txt").write_text(combined, encoding="utf-8")
    for lbl, text in tab_texts.items():
        (DBG_DIR / f"{slug}_{lbl}.txt").write_text(text, encoding="utf-8")

    return {
        "match": match_name,
        "home_team": home,
        "away_team": away,
        "source_url": url,
        "market_count": len(all_markets),
        "markets": all_markets,
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DBG_DIR.mkdir(parents=True, exist_ok=True)

    matches, errors = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        links = collect_match_links(page)[:MAX_MATCHES]

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

    good = [m for m in matches if m.get("market_count", 0) > 0]

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "PaddyPower",
        "market_type": "props",
        "source_url": LIST_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(matches),
        "matches_with_markets": len(good),
        "error_count": len(errors),
        "errors": errors,
        "matches": matches,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅  Done — {len(good)}/{len(matches)} matches with markets → {OUT_PATH}")


if __name__ == "__main__":
    main()
