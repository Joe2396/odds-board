import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_PATH = ROOT / "ufc" / "data" / "props.json"
OUT_PATH = ROOT / "ufc" / "data" / "props_filtered.json"

data = json.load(open(IN_PATH, encoding="utf-8"))

filtered = [f for f in data["fights"] if f.get("has_props")]

output = {
    "updated_at": data.get("updated_at"),
    "fights": filtered
}

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)

print(f"Saved filtered props to {OUT_PATH}")