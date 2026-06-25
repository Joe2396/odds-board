#!/usr/bin/env python3
# FOOTBALL_EV_BALANCED_PROPS_V4
import json
import os
import re
from datetime import datetime, timezone

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

OUT_PATH = os.path.join(ROOT, "football", "data", "ev_alerts.json")

MIN_EV_PERCENT = 20.0
MIN_BOOKMAKERS_FOR_FAIR_PRICE = 3


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


def decimal_to_fractional(decimal_odds):
    if not decimal_odds or decimal_odds <= 1:
        return ""

    frac = decimal_odds - 1

    # Simple readable approximation.
    common = [
        (1, 20), (1, 16), (1, 14), (1, 12), (1, 10), (1, 8), (1, 7),
        (1, 6), (1, 5), (2, 9), (1, 4), (2, 7), (3, 10), (1, 3),
        (4, 11), (2, 5), (4, 9), (1, 2), (8, 15), (4, 7), (8, 13),
        (4, 6), (8, 11), (4, 5), (5, 6), (10, 11), (1, 1), (11, 10),
        (6, 5), (5, 4), (11, 8), (6, 4), (13, 8), (7, 4), (15, 8),
        (2, 1), (21, 10), (11, 5), (9, 4), (12, 5), (5, 2), (13, 5),
        (11, 4), (3, 1), (10, 3), (7, 2), (4, 1), (9, 2), (5, 1),
        (11, 2), (6, 1), (7, 1), (8, 1), (9, 1), (10, 1), (11, 1),
        (12, 1), (14, 1), (16, 1), (20, 1), (25, 1), (28, 1), (33, 1),
        (40, 1), (50, 1), (60, 1),
    ]

    best = min(common, key=lambda x: abs((x[0] / x[1]) - frac))
    if best == (1, 1):
        return "EVS"

    return f"{best[0]}/{best[1]}"


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
        "source_url": row.get("source_url") or "",
    })


def remove_bookmaker_vig(selection_prices):
    """
    Uses all available prices for one fixture to estimate fair probability.

    For each bookmaker with full home/draw/away prices:
    - Convert their 1X2 book to implied probabilities.
    - Remove margin by normalising probabilities to 100%.
    - Average the fair probabilities across bookmakers.

    This is better than just averaging odds, because it handles overround.
    """
    books = {}

    for side in ["home", "draw", "away"]:
        for offer in selection_prices[side]:
            book = offer["bookmaker"]
            books.setdefault(book, {})[side] = offer["decimal_odds"]

    fair_probs = {
        "home": [],
        "draw": [],
        "away": [],
    }

    for book, sides in books.items():
        if not all(side in sides for side in ["home", "draw", "away"]):
            continue

        raw_probs = {
            "home": 1 / sides["home"],
            "draw": 1 / sides["draw"],
            "away": 1 / sides["away"],
        }

        total = sum(raw_probs.values())

        if total <= 0:
            continue

        for side in ["home", "draw", "away"]:
            fair_probs[side].append(raw_probs[side] / total)

    averaged = {}

    for side in ["home", "draw", "away"]:
        if fair_probs[side]:
            averaged[side] = sum(fair_probs[side]) / len(fair_probs[side])
        else:
            averaged[side] = None

    return averaged



# ── Props EV alerts ────────────────────────────────────────────────────────────

MIN_EV_PROPS = 20.0

# Props EV is deliberately stricter than moneyline EV. One malformed sparse
# player row can otherwise create hundreds of false alerts.
MIN_BOOKS_PROPS = 4
MIN_COMPARISON_BOOKS_PROPS = 3
MAX_EV_PROPS = 40.0
MAX_BEST_TO_SECOND_PRICE_RATIO = 1.35
MAX_CONSENSUS_PRICE_RATIO = 1.35
TOP_CONSENSUS_BOOKS = 3
MAX_PROPS_ALERTS_PER_FIXTURE = 12

# A second tier can retain genuine, very large standout prices, but only when
# the source and comparison ladders provide enough structural evidence.
MAX_VERIFIED_HIGH_EV_PROPS = 250.0
HIGH_EDGE_MAX_BEST_SECOND_RATIO = 2.50
HIGH_EDGE_MAX_CONSENSUS_RATIO = 2.50
MIN_FULL_COMPARISON_LADDERS = 2

