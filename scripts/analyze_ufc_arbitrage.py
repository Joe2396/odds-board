import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ODDS_JSON = ROOT / "ufc" / "data" / "odds.json"
OUT_PATH = ROOT / "ufc" / "data" / "arbitrage.json"


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

                if name not in prices:
                    prices[name] = []

                prices[name].append(
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
        "event_id": event.get("id"),
        "commence_time": event.get("commence_time"),
        "fight": f"{fighters[0]} vs {fighters[1]}",
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


def main():
    data = load_json(ODDS_JSON, {"events": []})
    events = data.get("events", [])

    results = []

    for event in events:
        analysis = analyze_event(event)
        if analysis:
            results.append(analysis)

    arbs = [r for r in results if r["is_arbitrage"]]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": "odds_json",
                "total_fights_checked": len(results),
                "arbitrage_count": len(arbs),
                "fights": results,
                "arbitrage_opportunities": arbs,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Checked {len(results)} UFC fights")
    print(f"Found {len(arbs)} arbitrage opportunities")
    print(f"Saved arbitrage analysis to {OUT_PATH}")

    for arb in arbs[:10]:
        print(
            "-",
            arb["fight"],
            "| margin:",
            f'{arb["profit_margin_percent"]}%',
        )


if __name__ == "__main__":
    main()
