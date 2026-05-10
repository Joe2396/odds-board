import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ODDS_JSON = ROOT / "ufc" / "data" / "odds.json"
OUT_PATH = ROOT / "ufc" / "data" / "arbitrage.json"

PROP_FILES = [
    ("PaddyPower", ROOT / "ufc" / "data" / "props_filtered.json"),
    ("BoyleSports", ROOT / "ufc" / "data" / "boylesports_props_filtered.json"),
    ("BetVictor", ROOT / "ufc" / "data" / "betvictor_props_filtered.json"),
    ("Coral", ROOT / "ufc" / "data" / "coral_props_filtered.json"),
    ("BetMGM", ROOT / "ufc" / "data" / "betmgm_props_filtered.json"),
]


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def implied_prob(decimal_odds):
    try:
        odds = float(decimal_odds)
        if odds <= 1:
            return None
        return 1 / odds
    except Exception:
        return None


def fractional_to_decimal(value):
    value = str(value or "").strip().upper()

    if not value:
        return None

    if value == "EVS":
        return 2.0

    if "/" in value:
        try:
            a, b = value.split("/", 1)
            return round((float(a) / float(b)) + 1, 6)
        except Exception:
            return None

    try:
        val = float(value)
        if val > 1:
            return val
    except Exception:
        pass

    return None


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def norm_text(s):
    s = clean(s).lower()
    s = s.replace(" vs ", " v ")
    s = s.replace(" versus ", " v ")
    s = s.replace("–", "-").replace("—", "-")
    s = s.replace("-", " ")
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fight_key(name):
    text = norm_text(name)

    if " v " in text:
        left, right = text.split(" v ", 1)
        return " v ".join(sorted([left.strip(), right.strip()]))

    return text


def get_h2h_outcomes(event):
    prices = {}

    for bookmaker in event.get("bookmakers", []):
        book_title = bookmaker.get("title") or bookmaker.get("key")

        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue

            for outcome in market.get("outcomes", []):
                name = outcome.get("name")
                price = outcome.get("price")

                if not name or price is None:
                    continue

                try:
                    price = float(price)
                except Exception:
                    continue

                prices.setdefault(name, []).append(
                    {
                        "bookmaker": book_title,
                        "price": price,
                        "last_update": bookmaker.get("last_update"),
                    }
                )

    return prices


def analyze_event(event):
    outcomes = get_h2h_outcomes(event)

    if len(outcomes) != 2:
        return None

    best = {}

    for fighter, offers in outcomes.items():
        offers = sorted(offers, key=lambda x: x["price"], reverse=True)
        best[fighter] = offers[0]

    fighters = list(best.keys())

    p1 = implied_prob(best[fighters[0]]["price"])
    p2 = implied_prob(best[fighters[1]]["price"])

    if p1 is None or p2 is None:
        return None

    arb_sum = p1 + p2
    is_arb = arb_sum < 1
    profit_margin = (1 - arb_sum) * 100

    return {
        "type": "moneyline",
        "event_id": event.get("id"),
        "commence_time": event.get("commence_time"),
        "fight": f"{fighters[0]} vs {fighters[1]}",
        "market": "Moneyline",
        "fighters": {
            fighters[0]: {
                "best_bookmaker": best[fighters[0]]["bookmaker"],
                "best_price": best[fighters[0]]["price"],
                "implied_probability": round(p1 * 100, 2),
            },
            fighters[1]: {
                "best_bookmaker": best[fighters[1]]["bookmaker"],
                "best_price": best[fighters[1]]["price"],
                "implied_probability": round(p2 * 100, 2),
            },
        },
        "arb_sum": round(arb_sum, 6),
        "is_arbitrage": is_arb,
        "profit_margin_percent": round(profit_margin, 2),
    }


def canonical_market(market):
    m = norm_text(market)

    if "distance" in m:
        return "Goes The Distance"

    if "round" in m:
        return "Total Rounds"

    return ""


def canonical_selection(selection):
    s = clean(selection)
    low = s.lower()

    if low == "yes":
        return "Yes"

    if low == "no":
        return "No"

    m = re.search(r"\b(over|under)\s+([0-9]+(?:\.[0-9]+)?)\b", low)
    if m:
        side = m.group(1).title()
        line = m.group(2)
        return f"{side} {line}"

    return ""


def complementary_selection(selection):
    s = clean(selection)

    if s == "Yes":
        return "No"

    if s == "No":
        return "Yes"

    m = re.match(r"^(Over|Under)\s+([0-9]+(?:\.[0-9]+)?)$", s)
    if m:
        side = m.group(1)
        line = m.group(2)
        other = "Under" if side == "Over" else "Over"
        return f"{other} {line}"

    return ""