# Unibet player grids can contain blank early columns. It is no longer
# quarantined wholesale; Shots/SOT are admitted only when the full 1+/2+/3+
# ladder exists and is monotonic for that player.
STRICT_FULL_LADDER_BOOK_MARKETS = {
    ("Unibet", "shots"),
    ("Unibet", "shots_on_target"),
}

# Keep the first safety release to structured threshold markets. Assists,
# goalscorers and cards are one-sided markets and need a separate fair-price
# model before being published as EV alerts.
SAFE_THRESHOLD_EV_MARKETS = {
    "shots",
    "shots_on_target",
    "player_tackles_completed",
    "player_fouls_committed",
    "player_fouls_won",
    "player_fouls_conceded",
}


def _median(values):
    values = sorted(float(value) for value in values)

    if not values:
        return None

    middle = len(values) // 2

    if len(values) % 2:
        return values[middle]

    return (values[middle - 1] + values[middle]) / 2


def _line_number(value):
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _book_ladder_prices(
    market_data,
    bookmaker,
    lines,
):
    prices = []

    for line in lines:
        offer = (market_data.get(line) or {}).get(bookmaker)

        if not isinstance(offer, dict):
            return None

        try:
            decimal = float(offer.get("decimal"))
        except Exception:
            return None

        if decimal <= 1:
            return None

        prices.append(decimal)

    return prices


def _prices_are_monotonic(prices):
    if not prices:
        return False

    # Higher thresholds must never be shorter than lower thresholds.
    return all(
        higher + 1e-9 >= lower
        for lower, higher in zip(prices, prices[1:])
    )


def _book_full_core_ladder_is_safe(
    market_data,
    bookmaker,
):
    """
    Require an explicit, monotonic 1+/2+/3+ ladder.

    This is the key defence against sparse Unibet rows being shifted left:
    a player with only later threshold prices cannot enter EV.
    """
    prices = _book_ladder_prices(
        market_data,
        bookmaker,
        ("0.5", "1.5", "2.5"),
    )

    return bool(
        prices
        and _prices_are_monotonic(prices)
    )


def _book_ladder_is_safe(
    market_data,
    bookmaker,
    current_line,
):
    """
    Require every lower threshold through the candidate line.

    Example:
      2+ needs valid 1+ and 2+ prices.
      3+ needs valid 1+, 2+ and 3+ prices.
    """
    current = _line_number(current_line)

    if current is None:
        return False

    required_lines = [
        line
        for line in ("0.5", "1.5", "2.5")
        if float(line) <= current
    ]

    prices = _book_ladder_prices(
        market_data,
        bookmaker,
        required_lines,
    )

    return bool(
        prices
        and _prices_are_monotonic(prices)
    )


def _safe_props_offer(
    market_key,
    market_data,
    line,
    bookmaker,
    offer,
):
    if market_key not in SAFE_THRESHOLD_EV_MARKETS:
        return False

    if (
        bookmaker,
        market_key,
    ) in STRICT_FULL_LADDER_BOOK_MARKETS:
        if not _book_full_core_ladder_is_safe(
            market_data,
            bookmaker,
        ):
            return False
    elif not _book_ladder_is_safe(
        market_data,
        bookmaker,
        line,
    ):
        return False

    try:
        decimal = float(offer.get("decimal"))
    except Exception:
        return False

    return 1.01 <= decimal <= 51.0


def _verified_high_edge_structure(
    market_data,
    candidate_bookmaker,
    comparison_bookmakers,
):
    """
    Extreme alerts need stronger structural evidence than ordinary alerts.

    The standout bookmaker must have a complete 1+/2+/3+ ladder, and at least
    two other bookmakers must independently have complete monotonic ladders.
    """
    if not _book_full_core_ladder_is_safe(
        market_data,
        candidate_bookmaker,
    ):
        return False

    full_comparison_count = sum(
        1
        for bookmaker in comparison_bookmakers
        if _book_full_core_ladder_is_safe(
            market_data,
            bookmaker,
        )
    )

    return (
        full_comparison_count
        >= MIN_FULL_COMPARISON_LADDERS
    )


