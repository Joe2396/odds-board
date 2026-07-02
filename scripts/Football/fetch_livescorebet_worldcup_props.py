#!/usr/bin/env python3
import json
import os
import re
import sys
import shutil
import time
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

LIVE_OUT_PATH = ROOT / "football" / "data" / "livescorebet_worldcup_props.json"
LEGACY_STAGING_PATH = ROOT / "football" / "data" / "livescorebet_worldcup_props_PRODUCTION_V3_STAGING.json"
STAGING_OUT_PATH = ROOT / "football" / "data" / "livescorebet_worldcup_props_PRODUCTION_V4_STAGING.json"
OUT_PATH = STAGING_OUT_PATH

DEBUG_DIR = ROOT / "football" / "debug" / "livescorebet_worldcup_props_PRODUCTION_V4"
VALIDATION_REPORT_PATH = DEBUG_DIR / "production_validation_report.json"
BACKUP_DIR = ROOT / "football" / "data" / "backups"
MAX_FAILURE_DEBUG_CHARS = 500_000
MIN_ACTIVE_FIXTURES = 3

COUPON_URL     = "https://www.livescorebet.com/ie/coupon/21127/"
PLAYER_GRP_ID  = "757"
MAX_MATCHES = 7
ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
SCOPE_MARKER = "__LSB_SCOPE__"

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

MARKET_STOP_HEADINGS = {
    "Both Teams to Score",
    "Total Goals",
    "First Goal (Draw: No Goals)",
    "Double Chance",
    "Draw No Bet",
    "Correct Score",
    "Goalscorer",
    "Team to Win and Both Teams to Score",
    "Half Time/Full Time",
    "3-Way Handicap",
    "Total Corners",
    "Most Corners",
    "Total Cards",
    "Most Cards",
    "To Get a Card",
    "Total Shots on Target",
    "Total Shots",
    "Player's shots on target",
    "Player's shots",
    "Player's fouls conceded",
    "Player's tackles completed",
    "To give an assist",
}

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))

def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")

def slugify(s):
    return normalize(s).replace("_", "-")

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
    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(selections),
        "selections": selections,
    }

def dedupe_market(market):
    seen = set()
    out = []
    for s in market.get("selections", []):
        key = (
            s.get("normalized_selection"),
            s.get("odds"),
            s.get("line"),
            s.get("side"),
            s.get("player"),
            s.get("team"),
            s.get("prop_type"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    market["selections"] = out
    market["selection_count"] = len(out)
    return market

# ── Match market parsers ─────────────────────────────────────────────────────

def parse_match_result(lines, home, away):
    selections = []
    for i in range(len(lines) - 6):
        if (
            clean(lines[i]) == "Full Time"
            and clean(lines[i + 1]) == home
            and clean(lines[i + 2]) == "Draw"
            and clean(lines[i + 3]) == away
            and is_odds(lines[i + 4])
            and is_odds(lines[i + 5])
            and is_odds(lines[i + 6])
        ):
            selections = [
                sel(home, lines[i + 4], {"side": "home"}),
                sel("Draw", lines[i + 5], {"side": "draw"}),
                sel(away, lines[i + 6], {"side": "away"}),
            ]
            break
    return dedupe_market(mkt("Match Betting", selections))

def parse_btts(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Both Teams to Score"), -1)
    if idx == -1:
        return mkt("Both Teams To Score", selections)

    block = lines[idx:idx + 35]
    period_map = {
        "Full time": "Both Teams To Score",
        "Full Time": "Both Teams To Score",
        "1st Half": "Both Teams To Score in the First Half",
        "2nd Half": "Both Teams To Score in the Second Half",
    }

    for i, line in enumerate(block):
        label = clean(line)
        if label in period_map and i + 2 < len(block):
            yes_odds = clean(block[i + 1])
            no_odds = clean(block[i + 2])
            if is_odds(yes_odds) and is_odds(no_odds):
                base = period_map[label]
                selections.append(sel(f"{base} - Yes", yes_odds, {"side": "yes"}))
                selections.append(sel(f"{base} - No", no_odds, {"side": "no"}))

    return dedupe_market(mkt("Both Teams To Score", selections))

def parse_total_goals(lines):
    markets = parse_scoped_ou(lines, "Total Goals", "Goals", max_line=5.5)
    return markets[0] if markets else mkt("Total Goals Over / Under", [])

def parse_total_corners(lines):
    markets = parse_scoped_ou(lines, "Total Corners", "Corners", max_line=15.5)
    return markets[0] if markets else mkt("Total Corners Over / Under", [])

def parse_total_cards(lines):
    markets = parse_scoped_ou(lines, "Total Cards", "Cards", max_line=8.5)
    return markets[0] if markets else mkt("Total Cards Over / Under", [])

def parse_total_shots_on_target_scoped(lines, home, away):
    # Shots scopes are tabbed on LiveScoreBet. Only trust text captured
    # immediately after an explicit scope click. Parsing the full page body can
    # attach the active "Both Teams Combined" prices to the final visible team
    # tab, which creates false team-total arbitrage opportunities.
    return parse_scoped_markers(
        lines,
        "Total Shots on Target",
        "Shots On Target",
        max_line=12.5,
    )

def parse_total_shots_scoped(lines, home, away):
    # See parse_total_shots_on_target_scoped: marker captures are deliberately
    # fail-closed. Missing scope captures are safer than mislabelled team odds.
    return parse_scoped_markers(
        lines,
        "Total Shots",
        "Shots",
        max_line=35.5,
    )

def parse_scoped_ou(lines, heading, label_suffix, max_line=None, home=None, away=None):
    idx = next((i for i, l in enumerate(lines) if clean(l) == heading), -1)
    if idx == -1:
        return []

    block = lines[idx:idx + 150]

    scopes = ["Both Teams Combined"]
    if home:
        scopes.append(home)
    if away:
        scopes.append(away)

    scope_positions = []
    for i, line in enumerate(block):
        label = clean(line)
        if label in scopes:
            scope_positions.append((label, i))

    if not scope_positions:
        return []

    markets = []

    for scope_idx, (scope, pos) in enumerate(scope_positions):
        end = len(block)
        if scope_idx + 1 < len(scope_positions):
            end = scope_positions[scope_idx + 1][1]

        scope_block = block[pos:end]
        selections = []

        for i, line in enumerate(scope_block):
            label = clean(line)

            if label in {"Over", "Under"}:
                continue

            if label in WORLD_CUP_TEAMS or label == "Both Teams Combined":
                continue

            if re.match(r"^\d+(?:\.\d+)?$", label):
                if i + 2 >= len(scope_block):
                    continue

                over_odds = clean(scope_block[i + 1])
                under_odds = clean(scope_block[i + 2])

                if not is_odds(over_odds) or not is_odds(under_odds):
                    continue

                try:
                    if max_line is not None and float(label) > float(max_line):
                        continue
                except Exception:
                    pass

                selections.append(sel(f"Over {label}", over_odds, {"side": "over", "line": label}))
                selections.append(sel(f"Under {label}", under_odds, {"side": "under", "line": label}))

        if not selections:
            continue

        if scope == "Both Teams Combined":
            market_name = f"Total {label_suffix} Over / Under"
        elif home and scope == home:
            market_name = f"{home} {label_suffix} Over / Under"
        elif away and scope == away:
            market_name = f"{away} {label_suffix} Over / Under"
        else:
            market_name = f"{scope} {label_suffix} Over / Under"

        markets.append(dedupe_market(mkt(market_name, selections)))

    return markets


def parse_scoped_markers(lines, heading, label_suffix, max_line=None):
    markers = []
    for i, line in enumerate(lines):
        line = clean(line)
        if line.startswith(SCOPE_MARKER + "|"):
            parts = line.split("|", 2)
            if len(parts) == 3 and parts[1] == heading:
                markers.append((i, parts[2]))

    markets = []
    for n, (start, scope) in enumerate(markers):
        end = markers[n + 1][0] if n + 1 < len(markers) else len(lines)
        chunk = lines[start + 1:end]
        idx = next((i for i, l in enumerate(chunk) if clean(l) == heading), -1)
        if idx == -1:
            continue

        block = chunk[idx:idx + 140]
        selections = []

        for i, line in enumerate(block):
            label = clean(line)
            if not re.match(r"^\d+(?:\.\d+)?$", label):
                continue
            if i + 2 >= len(block):
                continue

            over_odds = clean(block[i + 1])
            under_odds = clean(block[i + 2])
            if not is_odds(over_odds) or not is_odds(under_odds):
                continue

            try:
                if max_line is not None and float(label) > float(max_line):
                    continue
            except Exception:
                pass

            extra_o = {"side": "over", "line": label}
            extra_u = {"side": "under", "line": label}

            if scope != "Both Teams Combined":
                extra_o["team"] = scope
                extra_u["team"] = scope
                selections.append(sel(f"{scope} Over {label}", over_odds, extra_o))
                selections.append(sel(f"{scope} Under {label}", under_odds, extra_u))
            else:
                selections.append(sel(f"Over {label}", over_odds, extra_o))
                selections.append(sel(f"Under {label}", under_odds, extra_u))

        if not selections:
            continue

        if scope == "Both Teams Combined":
            market_name = f"Total {label_suffix} Over / Under"
        else:
            market_name = f"{scope} {label_suffix} Over / Under"

        markets.append(dedupe_market(mkt(market_name, selections)))

    return markets

def parse_double_chance(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Double Chance"), -1)
    if idx == -1:
        return mkt("Double Chance", selections)

    block = lines[idx:idx + 40]
    label_map = {
        "1X": "Home or Draw",
        "X2": "Away or Draw",
        "12": "Home or Away",
    }

    labels = [clean(l) for l in block if clean(l) in label_map]
    odds = [clean(l) for l in block if is_odds(l)]

    for i, label in enumerate(labels[:7]):
        if i < len(odds):
            selections.append(sel(label_map[label], odds[i]))

    return dedupe_market(mkt("Double Chance", selections))

def parse_half_time_result(lines, home, away):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) in {"Half Time", "Half-Time Result", "Half Time Result"}), -1)
    if idx == -1:
        idx = next((i for i, l in enumerate(lines) if clean(l) == "1st Half"), -1)
    if idx == -1:
        return mkt("Half Time Result", selections)

    block = lines[idx:idx + 60]

    for i in range(len(block) - 6):
        if (
            clean(block[i]) == home
            and clean(block[i + 1]) == "Draw"
            and clean(block[i + 2]) == away
            and is_odds(block[i + 3])
            and is_odds(block[i + 4])
            and is_odds(block[i + 5])
        ):
            selections = [
                sel(home, block[i + 3], {"side": "home"}),
                sel("Draw", block[i + 4], {"side": "draw"}),
                sel(away, block[i + 5], {"side": "away"}),
            ]
            break

    return dedupe_market(mkt("Half Time Result", selections))

def parse_ht_ft(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Half Time/Full Time"), -1)
    if idx == -1:
        return mkt("Half Time / Full Time", selections)

    block = lines[idx:idx + 40]
    for i, line in enumerate(block):
        label = clean(line)
        if "/" in label and i + 1 < len(block) and is_odds(block[i + 1]):
            selections.append(sel(label, block[i + 1]))

    return dedupe_market(mkt("Half Time / Full Time", selections))

def parse_most_corners(lines, home, away):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "Most Corners"), -1)
    if idx == -1:
        return mkt("Team With Most Corners", selections)

    block = lines[idx:idx + 35]

    for i in range(len(block) - 6):
        if (
            clean(block[i]) == home
            and clean(block[i + 1]) == "Draw"
            and clean(block[i + 2]) == away
            and clean(block[i + 3]) == "Full time"
            and is_odds(block[i + 4])
            and is_odds(block[i + 5])
            and is_odds(block[i + 6])
        ):
            selections = [
                sel(home, block[i + 4], {"side": "home"}),
                sel("Draw", block[i + 5], {"side": "draw"}),
                sel(away, block[i + 6], {"side": "away"}),
            ]
            break

    return dedupe_market(mkt("Team With Most Corners", selections))

