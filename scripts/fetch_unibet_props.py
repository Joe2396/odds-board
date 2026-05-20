from pathlib import Path
from datetime import datetime, timezone
import json

ROOT = Path(__file__).resolve().parents[1]
IN_PATH = ROOT / "ufc" / "data" / "debug" / "unibet_response_1.json"
OUT_PATH = ROOT / "ufc" / "data" / "unibet_props.json"

print("RUNNING UNIBET UFC JSON PARSER")


def parse_lobby(data):
    fights = []
    matches = data.get("view", {}).get("matches", []) or []

    for accordion in matches:
        event_date = accordion.get("header") or accordion.get("identifier") or ""

        for group in accordion.get("contestGroups", []) or []:
            for contest in group.get("contests", []) or []:
                fight_name = contest.get("name") or ""
                if " vs " not in fight_name:
                    continue

                fight_betting = []

                for prop in contest.get("propositions", []) or []:
                    if prop.get("propositionKey") != "winner":
                        continue

                    for opt in prop.get("options", []) or []:
                        selection = opt.get("optionName")
                        price = opt.get("price")

                        if selection and price:
                            fight_betting.append({
                                "selection": selection,
                                "odds": str(price)
                            })

                if len(fight_betting) < 2:
                    continue

                fights.append({
                    "bookmaker": "Unibet",
                    "fight": fight_name,
                    "fight_name": fight_name,
                    "date": event_date,
                    "start_time": contest.get("startDateTimeUtc", {}).get("value", ""),
                    "contest_key": contest.get("contestKey", ""),
                    "url": "https://www.unibet.ie/betting/odds/mma/ufc",
                    "markets": {
                        "fight_betting": fight_betting
                    }
                })

                print(f"FOUND: {fight_name} | {fight_betting[0]['odds']} / {fight_betting[1]['odds']}")

    return fights


def main():
    data = json.loads(IN_PATH.read_text(encoding="utf-8"))
    fights = parse_lobby(data)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "unibet",
        "bookmaker": "Unibet",
        "url": "https://www.unibet.ie/betting/odds/mma/ufc",
        "count": len(fights),
        "fights": fights,
    }

    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Saved {len(fights)} Unibet fights to {OUT_PATH}")


if __name__ == "__main__":
    main()