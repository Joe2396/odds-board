#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]

EVENTS_JSON = ROOT / "ufc" / "data" / "events.json"
FIGHTERS_JSON = ROOT / "ufc" / "data" / "fighters.json"
OUT_DIR = ROOT / "ufc" / "fighters"

BASE_PATH = "/odds-board/ufc"


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def html_escape(s):
    if s is None:
        return "-"
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_fighters_db():
    raw = load_json(FIGHTERS_JSON, {"fighters": []})
    fighters_list = raw.get("fighters", [])

    fighters_db = {}
    for f in fighters_list:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("espn_id") or "").strip()
        if not fid:
            continue
        fighters_db[fid] = f

    return fighters_db


def build_fighter_page(fighter):
    name = html_escape(fighter.get("name"))
    record = html_escape(fighter.get("record"))
    height = html_escape(fighter.get("height"))
    weight = html_escape(fighter.get("weight"))
    reach = html_escape(fighter.get("reach"))
    stance = html_escape(fighter.get("stance"))
    age = html_escape(fighter.get("age"))
    image = fighter.get("image_url") or ""

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{name}</title>
</head>
<body>
  <h1>{name}</h1>
  <p><strong>Record:</strong> {record}</p>
  <p><strong>Height:</strong> {height}</p>
  <p><strong>Weight:</strong> {weight}</p>
  <p><strong>Reach:</strong> {reach}</p>
  <p><strong>Stance:</strong> {stance}</p>
  <p><strong>Age:</strong> {age}</p>
  {"<img src='" + image + "' width='200'>" if image else ""}
  <p><a href="{BASE_PATH}/">Back to UFC Hub</a></p>
</body>
</html>
"""


def main():
    fighters_db = build_fighters_db()

    if not fighters_db:
        print("No fighters found.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    count = 0

    for fid, fighter in fighters_db.items():
        html = build_fighter_page(fighter)

        out_path = OUT_DIR / f"{fid}.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        count += 1

    print(f"Wrote {count} fighter pages")


if __name__ == "__main__":
    main()
