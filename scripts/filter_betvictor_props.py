import json
import re
from pathlib import Path
from datetime import datetime, timezone

print("FILTERING BETVICTOR UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]

IN_PATH = ROOT / "ufc" / "data" / "betvictor_props.json"
OUT_PATH = ROOT / "ufc" / "data" / "betvictor_props_filtered.json"

with open(IN_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

fights = data.get("fights", [])


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


filtered_fights = []

for fight in fights:
    fight_name = fight.get("fight_name", "")
    markets = fight.get("markets", [])

    method_props = []
    round_props = []
    distance_props = []

    for market in markets:
        text = clean_text(market)
        lower = text.lower()

        if any(x in lower for x in [
            "ko",
            "submission",
            "decision",
        ]):
            method_props.append(text)

        if "round" in lower:
            round_props.append(text)

        if "distance" in lower:
            distance_props.append(text)

    filtered_fights.append({
        "bookmaker": "BetVictor",
        "fight_name": fight_name,
        "url": fight.get("url"),
        "method_props": sorted(list(set(method_props))),
        "round_props": sorted(list(set(round_props))),
        "distance_props": sorted(list(set(distance_props))),
        "method_count": len(set(method_props)),
        "round_count": len(set(round_props)),
        "distance_count": len(set(distance_props)),
        "total_props": (
            len(set(method_props))
            + len(set(round_props))
            + len(set(distance_props))
        ),
    })

output = {
    "bookmaker": "BetVictor",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "fight_count": len(filtered_fights),
    "fights": filtered_fights,
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print("\nDONE")
print(f"Saved: {OUT_PATH}")

for fight in filtered_fights:
    print("\n================================")
    print(fight["fight_name"])
    print("Method:", fight["method_count"])
    print("Rounds:", fight["round_count"])
    print("Distance:", fight["distance_count"])
    print("Total:", fight["total_props"])