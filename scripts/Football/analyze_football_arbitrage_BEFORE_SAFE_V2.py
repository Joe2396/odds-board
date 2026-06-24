#!/usr/bin/env python3
import json
import os
import re
from datetime import datetime, timezone
from itertools import product

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

BOOK_FILES = {
    "PaddyPower": os.path.join(ROOT, "football", "data", "paddypower_worldcup_moneylines.json"),
    "BoyleSports": os.path.join(ROOT, "football", "data", "boylesports_worldcup_moneylines.json"),
    "BetVictor": os.path.join(ROOT, "football", "data", "betvictor_worldcup_moneylines.json"),
    "Unibet": os.path.join(ROOT, "football", "data", "unibet_worldcup_moneylines.json"),
    "LiveScoreBet": os.path.join(ROOT, "football", "data", "livescorebet_worldcup_moneylines.json"),
    "WilliamHill": os.path.join(ROOT, "football", "data", "williamhill_worldcup_moneylines.json"),
    "888Sport": os.path.join(ROOT, "football", "data", "888sport_worldcup_moneylines.json"),

    "Bwin": os.path.join(ROOT, "football", "data", "bwin_worldcup_moneylines.json"),}

OUT_PATH = os.path.join(ROOT, "football", "data", "arbitrage.json")


def fractional_to_decimal(value):
    value = str(value or "").strip().upper()

    if value in {"EVS", "EVENS", "EVEN"}:
        return 2.0

    if "/" in value:
        try:
            num, den = value.split("/", 1)
            return round((float(num) / float(den)) + 1, 6)
        except Exception:
            return None

    try:
        decimal = float(value)
        if decimal > 1:
            return decimal
    except Exception:
        pass

    return None


def implied_probability(decimal_odds):
    if not decimal_odds or decimal_odds <= 1:
        return None
    return 1 / decimal_odds


