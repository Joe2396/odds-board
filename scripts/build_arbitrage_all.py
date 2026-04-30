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
        fighters = arb.get("fighters", {})

        bookmakers = []
        for fighter, info in fighters.items():
            bookmakers.append({
                "selection": fighter,
                "bookmaker": info.get("best_bookmaker"),
                "odds": info.get("best_price"),
                "implied_probability": info.get("implied_probability"),
            })

        unified.append({
            "sport": "UFC",
            "event": arb.get("fight"),
            "market": "Moneyline",
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