# ── Player parsers ───────────────────────────────────────────────────────────

def parse_goalscorers(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) in {"Goalscorer", "Player to Score"}), -1)
    if idx == -1:
        return mkt("Player to Score", selections)

    skip = {
        "Goalscorer", "Player to Score", "First", "Anytime", "View more",
        "SUB", "PAYOUT", "applies to these markets", "Goal Method",
    } | WORLD_CUP_TEAMS

    block = lines[idx:idx + 220]

    i = 0
    while i < len(block):
        player = clean(block[i])

        if not player or player in skip or is_odds(player) or len(player) > 50:
            i += 1
            continue

        if i + 2 < len(block) and is_odds(block[i + 1]) and is_odds(block[i + 2]):
            selections.append(sel(
                f"{player} First Goalscorer",
                block[i + 1],
                {"player": player, "prop_type": "first_goalscorer"},
            ))
            selections.append(sel(
                f"{player} Anytime Goalscorer",
                block[i + 2],
                {"player": player, "prop_type": "anytime_goalscorer"},
            ))
            i += 3
        else:
            i += 1

    return dedupe_market(mkt("Player to Score", selections))

def parse_player_shots_on_target(lines):
    return _parse_player_over_market(lines, "Player's shots on target", "Shots On Target", "shots_on_target")

def parse_player_shots(lines):
    return _parse_player_over_market(lines, "Player's shots", "Shots", "shots")

def parse_player_fouls_conceded(lines):
    return _parse_player_over_market(lines, "Player's fouls conceded", "Player Fouls Conceded", "fouls_conceded")

def parse_player_tackles_completed(lines):
    return _parse_player_over_market(lines, "Player's tackles completed", "Player Tackles Completed", "tackles_completed")

def _parse_player_over_market(lines, header, market_name, prop_type):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == header), -1)
    if idx == -1:
        return mkt(market_name, selections)

    block = lines[idx:idx + 320]

    thresholds = []
    threshold_idx = -1

    for i, line in enumerate(block[:35]):
        label = clean(line)
        if re.match(r"^Over \d+(?:\.\d+)?$", label):
            if threshold_idx == -1:
                threshold_idx = i
            thresholds.append(label.replace("Over ", ""))

    if not thresholds:
        return mkt(market_name, selections)

    n = len(thresholds)

    i = threshold_idx + n
    team_name_count = 0
    while i < len(block):
        player = clean(block[i])

        # Stop when we hit the second team tab (e.g. Paraguay after USA)
        if player in WORLD_CUP_TEAMS:
            team_name_count += 1
            if team_name_count >= 2:
                break
            i += 1
            continue

        if not player or player in {header, "View more"} or is_odds(player) or len(player) > 50:
            i += 1
            continue

        odds_found = []
        for j in range(1, n + 1):
            if i + j < len(block) and is_odds(block[i + j]):
                odds_found.append(clean(block[i + j]))
            else:
                break

        if odds_found:
            for k, odds in enumerate(odds_found):
                threshold = thresholds[k]
                selections.append(sel(
                    f"{player} Over {threshold} {market_name}",
                    odds,
                    {"player": player, "line": threshold, "side": "over", "prop_type": prop_type},
                ))
            i += len(odds_found) + 1
        else:
            i += 1

    return dedupe_market(mkt(market_name, selections))

def parse_player_assists(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "To give an assist"), -1)
    if idx == -1:
        return mkt("Player To Assist", selections)

    skip = {"To give an assist", "View more"} | WORLD_CUP_TEAMS
    block = lines[idx:idx + 80]

    i = 0
    while i < len(block):
        player = clean(block[i])
        if not player or player in skip or is_odds(player) or len(player) > 50:
            i += 1
            continue

        if i + 1 < len(block) and is_odds(block[i + 1]):
            selections.append(sel(f"{player} To Assist", block[i + 1], {"player": player}))
            i += 2
        else:
            i += 1

    return dedupe_market(mkt("Player To Assist", selections))

