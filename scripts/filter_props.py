import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_PATH   = ROOT / "ufc" / "data" / "props.json"
BWIN_PATH = ROOT / "ufc" / "data" / "bwin_props.json"
OUT_PATH  = ROOT / "ufc" / "data" / "props_filtered.json"

data = json.load(open(IN_PATH, encoding="utf-8"))
fights = [f for f in data["fights"] if f.get("has_props")]

# Merge Bwin fights
if BWIN_PATH.exists():
    bwin = json.load(open(BWIN_PATH, encoding="utf-8"))
    bwin_fights = []
    for f in bwin.get("fights", []):
        markets = f.get("markets", {})
        fb = markets.get("fight_betting", [])
        if fb:
            # Strip country codes e.g. "Rafael Fiziev AZE" -> "Rafael Fiziev"
            f["fight"] = re.sub(r'\s+[A-Z]{3}(?=\s+vs|\s+$|$)', '', f.get("fight", "")).strip()
            f["has_props"] = True
            bwin_fights.append(f)
    fights.extend(bwin_fights)
    print(f"Merged {len(bwin_fights)} Bwin fights")

output = {"updated_at": data.get("updated_at"), "fights": fights}
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)
print(f"Saved filtered props to {OUT_PATH} ({len(fights)} fights)")