def _build_safe_threshold_alert(
    gen,
    fixture,
    player_name,
    market_key,
    market_data,
    line,
):
    """
    Build one exact player/market/line candidate.

    Normal prices use the conservative V3 consensus rules. Very large standout
    prices enter only through the verified full-ladder route.
    """
    raw_line_data = market_data.get(line) or {}

    safe_offers = {
        bookmaker: offer
        for bookmaker, offer in raw_line_data.items()
        if _safe_props_offer(
            market_key,
            market_data,
            line,
            bookmaker,
            offer,
        )
    }

    if len(safe_offers) < MIN_BOOKS_PROPS:
        return None, "not_enough_safe_books"

    ranked = sorted(
        safe_offers.items(),
        key=lambda item: item[1]["decimal"],
        reverse=True,
    )

    best_bookmaker, best_offer = ranked[0]
    second_decimal = ranked[1][1]["decimal"]

    if second_decimal <= 1:
        return None, "invalid_second_price"

    best_second_ratio = (
        best_offer["decimal"] / second_decimal
    )

    comparison = {
        bookmaker: offer
        for bookmaker, offer in safe_offers.items()
        if bookmaker != best_bookmaker
    }

    if len(comparison) < MIN_COMPARISON_BOOKS_PROPS:
        return None, "not_enough_comparison_books"

    comparison_decimals = sorted(
        (
            offer["decimal"]
            for offer in comparison.values()
        ),
        reverse=True,
    )

    top_consensus = comparison_decimals[
        :TOP_CONSENSUS_BOOKS
    ]

    if len(top_consensus) < TOP_CONSENSUS_BOOKS:
        return None, "not_enough_top_consensus_books"

    top_consensus_ratio = (
        top_consensus[0] / top_consensus[-1]
    )

    verified_high_edge = _verified_high_edge_structure(
        market_data,
        best_bookmaker,
        comparison.keys(),
    )

    normal_structure = (
        best_second_ratio
            <= MAX_BEST_TO_SECOND_PRICE_RATIO
        and top_consensus_ratio
            <= MAX_CONSENSUS_PRICE_RATIO
    )

    high_edge_structure = (
        verified_high_edge
        and best_second_ratio
            <= HIGH_EDGE_MAX_BEST_SECOND_RATIO
        and top_consensus_ratio
            <= HIGH_EDGE_MAX_CONSENSUS_RATIO
    )

    if not normal_structure and not high_edge_structure:
        if best_second_ratio > HIGH_EDGE_MAX_BEST_SECOND_RATIO:
            return None, "isolated_best_price"
        return None, "consensus_disagreement"

    fair_decimal = _median(top_consensus)

    if not fair_decimal or fair_decimal <= 1:
        return None, "invalid_fair_decimal"

    if fair_decimal > 27:
        return None, "fair_price_too_large"

    fair_probability = 1.0 / fair_decimal
    ev_percent = (
        best_offer["decimal"] * fair_probability - 1
    ) * 100

    if ev_percent < MIN_EV_PROPS:
        return None, "below_minimum_ev"

    if normal_structure:
        if ev_percent > MAX_EV_PROPS:
            # A result too large for the normal route must satisfy the stronger
            # verified ladder checks.
            if not high_edge_structure:
                return None, "implausible_ev"
    elif ev_percent > MAX_VERIFIED_HIGH_EV_PROPS:
        return None, "implausible_verified_high_ev"

    threshold = gen.LINE_LABELS.get(
        line,
        f"{line}+",
    )

    props_payload = (
        fixture.get("props", {})
        .get(best_bookmaker, {})
    )

    safety_model = (
        "verified_full_ladder_high_edge_v4"
        if (
            high_edge_structure
            and ev_percent > MAX_EV_PROPS
        )
        else "top_three_consensus_v4"
    )

    return {
        "sport": "Football",
        "competition": "FIFA World Cup",
        "market": gen.pretty_market_name(market_key),
        "type": "props_player",
        "match": fixture.get("match", ""),
        "date_label": fixture.get("date_label", ""),
        "time": fixture.get("time", ""),
        "selection": f"{player_name} {threshold}",
        "bookmaker": best_bookmaker,
        "bookmaker_odds": best_offer["odds"],
        "bookmaker_decimal_odds": round(
            best_offer["decimal"],
            6,
        ),
        "fair_decimal_odds": round(
            fair_decimal,
            6,
        ),
        "fair_fractional_odds": decimal_to_fractional(
            fair_decimal
        ),
        "fair_probability": round(
            fair_probability,
            6,
        ),
        "ev_percent": round(ev_percent, 3),
        "bookmaker_count": len(safe_offers),
        "comparison_bookmaker_count": len(
            comparison
        ),
        "source_url": props_payload.get(
            "source_url",
            "",
        ),
        "safety_model": safety_model,
        "verified_high_edge": (
            safety_model
            == "verified_full_ladder_high_edge_v4"
        ),
    }, ""

