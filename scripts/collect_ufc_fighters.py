#!/usr/bin/env python3
import json
import os
import re
import time
from typing import Any, Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVENTS_PATH = os.path.join(ROOT, "ufc", "data", "events.json")
FIGHTERS_PATH = os.path.join(ROOT, "ufc", "data", "fighters.json")


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def normalize_name(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^a-z0-9à-ÿ ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def slugify_name(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^a-z0-9à-ÿ]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def make_fighter_key(name: str) -> str:
    return slugify_name(name)


def empty_fighter_record(name: str, fighter_key: str) -> Dict[str, Any]:
    return {
        "fighter_key": fighter_key,
        "name": name,
        "normalized_name": normalize_name(name),
        "espn_id": "",
        "profile": {
            "nickname": "",
            "height": "",
            "weight": "",
            "reach": "",
            "stance": "",
            "dob": "",
        },
        "upcoming_fights": [],
        "recent_fights": [],
        "source": {
            "provider": "local",
            "last_synced": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }


def add_upcoming_fight(fighter: Dict[str, Any], event: Dict[str, Any], fight: Dict[str, Any], corner: str, opponent_name: str) -> None:
    entry = {
        "event_id": str(((event.get("source") or {}).get("event_id")) or "").strip(),
        "event_name": str(event.get("name") or "").strip(),
        "event_date": str(event.get("date") or "").strip(),
        "fight_id": str(fight.get("id") or "").strip(),
        "bout": str(fight.get("bout") or "").strip(),
        "corner": corner,
        "opponent_name": opponent_name,
        "weight_class": str(fight.get("weight_class") or "").strip(),
        "status": str(fight.get("status") or "").strip(),
        "order": int(fight.get("order") or 0),
    }

    existing = fighter.get("upcoming_fights", []) or []
    key = (entry["fight_id"], entry["corner"])
    existing_keys = {(x.get("fight_id"), x.get("corner")) for x in existing}
    if key not in existing_keys:
        existing.append(entry)

    existing.sort(key=lambda x: (x.get("event_date", ""), x.get("order", 0)))
    fighter["upcoming_fights"] = existing


def merge_fighter(existing: Dict[str, Any], incoming_name: str, incoming_key: str, espn_id: str) -> Dict[str, Any]:
    if not existing:
        existing = empty_fighter_record(incoming_name, incoming_key)

    if not existing.get("name"):
        existing["name"] = incoming_name

    if not existing.get("normalized_name"):
        existing["normalized_name"] = normalize_name(existing.get("name", incoming_name))

    if not existing.get("fighter_key"):
        existing["fighter_key"] = incoming_key

    # Only fill espn_id if currently blank.
    if espn_id and not existing.get("espn_id"):
        existing["espn_id"] = espn_id

    existing.setdefault("profile", {
        "nickname": "",
        "height": "",
        "weight": "",
        "reach": "",
        "stance": "",
        "dob": "",
    })
    existing.setdefault("upcoming_fights", [])
    existing.setdefault("recent_fights", [])
    existing.setdefault("source", {
        "provider": "local",
        "last_synced": "",
    })
    existing["source"]["last_synced"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return existing


def main() -> None:
    events_payload = load_json(EVENTS_PATH, {"events": []})
    fighters_payload = load_json(FIGHTERS_PATH, {"generated_at": None, "fighters": []})

    events = events_payload.get("events", []) or []
    existing_fighters = fighters_payload.get("fighters", []) or []

    fighters_by_key: Dict[str, Dict[str, Any]] = {}

    for f in existing_fighters:
        fighter_key = str(f.get("fighter_key") or "").strip()
        if not fighter_key:
            name = str(f.get("name") or "").strip()
            fighter_key = make_fighter_key(name)
            f["fighter_key"] = fighter_key
        fighters_by_key[fighter_key] = f

    scheduled_fight_count = 0

    for event in events:
        for fight in event.get("fights", []) or []:
            if str(fight.get("status") or "").strip().lower() != "scheduled":
                continue

            scheduled_fight_count += 1

            red = fight.get("red") or {}
            blue = fight.get("blue") or {}

            red_name = str(red.get("name") or "").strip()
            blue_name = str(blue.get("name") or "").strip()

            if red_name:
                red_key = make_fighter_key(red_name)
                red_record = merge_fighter(
                    fighters_by_key.get(red_key, {}),
                    red_name,
                    red_key,
                    str(red.get("espn_id") or "").strip(),
                )
                add_upcoming_fight(red_record, event, fight, "red", blue_name)
                fighters_by_key[red_key] = red_record
                red["fighter_key"] = red_key

            if blue_name:
                blue_key = make_fighter_key(blue_name)
                blue_record = merge_fighter(
                    fighters_by_key.get(blue_key, {}),
                    blue_name,
                    blue_key,
                    str(blue.get("espn_id") or "").strip(),
                )
                add_upcoming_fight(blue_record, event, fight, "blue", red_name)
                fighters_by_key[blue_key] = blue_record
                blue["fighter_key"] = blue_key

    fighters = list(fighters_by_key.values())
    fighters.sort(key=lambda x: x.get("name", "").lower())

    fighters_payload["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    fighters_payload["fighters"] = fighters

    save_json(FIGHTERS_PATH, fighters_payload)
    save_json(EVENTS_PATH, events_payload)

    print(f"Found {len(events)} total events")
    print(f"Found {scheduled_fight_count} scheduled fights")
    print(f"Stored {len(fighters)} fighters in ufc/data/fighters.json")


if __name__ == "__main__":
    main()
