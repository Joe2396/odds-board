import json
import re
from pathlib import Path
from datetime import datetime, timezone

print("FILTERING BOYLESPORTS PROPS")

ROOT = Path(__file__).resolve().parents[1]
IN_PATH = ROOT / "ufc" / "data" / "boylesports_props.json"
OUT_PATH = ROOT / "ufc" / "data" / "boylesports_props_filtered.json"


def is_bad_selection(selection):
    s = str(selection or "").strip().lower()

    if not s:
        return True

    bad_exact = {
        "22:00",
        "23:00",
        "26 mins",
        "27 mins",
        "selected",
        "cash out",
    }

    if s in bad_exact:
        return True

    if re.match(r"^\d{1,2}:\d{2}$", s):
        return True

    if re.match(r"^\d+\s*mins?$", s):
        return True

    bad_contains = [
        "bet builder",
        "acca boost",
        "boost",
        "betslip",
        "gaming quick links",
        "football",
        "today",
    ]

    return any(b in s for b in bad_contains)


def clean_items(items):
    cleaned = []

    for item in items or []:
        selection = item.get("selection", "").strip()
        odds = item.get("odds", "").strip()

        if not selection or not odds:
            continue

        if is_bad_selection(selection):
            continue

        cleaned.append({
            "selection": selection,
            "odds": odds,
        })

    return cleaned


def split_go_distance(rounds):
    rounds_clean = []
    go_distance = []

    for item in rounds or []:
        selection = item.get("selection", "").strip().lower()

        if selection in ["yes", "no"]:
            go_distance.append(item)
        else:
            rounds_clean.append(item)

    return rounds_clean, go_distance


def main():
    if not IN_PATH.exists():
        print(f"Missing input file: {IN_PATH}")
        return

    with open(IN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    filtered_fights = []

    for fight in data.get("fights", []):
        markets = fight.get("markets", {})

        method = clean_items(markets.get("method_of_victory", []))
        rounds_raw = clean_items(markets.get("rounds", []))
        rounds, go_distance_from_rounds = split_go_distance(rounds_raw)

        existing_distance = clean_items(markets.get("go_the_distance", []))
        go_distance = existing_distance or go_distance_from_rounds

        has_props = bool(method or rounds or go_distance)

        if not has_props:
            continue

        filtered_fights.append({
            "fight": fight.get("fight"),
            "url": fight.get("url"),
            "bookmaker": "BoyleSports",
            "has_props": True,
            "scraped_at": fight.get("scraped_at"),
            "markets": {
                "method_of_victory": method,
                "rounds": rounds,
                "go_the_distance": go_distance,
            }
        })

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "boylesports",
        "bookmaker": "BoyleSports",
        "count": len(filtered_fights),
        "fights": filtered_fights,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Input fights: {len(data.get('fights', []))}")
    print(f"Filtered fights: {len(filtered_fights)}")
    print(f"Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()