import json
import os
from pathlib import Path
from datetime import datetime, timezone

print("FILTERING CORAL UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]

IN_PATH = ROOT / "ufc" / "data" / "coral_props.json"
OUT_PATH = ROOT / "ufc" / "data" / "coral_props_filtered.json"


def load_data():
    if not IN_PATH.exists():
        return {"fights": []}

    with open(IN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def add_market(markets, key, selection, odds):
    selection = str(selection or "").strip()
    odds = str(odds or "").strip()

    if not selection or not odds:
        return

    markets.setdefault(key, []).append({
        "selection": selection,
        "odds": odds,
    })


def dedupe_market(items):
    seen = set()
    cleaned = []

    for item in items or []:
        if not isinstance(item, dict):
            continue

        selection = str(item.get("selection") or "").strip()
        odds = str(item.get("odds") or "").strip()

        if not selection or not odds:
            continue

        key = (selection.lower(), odds)

        if key in seen:
            continue

        seen.add(key)
        cleaned.append({
            "selection": selection,
            "odds": odds,
        })

    return cleaned


def main():
    raw = load_data()

    filtered = {
        "bookmaker": "Coral",
        "source": "coral",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "fights": [],
    }

    for fight in raw.get("fights", []) or []:
        fight_name = (
            fight.get("fight")
            or fight.get("fight_name")
            or fight.get("name")
            or "Unknown fight"
        )

        url = fight.get("url")

        structured = {
            "fight": fight_name,
            "fight_name": fight_name,
            "url": url,
            "bookmaker": "Coral",
            "markets": {
                "fight_betting": [],
                "method_of_victory": [],
                "go_the_distance": [],
                "total_rounds": [],
            },
        }

        markets_blob = fight.get("markets", {})

        # New Coral structured scraper format:
        # "markets": {
        #   "fight_betting": [...],
        #   "go_the_distance": [...],
        #   "method_of_victory": [...],
        #   "raw": [...]
        # }
        if isinstance(markets_blob, dict):
            for item in markets_blob.get("fight_betting", []) or []:
                if not isinstance(item, dict):
                    continue
                add_market(
                    structured["markets"],
                    "fight_betting",
                    item.get("selection"),
                    item.get("odds"),
                )

            for item in markets_blob.get("go_the_distance", []) or []:
                if not isinstance(item, dict):
                    continue
                add_market(
                    structured["markets"],
                    "go_the_distance",
                    item.get("selection"),
                    item.get("odds"),
                )

            for item in markets_blob.get("method_of_victory", []) or []:
                if not isinstance(item, dict):
                    continue
                add_market(
                    structured["markets"],
                    "method_of_victory",
                    item.get("selection"),
                    item.get("odds"),
                )

            for item in markets_blob.get("total_rounds", []) or []:
                if not isinstance(item, dict):
                    continue
                add_market(
                    structured["markets"],
                    "total_rounds",
                    item.get("selection"),
                    item.get("odds"),
                )

            # Fallback from raw if specific sections are empty
            for item in markets_blob.get("raw", []) or []:
                if not isinstance(item, dict):
                    continue

                market = str(item.get("market") or "").lower().strip()
                selection = item.get("selection")
                odds = item.get("odds")

                if market == "fight_betting":
                    add_market(structured["markets"], "fight_betting", selection, odds)
                elif market == "go_the_distance":
                    add_market(structured["markets"], "go_the_distance", selection, odds)
                elif market == "method_of_victory":
                    add_market(structured["markets"], "method_of_victory", selection, odds)
                elif market == "total_rounds":
                    add_market(structured["markets"], "total_rounds", selection, odds)

        # Older/fallback format:
        # "markets": [
        #   {"market": "...", "selection": "...", "odds": "..."}
        # ]
        elif isinstance(markets_blob, list):
            for item in markets_blob:
                if not isinstance(item, dict):
                    continue

                market = str(item.get("market") or "").lower().strip()
                selection = item.get("selection")
                odds = item.get("odds")

                if market == "fight_betting":
                    add_market(structured["markets"], "fight_betting", selection, odds)
                elif market == "go_the_distance":
                    add_market(structured["markets"], "go_the_distance", selection, odds)
                elif market == "method_of_victory":
                    add_market(structured["markets"], "method_of_victory", selection, odds)
                elif market == "total_rounds":
                    add_market(structured["markets"], "total_rounds", selection, odds)

        for key in structured["markets"]:
            structured["markets"][key] = dedupe_market(structured["markets"][key])

        total_markets = sum(len(v) for v in structured["markets"].values())

        if total_markets > 0:
            filtered["fights"].append(structured)

    filtered["fight_count"] = len(filtered["fights"])

    os.makedirs(OUT_PATH.parent, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)

    print("\nDONE")
    print(f"Saved: {OUT_PATH}")
    print(f"Filtered fights: {len(filtered['fights'])}")

    for fight in filtered["fights"]:
        markets = fight["markets"]

        fb = len(markets.get("fight_betting", []))
        mov = len(markets.get("method_of_victory", []))
        gtd = len(markets.get("go_the_distance", []))
        tr = len(markets.get("total_rounds", []))

        print("\n==============================")
        print(fight["fight_name"])
        print(f"Fight betting: {fb}")
        print(f"Method: {mov}")
        print(f"GTD: {gtd}")
        print(f"Total rounds: {tr}")
        print(f"Total: {fb + mov + gtd + tr}")


if __name__ == "__main__":
    main()