def parse_player_cards(lines):
    selections = []
    idx = next((i for i, l in enumerate(lines) if clean(l) == "To Get a Card"), -1)
    if idx == -1:
        return mkt("Player To Get A Card", selections)

    skip = {"To Get a Card", "View more"} | WORLD_CUP_TEAMS
    block = lines[idx:idx + 100]

    i = 0
    while i < len(block):
        player = clean(block[i])
        if not player or player in skip or is_odds(player) or len(player) > 50:
            i += 1
            continue

        if i + 1 < len(block) and is_odds(block[i + 1]):
            selections.append(sel(f"{player} To Get A Card", block[i + 1], {"player": player}))
            i += 2
        else:
            i += 1

    return dedupe_market(mkt("Player To Get A Card", selections))

# ── Master parsers ───────────────────────────────────────────────────────────

def parse_standard_props(text, home, away):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    markets = []

    basic_parsers = [
        (parse_match_result, (lines, home, away)),
        (parse_btts, (lines,)),
        (parse_total_goals, (lines,)),
        (parse_double_chance, (lines,)),
        (parse_half_time_result, (lines, home, away)),
        (parse_ht_ft, (lines,)),
        (parse_goalscorers, (lines,)),
        (parse_total_corners, (lines,)),
        (parse_most_corners, (lines, home, away)),
        (parse_total_cards, (lines,)),
        (parse_player_cards, (lines,)),
        (parse_player_shots_on_target, (lines,)),
    ]

    for parser, args in basic_parsers:
        try:
            market = parser(*args)
            if market["selections"]:
                markets.append(market)
        except Exception as e:
            print(f"    Parser error ({parser.__name__}): {e}")

    for scoped_func in [parse_total_shots_on_target_scoped, parse_total_shots_scoped]:
        try:
            scoped_markets = scoped_func(lines, home, away)
            for market in scoped_markets:
                if market["selections"]:
                    markets.append(market)
        except Exception as e:
            print(f"    Parser error ({scoped_func.__name__}): {e}")

    return markets

def parse_player_props(text):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    markets = []

    for parser in [
        parse_goalscorers,
        parse_player_shots_on_target,
        parse_player_shots,
        parse_player_fouls_conceded,
        parse_player_tackles_completed,
        parse_player_assists,
        parse_player_cards,
    ]:
        try:
            market = parser(lines)
            if market["selections"]:
                markets.append(market)
        except Exception as e:
            print(f"    Parser error ({parser.__name__}): {e}")

    return markets

# ── Browser helpers ──────────────────────────────────────────────────────────

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
                    page.wait_for_timeout(500)
                except Exception:
                    pass
    except Exception:
        pass

def wait_for_market_content(page, ready_markers=None, timeout_ms=4500):
    """
    Wait until the page has fractional prices and one expected market marker.

    This retains the old 4.5 second maximum but usually returns much earlier.
    """
    markers = [clean(x) for x in (ready_markers or []) if clean(x)]
    started = time.perf_counter()

    while (time.perf_counter() - started) * 1000 < timeout_ms:
        try:
            state = page.evaluate(
                r"""
                (markers) => {
                    const text = document.body
                        ? (document.body.innerText || '')
                        : '';
                    const odds = text.match(
                        /(?:^|\s)(?:\d+\/\d+|EVS|EVENS|EVEN)(?=\s|$)/gmi
                    ) || [];
                    const markerFound =
                        !markers.length ||
                        markers.some(marker => text.includes(marker));
                    return {
                        markerFound,
                        oddsCount: odds.length,
                        textLength: text.length
                    };
                }
                """,
                markers,
            )
        except Exception:
            state = {}

        if (
            state.get("markerFound")
            and state.get("oddsCount", 0) >= 3
            and state.get("textLength", 0) >= 500
        ):
            return round(time.perf_counter() - started, 2)

        page.wait_for_timeout(250)

    return round(time.perf_counter() - started, 2)


def collect_loaded_page_text(
    page,
    scroll_steps=18,
    ready_markers=None,
    accept_cookie_banner=True,
):
    ready_seconds = wait_for_market_content(
        page,
        ready_markers=ready_markers,
        timeout_ms=4500,
    )

    if accept_cookie_banner:
        accept_cookies(page)

    scroll_started = time.perf_counter()

    for _ in range(scroll_steps):
        page.mouse.wheel(0, 650)
        page.wait_for_timeout(250)

    expand_view_more(page)
    page.keyboard.press("Control+Home")
    page.wait_for_timeout(400)

    text = page.locator("body").inner_text(timeout=30000)

    return text, {
        "ready_seconds": ready_seconds,
        "scroll_expand_seconds": round(
            time.perf_counter() - scroll_started,
            2,
        ),
    }


def get_page_text(
    page,
    url,
    scroll_steps=18,
    ready_markers=None,
):
    navigation_started = time.perf_counter()
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )
    dom_seconds = round(
        time.perf_counter() - navigation_started,
        2,
    )

    text, timing = collect_loaded_page_text(
        page,
        scroll_steps=scroll_steps,
        ready_markers=ready_markers,
        accept_cookie_banner=True,
    )
    timing["domcontentloaded_seconds"] = dom_seconds
    return text, timing


