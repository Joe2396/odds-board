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
    # "Unibet":     ("unibet_worldcup_props.json",       "fractional"),  # not ready
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


def scan_props_arbitrage(root):
    """Scan O/U prop markets across bookmakers for arbitrage."""
    # Structure: {fixture_key: {market_key: {line: {side: [{bk, odds, decimal}]}}}}
    data = {}

    for bk, (fname, fmt) in PROPS_FILES.items():
        path = os.path.join(root, "football", "data", fname)
        raw = load_json(path)
        if not raw:
            continue
        matches = raw.get("matches") or []
        if isinstance(raw, list):
            matches = raw

        for m in matches:
            home = m.get("home_team", "")
            away = m.get("away_team", "")
            if not home or not away:
                continue
            fk = fixture_key(home, away)
            markets = m.get("markets") or {}
            if isinstance(markets, list):
                markets = {mk.get("market", ""): mk for mk in markets}

            for mkt_name, mkt_data in markets.items():
                mk = normalize_key(mkt_name)
                if not any(ok in mk for ok in ["over_under", "over", "corners", "cards", "shots", "goals"]):
                    continue
                sels = mkt_data.get("selections") or []
                for sel in sels:
                    if not isinstance(sel, dict): continue
                    sn = sel.get("selection", "")
                    odds_raw = sel.get("odds") or sel.get("price", "")
                    side = sel.get("side", "")
                    line = sel.get("line", "")

                    # Extract side/line from selection name if not set
                    if not side or not line:
                        import re as _re
                        m2 = _re.match(r"(over|under)\s+([\d.]+)", sn, _re.I)
                        if m2:
                            side = m2.group(1).lower()
                            line = m2.group(2)

                    if not side or not line or not odds_raw:
                        continue

                    dec = fractional_to_decimal(odds_raw)
                    if not dec or dec <= 1:
                        continue

                    data.setdefault(fk, {}).setdefault(mk, {}).setdefault(line, {}).setdefault(side, [])
                    data[fk][mk][line][side].append({
                        "bookmaker": bk, "odds": odds_raw, "decimal": dec,
                        "match": f"{home} v {away}"
                    })

    # Find arbs
    arbs = []
    near_misses = []
    for fk, markets in data.items():
        for mk, lines in markets.items():
            for line, sides in lines.items():
                if "over" not in sides or "under" not in sides:
                    continue
                best_over  = max(sides["over"],  key=lambda x: x["decimal"])
                best_under = max(sides["under"], key=lambda x: x["decimal"])
                arb_sum = (1/best_over["decimal"]) + (1/best_under["decimal"])
                row = {
                    "sport": "Football",
                    "competition": "FIFA World Cup",
                    "type": "props_ou",
                    "match": best_over["match"],
                    "market": mk.replace("_", " ").title(),
                    "line": line,
                    "arb_sum": round(arb_sum, 6),
                    "arb_percent": round(arb_sum * 100, 3),
                    "profit_margin_percent": round(((1/arb_sum) - 1) * 100, 3),
                    "bookmaker_count": 2,
                    "selections": {
                        "over":  {"bookmaker": best_over["bookmaker"],  "odds": best_over["odds"],  "decimal_odds": best_over["decimal"]},
                        "under": {"bookmaker": best_under["bookmaker"], "odds": best_under["odds"], "decimal_odds": best_under["decimal"]},
                    },
                    "all_prices": {
                        "over":  sorted(sides["over"],  key=lambda x: x["decimal"], reverse=True),
                        "under": sorted(sides["under"], key=lambda x: x["decimal"], reverse=True),
                    }
                }
                if arb_sum < 1:
                    arbs.append(row)
                elif arb_sum < 1.04:
                    near_misses.append(row)

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
    props_arbs, props_near_misses = scan_props_arbitrage(ROOT)
    print(f"Props arb opportunities: {len(props_arbs)}")
    print(f"Props near misses: {len(props_near_misses)}")

    all_arbs = arbitrage + props_arbs
    all_near_misses = (near_misses + props_near_misses)
    all_near_misses.sort(key=lambda x: x["arb_sum"])

    output["arbitrage"] = all_arbs
    output["near_misses"] = all_near_misses[:25]
    output["arbitrage_count"] = len(all_arbs)
    output["near_miss_count"] = len(all_near_misses)
    output["props_arb_count"] = len(props_arbs)

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