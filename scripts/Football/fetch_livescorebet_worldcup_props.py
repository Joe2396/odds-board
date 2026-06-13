#!/usr/bin/env python3
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
    marker_markets = parse_scoped_markers(lines, "Total Shots on Target", "Shots On Target", max_line=12.5)
    if marker_markets:
        return marker_markets
    return parse_scoped_ou(
        lines,
        "Total Shots on Target",
        "Shots On Target",
        max_line=12.5,
        home=home,
        away=away,
    )

def parse_total_shots_scoped(lines, home, away):
    marker_markets = parse_scoped_markers(lines, "Total Shots", "Shots", max_line=35.5)
    if marker_markets:
        return marker_markets
    return parse_scoped_ou(
        lines,
        "Total Shots",
        "Shots",
        max_line=35.5,
        home=home,
        away=away,
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

def get_page_text(page, url, scroll_steps=18):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4500)
    accept_cookies(page)

    for _ in range(scroll_steps):
        page.mouse.wheel(0, 650)
        page.wait_for_timeout(250)

    expand_view_more(page)
    page.keyboard.press("Control+Home")
    page.wait_for_timeout(400)

    return page.locator("body").inner_text(timeout=30000)

def get_match_links(page):
    print(f"Opening coupon page: {COUPON_URL}")
    page.goto(COUPON_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)
    accept_cookies(page)

    for _ in range(20):
        page.mouse.wheel(0, 750)
        page.wait_for_timeout(350)

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
    lines = [clean(l) for l in text.splitlines() if clean(l)]

    for i, line in enumerate(lines):
        if line in WORLD_CUP_TEAMS and i + 2 < len(lines):
            if clean(lines[i + 1]) == "Draw" and clean(lines[i + 2]) in WORLD_CUP_TEAMS:
                return line, lines[i + 2]

    return "", ""


def click_market_heading_if_needed(page, heading):
    try:
        loc = page.get_by_text(heading, exact=True)
        if not loc.count():
            return False
        item = loc.first
        item.scroll_into_view_if_needed(timeout=2000)
        page.wait_for_timeout(300)
        visible = page.evaluate(
            """(heading) => {
                const norm = s => (s || '').replace(/\s+/g, ' ').trim();
                const els = Array.from(document.querySelectorAll('body *')).filter(e => norm(e.innerText) === heading);
                if (!els.length) return false;
                let node = els[0];
                for (let d = 0; d < 8 && node; d++, node = node.parentElement) {
                    const txt = norm(node.innerText);
                    if (txt.includes(heading) && txt.includes('Over') && txt.includes('Under') && /(?:\d+\/\d+|EVS|EVENS|Evens)/i.test(txt)) return true;
                }
                return false;
            }""",
            heading,
        )
        if not visible:
            item.click(timeout=2000)
            page.wait_for_timeout(900)
        return True
    except Exception:
        return False


def click_scope_in_market(page, heading, scope):
    try:
        loc = page.get_by_text(scope, exact=True)
        count = loc.count()
        print(f"    scope click: {heading} / {scope} count={count}")
        if not count:
            return False

        item = loc.last
        item.scroll_into_view_if_needed(timeout=3000)
        page.wait_for_timeout(500)
        item.click(timeout=3000)
        page.wait_for_timeout(1400)
        expand_view_more(page)
        return True
    except Exception as e:
        print(f"    scope click failed: {heading} / {scope}: {e}")
        return False

def collect_shots_scope_text(page, home, away):
    chunks = []
    for heading in ["Total Shots", "Total Shots on Target"]:
        click_market_heading_if_needed(page, heading)
        for scope in ["Both Teams Combined", home, away]:
            if not scope:
                continue
            if not click_scope_in_market(page, heading, scope):
                continue
            try:
                body = page.locator("body").inner_text(timeout=30000)
                chunks.append(f"\n{SCOPE_MARKER}|{heading}|{scope}\n{body}\n")
            except Exception:
                pass
    return "".join(chunks)

def scrape_match(page, fixture):
    url = fixture["url"]
    name = fixture["name"]

    print(f"\n  [{name}]")

    print("    Pass 1: standard markets")
    text1 = get_page_text(page, url, scroll_steps=20)
    home, away = detect_teams(text1)

    if not home:
        slug = url.split("/world-cup-2026/")[-1].split("/")[0]
        parts = slug.split("-")
        home = parts[0].title()
        away = " ".join(parts[1:]).title()

    scoped_text = collect_shots_scope_text(page, home, away)
    text1_for_parse = text1 + scoped_text

    (DEBUG_DIR / f"{slugify(name)}_standard.txt").write_text(text1_for_parse, encoding="utf-8")

    standard_markets = parse_standard_props(text1_for_parse, home, away)
    print(f"    Standard markets: {len(standard_markets)} — {[m['market'] for m in standard_markets]}")

    print("    Pass 2: player markets")
    player_url = f"{url}?marketGroupId={PLAYER_GRP_ID}"
    text2 = get_page_text(page, player_url, scroll_steps=25)
    (DEBUG_DIR / f"{slugify(name)}_player.txt").write_text(text2, encoding="utf-8")

    player_markets = parse_player_props(text2)
    print(f"    Player markets: {len(player_markets)} — {[m['market'] for m in player_markets]}")

    seen = set()
    all_markets = []

    for market in standard_markets + player_markets:
        key = market["normalized_market"]
        if key in seen:
            continue
        seen.add(key)
        all_markets.append(market)

    return {
        "match": f"{home} v {away}",
        "home_team": home,
        "away_team": away,
        "url": url,
        "market_count": len(all_markets),
        "markets": all_markets,
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
            print(f"\n[{i + 1}/{len(fixtures)}]")
            try:
                result = scrape_match(page, fixture)
                results.append(result)
            except Exception as e:
                print(f"  ⚠ Error: {e}")
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
        "source_url": COUPON_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches": results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved → {OUT_PATH}")
    print("\n── Summary ─────────────────────────────────────────────")
    for r in results:
        print(f"  {r['match']:<40} {r['market_count']} markets")
        for m in r["markets"]:
            print(f"      - {m['market']} ({m['selection_count']})")
    print("─" * 60)

if __name__ == "__main__":
    main()