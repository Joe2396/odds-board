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
        "alert_count": len(alerts),
        "alerts": alerts,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("")
    print("Football EV scan complete")
    print(f"Fixtures found: {len(fixtures)}")
    print(f"Fixtures compared: {compared_fixtures}")
    print(f"Fixtures skipped: {skipped_fixtures}")
    print(f"EV alerts >= {MIN_EV_PERCENT}%: {len(alerts)}")
    print(f"Saved to: {OUT_PATH}")

    if alerts:
        print("")
        print("Top Football EV alerts:")
        for alert in alerts[:20]:
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