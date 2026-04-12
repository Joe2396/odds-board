#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVENTS_PATH = os.path.join(ROOT, "ufc", "data", "events.json")
REFERENCE_PATH = os.path.join(ROOT, "ufc", "data", "events_fresh_reference.json")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def main():
    current = load_json(EVENTS_PATH, {"generated_at": None, "events": []})
    reference = load_json(REFERENCE_PATH, {"generated_at": None, "events": []})

    fresh_events = reference.get("events", []) or []

    updated = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": fresh_events
    }

    save_json(EVENTS_PATH, updated)

    print(f"Updated {EVENTS_PATH} with {len(fresh_events)} upcoming events from reference file.")


if __name__ == "__main__":
    main()
