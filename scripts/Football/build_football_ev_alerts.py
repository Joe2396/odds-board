#!/usr/bin/env python3
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
}

OUT_PATH = os.path.join(ROOT, "football", "data", "ev_alerts.json")

MIN_EV_PERCENT = 10.0
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

MIN_EV_PROPS = 10.0
MIN_BOOKS_PROPS = 4


def scan_props_ev_from_index(root):
    """
    Use generate_worldcup_page.py's load_all() and build_player_index() to get
    cleanly normalised player props data, then find EV across bookmakers.
    """
    import sys
    scripts_path = os.path.join(root, "scripts", "Football")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)

    try:
        import generate_worldcup_page as gen
    except ImportError as e:
        print(f"Could not import generate_worldcup_page: {e}")
        return []

    try:
        fixtures, _, _ = gen.load_all()
    except Exception as e:
        print(f"load_all() failed: {e}")
        return []

    alerts = []

    for fixture in fixtures:
        props = fixture.get("props") or {}
        if not props:
            continue

        home = fixture.get("home_team", "")
        away = fixture.get("away_team", "")
        match_label = fixture.get("match", "")
        date_label = fixture.get("date_label", "")
        time_label = fixture.get("time", "")

        try:
            player_index = gen.build_player_index(props)
        except Exception:
            continue

        # Bookmakers excluded from props EV (scraper not ready)
        # Excluded bookmakers - props scraper not verified accurate yet
        EXCLUDED_BK = {"Unibet", "Midnite"}

        # Markets excluded from props EV (inconsistent structure across books)
        EXCLUDED_MARKETS = {
            # Goalscorer markets - structured differently per book
            "anytime_scorer", "first_goalscorer", "last_goalscorer",
            "player_to_score", "goalscorer", "to_score",
            "anytime_goalscorer", "player_scored",
            # Card markets - single odds, inconsistent across books
            "player_to_get_a_card", "player_cards", "player_carded",
            "player_booked", "to_be_carded", "player_card",
        }

        # For each player × market × threshold, collect prices across books
        for pk, pdata in player_index.items():
            player_name = pdata["name"]
            for mk, mk_data in pdata["markets"].items():
                if mk in EXCLUDED_MARKETS:
                    continue
                if mk in gen.THRESHOLD_MARKETS:
                    # mk_data = {line: {bk: {odds, decimal}}}
                    # Only compare line=0.5 - ensures same baseline across all books
                    # (BoyleSports starts shots at 2.5+ which causes false EV vs books starting at 0.5)
                    for line, line_data in mk_data.items():
                        if line not in {"0.5", "1.5", "2.5"}:
                            continue
                        if len(line_data) < MIN_BOOKS_PROPS:
                            continue

                        # Remove outliers: drop any price more than 5x from the minimum
                        # Also exclude bookmakers not ready for props EV
                        pre_filtered = {b: o for b, o in line_data.items() if b not in EXCLUDED_BK}
                        if not pre_filtered:
                            continue
                        min_dec = min(o["decimal"] for o in pre_filtered.values())
                        filtered = {b: o for b, o in pre_filtered.items()
                                   if o["decimal"] / min_dec <= 5}
                        if len(filtered) < MIN_BOOKS_PROPS:
                            continue
                        decimals = [o["decimal"] for o in filtered.values()]
                        avg_prob = sum(1/d for d in decimals) / len(decimals)
                        if avg_prob <= 0:
                            continue
                        fair_decimal = 1 / avg_prob
                        # Skip if fair price is longer than 25/1 (decimal 27)
                        if fair_decimal > 27:
                            continue
                        line_data = filtered  # use filtered for EV calculation
                        for bk, o in line_data.items():
                            ev = ((o["decimal"] * avg_prob) - 1) * 100
                            if ev >= MIN_EV_PROPS:
                                threshold = gen.LINE_LABELS.get(line, line + "+")
                                alerts.append({
                                    "sport": "Football",
                                    "competition": "FIFA World Cup",
                                    "market": gen.pretty_market_name(mk),
                                    "type": "props_player",
                                    "match": match_label,
                                    "date_label": date_label,
                                    "time": time_label,
                                    "selection": f"{player_name} {threshold}",
                                    "bookmaker": bk,
                                    "bookmaker_odds": o["odds"],
                                    "bookmaker_decimal_odds": round(o["decimal"], 6),
                                    "fair_decimal_odds": round(fair_decimal, 6),
                                    "fair_fractional_odds": decimal_to_fractional(fair_decimal),
                                    "fair_probability": round(avg_prob, 6),
                                    "ev_percent": round(ev, 3),
                                    "bookmaker_count": len(line_data),
                                    "source_url": "",
                                })
                else:
                    # mk_data = {bk: {odds, decimal}}
                    filtered_mk = {bk: o for bk, o in mk_data.items() if bk not in EXCLUDED_BK}
                    if len(filtered_mk) < MIN_BOOKS_PROPS:
                        continue
                    mk_data = filtered_mk
                    decimals_raw = [o["decimal"] for o in mk_data.values()]
                    sorted_dec2 = sorted(decimals_raw)
                    median_dec2 = sorted_dec2[len(sorted_dec2)//2]
                    filtered2 = {bk: o for bk, o in mk_data.items()
                                if o["decimal"] / median_dec2 <= 8 and median_dec2 / o["decimal"] <= 8}
                    if len(filtered2) < MIN_BOOKS_PROPS:
                        continue
                    decimals = [o["decimal"] for o in filtered2.values()]
                    avg_prob = sum(1/d for d in decimals) / len(decimals)
                    if avg_prob <= 0:
                        continue
                    fair_decimal = 1 / avg_prob
                    if fair_decimal > 27:
                        continue
                    for bk, o in mk_data.items():
                        ev = ((o["decimal"] * avg_prob) - 1) * 100
                        if ev >= MIN_EV_PROPS:
                            alerts.append({
                                "sport": "Football",
                                "competition": "FIFA World Cup",
                                "market": gen.pretty_market_name(mk),
                                "type": "props_player",
                                "match": match_label,
                                "date_label": date_label,
                                "time": time_label,
                                "selection": player_name,
                                "bookmaker": bk,
                                "bookmaker_odds": o["odds"],
                                "bookmaker_decimal_odds": round(o["decimal"], 6),
                                "fair_decimal_odds": round(fair_decimal, 6),
                                "fair_fractional_odds": decimal_to_fractional(fair_decimal),
                                "fair_probability": round(avg_prob, 6),
                                "ev_percent": round(ev, 3),
                                "bookmaker_count": len(mk_data),
                                "source_url": "",
                            })

    alerts.sort(key=lambda x: x["ev_percent"], reverse=True)
    print(f"Props EV alerts >= {MIN_EV_PROPS}%: {len(alerts)}")
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
    print(f"Props EV alerts >= {MIN_EV_PROPS}%: {len(props_alerts)}")

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
        "alerts": all_alerts,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

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