def get_match_links(page):
    """
    Conservative fixture discovery.

    The original V1 waited 8 seconds and always performed 20 scrolls. This
    version polls the same link selector and stops only after all 15 links have
    appeared and the count is stable. It falls back to the full 20 rounds.
    """
    print(f"Opening coupon page: {COUPON_URL}")

    page.goto(
        COUPON_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(1800)
    accept_cookies(page)

    target_count = 15
    stable_rounds = 0
    previous_count = -1
    links = []

    for round_index in range(20):
        try:
            links = page.evaluate(
                """
                () => [...new Set(
                    Array.from(document.querySelectorAll('a'))
                        .map(a => a.href)
                        .filter(h =>
                            h &&
                            h.includes('/world-cup-2026/') &&
                            h.includes('/SBTE_')
                        )
                )]
                """
            )
        except Exception:
            links = []

        current_count = len(links)

        if current_count == previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0

        print(
            f"  coupon links after round "
            f"{round_index + 1}: {current_count}"
        )

        if (
            current_count >= target_count
            and stable_rounds >= 1
        ):
            break

        previous_count = current_count
        page.mouse.wheel(0, 750)
        page.wait_for_timeout(350)

    # Final read after the last scroll.
    try:
        final_links = page.evaluate(
            """
            () => [...new Set(
                Array.from(document.querySelectorAll('a'))
                    .map(a => a.href)
                    .filter(h =>
                        h &&
                        h.includes('/world-cup-2026/') &&
                        h.includes('/SBTE_')
                    )
            )]
            """
        )
        if len(final_links) > len(links):
            links = final_links
    except Exception:
        pass

    fixtures = []
    seen = set()

    for url in links:
        base_url = url.split("?")[0]
        if base_url in seen:
            continue

        seen.add(base_url)
        slug = (
            base_url
            .split("/world-cup-2026/")[-1]
            .split("/")[0]
        )
        name = slug.replace("-", " ").title()

        fixtures.append({
            "url": base_url,
            "name": name,
        })

    print(f"Found {len(fixtures)} match links")
    return fixtures[:MAX_MATCHES]


def detect_teams(text, fallback_slug=""):
    lines = [clean(l) for l in text.splitlines() if clean(l)]

    for i, line in enumerate(lines):
        if line in WORLD_CUP_TEAMS and i + 2 < len(lines):
            if clean(lines[i + 1]) == "Draw" and clean(lines[i + 2]) in WORLD_CUP_TEAMS:
                return line, lines[i + 2]

    return "", ""


def _has_fractional_price(text):
    return bool(re.search(r"(?:^|\s)(?:\d+/\d+|EVS|EVENS|EVEN)(?:\s|$)", clean(text), re.I))


def _visible_exact_text(root, text):
    """Return the first visible exact-text locator inside root."""
    try:
        loc = root.get_by_text(text, exact=True)
        for i in range(loc.count()):
            item = loc.nth(i)
            try:
                if item.is_visible():
                    return item
            except Exception:
                continue
    except Exception:
        pass
    return None


def _market_container(page, heading, require_prices=False):
    """
    Find the smallest visible ancestor containing one specific market card.

    LiveScoreBet repeats scope labels elsewhere on the page. Scoping clicks to
    the card containing the requested heading prevents a click intended for
    "Total Shots on Target" from hitting a similarly named tab in another card.
    """
    try:
        headings = page.get_by_text(heading, exact=True)
        for i in range(headings.count()):
            heading_loc = headings.nth(i)
            try:
                if not heading_loc.is_visible():
                    continue
            except Exception:
                continue

            node = heading_loc
            for _ in range(10):
                try:
                    node = node.locator("xpath=..")
                    text = clean(node.inner_text(timeout=1500))
                except Exception:
                    break

                if heading not in text:
                    continue

                has_scope_tabs = "Both Teams Combined" in text
                has_ou_headers = "Over" in text and "Under" in text
                has_prices = _has_fractional_price(text)

                if has_scope_tabs and has_ou_headers and (has_prices or not require_prices):
                    return node
    except Exception:
        pass
    return None


def _scope_state(item):
    """
    Return True/False when the DOM exposes an active state, otherwise None.

    The site has changed its tab markup before, so this checks ARIA flags,
    active/selected class names, data attributes, and the visible underline.
    """
    try:
        return item.evaluate(
            """el => {
                const nodes = [el, el.parentElement, el.parentElement && el.parentElement.parentElement]
                    .filter(Boolean);
                let sawExplicitFalse = false;

                for (const node of nodes) {
                    const attrs = [
                        node.getAttribute('aria-selected'),
                        node.getAttribute('aria-pressed'),
                        node.getAttribute('data-active'),
                        node.getAttribute('data-selected')
                    ].filter(v => v !== null);

                    if (attrs.some(v => String(v).toLowerCase() === 'true')) return true;
                    if (attrs.some(v => String(v).toLowerCase() === 'false')) sawExplicitFalse = true;

                    const cls = String(node.className || '').toLowerCase();
                    if (/(^|[\\s_-])(active|selected|current)([\\s_-]|$)/.test(cls)) return true;

                    const style = getComputedStyle(node);
                    if (parseFloat(style.borderBottomWidth || '0') >= 2 &&
                        style.borderBottomStyle !== 'none' &&
                        style.borderBottomColor !== 'rgba(0, 0, 0, 0)') {
                        return true;
                    }

                    for (const child of node.children || []) {
                        const cs = getComputedStyle(child);
                        if (parseFloat(cs.borderBottomWidth || '0') >= 2 &&
                            cs.borderBottomStyle !== 'none' &&
                            cs.borderBottomColor !== 'rgba(0, 0, 0, 0)') {
                            return true;
                        }
                    }
                }

                return sawExplicitFalse ? false : null;
            }"""
        )
    except Exception:
        return None


def _detect_active_scope(container, scopes):
    active = []
    for scope in scopes:
        item = _visible_exact_text(container, scope)
        if item is None:
            continue
        if _scope_state(item) is True:
            active.append(scope)
    return active[0] if len(active) == 1 else ""


def expand_view_more_in_market(page, container):
    """Expand only buttons belonging to the current market card."""
    try:
        buttons = container.get_by_text("View more", exact=True)
        count = buttons.count()
        for i in range(count):
            try:
                button = buttons.nth(i)
                if not button.is_visible():
                    continue
                button.scroll_into_view_if_needed(timeout=2000)
                button.click(timeout=3000)
                page.wait_for_timeout(450)
            except Exception:
                pass
    except Exception:
        pass


def click_market_heading_if_needed(page, heading):
    try:
        item = _visible_exact_text(page, heading)
        if item is None:
            return False

        item.scroll_into_view_if_needed(timeout=2500)
        page.wait_for_timeout(300)

        container = _market_container(page, heading, require_prices=True)
        if container is None:
            item.click(timeout=2500)
            page.wait_for_timeout(1000)

        return _market_container(page, heading, require_prices=False) is not None
    except Exception as e:
        print(f"    heading open failed: {heading}: {e}")
        return False


def capture_scope_market_text(page, heading, scope, all_scopes):
    """
    Click one scope within one market and return only that market card's text.

    Returning card text rather than the entire page is the key protection
    against assigning the active combined prices to a team tab.
    """
    container = _market_container(page, heading, require_prices=False)
    if container is None:
        print(f"    market container not found: {heading}")
        return ""

    item = _visible_exact_text(container, scope)
    count = container.get_by_text(scope, exact=True).count()
    print(f"    scope click: {heading} / {scope} count={count}")
    if item is None:
        return ""

    try:
        item.scroll_into_view_if_needed(timeout=3000)
        page.wait_for_timeout(350)
        item.click(timeout=3000)
        page.wait_for_timeout(1400)
    except Exception as e:
        print(f"    scope click failed: {heading} / {scope}: {e}")
        return ""

    # LiveScoreBet can rerender the market after a tab click, so reacquire it.
    container = _market_container(page, heading, require_prices=True)
    if container is None:
        print(f"    no prices after scope click: {heading} / {scope}")
        return ""

    expand_view_more_in_market(page, container)
    page.wait_for_timeout(350)
    container = _market_container(page, heading, require_prices=True) or container

    active_scope = _detect_active_scope(container, all_scopes)
    if active_scope and active_scope != scope:
        # One retry if the first click was swallowed by a rerender.
        retry_item = _visible_exact_text(container, scope)
        if retry_item is not None:
            try:
                retry_item.click(timeout=3000, force=True)
                page.wait_for_timeout(1200)
                container = _market_container(page, heading, require_prices=True) or container
                active_scope = _detect_active_scope(container, all_scopes)
            except Exception:
                pass

    if active_scope and active_scope != scope:
        print(
            f"    scope verification failed: wanted {scope}, "
            f"active {active_scope}; skipping"
        )
        return ""

    try:
        text = container.inner_text(timeout=30000)
    except Exception:
        return ""

    if heading not in text or not _has_fractional_price(text):
        return ""

    return text


def collect_shots_scope_text(page, home, away):
    chunks = []
    scopes = [scope for scope in ["Both Teams Combined", home, away] if scope]

    for heading in ["Total Shots", "Total Shots on Target"]:
        if not click_market_heading_if_needed(page, heading):
            continue

        for scope in scopes:
            market_text = capture_scope_market_text(
                page,
                heading,
                scope,
                scopes,
            )
            if not market_text:
                continue
            chunks.append(
                f"\n{SCOPE_MARKER}|{heading}|{scope}\n{market_text}\n"
            )

    return "".join(chunks)


# ---------------------------------------------------------------------------
# LIVESCOREBET_FULL_MATCH_TEAM_SHOTS_DOM_V1
# Verified on TEST3: exact Match/Home/Away rows for Shots and SOT.
# ---------------------------------------------------------------------------

STATS_GRP_ID = "595"


def _with_market_group(url, group_id):
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["marketGroupId"] = str(group_id)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _fractional_to_decimal(value):
    value = clean(value).upper()
    if value in {"EVS", "EVENS", "EVEN"}:
        return 2.0
    if "/" not in value:
        return None
    try:
        numerator, denominator = value.split("/", 1)
        denominator = float(denominator)
        if denominator == 0:
            return None
        return float(numerator) / denominator + 1.0
    except Exception:
        return None


def _source_pair_is_plausible(over_odds, under_odds):
    over_decimal = _fractional_to_decimal(over_odds)
    under_decimal = _fractional_to_decimal(under_odds)
    if not over_decimal or not under_decimal:
        return False
    source_sum = (1.0 / over_decimal) + (1.0 / under_decimal)
    return 0.90 <= source_sum <= 1.30


def _scroll_until_stats_market(page, heading):
    page.keyboard.press("Control+Home")
    page.wait_for_timeout(300)
    for _ in range(36):
        try:
            locator = page.get_by_text(heading, exact=True)
            for index in range(locator.count()):
                try:
                    if locator.nth(index).is_visible():
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        page.mouse.wheel(0, 650)
        page.wait_for_timeout(180)
    return False


def _expand_stats_market(page, heading):
    if not _scroll_until_stats_market(page, heading):
        return False
    try:
        result = page.evaluate(
            r"""heading => {
                const norm = value => (value || "").replace(/\s+/g, " ").trim();
                const visible = element => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
                };
                const leaves = Array.from(document.querySelectorAll("body *")).filter(element =>
                    element.childElementCount === 0 && norm(element.innerText) === heading && visible(element)
                );
                if (!leaves.length) return {found:false, clicked:false};
                const leaf = leaves[0];
                let card = null;
                for (let node = leaf; node && node !== document.body; node = node.parentElement) {
                    const text = norm(node.innerText);
                    if (text.includes(heading) && (text.includes("Both Teams Combined") || text.includes("Over") || text.includes("Under"))) {
                        card = node;
                        break;
                    }
                }
                const cardText = norm((card || leaf.parentElement || leaf).innerText);
                const alreadyOpen = cardText.includes("Over") && cardText.includes("Under") && /(?:\d+\/\d+|EVS|EVENS)/i.test(cardText);
                if (alreadyOpen) return {found:true, clicked:false};
                let target = leaf;
                for (let node = leaf; node && node !== document.body; node = node.parentElement) {
                    const tag = node.tagName.toLowerCase();
                    const role = (node.getAttribute("role") || "").toLowerCase();
                    const cursor = getComputedStyle(node).cursor;
                    if (tag === "button" || role === "button" || cursor === "pointer") {
                        target = node;
                        break;
                    }
                }
                target.scrollIntoView({block:"center", behavior:"instant"});
                target.click();
                return {found:true, clicked:true};
            }""",
            heading,
        )
    except Exception:
        return False
    if not result or not result.get("found"):
        return False
    page.wait_for_timeout(900)
    return True


def _stats_component_state(page, heading, scopes):
    try:
        return page.evaluate(
            r"""payload => {
                const norm = value => (value || "").replace(/\s+/g, " ").trim();
                const visible = element => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
                };
                const isOdds = value => /^(?:\d+\/\d+|EVS|EVENS|EVEN)$/i.test(norm(value));
                const isLine = value => /^\d+(?:\.\d+)?$/.test(norm(value));
                const targetHeadings = new Set(["Total Shots", "Total Shots on Target"]);
                const headingLeaves = Array.from(document.querySelectorAll("body *")).filter(element =>
                    element.childElementCount === 0 && norm(element.innerText) === payload.heading && visible(element)
                );
                const candidates = [];
                for (const leaf of headingLeaves) {
                    let depth = 0;
                    for (let node = leaf.parentElement; node && node !== document.body && depth < 12; node = node.parentElement, depth += 1) {
                        const text = norm(node.innerText);
                        if (!text.includes(payload.heading) || !text.includes("Over") || !text.includes("Under") || !/(?:\d+\/\d+|EVS|EVENS)/i.test(text)) continue;
                        const leaves = Array.from(node.querySelectorAll("*")).filter(element => element.childElementCount === 0 && visible(element) && norm(element.innerText));
                        const foreignHeading = leaves.some(element => {
                            const value = norm(element.innerText);
                            return targetHeadings.has(value) && value !== payload.heading;
                        });
                        if (foreignHeading) continue;
                        const scopeHits = payload.scopes.filter(scope => leaves.some(element => norm(element.innerText) === scope));
                        if (scopeHits.length < 2) continue;
                        const oddsCount = leaves.filter(element => isOdds(element.innerText)).length;
                        const lineCount = leaves.filter(element => isLine(element.innerText)).length;
                        if (!oddsCount || !lineCount) continue;
                        const rect = node.getBoundingClientRect();
                        candidates.push({node, leaves, area:rect.width * rect.height});
                    }
                }
                candidates.sort((a,b) => a.area - b.area);
                const selected = candidates[0];
                if (!selected) return {found:false, reason:"exact component not found", rows:[], tabs:[]};
                const leaves = selected.leaves;
                const headerOver = leaves.find(element => norm(element.innerText) === "Over");
                const headerUnder = leaves.find(element => norm(element.innerText) === "Under");
                const center = element => {
                    const rect = element.getBoundingClientRect();
                    return {x:rect.left + rect.width / 2, y:rect.top + rect.height / 2};
                };
                const overX = headerOver ? center(headerOver).x : null;
                const underX = headerUnder ? center(headerUnder).x : null;
                const lines = leaves.filter(element => isLine(element.innerText)).map(element => ({value:norm(element.innerText), ...center(element)}));
                const odds = leaves.filter(element => isOdds(element.innerText)).map(element => ({value:norm(element.innerText), ...center(element)}));
                const rows = [];
                for (const line of lines) {
                    const sameRow = odds.filter(price => Math.abs(price.y - line.y) <= 32);
                    if (sameRow.length < 2) continue;
                    let over = null;
                    let under = null;
                    if (overX !== null && underX !== null) {
                        over = sameRow.reduce((best, price) => !best || Math.abs(price.x - overX) < Math.abs(best.x - overX) ? price : best, null);
                        under = sameRow.filter(price => price !== over).reduce((best, price) => !best || Math.abs(price.x - underX) < Math.abs(best.x - underX) ? price : best, null);
                    } else {
                        const ordered = [...sameRow].sort((a,b) => a.x - b.x);
                        over = ordered[0] || null;
                        under = ordered[1] || null;
                    }
                    if (!over || !under) continue;
                    rows.push({line:line.value, over:over.value, under:under.value});
                }
                const dedupedRows = [];
                const rowKeys = new Set();
                for (const row of rows.sort((a,b) => Number(a.line) - Number(b.line))) {
                    const key = row.line + "|" + row.over + "|" + row.under;
                    if (rowKeys.has(key)) continue;
                    rowKeys.add(key);
                    dedupedRows.push(row);
                }
                const tabs = [];
                for (const scope of payload.scopes) {
                    const matches = leaves.filter(element => norm(element.innerText) === scope);
                    if (!matches.length) continue;
                    let target = matches[matches.length - 1];
                    for (let node = target; node && node !== selected.node; node = node.parentElement) {
                        const tag = node.tagName.toLowerCase();
                        const role = (node.getAttribute("role") || "").toLowerCase();
                        const cursor = getComputedStyle(node).cursor;
                        if (tag === "button" || role === "button" || role === "tab" || cursor === "pointer") {
                            target = node;
                            break;
                        }
                    }
                    const point = center(target);
                    tabs.push({label:scope, x:point.x, y:point.y});
                }
                return {found:true, rows:dedupedRows, tabs, text:norm(selected.node.innerText)};
            }""",
            {"heading": heading, "scopes": scopes},
        )
    except Exception as error:
        return {"found": False, "reason": str(error), "rows": [], "tabs": []}


def _click_stats_scope(page, heading, scope, scopes):
    state = _stats_component_state(page, heading, scopes)
    if not state.get("found"):
        return False
    tab = next((item for item in state.get("tabs", []) if item.get("label") == scope), None)
    if not tab:
        return False
    page.mouse.click(tab["x"], tab["y"])
    page.wait_for_timeout(1100)
    return True


def _expand_stats_view_more(page, heading, scopes):
    try:
        result = page.evaluate(
            r"""payload => {
                const norm = value => (value || "").replace(/\s+/g, " ").trim();
                const visible = element => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
                };
                const headingLeaf = Array.from(document.querySelectorAll("body *")).find(element =>
                    element.childElementCount === 0 && norm(element.innerText) === payload.heading && visible(element)
                );
                if (!headingLeaf) return 0;
                let component = null;
                for (let node = headingLeaf.parentElement; node && node !== document.body; node = node.parentElement) {
                    const text = norm(node.innerText);
                    if (text.includes(payload.heading) && text.includes("Over") && text.includes("Under") && payload.scopes.filter(scope => text.includes(scope)).length >= 2) {
                        component = node;
                        break;
                    }
                }
                if (!component) return 0;
                const buttons = Array.from(component.querySelectorAll("button, a, [role='button']")).filter(element =>
                    visible(element) && /^(view more|show more|show all|see all)$/i.test(norm(element.innerText))
                );
                let clicks = 0;
                for (const button of buttons) {
                    button.scrollIntoView({block:"center", behavior:"instant"});
                    button.click();
                    clicks += 1;
                }
                return clicks;
            }""",
            {"heading": heading, "scopes": scopes},
        )
    except Exception:
        return 0
    if result:
        page.wait_for_timeout(650)
    return int(result or 0)


def _stats_rows_signature(rows):
    return "|".join(f"{row.get('line')}:{row.get('over')}:{row.get('under')}" for row in rows)


def _build_stats_market(heading, label, scope, rows, max_line):
    selections = []
    for row in rows:
        line = clean(row.get("line"))
        over = clean(row.get("over")).upper()
        under = clean(row.get("under")).upper()
        if not re.match(r"^\d+(?:\.\d+)?$", line) or not is_odds(over) or not is_odds(under):
            continue
        try:
            if float(line) > max_line:
                continue
        except Exception:
            continue
        if not _source_pair_is_plausible(over, under):
            continue
        over_extra = {"side":"over", "line":line}
        under_extra = {"side":"under", "line":line}
        if scope != "Both Teams Combined":
            over_extra["team"] = scope
            under_extra["team"] = scope
            over_name = f"{scope} Over {line}"
            under_name = f"{scope} Under {line}"
        else:
            over_name = f"Over {line}"
            under_name = f"Under {line}"
        selections.append(sel(over_name, over, over_extra))
        selections.append(sel(under_name, under, under_extra))
    market_name = f"Total {label} Over / Under" if scope == "Both Teams Combined" else f"{scope} {label} Over / Under"
    market = dedupe_market(mkt(market_name, selections))
    market["source_heading"] = heading
    market["scope"] = scope
    market["complete_pair_count"] = market.get("selection_count", 0) // 2
    return market


def collect_shots_scope_markets_dom(page, url, home, away):
    stats_url = _with_market_group(url, STATS_GRP_ID)
    page.goto(stats_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    accept_cookies(page)
    scopes = ["Both Teams Combined", home, away]
    targets = (("Total Shots", "Shots", 60.5), ("Total Shots on Target", "Shots On Target", 30.5))
    markets = []
    audit = []
    for heading, label, max_line in targets:
        if not _expand_stats_market(page, heading):
            audit.append({"heading":heading, "status":"heading_unavailable"})
            print(f"    {heading}: unavailable")
            continue
        seen_scope_signatures = set()
        for scope in scopes:
            if not _click_stats_scope(page, heading, scope, scopes):
                audit.append({"heading":heading, "scope":scope, "status":"scope_click_failed"})
                print(f"    {heading} / {scope}: scope click failed")
                continue
            for _ in range(3):
                clicks = _expand_stats_view_more(page, heading, scopes)
                if not clicks:
                    break
            best_state = None
            best_rows = []
            for _ in range(8):
                state = _stats_component_state(page, heading, scopes)
                rows = state.get("rows") or []
                if len(rows) > len(best_rows):
                    best_rows = rows
                    best_state = state
                page.wait_for_timeout(250)
            if not best_state or not best_rows:
                audit.append({"heading":heading, "scope":scope, "status":"no_rows"})
                print(f"    {heading} / {scope}: no rows")
                continue
            signature = _stats_rows_signature(best_rows)
            if scope != "Both Teams Combined" and signature in seen_scope_signatures:
                audit.append({"heading":heading, "scope":scope, "status":"duplicate_scope_signature_rejected", "rows":len(best_rows)})
                print(f"    {heading} / {scope}: duplicate scope rejected")
                continue
            seen_scope_signatures.add(signature)
            market = _build_stats_market(heading, label, scope, best_rows, max_line)
            pairs = market.get("complete_pair_count", 0)
            if not pairs:
                audit.append({"heading":heading, "scope":scope, "status":"no_plausible_complete_pairs", "raw_rows":len(best_rows)})
                print(f"    {heading} / {scope}: no plausible complete pairs")
                continue
            markets.append(market)
            audit.append({"heading":heading, "scope":scope, "status":"captured", "raw_rows":len(best_rows), "complete_pairs":pairs, "signature":signature})
            print(f"    {heading} / {scope}: {pairs} complete Over/Under line(s)")
    return markets, audit


def _is_aggregate_shots_market(market):
    key = normalize(market.get("normalized_market") or market.get("market") or "")
    return key == "total_shots_over_under" or key == "total_shots_on_target_over_under" or key.endswith("_shots_over_under") or key.endswith("_shots_on_target_over_under")


def _expected_aggregate_shots_markets(home, away):
    return {
        "total_shots_over_under",
        normalize(f"{home} Shots Over / Under"),
        normalize(f"{away} Shots Over / Under"),
        "total_shots_on_target_over_under",
        normalize(f"{home} Shots On Target Over / Under"),
        normalize(f"{away} Shots On Target Over / Under"),
    }

def scrape_match(page, fixture):
    fixture_started = time.perf_counter()
    url = fixture["url"]
    name = fixture["name"]
    player_url = f"{url}?marketGroupId={PLAYER_GRP_ID}"
    player_page = None

    print(f"\n  [{name}]")

    print("    Pass 1: standard markets")
    standard_nav_started = time.perf_counter()

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )
    standard_dom_seconds = round(
        time.perf_counter() - standard_nav_started,
        2,
    )

    standard_ready_seconds = wait_for_market_content(
        page,
        ready_markers=[
            "Full Time",
            "Both Teams to Score",
            "Total Goals",
        ],
        timeout_ms=4500,
    )
    accept_cookies(page)

    # Start the player page now. The browser continues loading it in the
    # background while we scroll and capture standard/team-stat markets.
    prefetch_started = time.perf_counter()
    player_page = page.context.new_page()
    player_page.goto(
        player_url,
        wait_until="commit",
        timeout=60000,
    )
    player_prefetch_commit_seconds = round(
        time.perf_counter() - prefetch_started,
        2,
    )

    text1, standard_load_timing = collect_loaded_page_text(
        page,
        scroll_steps=20,
        ready_markers=[
            "Full Time",
            "Both Teams to Score",
            "Total Goals",
        ],
        accept_cookie_banner=False,
    )

    home, away = detect_teams(text1)

    if not home:
        slug = url.split("/world-cup-2026/")[-1].split("/")[0]
        parts = slug.split("-")
        home = parts[0].title()
        away = " ".join(parts[1:]).title()

    standard_debug_text = text1

    parse_standard_started = time.perf_counter()
    standard_markets = parse_standard_props(
        text1,
        home,
        away,
    )
    standard_parse_seconds = round(
        time.perf_counter() - parse_standard_started,
        2,
    )

    standard_markets = [
        market
        for market in standard_markets
        if not _is_aggregate_shots_market(market)
    ]

    shots_started = time.perf_counter()
    aggregate_shots_markets, aggregate_shots_audit = (
        collect_shots_scope_markets_dom(
            page,
            url,
            home,
            away,
        )
    )
    shots_scope_seconds = round(
        time.perf_counter() - shots_started,
        2,
    )

    standard_markets.extend(aggregate_shots_markets)

    aggregate_shots_market_names = {
        market.get("normalized_market")
        for market in aggregate_shots_markets
    }
    expected_aggregate_shots = _expected_aggregate_shots_markets(home, away)
    aggregate_shots_status = (
        "complete"
        if aggregate_shots_market_names == expected_aggregate_shots
        else "partial"
        if aggregate_shots_market_names
        else "unavailable"
    )

    print(
        f"    Aggregate Shots/SOT DOM: "
        f"{len(aggregate_shots_markets)}/6 markets | "
        f"{sum(m.get('complete_pair_count', 0) for m in aggregate_shots_markets)} "
        f"complete line(s)"
    )

    print(
        f"    Standard markets: {len(standard_markets)} — "
        f"{[m['market'] for m in standard_markets]}"
    )

    print("    Pass 2: player markets (prefetched)")
    player_started = time.perf_counter()

    text2, player_load_timing = collect_loaded_page_text(
        player_page,
        scroll_steps=25,
        ready_markers=[
            "Goalscorer",
            "Player's shots on target",
            "To give an assist",
            "To Get a Card",
        ],
        accept_cookie_banner=False,
    )

    player_debug_text = text2

    parse_player_started = time.perf_counter()
    player_markets = parse_player_props(text2)
    player_parse_seconds = round(
        time.perf_counter() - parse_player_started,
        2,
    )
    player_total_seconds = round(
        time.perf_counter() - player_started,
        2,
    )

    print(
        f"    Player markets: {len(player_markets)} — "
        f"{[m['market'] for m in player_markets]}"
    )

    seen = set()
    all_markets = []

    for market in standard_markets + player_markets:
        key = market["normalized_market"]
        if key in seen:
            continue
        seen.add(key)
        all_markets.append(market)

    total_seconds = round(
        time.perf_counter() - fixture_started,
        2,
    )

    market_names = {
        market["normalized_market"]
        for market in all_markets
    }

    required_markets = {
        "match_betting",
        "both_teams_to_score",
        "total_goals_over_under",
        "double_chance",
        "half_time_result",
        "half_time_full_time",
        "player_to_score",
        "total_corners_over_under",
        "team_with_most_corners",
        "total_cards_over_under",
        "player_to_get_a_card",
        "shots_on_target",
        "total_shots_over_under",
        normalize(f"{home} Shots Over / Under"),
        normalize(f"{away} Shots Over / Under"),
        "total_shots_on_target_over_under",
        normalize(f"{home} Shots On Target Over / Under"),
        normalize(f"{away} Shots On Target Over / Under"),
        "shots",
        "player_fouls_conceded",
        "player_to_assist",
    }

    missing_required = sorted(
        required_markets - market_names
    )
    quality_status = (
        "PASS"
        if len(all_markets) >= 21 and not missing_required
        else "FAIL"
    )

    timing = {
        "standard_domcontentloaded_seconds": standard_dom_seconds,
        "standard_initial_ready_seconds": standard_ready_seconds,
        "player_prefetch_commit_seconds": player_prefetch_commit_seconds,
        "standard_scroll_expand_seconds": standard_load_timing[
            "scroll_expand_seconds"
        ],
        "shots_scope_seconds": shots_scope_seconds,
        "standard_parse_seconds": standard_parse_seconds,
        "player_ready_seconds": player_load_timing[
            "ready_seconds"
        ],
        "player_scroll_expand_seconds": player_load_timing[
            "scroll_expand_seconds"
        ],
        "player_parse_seconds": player_parse_seconds,
        "player_pass_total_seconds": player_total_seconds,
        "total_seconds": total_seconds,
    }

    print(
        "    Timing: "
        f"standard DOM={standard_dom_seconds}s | "
        f"standard ready={standard_ready_seconds}s | "
        f"standard scroll={standard_load_timing['scroll_expand_seconds']}s | "
        f"shots scopes={shots_scope_seconds}s | "
        f"player ready={player_load_timing['ready_seconds']}s | "
        f"player scroll={player_load_timing['scroll_expand_seconds']}s | "
        f"TOTAL={total_seconds}s"
    )

    print(
        f"    QUALITY {quality_status}: "
        f"{len(all_markets)} markets"
        + (
            f" | missing={missing_required}"
            if missing_required
            else ""
        )
    )

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    debug_path = DEBUG_DIR / f"{slugify(name)}.json"

    if quality_status == "PASS":
        debug_payload = {
            "match": f"{home} v {away}",
            "url": url,
            "quality_status": quality_status,
            "market_count": len(all_markets),
            "markets": [
                {
                    "market": market["market"],
                    "selection_count": market["selection_count"],
                }
                for market in all_markets
            ],
            "timing": timing,
            "note": (
                "Full successful page text disabled in production "
                "to limit disk usage."
            ),
        }
    else:
        debug_payload = {
            "match": f"{home} v {away}",
            "url": url,
            "quality_status": quality_status,
            "market_count": len(all_markets),
            "missing_required_markets": missing_required,
            "markets": [
                {
                    "market": market["market"],
                    "selection_count": market["selection_count"],
                }
                for market in all_markets
            ],
            "timing": timing,
            "standard_text": standard_debug_text[:MAX_FAILURE_DEBUG_CHARS],
            "player_text": player_debug_text[:MAX_FAILURE_DEBUG_CHARS],
            "debug_truncated": (
                len(standard_debug_text) > MAX_FAILURE_DEBUG_CHARS
                or len(player_debug_text) > MAX_FAILURE_DEBUG_CHARS
            ),
        }

    debug_path.write_text(
        json.dumps(debug_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    try:
        player_page.close()
    except Exception:
        pass

    return {
        "match": f"{home} v {away}",
        "home_team": home,
        "away_team": away,
        "url": url,
        "market_count": len(all_markets),
        "quality_status": quality_status,
        "missing_required_markets": missing_required,
        "elapsed_seconds": total_seconds,
        "timing": timing,
        "aggregate_shots_dom_status": aggregate_shots_status,
        "aggregate_shots_dom_audit": aggregate_shots_audit,
        "markets": all_markets,
    }



def scoped_sot_market_names(home, away):
    return {
        "total_shots_on_target_over_under",
        normalize(f"{home} Shots On Target Over / Under"),
        normalize(f"{away} Shots On Target Over / Under"),
    }


def sanitize_incomplete_scoped_sot_sets(output):
    """
    Fail closed per fixture.

    When only part of the combined/home/away SOT scope set was captured,
    remove that incomplete scope set from that fixture. This protects against
    assigning combined prices to a team while preserving every other valid
    market from the completed run.
    """
    warnings = []

    for row in output.get("matches", []):
        home = clean(row.get("home_team"))
        away = clean(row.get("away_team"))
        match_name = clean(row.get("match"))

        expected = scoped_sot_market_names(home, away)
        markets = [
            market
            for market in row.get("markets", [])
            if isinstance(market, dict)
        ]
        present = {
            normalize(market.get("market"))
            for market in markets
            if normalize(market.get("market")) in expected
        }

        if not present or present == expected:
            continue

        row["markets"] = [
            market
            for market in markets
            if normalize(market.get("market")) not in expected
        ]
        row["market_count"] = len(row["markets"])
        row["quality_status"] = "FAIL"

        missing = set(row.get("missing_required_markets", []))
        missing.update(expected)
        row["missing_required_markets"] = sorted(missing)

        warning = (
            f"{match_name}: removed incomplete scoped Shots On Target set "
            f"({', '.join(sorted(present))}) to prevent mislabelled team odds."
        )
        warnings.append(warning)
        row.setdefault("sanitization_notes", []).append(warning)

    output["match_count"] = len(output.get("matches", []))
    output["sanitization_warnings"] = warnings
    return warnings


def validate_production_output(output):
    errors = []
    warnings = list(output.get("sanitization_warnings", []))
    matches = output.get("matches", [])

    discovered = output.get("discovered_fixture_count")
    if not isinstance(discovered, int) or discovered <= 0:
        discovered = len(matches)

    if len(matches) != discovered:
        errors.append(
            f"Expected {discovered} rows from coupon discovery, "
            f"got {len(matches)}."
        )

    if discovered > MAX_MATCHES:
        errors.append(
            f"Coupon discovery returned {discovered}, above MAX_MATCHES "
            f"{MAX_MATCHES}."
        )

    if discovered < MIN_ACTIVE_FIXTURES:
        errors.append(
            f"Only {discovered} active coupon fixtures were discovered; "
            f"minimum safety threshold is {MIN_ACTIVE_FIXTURES}."
        )

    urls = [clean(row.get("url")) for row in matches]
    duplicate_urls = sorted({
        url for url in urls
        if url and urls.count(url) > 1
    })
    if duplicate_urls:
        errors.append(
            "Duplicate fixture URLs: " + ", ".join(duplicate_urls)
        )

    error_rows = [
        row for row in matches
        if clean(row.get("error"))
    ]
    if error_rows:
        errors.append(
            f"{len(error_rows)} fixture(s) ended with errors: "
            + ", ".join(clean(row.get("match")) for row in error_rows)
        )

    full_quality = [
        row for row in matches
        if row.get("quality_status") == "PASS"
        and row.get("market_count", 0) >= 21
        and not row.get("missing_required_markets")
    ]

    if len(full_quality) < 3:
        errors.append(
            f"Expected at least 3 complete full-market fixtures; "
            f"got {len(full_quality)}."
        )

    per_match = []

    for row in matches:
        match_name = clean(row.get("match"))
        home = clean(row.get("home_team"))
        away = clean(row.get("away_team"))
        market_names = {
            normalize(market.get("market"))
            for market in row.get("markets", [])
            if isinstance(market, dict)
        }

        row_errors = []
        row_warnings = []

        expected_sot = scoped_sot_market_names(home, away)
        scoped_present = market_names & expected_sot

        if scoped_present and scoped_present != expected_sot:
            row_errors.append(
                "Incomplete scoped Shots On Target set remains after "
                "sanitization: " + ", ".join(sorted(scoped_present))
            )

        if row.get("quality_status") == "PASS":
            if row.get("market_count", 0) < 21:
                row_errors.append(
                    "Marked PASS with fewer than 21 markets."
                )
            if row.get("missing_required_markets"):
                row_errors.append(
                    "Marked PASS but missing-required list is not empty."
                )
        elif row.get("market_count", 0) >= 15:
            row_warnings.append(
                "Rich fixture did not meet the full required-market requirement."
            )

        if row_errors:
            errors.append(
                f"{match_name}: " + "; ".join(row_errors)
            )

        for warning in row_warnings:
            warnings.append(f"{match_name}: {warning}")

        per_match.append({
            "match": match_name,
            "market_count": row.get("market_count", 0),
            "quality_status": row.get("quality_status", "UNKNOWN"),
            "missing_required_markets": row.get(
                "missing_required_markets", []
            ),
            "sanitization_notes": row.get(
                "sanitization_notes", []
            ),
            "errors": row_errors,
            "warnings": row_warnings,
        })

    return {
        "status": "PASS" if not errors else "FAIL",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "requested_max_matches": MAX_MATCHES,
        "expected_matches_from_coupon": discovered,
        "actual_matches": len(matches),
        "coupon_shortfall_from_max": max(
            0,
            MAX_MATCHES - discovered,
        ),
        "complete_18_market_matches": len(full_quality),
        "errors": errors,
        "warnings": warnings,
        "per_match": per_match,
    }


def atomic_promote_staging():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    backup_path = None
    if LIVE_OUT_PATH.exists():
        backup_path = (
            BACKUP_DIR
            / f"livescorebet_worldcup_props_before_prod_v4_{timestamp}.json"
        )
        shutil.copy2(LIVE_OUT_PATH, backup_path)

    temporary_live = LIVE_OUT_PATH.with_suffix(".json.tmp")
    shutil.copy2(STAGING_OUT_PATH, temporary_live)
    os.replace(temporary_live, LIVE_OUT_PATH)

    return backup_path


def print_validation_and_promote(output, source_label):
    sanitization_warnings = sanitize_incomplete_scoped_sot_sets(output)

    STAGING_OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    report = validate_production_output(output)
    VALIDATION_REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\nSource staging → {source_label}")
    print(f"Sanitized staging → {STAGING_OUT_PATH}")
    print(f"Validation report → {VALIDATION_REPORT_PATH}")

    print("\n── Availability-aware validation ─────────────────────")
    print(
        f"  Coupon fixtures:      "
        f"{report['actual_matches']}/"
        f"{report['expected_matches_from_coupon']}"
    )
    print(
        f"  Max requested:        "
        f"{report['requested_max_matches']}"
    )
    print(
        f"  Coupon shortfall:     "
        f"{report['coupon_shortfall_from_max']}"
    )
    print(
        f"  Complete full-market: "
        f"{report['complete_18_market_matches']}"
    )

    if sanitization_warnings:
        print("\nSanitized incomplete scope sets:")
        for warning in sanitization_warnings:
            print(f"  - {warning}")

    if report["warnings"]:
        print("\nWarnings:")
        for warning in report["warnings"]:
            print(f"  - {warning}")

    if report["status"] != "PASS":
        print("\nVALIDATION FAIL — live JSON was NOT changed.")
        for error in report["errors"]:
            print(f"  - {error}")
        raise SystemExit(1)

    backup_path = atomic_promote_staging()

    print("\nVALIDATION PASS")
    if backup_path:
        print(f"Previous live backup → {backup_path}")
    else:
        print("No previous live JSON existed; no backup was required.")

    print(f"Live JSON promoted → {LIVE_OUT_PATH}")


def promote_existing_v3_staging():
    """
    Reuse the completed 21-minute V3 run without opening a browser.
    """
    STAGING_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not LEGACY_STAGING_PATH.exists():
        raise FileNotFoundError(
            f"Existing V3 staging file not found: {LEGACY_STAGING_PATH}"
        )

    output = json.loads(
        LEGACY_STAGING_PATH.read_text(encoding="utf-8")
    )

    matches = output.get("matches", [])
    output["requested_max_matches"] = MAX_MATCHES
    output["discovered_fixture_count"] = len(matches)
    output["coupon_shortfall_from_max"] = max(
        0,
        MAX_MATCHES - len(matches),
    )
    output["scraper_version"] = (
        "production_v4_availability_aware_repaired_from_v3"
    )
    output["repaired_at"] = datetime.now(
        timezone.utc
    ).isoformat()
    output["source_staging_file"] = str(LEGACY_STAGING_PATH)

    print("=" * 68)
    print("LiveScoreBet Props — PROMOTE EXISTING V3 STAGING")
    print("No browser run; no rescrape.")
    print("=" * 68)

    print_validation_and_promote(
        output,
        source_label=str(LEGACY_STAGING_PATH),
    )



def main():
    STAGING_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 68)
    print("LiveScoreBet Props — PRODUCTION V4 AVAILABILITY AWARE")
    print(
        f"PRODUCTION: MAX_MATCHES = {MAX_MATCHES} | "
        "staging + validation + atomic promotion"
    )
    print("=" * 68)

    run_started = time.perf_counter()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1700, "height": 1000}
        )

        def block_heavy_resources(route):
            if route.request.resource_type in {
                "image",
                "media",
                "font",
            }:
                route.abort()
            else:
                route.continue_()

        context.route("**/*", block_heavy_resources)
        page = context.new_page()

        fixtures_started = time.perf_counter()
        fixtures = get_match_links(page)
        print(
            f"Fixture discovery: "
            f"{round(time.perf_counter() - fixtures_started, 2)}s"
        )

        results = []

        for index, fixture in enumerate(fixtures, 1):
            print(f"\n[{index}/{len(fixtures)}]")
            try:
                result = scrape_match(page, fixture)
                results.append(result)
            except KeyboardInterrupt:
                browser.close()
                raise
            except Exception as exc:
                print(
                    f"  ⚠ Error: {type(exc).__name__}: {exc}"
                )
                for extra_page in list(context.pages):
                    if extra_page is page:
                        continue
                    try:
                        extra_page.close()
                    except Exception:
                        pass

                results.append({
                    "match": fixture.get("name", ""),
                    "home_team": "",
                    "away_team": "",
                    "url": fixture.get("url", ""),
                    "market_count": 0,
                    "quality_status": "FAIL",
                    "missing_required_markets": [],
                    "elapsed_seconds": 0,
                    "timing": {},
                    "markets": [],
                    "error": f"{type(exc).__name__}: {exc}",
                })

        browser.close()

    runtime_seconds = round(
        time.perf_counter() - run_started,
        1,
    )

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "LiveScoreBet",
        "market_type": "props",
        "scraper_version": "production_v4_availability_aware",
        "source_url": COUPON_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": runtime_seconds,
        "requested_max_matches": MAX_MATCHES,
        "discovered_fixture_count": len(fixtures),
        "coupon_shortfall_from_max": max(
            0,
            MAX_MATCHES - len(fixtures),
        ),
        "match_count": len(results),
        "matches": results,
    }

    print(
        f"\nRuntime → {runtime_seconds}s "
        f"({round(runtime_seconds / 60, 1)} minutes)"
    )

    print_validation_and_promote(
        output,
        source_label="fresh browser scrape",
    )

    print("\n── Summary ───────────────────────────────────────────")
    for row in results:
        print(
            f"  {row['match']:<40} "
            f"{row.get('market_count', 0)} markets | "
            f"{row.get('elapsed_seconds', 0)}s | "
            f"{row.get('quality_status', 'UNKNOWN')}"
        )
    print("─" * 68)

if __name__ == "__main__":
    if "--promote-existing-staging" in sys.argv:
        promote_existing_v3_staging()
    else:
        main()
