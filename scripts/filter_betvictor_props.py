import json
import re
from pathlib import Path
from datetime import datetime, timezone

print("FILTERING BETVICTOR UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]

IN_PATH = ROOT / "ufc" / "data" / "betvictor_props.json"
OUT_PATH = ROOT / "ufc" / "data" / "betvictor_props_filtered.json"


def clean_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def is_valid_odds(odds):
    odds = clean_text(odds).upper()
    return (
        odds == "EVS"
        or bool(re.match(r"^\d+/\d+$", odds))
        or bool(re.match(r"^\d+\.\d+$", odds))
    )


def is_junk_selection(selection):
    s = clean_text(selection).lower()

    if not s:
        return True

    junk_exact = {
        "popular",
        "all markets",
        "bet boosts",
        "lucky dip",
        "cash out",
        "in-play",
        "sports home",
        "offers",
        "betslip",
        "log in",
        "sign up",
        "ufc",
        "mma",
        "yes",
        "no",
    }

    junk_contains = [
        "terms",
        "privacy",
        "cookies",
        "safer gambling",
        "help",
        "contact",
        "casino",
        "football",
        "horse racing",
        "bet calculator",
        "minutes",
        "mins",
        "starts in",
        "today",
        "tomorrow",
    ]

    if s in junk_exact:
        return True

    if any(x in s for x in junk_contains):
        return True

    if re.match(r"^\d{1,2}:\d{2}$", s):
        return True

    if re.match(r"^\d+\s*mins?$", s):
        return True

    return False


def keep_market_item(item):
    selection = clean_text(item.get("selection"))
    odds = clean_text(item.get("odds"))

    if is_junk_selection(selection):
        return False

    if not is_valid_odds(odds):
        return False

    return True


def normalize_market_key(key):
    key = clean_text(key).lower()

    if key in ["fight_betting", "to_win", "moneyline"]:
        return "fight_betting"

    if key in ["method_of_victory", "method", "winning_method"]:
        return "method_of_victory"

    if key in ["rounds", "round_betting", "total_rounds"]:
        return "rounds"

    if key in ["go_the_distance", "distance", "fight_go_distance"]:
        return "go_the_distance"

    return key


def dedupe_items(items):
    seen = set()
    out = []

    for item in items:
        selection = clean_text(item.get("selection"))
        odds = clean_text(item.get("odds"))

        key = (selection.lower(), odds.upper())

        if key in seen:
            continue

        seen.add(key)
        out.append({
            "selection": selection,
            "odds": odds,
        })

    return out


with open(IN_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

filtered_fights = []

for fight in data.get("fights", []):
    fight_name = clean_text(
        fight.get("fight")
        or fight.get("fight_name")
        or fight.get("bout")
    )

    raw_markets = fight.get("markets") or {}

    filtered_markets = {
        "fight_betting": [],
        "method_of_victory": [],
        "rounds": [],
        "go_the_distance": [],
    }

    if isinstance(raw_markets, dict):
        for raw_key, raw_items in raw_markets.items():
            market_key = normalize_market_key(raw_key)

            if market_key not in filtered_markets:
                continue

            if not isinstance(raw_items, list):
                continue

            for item in raw_items:
                if not isinstance(item, dict):
                    continue

                if keep_market_item(item):
                    filtered_markets[market_key].append({
                        "selection": clean_text(item.get("selection")),
                        "odds": clean_text(item.get("odds")),
                    })

    for key in filtered_markets:
        filtered_markets[key] = dedupe_items(filtered_markets[key])

    total_props = sum(len(v) for v in filtered_markets.values())

    if total_props == 0:
        continue

    filtered_fights.append({
        "bookmaker": "BetVictor",
        "fight": fight_name,
        "fight_name": fight_name,
        "url": fight.get("url"),
        "has_props": True,
        "scraped_at": fight.get("scraped_at"),
        "markets": filtered_markets,
        "counts": {
            "fight_betting": len(filtered_markets["fight_betting"]),
            "method_of_victory": len(filtered_markets["method_of_victory"]),
            "rounds": len(filtered_markets["rounds"]),
            "go_the_distance": len(filtered_markets["go_the_distance"]),
            "total": total_props,
        },
    })

output = {
    "bookmaker": "BetVictor",
    "source": "betvictor",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "fight_count": len(filtered_fights),
    "fights": filtered_fights,
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print("\nDONE")
print(f"Saved: {OUT_PATH}")
print(f"Filtered fights: {len(filtered_fights)}")

for fight in filtered_fights:
    c = fight["counts"]
    print("\n================================")
    print(fight["fight_name"])
    print("Fight Betting:", c["fight_betting"])
    print("Method:", c["method_of_victory"])
    print("Rounds:", c["rounds"])
    print("Distance:", c["go_the_distance"])
    print("Total:", c["total"])