def normalize_team(name):
    name = str(name or "").lower().strip()

    replacements = {
        "türkiye": "turkiye",
        "turkey": "turkiye",
        "czech republic": "czechia",
        "bosnia & herzegovina": "bosnia",
        "bosnia and herzegovina": "bosnia",
        "cape verde islands": "cape verde",
        "congo dr": "dr congo",
        "curaçao": "curacao",
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    name = re.sub(r"[^a-z0-9]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()

    return name


def fixture_key(home, away):
    return f"{normalize_team(home)}__{normalize_team(away)}"


def loose_fixture_key(home, away):
    teams = sorted([normalize_team(home), normalize_team(away)])
    return "__".join(teams)


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def add_offer(fixtures, key, side, bookmaker, raw_odds, row):
    decimal = fractional_to_decimal(raw_odds)

    if not decimal or decimal <= 1:
        return

    fixtures[key]["selections"][side].append({
        "bookmaker": bookmaker,
        "odds": raw_odds,
        "decimal_odds": decimal,
        "implied_probability": round(implied_probability(decimal), 6),
        "source_url": row.get("source_url") or "",
    })



# ── Props arbitrage ────────────────────────────────────────────────────────────

PROPS_FILES = {
    "PaddyPower":   ("paddypower_worldcup_props.json",   "fractional"),
    "BoyleSports":  ("boylesports_worldcup_props_complete.json", "fractional"),
    "LiveScoreBet": ("livescorebet_worldcup_props.json", "fractional"),
    "Ladbrokes":    ("ladbrokes_worldcup_props.json",    "fractional"),
    "WilliamHill":  ("williamhill_worldcup_props.json",  "fractional"),
    "BetVictor":    ("betvictor_worldcup_props.json",    "fractional"),
    # "Midnite":    ("midnite_worldcup_props.json",      "fractional"),  # dict format, not list
    "Unibet":      ("unibet_worldcup_props.json", "fractional"),
}


NAMED_PROPS_FILES = {
    # Existing scope-verified props sources
    "PaddyPower":   "paddypower_worldcup_props.json",
    "BoyleSports":  "boylesports_worldcup_props_complete.json",
    "LiveScoreBet": "livescorebet_worldcup_props.json",
    "Ladbrokes":    "ladbrokes_worldcup_props.json",
    "WilliamHill":  "williamhill_worldcup_props.json",
    "BetVictor":    "betvictor_worldcup_props.json",

    # These formats are reliable for BTTS / Double Chance / Half Time Result,
    # even though they are not yet enabled for the strict O/U scope scanner.
    "Unibet":       "unibet_worldcup_props.json",
    "888Sport":     "888sport_worldcup_props.json",
    "Midnite":       "midnite_worldcup_props.json",
}

OU_MARKET_KEYS = {
    "total_goals_over_under", "total_goals_over", "total_goals",
    "first_half_goals_over_under", "first_half_goals",
    "total_corners_over_under", "total_corners",
    "total_cards_over_under", "total_match_cards",
    "total_shots_on_target_over_under", "total_shots_over_under",
}


def normalize_key(s):
    s = str(s or "").lower().replace("&", "and").replace("?", "")
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "_", s).strip("_")


PLAYER_MARKET_WORDS = {
    "player", "goalscorer", "to_score", "to_assist", "tackles",
    "fouls", "carded", "to_get_a_card",
}


def classify_prop_metric(market_name):
    mk = normalize_key(market_name)

    if any(word in mk for word in PLAYER_MARKET_WORDS):
        return None

    if "shots_on_target" in mk:
        return "shots_on_target", "Shots On Target"
    if "shots" in mk:
        return "shots", "Shots"
    if "corners" in mk:
        return "corners", "Corners"
    if "cards" in mk or "booking_points" in mk:
        return "cards", "Cards"
    if "first_half" in mk and "goals" in mk:
        return "first_half_goals", "First Half Goals"
    if "goals" in mk:
        return "goals", "Goals"

    return None


def _canonical_fixture_team(value, home, away):
    value = normalize_team(value)
    home_c = normalize_team(home)
    away_c = normalize_team(away)

    if value == home_c:
        return home_c
    if value == away_c:
        return away_c
    return ""


def resolve_prop_identity(market_name, selection, selection_name, home, away):
    """
    Resolve a strict market identity using all available evidence.

    This understands:
      - actual team names in the market title
      - Home / Away market titles
      - selection["team"] metadata
      - actual team names in the selection label

    Returns:
      (canonical_key, display_name, scope, scope_team, metric)
    or:
      (None, reason)
    """
    metric_info = classify_prop_metric(market_name)
    if not metric_info:
        return None, "unsupported/player market"

    metric, label = metric_info
    mk = normalize_key(market_name)
    sn = normalize_key(selection_name)

    home_c = normalize_team(home)
    away_c = normalize_team(away)
    home_k = normalize_key(home_c)
    away_k = normalize_key(away_c)

    candidates = []

    # Actual team names in the market title.
    if home_k and home_k in mk:
        candidates.append(home_c)
    if away_k and away_k in mk:
        candidates.append(away_c)

    # Generic Home / Away market titles.
    title_tokens = set(mk.split("_"))
    if "home" in title_tokens:
        candidates.append(home_c)
    if "away" in title_tokens:
        candidates.append(away_c)

    # Explicit team metadata from the scraper.
    explicit_team = _canonical_fixture_team(
        selection.get("team") or "",
        home,
        away,
    )
    if explicit_team:
        candidates.append(explicit_team)

    # Actual team names in the selection text.
    if home_k and home_k in sn:
        candidates.append(home_c)
    if away_k and away_k in sn:
        candidates.append(away_c)

    unique_candidates = {x for x in candidates if x}

    if len(unique_candidates) > 1:
        return None, "conflicting team scope"

    if len(unique_candidates) == 1:
        scope_team = next(iter(unique_candidates))
        canonical = f"team_{metric}::{scope_team}"
        display = f"{scope_team.title()} Total {label} Over Under"
        return canonical, display, "team", scope_team, metric

    # A title that explicitly says home/away/team but could not be resolved
    # must not silently become a match total.
    team_markers = {
        "home", "away", "team", "team_total", "home_team", "away_team",
    }
    if any(marker in mk for marker in team_markers):
        return None, "ambiguous team scope"

    canonical = f"match_{metric}"
    display = f"Total {label} Over Under"
    return canonical, display, "match", "", metric


def should_quarantine_offer(bookmaker, canonical_market, line):
    """
    Keep confirmed bad source rows off the live board until their source parser
    has been repaired and verified.
    """
    line = str(line or "").strip()

    if (
        bookmaker == "BetVictor"
        and canonical_market == "match_goals"
        and line == "0.5"
    ):
        return "BetVictor unverified Total Goals 0.5"

    return ""


def remove_duplicate_match_team_ladders(data, rejected):
    """
    If one bookmaker produces an identical full ladder for a match total and a
    team total, the team scope is almost certainly a parser copy/misclick.

    The comparison requires at least four identical selections, so one
    coincidental matching price is not enough to trigger it.
    """
    for fixture_markets in data.values():
        by_metric = {}

        for canonical_mk, lines in fixture_markets.items():
            if canonical_mk.startswith("match_"):
                metric = canonical_mk[len("match_"):]
                scope = "match"
            elif canonical_mk.startswith("team_"):
                metric = canonical_mk[len("team_"):].split("::", 1)[0]
                scope = "team"
            else:
                continue

            by_metric.setdefault(metric, []).append(
                (canonical_mk, scope, lines)
            )

        for metric, entries in by_metric.items():
            match_entries = [e for e in entries if e[1] == "match"]
            team_entries = [e for e in entries if e[1] == "team"]

            if not match_entries or not team_entries:
                continue

            match_key, _, match_lines = match_entries[0]

            bookmakers = set()
            for sides in match_lines.values():
                for offers in sides.values():
                    bookmakers.update(o["bookmaker"] for o in offers)

            for bookmaker in bookmakers:
                match_fp = set()
                for line, sides in match_lines.items():
                    for side, offers in sides.items():
                        for offer in offers:
                            if offer["bookmaker"] == bookmaker:
                                match_fp.add((line, side, offer["odds"]))

                if len(match_fp) < 4:
                    continue

                for team_key, _, team_lines in team_entries:
                    team_fp = set()
                    for line, sides in team_lines.items():
                        for side, offers in sides.items():
                            for offer in offers:
                                if offer["bookmaker"] == bookmaker:
                                    team_fp.add((line, side, offer["odds"]))

                    if team_fp != match_fp:
                        continue

                    removed = 0
                    for line, sides in team_lines.items():
                        for side in list(sides):
                            before = len(sides[side])
                            sides[side] = [
                                o for o in sides[side]
                                if o["bookmaker"] != bookmaker
                            ]
                            removed += before - len(sides[side])

                    if removed:
                        reason = (
                            f"{bookmaker} duplicate match/team {metric} ladder"
                        )
                        rejected[reason] = rejected.get(reason, 0) + removed



def unibet_ou_market_is_safe(market_name, market_data, home, away):
    """
    Allow only Unibet match/team O/U markets that can be scoped safely.

    The Unibet file also contains player Shots, SOT, Cards and other props.
    Some of those market titles are generic, so this check also inspects every
    selection for player metadata before allowing the market into the match/team
    O/U arb scanner.
    """
    mk = normalize_key(market_name)
    selections = market_data.get("selections") or []

    named_only = {
        "both_teams_to_score",
        "btts",
        "double_chance",
        "half_time_result",
        "half_time",
        "match_betting",
        "anytime_goalscorer",
        "first_goalscorer",
    }
    if mk in named_only:
        return False

    player_words = {
        "player",
        "goalscorer",
        "anytime_scorer",
        "first_scorer",
        "assist",
        "tackle",
        "foul",
        "to_get_a_card",
        "player_cards",
    }
    if any(word in mk for word in player_words):
        return False

    for selection in selections:
        if not isinstance(selection, dict):
            continue

        if selection.get("player"):
            return False

        prop_type = normalize_key(selection.get("prop_type") or "")
        if any(word in prop_type for word in {
            "player",
            "shots",
            "shots_on_target",
            "cards",
            "assist",
            "tackles",
            "fouls",
            "goalscorer",
        }):
            return False

    # Require an explicitly aggregate market. This stops a generic Unibet
    # "Shots" or "Shots On Target" player table from becoming a match total.
    safe_aggregate_markers = {
        "total_goals",
        "first_half_goals",
        "1st_half_goals",
        "total_cards",
        "total_corners",
        "team_total_goals",
        "total_team_goals",
        "match_shots",
        "match_shots_on_target",
        "team_shots",
        "team_shots_on_target",
        "home_shots",
        "away_shots",
        "home_shots_on_target",
        "away_shots_on_target",
    }

    if any(marker in mk for marker in safe_aggregate_markers):
        return True

    home_key = normalize_key(normalize_team(home))
    away_key = normalize_key(normalize_team(away))

    # Named-team aggregate market, e.g. "Germany Total Goals Over / Under".
    if (
        ("total" in mk or "over_under" in mk)
        and (
            (home_key and home_key in mk)
            or (away_key and away_key in mk)
        )
    ):
        return True

    return False


def scan_props_arbitrage(root):
    """Scan strictly matched O/U prop markets across bookmakers."""
    data = {}
    rejected = {}

    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1

    for bk, (fname, fmt) in PROPS_FILES.items():
        path = os.path.join(root, "football", "data", fname)
        raw = load_json(path)
        if not raw:
            continue

        matches = raw.get("matches") or []
        if isinstance(raw, list):
            matches = raw

        for m in matches:
            home, away = get_prop_match_teams(m)
            if not home or not away:
                continue

            fk = fixture_key(home, away)
            for mkt_name, mkt_data in iter_market_items(
                m,
                bk,
            ):
                if not isinstance(mkt_data, dict):
                    continue


                if bk == "Unibet" and not unibet_ou_market_is_safe(
                    mkt_name,
                    mkt_data,
                    home,
                    away,
                ):
                    reject("Unibet unsupported/player O/U market")
                    continue
                sels = mkt_data.get("selections") or []

                for sel in sels:
                    if not isinstance(sel, dict):
                        continue

                    sn = sel.get("selection", "")
                    odds_raw = sel.get("odds") or sel.get("price", "")
                    side = str(sel.get("side") or "").lower().strip()
                    line = str(sel.get("line") or "").strip()

                    if not side or not line:
                        m2 = re.search(
                            r"\b(over|under)\s+([\d.]+)\b",
                            str(sn),
                            re.I,
                        )
                        if m2:
                            side = m2.group(1).lower()
                            line = m2.group(2)

                    if side not in {"over", "under"} or not line or not odds_raw:
                        continue

                    identity = resolve_prop_identity(
                        mkt_name,
                        sel,
                        sn,
                        home,
                        away,
                    )

                    if not identity or identity[0] is None:
                        reason = (
                            identity[1]
                            if identity and len(identity) > 1
                            else "unresolved market identity"
                        )
                        reject(reason)
                        continue

                    (
                        canonical_mk,
                        display_name,
                        scope,
                        scope_team,
                        metric,
                    ) = identity

                    quarantine_reason = should_quarantine_offer(
                        bk,
                        canonical_mk,
                        line,
                    )
                    if quarantine_reason:
                        reject(quarantine_reason)
                        continue

                    dec = fractional_to_decimal(odds_raw)
                    if not dec or dec <= 1:
                        continue

                    offer = {
                        "bookmaker": bk,
                        "odds": odds_raw,
                        "decimal": dec,
                        "match": f"{home} v {away}",
                        "market": display_name,
                        "source_market": mkt_name,
                        "scope": scope,
                        "scope_team": scope_team,
                        "metric": metric,
                    }

                    data.setdefault(fk, {}).setdefault(
                        canonical_mk, {}
                    ).setdefault(line, {}).setdefault(side, []).append(offer)

    remove_duplicate_match_team_ladders(data, rejected)

    arbs = []
    near_misses = []

    for fk, markets in data.items():
        for canonical_mk, lines in markets.items():
            for line, sides in lines.items():
                overs = sides.get("over") or []
                unders = sides.get("under") or []
                if not overs or not unders:
                    continue

                pairs = [
                    (over, under)
                    for over in overs
                    for under in unders
                    if over["bookmaker"] != under["bookmaker"]
                ]
                if not pairs:
                    continue

                best_over, best_under = min(
                    pairs,
                    key=lambda pair: (
                        (1 / pair[0]["decimal"])
                        + (1 / pair[1]["decimal"])
                    ),
                )

                arb_sum = (
                    (1 / best_over["decimal"])
                    + (1 / best_under["decimal"])
                )

                row = {
                    "sport": "Football",
                    "competition": "FIFA World Cup",
                    "type": "props_ou",
                    "match": best_over["match"],
                    "market": best_over["market"],
                    "canonical_market": canonical_mk,
                    "scope": best_over["scope"],
                    "scope_team": best_over["scope_team"],
                    "line": line,
                    "arb_sum": round(arb_sum, 6),
                    "arb_percent": round(arb_sum * 100, 3),
                    "profit_margin_percent": round(
                        ((1 / arb_sum) - 1) * 100,
                        3,
                    ),
                    "bookmaker_count": 2,
                    "selections": {
                        "over": {
                            "bookmaker": best_over["bookmaker"],
                            "odds": best_over["odds"],
                            "decimal_odds": best_over["decimal"],
                            "source_market": best_over["source_market"],
                        },
                        "under": {
                            "bookmaker": best_under["bookmaker"],
                            "odds": best_under["odds"],
                            "decimal_odds": best_under["decimal"],
                            "source_market": best_under["source_market"],
                        },
                    },
                    "all_prices": {
                        "over": sorted(
                            overs,
                            key=lambda x: x["decimal"],
                            reverse=True,
                        ),
                        "under": sorted(
                            unders,
                            key=lambda x: x["decimal"],
                            reverse=True,
                        ),
                    },
                }

                if arb_sum < 1:
                    arbs.append(row)
                elif arb_sum < 1.04:
                    near_misses.append(row)

    arbs.sort(
        key=lambda x: x["profit_margin_percent"],
        reverse=True,
    )
    near_misses.sort(key=lambda x: x["arb_sum"])

    if rejected:
        print("Props safety filters:")
        for reason, count in sorted(rejected.items()):
            print(f"  - {reason}: {count} offer(s) skipped")

    return arbs, near_misses



def get_prop_match_teams(match):
    """Support both the common props schema and Midnite's home/away schema."""
    home = match.get("home_team") or match.get("home") or ""
    away = match.get("away_team") or match.get("away") or ""
    return str(home).strip(), str(away).strip()


def _midnite_selection(name, odds, side="", line="", team="", **extra):
    if odds in {None, ""}:
        return None

    selection = {
        "selection": name,
        "normalized_selection": normalize_key(name),
        "odds": odds,
    }

    if side:
        selection["side"] = side
    if line != "":
        selection["line"] = str(line)
    if team:
        selection["team"] = team

    selection.update(extra)
    return selection


def _midnite_market(name, selections):
    selections = [
        selection for selection in selections
        if isinstance(selection, dict)
    ]
    return {
        "market": name,
        "normalized_market": normalize_key(name),
        "selection_count": len(selections),
        "selections": selections,
    }


def _midnite_decimal_line(raw):
    """Convert a Midnite key suffix such as 0_5 to the line 0.5."""
    raw = str(raw or "").strip("_")
    if not raw:
        return ""

    try:
        value = float(raw.replace("_", "."))
    except Exception:
        return ""

    if value.is_integer():
        return str(int(value))
    return str(value)


def _midnite_plus_line(raw):
    """
    Midnite threshold markets use N+ labels.

    Examples:
      1+ shot  == Over 0.5
      5+ cards == Over 4.5
    """
    raw = str(raw or "").strip("_")
    try:
        value = float(raw.replace("_", "."))
    except Exception:
        return ""

    line = value - 0.5
    if line.is_integer():
        return str(int(line))
    return str(line)


def _midnite_three_way_market_is_plausible(market):
    """Validate one complete Midnite three-way result market."""
    if not isinstance(market, dict):
        return False

    values = [
        fractional_to_decimal(market.get(key))
        for key in ("home", "draw", "away")
    ]

    if not all(values):
        return False

    implied_sum = sum(1.0 / value for value in values)
    return 0.98 <= implied_sum <= 1.35


def iter_midnite_market_items(match):
    """
    Adapt football/data/midnite_worldcup_props.json to the common market schema.

    Included:
      - Total Goals O/U
      - Total Cards, Corners, Shots and SOT threshold Overs
      - Home/Away team Shots and SOT threshold Overs
      - BTTS
      - Double Chance
      - First-half Result

    Player props remain outside the current football arb scanner.
    """
    home, away = get_prop_match_teams(match)
    raw_markets = match.get("markets") or {}

    if not isinstance(raw_markets, dict):
        return

    btts = raw_markets.get("btts") or {}
    if isinstance(btts, dict):
        market = _midnite_market(
            "Both Teams To Score",
            [
                _midnite_selection(
                    "Both Teams To Score - Yes",
                    btts.get("yes"),
                    side="yes",
                    period="full_time",
                    base_market="full_time_btts",
                ),
                _midnite_selection(
                    "Both Teams To Score - No",
                    btts.get("no"),
                    side="no",
                    period="full_time",
                    base_market="full_time_btts",
                ),
            ],
        )
        if market["selections"]:
            yield market["market"], market

    double_chance = raw_markets.get("double_chance") or {}
    if isinstance(double_chance, dict):
        market = _midnite_market(
            "Double Chance",
            [
                _midnite_selection(
                    f"{home} or Draw",
                    double_chance.get("home_or_draw"),
                    side="home_draw",
                    period="full_time",
                    base_market="double_chance",
                ),
                _midnite_selection(
                    f"{away} or Draw",
                    double_chance.get("away_or_draw"),
                    side="away_draw",
                    period="full_time",
                    base_market="double_chance",
                ),
                _midnite_selection(
                    f"{home} or {away}",
                    double_chance.get("home_or_away"),
                    side="home_away",
                    period="full_time",
                    base_market="double_chance",
                ),
            ],
        )
        if market["selections"]:
            yield market["market"], market

    half_result = raw_markets.get("half_result_1h") or {}
    if _midnite_three_way_market_is_plausible(half_result):
        market = _midnite_market(
            "Half Time Result",
            [
                _midnite_selection(
                    home,
                    half_result.get("home"),
                    side="home",
                    period="first_half",
                    base_market="half_time_result",
                ),
                _midnite_selection(
                    "Draw",
                    half_result.get("draw"),
                    side="draw",
                    period="first_half",
                    base_market="half_time_result",
                ),
                _midnite_selection(
                    away,
                    half_result.get("away"),
                    side="away",
                    period="first_half",
                    base_market="half_time_result",
                ),
            ],
        )
        if market["selections"]:
            yield market["market"], market
    elif half_result:
        print(
            f"  Midnite Half Time rejected for {home} v {away}: "
            f"{half_result}"
        )

    total_goals = raw_markets.get("total_goals") or {}
    if isinstance(total_goals, dict):
        selections = []

        for key, odds in total_goals.items():
            parsed = re.fullmatch(
                r"(over|under)_(\d+(?:_\d+)?)",
                str(key),
                re.I,
            )
            if not parsed:
                continue

            side = parsed.group(1).lower()
            line = _midnite_decimal_line(parsed.group(2))
            if not line:
                continue

            selections.append(
                _midnite_selection(
                    f"{side.title()} {line}",
                    odds,
                    side=side,
                    line=line,
                )
            )

        market = _midnite_market(
            "Total Goals Over / Under",
            selections,
        )
        if market["selections"]:
            yield market["market"], market

    threshold_markets = [
        ("total_cards", "Total Cards Over / Under", ""),
        ("total_corners", "Total Corners Over / Under", ""),
        (
            "total_shots_on_target",
            "Total Shots On Target Over / Under",
            "",
        ),
        ("total_shots", "Total Shots Over / Under", ""),
        (
            "home_shots_on_target",
            f"{home} Shots On Target Over / Under",
            home,
        ),
        (
            "away_shots_on_target",
            f"{away} Shots On Target Over / Under",
            away,
        ),
        ("home_shots", f"{home} Shots Over / Under", home),
        ("away_shots", f"{away} Shots Over / Under", away),
    ]

    for source_key, market_name, team in threshold_markets:
        raw_market = raw_markets.get(source_key) or {}
        if not isinstance(raw_market, dict):
            continue

        selections = []

        for key, odds in raw_market.items():
            parsed = re.fullmatch(
                r"over_(\d+(?:_\d+)?)",
                str(key),
                re.I,
            )
            if not parsed:
                continue

            line = _midnite_plus_line(parsed.group(1))
            if not line:
                continue

            label = (
                f"{team} Over {line}"
                if team
                else f"Over {line}"
            )

            selections.append(
                _midnite_selection(
                    label,
                    odds,
                    side="over",
                    line=line,
                    team=team,
                    source_threshold=(
                        f"{parsed.group(1).replace('_', '.')}+"
                    ),
                )
            )

        market = _midnite_market(market_name, selections)
        if market["selections"]:
            yield market["market"], market


def iter_market_items(match, bookmaker=None):
    """
    Yield (market name, market dict) from all supported bookmaker schemas.
    """
    if (
        bookmaker == "Midnite"
        or str(match.get("bookmaker") or "").lower() == "midnite"
    ):
        yield from iter_midnite_market_items(match)
        return

    markets = match.get("markets") or {}

    if isinstance(markets, list):
        for market in markets:
            if not isinstance(market, dict):
                continue
            name = market.get("market") or market.get("name") or ""
            if name:
                yield name, market
        return

    if isinstance(markets, dict):
        for name, market in markets.items():
            if isinstance(market, dict):
                yield name, market

def _selection_offer(bookmaker, odds_raw, match_name, market_name, label):
    decimal = fractional_to_decimal(odds_raw)
    if not decimal or decimal <= 1:
        return None

    return {
        "bookmaker": bookmaker,
        "odds": odds_raw,
        "decimal": decimal,
        "decimal_odds": decimal,
        "match": match_name,
        "source_market": market_name,
        "selection_label": label,
    }


def _is_standard_btts_market(market_name):
    mk = normalize_key(market_name)

    if "both_teams_to_score" not in mk and mk != "btts":
        return False

    blocked = {
        "result", "match_result", "first_half", "second_half",
        "1st_half", "2nd_half", "half_time", "halftime",
    }
    return not any(token in mk for token in blocked)


def resolve_btts_outcome(selection):
    """
    Accept only the ordinary full-time BTTS Yes/No selections.

    Exotic BTTS variants are rejected even if a scraper accidentally placed
    them inside a generic Both Teams To Score market.
    """
    name = normalize_key(
        selection.get("normalized_selection")
        or selection.get("selection")
        or ""
    )
    side = normalize_key(selection.get("side") or "")
    period = normalize_key(selection.get("period") or "")
    base_market = normalize_key(selection.get("base_market") or "")

    yes_names = {
        "yes",
        "btts_yes",
        "both_team_to_score_yes",
        "both_teams_to_score_yes",
        "both_teams_to_score_full_time_yes",
        "full_time_btts_yes",
    }
    no_names = {
        "no",
        "btts_no",
        "both_team_to_score_no",
        "both_teams_to_score_no",
        "both_teams_to_score_full_time_no",
        "full_time_btts_no",
    }

    if period and period not in {"full_time", "fulltime"}:
        return None

    if base_market and base_market not in {
        "full_time_btts",
        "both_teams_to_score",
        "btts",
    }:
        return None

    if name in yes_names and side in {"", "yes"}:
        return "yes"
    if name in no_names and side in {"", "no"}:
        return "no"

    return None

def _contains_team(text_key, team):
    team_key = normalize_key(normalize_team(team))
    return bool(team_key and team_key in text_key)


def resolve_double_chance_outcome(selection, home, away):
    """Map bookmaker-specific labels to home_draw/away_draw/home_away."""
    side = normalize_key(selection.get("side") or "")
    if side in {"home_draw", "away_draw", "home_away"}:
        return side

    name = normalize_key(
        selection.get("normalized_selection")
        or selection.get("selection")
        or ""
    )
    compact = name.replace("_", "")

    if compact in {"1x", "homedraw"}:
        return "home_draw"
    if compact in {"x2", "awaydraw"}:
        return "away_draw"
    if compact in {"12", "homeaway"}:
        return "home_away"

    has_home = _contains_team(name, home) or "home" in name.split("_")
    has_away = _contains_team(name, away) or "away" in name.split("_")
    has_draw = "draw" in name.split("_") or "the_draw" in name

    if has_home and has_draw and not has_away:
        return "home_draw"
    if has_away and has_draw and not has_home:
        return "away_draw"
    if has_home and has_away and not has_draw:
        return "home_away"

    return None


def _is_half_time_result_market(market_name):
    mk = normalize_key(market_name)

    # Explicitly exclude HT/FT and first-half totals.
    if any(token in mk for token in {
        "half_time_full_time", "half_time_fulltime", "ht_ft",
        "first_half_goals", "1st_half_goals", "total",
    }):
        return False

    accepted = {
        "half_time_result",
        "half_time",
        "halftime_result",
        "first_half_result",
        "1st_half_result",
        "1st_half_betting",
        "first_half_betting",
    }
    return mk in accepted or any(token in mk for token in {
        "half_time_result", "first_half_result", "1st_half_betting",
    })


def resolve_three_way_outcome(selection, home, away):
    """Map a selection to home/draw/away using side metadata or its label."""
    side = normalize_key(selection.get("side") or "")
    if side in {"home", "draw", "away"}:
        return side

    name = normalize_key(
        selection.get("normalized_selection")
        or selection.get("selection")
        or ""
    )

    if name in {"draw", "the_draw", "tie"}:
        return "draw"
    if _contains_team(name, home) or name == "home":
        return "home"
    if _contains_team(name, away) or name == "away":
        return "away"

    return None


def _best_two_way_pair(first, second):
    """Return the best cross-book pair for a two-outcome market."""
    pairs = [
        (a, b)
        for a in first
        for b in second
        if a["bookmaker"] != b["bookmaker"]
    ]
    if not pairs:
        return None

    return min(
        pairs,
        key=lambda pair: (1 / pair[0]["decimal"]) + (1 / pair[1]["decimal"]),
    )


def _best_multiway_combo(outcome_lists):
    """
    Pick one offer per outcome, requiring at least two different bookmakers.
    """
    combos = [
        combo
        for combo in product(*outcome_lists)
        if len({offer["bookmaker"] for offer in combo}) >= 2
    ]
    if not combos:
        return None

    return min(
        combos,
        key=lambda combo: sum(1 / offer["decimal"] for offer in combo),
    )


def _base_named_row(match_name, market, arb_type, arb_sum, selections, all_prices):
    return {
        "sport": "Football",
        "competition": "FIFA World Cup",
        "type": arb_type,
        "match": match_name,
        "market": market,
        "arb_sum": round(arb_sum, 6),
        "arb_percent": round(arb_sum * 100, 3),
        "profit_margin_percent": round(((1 / arb_sum) - 1) * 100, 3),
        "bookmaker_count": len({
            info["bookmaker"] for info in selections.values()
        }),
        "selections": selections,
        "all_prices": all_prices,
    }


def validate_double_chance_source_triplets(data, audit):
    """
    Remove a bookmaker's Double Chance offers for a fixture unless that source
    supplied a complete and internally plausible triplet.
    """
    for fixture in data.values():
        dc = fixture.get("double_chance") or {}
        outcomes = ("home_draw", "away_draw", "home_away")

        bookmakers = set()
        for outcome in outcomes:
            for offer in dc.get(outcome) or []:
                bookmakers.add(offer.get("bookmaker"))

        for bookmaker in sorted(bookmakers):
            offers = {}

            for outcome in outcomes:
                candidates = [
                    offer
                    for offer in dc.get(outcome) or []
                    if offer.get("bookmaker") == bookmaker
                ]
                if candidates:
                    offers[outcome] = max(
                        candidates,
                        key=lambda offer: offer["decimal"],
                    )

            valid = len(offers) == 3
            self_sum = None

            if valid:
                self_sum = 0.5 * sum(
                    1.0 / offers[outcome]["decimal"]
                    for outcome in outcomes
                )
                valid = 0.97 <= self_sum <= 1.25

            if valid:
                continue

            removed = 0
            for outcome in outcomes:
                before = len(dc.get(outcome) or [])
                dc[outcome] = [
                    offer
                    for offer in dc.get(outcome) or []
                    if offer.get("bookmaker") != bookmaker
                ]
                removed += before - len(dc[outcome])

            if removed:
                counts = audit.setdefault(
                    bookmaker,
                    {"matches": 0, "offers": 0},
                )
                counts["double_chance_rejected"] = (
                    counts.get("double_chance_rejected", 0) + removed
                )
                detail = (
                    f"{self_sum:.3f}"
                    if self_sum is not None
                    else "incomplete"
                )
                print(
                    f"  Double Chance safety: removed {removed} "
                    f"{bookmaker} offer(s) for {fixture.get('match')} "
                    f"(self sum {detail})"
                )


def scan_named_prop_arbitrage(root):
    """
    Scan:
      - Both Teams To Score (Yes / No)
      - Double Chance (Home/Draw, Away/Draw, Home/Away)
      - Half Time Result (Home / Draw / Away)

    Double Chance uses the correct overlapping-outcome hedge formula:
        total stake for £1 guaranteed return
        = 0.5 * (1/d_1X + 1/d_X2 + 1/d_12)
    """
    data = {}
    audit = {}

    for bookmaker, filename in NAMED_PROPS_FILES.items():
        path = os.path.join(root, "football", "data", filename)
        raw = load_json(path)
        if not raw:
            audit[bookmaker] = {"matches": 0, "offers": 0}
            continue

        matches = raw.get("matches") or []
        if isinstance(raw, list):
            matches = raw

        offers_added = 0
        matches_seen = 0

        for match in matches:
            if not isinstance(match, dict):
                continue

            home, away = get_prop_match_teams(match)
            if not home or not away:
                continue

            matches_seen += 1
            fk = fixture_key(home, away)
            match_name = match.get("match") or f"{home} v {away}"

            fixture = data.setdefault(fk, {
                "match": match_name,
                "home": home,
                "away": away,
                "btts": {"yes": [], "no": []},
                "double_chance": {
                    "home_draw": [],
                    "away_draw": [],
                    "home_away": [],
                },
                "half_time_result": {
                    "home": [],
                    "draw": [],
                    "away": [],
                },
            })

            for market_name, market in iter_market_items(match, bookmaker):
                selections = market.get("selections") or []

                if _is_standard_btts_market(market_name):
                    for selection in selections:
                        if not isinstance(selection, dict):
                            continue
                        outcome = resolve_btts_outcome(selection)
                        if not outcome:
                            continue
                        offer = _selection_offer(
                            bookmaker,
                            selection.get("odds") or selection.get("price"),
                            match_name,
                            market_name,
                            "Yes" if outcome == "yes" else "No",
                        )
                        if offer:
                            fixture["btts"][outcome].append(offer)
                            offers_added += 1
                    continue

                if normalize_key(market_name) == "double_chance":
                    labels = {
                        "home_draw": f"{home} or Draw",
                        "away_draw": f"{away} or Draw",
                        "home_away": f"{home} or {away}",
                    }
                    for selection in selections:
                        if not isinstance(selection, dict):
                            continue
                        outcome = resolve_double_chance_outcome(
                            selection, home, away
                        )
                        if not outcome:
                            continue
                        offer = _selection_offer(
                            bookmaker,
                            selection.get("odds") or selection.get("price"),
                            match_name,
                            market_name,
                            labels[outcome],
                        )
                        if offer:
                            fixture["double_chance"][outcome].append(offer)
                            offers_added += 1
                    continue

                if _is_half_time_result_market(market_name):
                    labels = {
                        "home": home,
                        "draw": "Draw",
                        "away": away,
                    }
                    for selection in selections:
                        if not isinstance(selection, dict):
                            continue
                        outcome = resolve_three_way_outcome(
                            selection, home, away
                        )
                        if not outcome:
                            continue
                        offer = _selection_offer(
                            bookmaker,
                            selection.get("odds") or selection.get("price"),
                            match_name,
                            market_name,
                            labels[outcome],
                        )
                        if offer:
                            fixture["half_time_result"][outcome].append(offer)
                            offers_added += 1

        audit[bookmaker] = {
            "matches": matches_seen,
            "offers": offers_added,
        }

    validate_double_chance_source_triplets(data, audit)

    arbs = []
    near_misses = []

    for fixture in data.values():
        match_name = fixture["match"]
        home = fixture["home"]
        away = fixture["away"]

        # BTTS
        yes_offers = fixture["btts"]["yes"]
        no_offers = fixture["btts"]["no"]
        pair = _best_two_way_pair(yes_offers, no_offers)
        if pair:
            best_yes, best_no = pair
            arb_sum = (1 / best_yes["decimal"]) + (1 / best_no["decimal"])
            row = _base_named_row(
                match_name,
                "Both Teams To Score",
                "props_btts",
                arb_sum,
                {
                    "yes": {
                        **best_yes,
                        "selection_label": "Yes",
                    },
                    "no": {
                        **best_no,
                        "selection_label": "No",
                    },
                },
                {
                    "yes": sorted(
                        yes_offers,
                        key=lambda x: x["decimal"],
                        reverse=True,
                    ),
                    "no": sorted(
                        no_offers,
                        key=lambda x: x["decimal"],
                        reverse=True,
                    ),
                },
            )
            if arb_sum < 1:
                arbs.append(row)
            elif arb_sum < 1.04:
                near_misses.append(row)

        # Half Time Result
        htr = fixture["half_time_result"]
        combo = _best_multiway_combo([
            htr["home"], htr["draw"], htr["away"]
        ]) if all(htr[key] for key in ["home", "draw", "away"]) else None

        if combo:
            best_home, best_draw, best_away = combo
            arb_sum = sum(1 / offer["decimal"] for offer in combo)
            row = _base_named_row(
                match_name,
                "Half Time Result",
                "props_half_time_result",
                arb_sum,
                {
                    "home": {
                        **best_home,
                        "selection_label": home,
                    },
                    "draw": {
                        **best_draw,
                        "selection_label": "Draw",
                    },
                    "away": {
                        **best_away,
                        "selection_label": away,
                    },
                },
                {
                    key: sorted(
                        htr[key],
                        key=lambda x: x["decimal"],
                        reverse=True,
                    )
                    for key in ["home", "draw", "away"]
                },
            )
            if arb_sum < 1:
                arbs.append(row)
            elif arb_sum < 1.04:
                near_misses.append(row)

        # Double Chance: overlapping outcomes. Each match result wins two bets.
        dc = fixture["double_chance"]
        combo = _best_multiway_combo([
            dc["home_draw"],
            dc["away_draw"],
            dc["home_away"],
        ]) if all(dc[key] for key in [
            "home_draw", "away_draw", "home_away"
        ]) else None

        if combo:
            best_hd, best_ad, best_ha = combo
            inverse_sum = sum(1 / offer["decimal"] for offer in combo)
            arb_sum = 0.5 * inverse_sum
            row = _base_named_row(
                match_name,
                "Double Chance",
                "props_double_chance",
                arb_sum,
                {
                    "home_draw": {
                        **best_hd,
                        "selection_label": f"{home} or Draw",
                    },
                    "away_draw": {
                        **best_ad,
                        "selection_label": f"{away} or Draw",
                    },
                    "home_away": {
                        **best_ha,
                        "selection_label": f"{home} or {away}",
                    },
                },
                {
                    key: sorted(
                        dc[key],
                        key=lambda x: x["decimal"],
                        reverse=True,
                    )
                    for key in [
                        "home_draw", "away_draw", "home_away"
                    ]
                },
            )
            if arb_sum < 1:
                arbs.append(row)
            elif arb_sum < 1.04:
                near_misses.append(row)

    arbs.sort(key=lambda row: row["profit_margin_percent"], reverse=True)
    near_misses.sort(key=lambda row: row["arb_sum"])

    print("Named props coverage:")
    for bookmaker, counts in audit.items():
        print(
            f"  - {bookmaker}: "
            f"{counts['matches']} matches, {counts['offers']} offers"
        )

    return arbs, near_misses

def main():
    fixtures = {}
    strict_index = {}
    loose_index = {}

    bookmaker_summary = {}

    for bookmaker, path in BOOK_FILES.items():
        data = load_json(path)

        if not data:
            bookmaker_summary[bookmaker] = {
                "file_found": False,
                "matches_loaded": 0,
                "path": path,
            }
            print(f"{bookmaker}: file missing or unreadable")
            continue

        rows = data.get("matches") or []
        loaded = 0

        for row in rows:
            home = row.get("home_team") or ""
            away = row.get("away_team") or ""
            odds = row.get("odds") or {}

            if not home or not away or not odds:
                continue

            strict_key = fixture_key(home, away)
            loose_key = loose_fixture_key(home, away)

            target_key = None

            if strict_key in strict_index:
                target_key = strict_index[strict_key]
            elif loose_key in loose_index:
                target_key = loose_index[loose_key]

            if not target_key:
                target_key = strict_key

                fixtures[target_key] = {
                    "sport": "Football",
                    "competition": row.get("competition") or "FIFA World Cup",
                    "match": row.get("match") or f"{home} v {away}",
                    "home_team": home,
                    "away_team": away,
                    "date_label": row.get("date_label") or "",
                    "time": row.get("time") or "",
                    "strict_key": strict_key,
                    "loose_key": loose_key,
                    "selections": {
                        "home": [],
                        "draw": [],
                        "away": [],
                    },
                    "bookmakers_seen": set(),
                }

                strict_index[strict_key] = target_key
                loose_index[loose_key] = target_key

            fixtures[target_key]["bookmakers_seen"].add(bookmaker)

            add_offer(fixtures, target_key, "home", bookmaker, odds.get("home"), row)
            add_offer(fixtures, target_key, "draw", bookmaker, odds.get("draw"), row)
            add_offer(fixtures, target_key, "away", bookmaker, odds.get("away"), row)

            loaded += 1

        bookmaker_summary[bookmaker] = {
            "file_found": True,
            "matches_loaded": loaded,
            "path": path,
        }

        print(f"{bookmaker}: loaded {loaded} matches")

    arbitrage = []
    near_misses = []

    compared_fixtures = 0
    skipped_fixtures = 0

    for key, fixture in fixtures.items():
        selections = fixture["selections"]

        if not selections["home"] or not selections["draw"] or not selections["away"]:
            skipped_fixtures += 1
            continue

        compared_fixtures += 1

        best_home = max(selections["home"], key=lambda x: x["decimal_odds"])
        best_draw = max(selections["draw"], key=lambda x: x["decimal_odds"])
        best_away = max(selections["away"], key=lambda x: x["decimal_odds"])

        arb_sum = (
            (1 / best_home["decimal_odds"])
            + (1 / best_draw["decimal_odds"])
            + (1 / best_away["decimal_odds"])
        )

        arb_percent = arb_sum * 100
        profit_margin_percent = ((1 / arb_sum) - 1) * 100

        row = {
            "sport": "Football",
            "competition": fixture["competition"],
            "type": "moneyline_1x2",
            "match": fixture["match"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "date_label": fixture["date_label"],
            "time": fixture["time"],
            "market": "Match Odds",
            "bookmaker_count": len(fixture["bookmakers_seen"]),
            "arb_sum": round(arb_sum, 6),
            "arb_percent": round(arb_percent, 3),
            "profit_margin_percent": round(profit_margin_percent, 3),
            "selections": {
                "home": best_home,
                "draw": best_draw,
                "away": best_away,
            },
            "all_prices": {
                "home": sorted(selections["home"], key=lambda x: x["decimal_odds"], reverse=True),
                "draw": sorted(selections["draw"], key=lambda x: x["decimal_odds"], reverse=True),
                "away": sorted(selections["away"], key=lambda x: x["decimal_odds"], reverse=True),
            },
        }

        if arb_sum < 1:
            arbitrage.append(row)
        else:
            near_misses.append(row)

    arbitrage.sort(key=lambda x: x["profit_margin_percent"], reverse=True)
    near_misses.sort(key=lambda x: x["arb_sum"])

    # Convert set() before writing JSON.
    for fixture in fixtures.values():
        fixture["bookmakers_seen"] = sorted(list(fixture["bookmakers_seen"]))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sport": "Football",
        "competition": "FIFA World Cup",
        "bookmaker_summary": bookmaker_summary,
        "fixture_count": len(fixtures),
        "compared_fixtures": compared_fixtures,
        "skipped_fixtures": skipped_fixtures,
        "arbitrage_count": len(arbitrage),
        "near_miss_count": len(near_misses),
        "arbitrage": arbitrage,
        "near_misses": near_misses[:25],
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    # Props arbitrage
    ou_props_arbs, ou_props_near_misses = scan_props_arbitrage(ROOT)
    named_props_arbs, named_props_near_misses = scan_named_prop_arbitrage(ROOT)

    props_arbs = ou_props_arbs + named_props_arbs
    props_near_misses = (
        ou_props_near_misses + named_props_near_misses
    )

    props_arbs.sort(
        key=lambda row: row["profit_margin_percent"],
        reverse=True,
    )
    props_near_misses.sort(key=lambda row: row["arb_sum"])

    print(f"O/U props arb opportunities: {len(ou_props_arbs)}")
    print(f"Named props arb opportunities: {len(named_props_arbs)}")
    print(f"Total props arb opportunities: {len(props_arbs)}")
    print(f"Props near misses: {len(props_near_misses)}")

    all_arbs = arbitrage + props_arbs
    all_near_misses = (near_misses + props_near_misses)
    all_near_misses.sort(key=lambda x: x["arb_sum"])

    output["arbitrage"] = all_arbs
    output["near_misses"] = all_near_misses[:25]
    output["arbitrage_count"] = len(all_arbs)
    output["near_miss_count"] = len(all_near_misses)
    output["props_arb_count"] = len(props_arbs)
    output["props_ou_arb_count"] = len(ou_props_arbs)
    output["props_named_arb_count"] = len(named_props_arbs)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("")
    print("Football arbitrage scan complete")
    print(f"Fixtures found: {len(fixtures)}")
    print(f"Fixtures compared: {compared_fixtures}")
    print(f"Fixtures skipped: {skipped_fixtures}")
    print(f"Arbitrage opportunities: {len(arbitrage)}")
    print(f"Near misses saved: {min(len(near_misses), 25)}")
    print(f"Saved to: {OUT_PATH}")

    if arbitrage:
        print("")
        print("Top arbitrage opportunities:")
        for arb in arbitrage[:10]:
            print(
                f"- {arb['match']} | "
                f"profit {arb['profit_margin_percent']}% | "
                f"home {arb['selections']['home']['odds']} {arb['selections']['home']['bookmaker']} | "
                f"draw {arb['selections']['draw']['odds']} {arb['selections']['draw']['bookmaker']} | "
                f"away {arb['selections']['away']['odds']} {arb['selections']['away']['bookmaker']}"
            )
    else:
        print("")
        print("No live football arbs found right now.")
        print("Closest near misses:")
        for miss in near_misses[:10]:
            print(
                f"- {miss['match']} | "
                f"arb {miss['arb_percent']}% | "
                f"home {miss['selections']['home']['odds']} {miss['selections']['home']['bookmaker']} | "
                f"draw {miss['selections']['draw']['odds']} {miss['selections']['draw']['bookmaker']} | "
                f"away {miss['selections']['away']['odds']} {miss['selections']['away']['bookmaker']}"
            )


if __name__ == "__main__":
    main()