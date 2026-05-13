import json
import re
from pathlib import Path

ROOT = Path(".")

def key(x):
    x = str(x or "").lower()
    x = x.replace(" versus ", " v ")
    x = x.replace(" vs ", " v ")
    x = x.replace("-", " ")
    x = re.sub(r"[^a-z0-9\s]", "", x)
    x = re.sub(r"\s+", " ", x).strip()

    if " v " in x:
        a, b = x.split(" v ", 1)
        return " v ".join(sorted([a.strip(), b.strip()]))

    return x

events = json.load(open(ROOT / "ufc/data/events.json", encoding="utf-8"))
props = json.load(open(ROOT / "ufc/data/props.json", encoding="utf-8"))

propkeys = {
    key(f.get("fight")): f
    for f in props.get("fights", [])
}

print("PROP KEYS WITH ALLEN/COSTA:")
for k in propkeys:
    if "allen" in k or "costa" in k:
        print("PROP:", k)

print("\nEVENT FIGHTS WITH ALLEN/COSTA:")
for event in events.get("events", []):
    for fight in event.get("fights", []):
        red = fight.get("red", {})
        blue = fight.get("blue", {})

        red_name = red.get("name") if isinstance(red, dict) else str(red)
        blue_name = blue.get("name") if isinstance(blue, dict) else str(blue)

        fight_name = f"{red_name} v {blue_name}"
        k = key(fight_name)

        if "allen" in k or "costa" in k:
            print("EVENT:", fight_name)
            print("KEY:", k)
            print("MATCH:", k in propkeys)
            print()