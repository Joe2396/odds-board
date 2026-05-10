#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

IN_PATH = ROOT / "ufc" / "data" / "betmgm_props.json"
OUT_PATH = ROOT / "ufc" / "data" / "betmgm_props_filtered.json"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clean(s):
    return " ".join(str(s or "").split())


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Missing input file: {IN_PATH}")

    with open(IN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_props = data.get("props", [])

    filtered = []

    for p in raw_props:
        fight = clean(p.get("fight"))
        market = clean(p.get("market"))
        selection = clean(p.get("selection"))
        odds = clean(p.get("odds"))

        if not market or not selection or not odds:
            continue

        if not fight:
            continue

        if market not in ["Goes The Distance", "Total Rounds", "Method of Victory"]:
            continue

        filtered.append({
            "bookmaker": "BetMGM",
            "source": "betmgm",
            "fight": fight,
            "fighter_a": clean(p.get("fighter_a")),
            "fighter_b": clean(p.get("fighter_b")),
            "event_time": clean(p.get("event_time")),
            "market": market,
            "selection": selection,
            "odds": odds,
        })

    output = {
        "updated_at": utc_now(),
        "source": "betmgm",
        "count": len(filtered),
        "props": filtered,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(filtered)} filtered BetMGM props to {OUT_PATH}")

    for p in filtered[:30]:
        print(f"- {p['fight']} | {p['market']} | {p['selection']} | {p['odds']}")


if __name__ == "__main__":
    main()