def load_prop_rows():
    rows = []

    for default_bookmaker, path in PROP_FILES:
        data = load_json(path, {"fights": [], "props": []})

        # Flat BetMGM-style format
        for p in data.get("props", []) or []:
            fight = clean(p.get("fight") or p.get("fight_name") or p.get("name"))
            market = canonical_market(p.get("market"))
            selection = canonical_selection(p.get("selection"))
            odds_raw = clean(p.get("odds"))
            decimal = fractional_to_decimal(odds_raw)
            bookmaker = clean(p.get("bookmaker") or default_bookmaker)

            if not fight or not market or not selection or not decimal:
                continue

            rows.append({
                "fight": fight,
                "fight_key": fight_key(fight),
                "bookmaker": bookmaker,
                "market": market,
                "selection": selection,
                "odds": odds_raw,
                "decimal_odds": decimal,
                "event_time": clean(p.get("event_time")),
                "source_file": str(path.relative_to(ROOT)),
            })

        # Nested bookmaker format
        for fight_obj in data.get("fights", []) or []:
            fight = clean(
                fight_obj.get("fight")
                or fight_obj.get("fight_name")
                or fight_obj.get("name")
            )
            bookmaker = clean(fight_obj.get("bookmaker") or default_bookmaker)

            if not fight:
                continue

            markets = fight_obj.get("markets") or {}

            possible_blocks = []

            if isinstance(markets, dict):
                possible_blocks.append(("Goes The Distance", markets.get("go_the_distance")))
                possible_blocks.append(("Total Rounds", markets.get("rounds") or markets.get("total_rounds")))

            possible_blocks.append(("Goes The Distance", fight_obj.get("distance_props")))
            possible_blocks.append(("Total Rounds", fight_obj.get("round_props")))

            for market_name, items in possible_blocks:
                if not items:
                    continue

                for item in items:
                    if isinstance(item, dict):
                        selection_raw = item.get("selection")
                        odds_raw = item.get("odds")
                    else:
                        continue

                    selection = canonical_selection(selection_raw)
                    decimal = fractional_to_decimal(odds_raw)

                    if not selection or not decimal:
                        continue

                    rows.append({
                        "fight": fight,
                        "fight_key": fight_key(fight),
                        "bookmaker": bookmaker,
                        "market": market_name,
                        "selection": selection,
                        "odds": clean(odds_raw),
                        "decimal_odds": decimal,
                        "event_time": clean(fight_obj.get("event_time")),
                        "source_file": str(path.relative_to(ROOT)),
                    })

    return rows


def best_by_book(rows):
    best = {}

    for row in rows:
        key = row["bookmaker"]

        if key not in best or row["decimal_odds"] > best[key]["decimal_odds"]:
            best[key] = row

    return list(best.values())


def analyze_prop_arbs(prop_rows):
    grouped = {}

    for row in prop_rows:
        key = (
            row["fight_key"],
            row["market"],
            row["selection"],
        )
        grouped.setdefault(key, []).append(row)

    checked = []
    seen_pairs = set()

    for (fkey, market, selection), rows_a in grouped.items():
        comp = complementary_selection(selection)
        if not comp:
            continue

        pair_key = tuple(sorted([selection, comp]))
        seen_key = (fkey, market, pair_key)

        if seen_key in seen_pairs:
            continue

        seen_pairs.add(seen_key)

        rows_b = grouped.get((fkey, market, comp), [])

        if not rows_b:
            continue

        best_a = sorted(best_by_book(rows_a), key=lambda x: x["decimal_odds"], reverse=True)[0]
        best_b = sorted(best_by_book(rows_b), key=lambda x: x["decimal_odds"], reverse=True)[0]

        p1 = implied_prob(best_a["decimal_odds"])
        p2 = implied_prob(best_b["decimal_odds"])

        if p1 is None or p2 is None:
            continue

        arb_sum = p1 + p2
        profit_margin = (1 - arb_sum) * 100

        checked.append({
            "type": "prop",
            "fight": best_a["fight"],
            "fight_key": fkey,
            "market": market,
            "selections": {
                selection: {
                    "bookmaker": best_a["bookmaker"],
                    "odds": best_a["odds"],
                    "decimal_odds": best_a["decimal_odds"],
                    "implied_probability": round(p1 * 100, 2),
                },
                comp: {
                    "bookmaker": best_b["bookmaker"],
                    "odds": best_b["odds"],
                    "decimal_odds": best_b["decimal_odds"],
                    "implied_probability": round(p2 * 100, 2),
                },
            },
            "arb_sum": round(arb_sum, 6),
            "is_arbitrage": arb_sum < 1,
            "profit_margin_percent": round(profit_margin, 2),
        })

    return checked


def main():
    data = load_json(ODDS_JSON, {"events": []})
    events = data.get("events", [])

    moneyline_results = []

    for event in events:
        analysis = analyze_event(event)
        if analysis:
            moneyline_results.append(analysis)

    prop_rows = load_prop_rows()
    prop_results = analyze_prop_arbs(prop_rows)

    moneyline_arbs = [r for r in moneyline_results if r["is_arbitrage"]]
    prop_arbs = [r for r in prop_results if r["is_arbitrage"]]

    all_arbs = moneyline_arbs + prop_arbs

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "source": "odds_json_plus_bookmaker_props",
        "total_moneyline_fights_checked": len(moneyline_results),
        "total_prop_markets_checked": len(prop_results),
        "total_prop_rows_loaded": len(prop_rows),
        "arbitrage_count": len(all_arbs),
        "moneyline_arbitrage_count": len(moneyline_arbs),
        "prop_arbitrage_count": len(prop_arbs),
        "fights": moneyline_results,
        "prop_markets": prop_results,
        "arbitrage_opportunities": all_arbs,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Checked {len(moneyline_results)} UFC moneyline fights")
    print(f"Loaded {len(prop_rows)} prop rows")
    print(f"Checked {len(prop_results)} two-way prop markets")
    print(f"Found {len(moneyline_arbs)} moneyline arbitrage opportunities")
    print(f"Found {len(prop_arbs)} prop arbitrage opportunities")
    print(f"Saved arbitrage analysis to {OUT_PATH}")

    for arb in all_arbs[:20]:
        print(
            "-",
            arb.get("fight"),
            "|",
            arb.get("market"),
            "| margin:",
            f'{arb["profit_margin_percent"]}%',
        )


if __name__ == "__main__":
    main()