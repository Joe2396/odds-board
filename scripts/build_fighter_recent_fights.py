import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
EVENTS_JSON = ROOT / "ufc" / "data" / "events.json"
FIGHTERS_JSON = ROOT / "ufc" / "data" / "fighters.json"

BASE_PATH = "/odds-board/ufc"


def load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def parse_date(d: str):
    # events.json uses YYYY-MM-DD
    try:
        return datetime.strptime(d, "%Y-%m-%d")
    except Exception:
        return None


def fight_to_entry(event: dict, fight: dict, me_side: str) -> dict:
    """
    Convert a fight in events.json into a normalized recent-fight row.
    NOTE: events.json currently doesn't include method/round/time/results,
          so we fill with what we have and keep placeholders.
    """
    event_slug = event.get("slug", "")
    event_name = event.get("name", "Event")
    date = event.get("date", "")

    fight_id = str(fight.get("id") or "").strip()
    status = fight.get("status", "")

    red = fight.get("red") or {}
    blue = fight.get("blue") or {}

    if me_side == "red":
        opp = blue
    else:
        opp = red

    opponent_name = opp.get("name") or "—"

    # If you later enrich events.json with results, these keys can be used:
    # winner_side = fight.get("winner")   # "red"/"blue"
    # method = fight.get("method")        # "DEC"/"KO/TKO"/"SUB"
    # round_ = fight.get("round")
    # time_ = fight.get("time")

    entry = {
        "date": date or None,
        "event": event_name,
        "event_slug": event_slug,
        "fight_id": fight_id or None,
        "opponent": opponent_name,
        # For now this is mostly "scheduled". Later can be "W"/"L" from winner data.
        "result": "Scheduled" if status == "scheduled" else (status or "—"),
        "method": "—",
        "round": "—",
        "time": "—",
        "urls": {
            "event": f"{BASE_PATH}/events/{event_slug}/" if event_slug else None,
            "fight": f"{BASE_PATH}/fights/{fight_id}/" if fight_id else None,
        },
    }
    return entry


def main():
    events_data = load_json(EVENTS_JSON)
    fighters_data = load_json(FIGHTERS_JSON)

    events = events_data.get("events", [])
    fighters = fighters_data.get("fighters", {})

    if not events or not isinstance(events, list):
        raise SystemExit("No events found in ufc/data/events.json")

    if not fighters or not isinstance(fighters, dict):
        raise SystemExit("No fighters found in ufc/data/fighters.json")

    # Collect recent fights per ESPN fighter id
    recent_by_id = {}  # fid -> [entries...]

    for ev in events:
        fights = ev.get("fights", [])
        if not isinstance(fights, list):
            continue

        for f in fights:
            red = f.get("red") or {}
            blue = f.get("blue") or {}

            red_id = str(red.get("espn_id") or "").strip()
            blue_id = str(blue.get("espn_id") or "").strip()

            if red_id:
                recent_by_id.setdefault(red_id, []).append(fight_to_entry(ev, f, "red"))
            if blue_id:
                recent_by_id.setdefault(blue_id, []).append(fight_to_entry(ev, f, "blue"))

    # Sort by event date desc and keep last 10
    for fid, rows in recent_by_id.items():
        def sort_key(r):
            dt = parse_date(r.get("date") or "")
            # None dates go last
            return dt or datetime.min

        rows_sorted = sorted(rows, key=sort_key, reverse=True)[:10]
        if fid in fighters and isinstance(fighters[fid], dict):
            fighters[fid]["recent_fights"] = rows_sorted

    fighters_data["fighters"] = fighters
    fighters_data["recent_fights_generated_at"] = datetime.utcnow().isoformat() + "Z"

    FIGHTERS_JSON.write_text(json.dumps(fighters_data, indent=2), encoding="utf-8")
    print(f"✅ Updated recent_fights for {len(recent_by_id)} fighters in {FIGHTERS_JSON}")


if __name__ == "__main__":
    main()
