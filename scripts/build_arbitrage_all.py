import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

UFC_ARB_JSON = ROOT / "ufc" / "data" / "arbitrage.json"
OUT_PATH = ROOT / "data" / "arbitrage_all.json"


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main():
    ufc_data = load_json(UFC_ARB_JSON, {})
    ufc_arbs = ufc_data.get("arbitrage_opportunities", [])

    unified = []

    for arb in ufc_arbs:
        arb_type = arb.get("type") or "moneyline"
        market = arb.get("market") or "Moneyline"

        bookmakers = []

        # Moneyline format
        if arb.get("fighters"):
            for fighter, info in arb.get("fighters", {}).items():
                bookmakers.append({
                    "selection": fighter,
                    "bookmaker": info.get("best_bookmaker"),
                    "odds": info.get("best_price"),
                    "decimal_odds": info.get("best_price"),
                    "implied_probability": info.get("implied_probability"),
                })

        # Prop format
        elif arb.get("selections"):
            for selection, info in arb.get("selections", {}).items():
                bookmakers.append({
                    "selection": selection,
                    "bookmaker": info.get("bookmaker"),
                    "odds": info.get("odds"),
                    "decimal_odds": info.get("decimal_odds"),
                    "implied_probability": info.get("implied_probability"),
                })

        if not bookmakers:
            continue

        unified.append({
            "sport": "UFC",
            "type": arb_type,
            "event": arb.get("fight"),
            "market": market,
            "commence_time": arb.get("commence_time"),
            "profit_margin_percent": arb.get("profit_margin_percent"),
            "arb_sum": arb.get("arb_sum"),
            "bookmakers": bookmakers,
            "source_file": "ufc/data/arbitrage.json",
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_arbitrage": len(unified),
            "arbitrage": unified,
        }, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(unified)} total arbitrage opportunities to {OUT_PATH}")


if __name__ == "__main__":
    main()