def scan_props_ev_from_index(root):
    """
    Build a small, fail-closed player-props EV list.

    Safety rules:
      - sparse Unibet Shots/SOT rows require complete full ladders;
      - five safe books are required;
      - the candidate is excluded from its own fair price;
      - fair price uses the median of the top three comparison prices;
      - only the best offer for each exact prop is evaluated;
      - isolated best prices and extreme EV are rejected;
      - only one threshold alert per player/market is published;
      - each fixture is capped at its strongest alerts.
    """
    import sys

    scripts_path = os.path.join(
        root,
        "scripts",
        "Football",
    )
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)

    try:
        import generate_worldcup_page as gen
    except ImportError as error:
        print(
            "Could not import generate_worldcup_page: "
            f"{error}"
        )
        return []

    try:
        fixtures, _, _ = gen.load_all()
    except Exception as error:
        print(f"load_all() failed: {error}")
        return []

    alerts = []
    rejected = {}

    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1

    for fixture in fixtures:
        props = fixture.get("props") or {}

        if not props:
            continue

        try:
            player_index = gen.build_player_index(
                props,
                fixture.get("home_team", ""),
                fixture.get("away_team", ""),
            )
        except Exception:
            reject("player_index_failed")
            continue

        fixture_candidates = []

        for player_data in player_index.values():
            player_name = player_data.get("name", "")

            if not player_name:
                continue

            for market_key, market_data in (
                player_data.get("markets", {}).items()
            ):
                if market_key not in SAFE_THRESHOLD_EV_MARKETS:
                    continue

                player_market_candidates = []

                for line in ("0.5", "1.5", "2.5"):
                    if line not in market_data:
                        continue

                    alert, reason = (
                        _build_safe_threshold_alert(
                            gen,
                            fixture,
                            player_name,
                            market_key,
                            market_data,
                            line,
                        )
                    )

                    if alert:
                        player_market_candidates.append(alert)
                    elif reason:
                        reject(reason)

                # Keep all thresholds that have EV so users can filter by odds range.
                # e.g. Maeda 2+ shots and 3+ shots both show if both have edge.
                if player_market_candidates:
                    fixture_candidates.extend(player_market_candidates)

        fixture_candidates.sort(
            key=lambda row: row["ev_percent"],
            reverse=True,
        )

        alerts.extend(
            fixture_candidates[
                :MAX_PROPS_ALERTS_PER_FIXTURE
            ]
        )

    alerts.sort(
        key=lambda row: row["ev_percent"],
        reverse=True,
    )

    print(
        "Safe props EV alerts "
        f"{MIN_EV_PROPS:.1f}%–{MAX_EV_PROPS:.1f}%: "
        f"{len(alerts)}"
    )

    if rejected:
        print("Props EV safety filters:")
        for reason, count in sorted(rejected.items()):
            print(f"  - {reason}: {count}")

    return alerts

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

    alerts = []
    skipped_fixtures = 0
    compared_fixtures = 0

    for key, fixture in fixtures.items():
        selections = fixture["selections"]
        bookmaker_count = len(fixture["bookmakers_seen"])

        if bookmaker_count < MIN_BOOKMAKERS_FOR_FAIR_PRICE:
            skipped_fixtures += 1
            continue

        if not selections["home"] or not selections["draw"] or not selections["away"]:
            skipped_fixtures += 1
            continue

        fair_probs = remove_bookmaker_vig(selections)

        if not all(fair_probs.get(side) for side in ["home", "draw", "away"]):
            skipped_fixtures += 1
            continue

        compared_fixtures += 1

        for side in ["home", "draw", "away"]:
            fair_prob = fair_probs[side]
            fair_decimal = 1 / fair_prob
            fair_fractional = decimal_to_fractional(fair_decimal)

            for offer in selections[side]:
                market_decimal = offer["decimal_odds"]

                ev_decimal = (market_decimal * fair_prob) - 1
                ev_percent = ev_decimal * 100

                if ev_percent >= MIN_EV_PERCENT:
                    if side == "home":
                        selection_name = fixture["home_team"]
                    elif side == "away":
                        selection_name = fixture["away_team"]
                    else:
                        selection_name = "Draw"

                    alerts.append({
                        "sport": "Football",
                        "competition": fixture["competition"],
                        "market": "Match Odds",
                        "type": "moneyline_1x2",
                        "match": fixture["match"],
                        "home_team": fixture["home_team"],
                        "away_team": fixture["away_team"],
                        "date_label": fixture["date_label"],
                        "time": fixture["time"],
                        "selection": selection_name,
                        "selection_side": side,
                        "bookmaker": offer["bookmaker"],
                        "bookmaker_odds": offer["odds"],
                        "bookmaker_decimal_odds": round(market_decimal, 6),
                        "fair_decimal_odds": round(fair_decimal, 6),
                        "fair_fractional_odds": fair_fractional,
                        "fair_probability": round(fair_prob, 6),
                        "ev_percent": round(ev_percent, 3),
                        "bookmaker_count": bookmaker_count,
                        "source_url": offer.get("source_url") or "",
                    })

    # Props EV alerts
    props_alerts = scan_props_ev_from_index(ROOT)
    print(f"Safe props EV alerts: {len(props_alerts)}")

    all_alerts = alerts + props_alerts
    all_alerts.sort(key=lambda x: x["ev_percent"], reverse=True)

    alerts.sort(key=lambda x: x["ev_percent"], reverse=True)

    for fixture in fixtures.values():
        fixture["bookmakers_seen"] = sorted(list(fixture["bookmakers_seen"]))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sport": "Football",
        "competition": "FIFA World Cup",
        "min_ev_percent": MIN_EV_PERCENT,
        "min_bookmakers_for_fair_price": MIN_BOOKMAKERS_FOR_FAIR_PRICE,
        "bookmaker_summary": bookmaker_summary,
        "fixture_count": len(fixtures),
        "compared_fixtures": compared_fixtures,
        "skipped_fixtures": skipped_fixtures,
        "alert_count": len(all_alerts),
        "moneyline_alert_count": len(alerts),
        "props_alert_count": len(props_alerts),
        "props_ev_safety": {
            "minimum_books": MIN_BOOKS_PROPS,
            "minimum_comparison_books": MIN_COMPARISON_BOOKS_PROPS,
            "top_consensus_books": TOP_CONSENSUS_BOOKS,
            "minimum_ev_percent": MIN_EV_PROPS,
            "maximum_ev_percent": MAX_EV_PROPS,
            "maximum_verified_high_ev_percent": MAX_VERIFIED_HIGH_EV_PROPS,
            "maximum_alerts_per_fixture": MAX_PROPS_ALERTS_PER_FIXTURE,
            "unibet_shots_sot_quarantined": False,
            "unibet_full_ladder_required": True,
            "model": "balanced_full_ladder_v4",
        },
        "alerts": all_alerts,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    temp_out_path = OUT_PATH + ".tmp"

    with open(temp_out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    os.replace(temp_out_path, OUT_PATH)

    print("")
    print("Football EV scan complete")
    print(f"Fixtures found: {len(fixtures)}")
    print(f"Fixtures compared: {compared_fixtures}")
    print(f"Fixtures skipped: {skipped_fixtures}")
    print(f"EV alerts >= {MIN_EV_PERCENT}%: {len(all_alerts)} ({len(alerts)} moneyline, {len(props_alerts)} props)")
    print(f"Saved to: {OUT_PATH}")

    if all_alerts:
        print("")
        print("Top Football EV alerts:")
        for alert in all_alerts[:20]:
            print(
                f"- {alert['match']} | {alert['selection']} | "
                f"{alert['bookmaker_odds']} {alert['bookmaker']} | "
                f"fair {alert['fair_fractional_odds']} | "
                f"EV +{alert['ev_percent']}%"
            )
    else:
        print("")
        print("No Football EV alerts found right now.")


if __name__ == "__main__":
    main()