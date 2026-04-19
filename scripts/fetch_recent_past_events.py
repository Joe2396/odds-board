#!/usr/bin/env python3
import json
import os
import requests
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVENTS_PATH = os.path.join(ROOT, "ufc", "data", "events.json")

SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/schedule"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def load_events():
    if not os.path.exists(EVENTS_PATH):
        return {"generated_at": None, "events": []}

    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_events(payload):
    with open(EVENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def fetch_schedule():
    r = requests.get(SCHEDULE_URL, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def build_event(ev):
    comp = ev.get("competitions", [{}])[0]

    return {
        "id": ev.get("id"),
        "slug": ev.get("id"),
        "name": ev.get("name"),
        "date": ev.get("date", "")[:10],
        "location": comp.get("venue", {}).get("fullName", ""),
        "status": "completed",
        "source": {
            "provider": "espn",
            "event_id": ev.get("id")
        },
        "fights": []  # we will fill later with your other script
    }


def main():
    payload = load_events()
    existing_events = payload.get("events", [])

    schedule = fetch_schedule()

    past_events = []

    for ev in schedule.get("events", []):
        status = ev.get("status", {}).get("type", {}).get("state", "")

        if status == "post":  # completed events only
            built = build_event(ev)
            past_events.append(built)

    # limit to last ~10 events
    past_events = past_events[:10]

    # merge: past events FIRST, then existing future events
    merged = past_events + existing_events

    payload["events"] = merged
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()

    save_events(payload)

    print(f"Added {len(past_events)} past events.")


if __name__ == "__main__":
    main()
