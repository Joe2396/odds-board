#!/usr/bin/env python3
import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH  = ROOT / "football" / "data" / "livescorebet_worldcup_props_FAST_TEST3_V3_CONSERVATIVE.json"
DEBUG_DIR = ROOT / "football" / "debug" / "livescorebet_worldcup_props_FAST_TEST3_V3_CONSERVATIVE"

COUPON_URL     = "https://www.livescorebet.com/ie/coupon/21127/"
PLAYER_GRP_ID  = "757"
MAX_MATCHES = 3
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

    for i, label in enumerate(labels[:3]):
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

    shots_started = time.perf_counter()
    scoped_text = collect_shots_scope_text(page, home, away)
    shots_scope_seconds = round(
        time.perf_counter() - shots_started,
        2,
    )

    text1_for_parse = text1 + scoped_text

    (
        DEBUG_DIR / f"{slugify(name)}_standard.txt"
    ).write_text(
        text1_for_parse,
        encoding="utf-8",
    )

    parse_standard_started = time.perf_counter()
    standard_markets = parse_standard_props(
        text1_for_parse,
        home,
        away,
    )
    standard_parse_seconds = round(
        time.perf_counter() - parse_standard_started,
        2,
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

    (
        DEBUG_DIR / f"{slugify(name)}_player.txt"
    ).write_text(
        text2,
        encoding="utf-8",
    )

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
        if len(all_markets) >= 18 and not missing_required
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
        "markets": all_markets,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LiveScoreBet Props — FAST TEST3 V3 CONSERVATIVE")
    print("=" * 60)

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

        for i, fixture in enumerate(fixtures):
            print(f"\n[{i + 1}/{len(fixtures)}]")
            try:
                result = scrape_match(page, fixture)
                results.append(result)
            except Exception as e:
                print(f"  ⚠ Error: {type(e).__name__}: {e}")
                for extra_page in list(context.pages):
                    if extra_page is page:
                        continue
                    try:
                        extra_page.close()
                    except Exception:
                        pass
                results.append({
                    "match": fixture["name"],
                    "home_team": "",
                    "away_team": "",
                    "url": fixture["url"],
                    "market_count": 0,
                    "markets": [],
                })

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "LiveScoreBet",
        "market_type": "props",
        "scraper_version": "fast_test3_v3_conservative",
        "source_url": COUPON_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches": results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved → {OUT_PATH}")
    print("\n── Summary ─────────────────────────────────────────────")
    for r in results:
        print(
            f"  {r['match']:<40} "
            f"{r['market_count']} markets | "
            f"{r.get('elapsed_seconds', 0)}s"
        )
        for m in r["markets"]:
            print(f"      - {m['market']} ({m['selection_count']})")
    print("─" * 60)

if __name__ == "__main__":
    main()