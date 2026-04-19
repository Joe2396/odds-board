#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVENTS_PATH = os.path.join(ROOT, "ufc", "data", "events.json")

# ESPN web API endpoint
SCHEDULE_URL = "https://site.web.api.espn.com/apis/common/v3/sports/mma/ufc/schedule"

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
        json.dump(payload, f, indent=2, ensure_ascii=False)


def fetch_schedule():
    r = requests.get(SCHEDULE_URL, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        print(f"Failed to fetch schedule: {r.status_code}")
        return {}
    return r.json()


def event_location(ev):
    venue = ev.get("venue") or {}
    address = venue.get("address") or {}

    parts = [
        venue.get("fullName") or venue.get("name") or "",
        address.get("city") or "",
        address.get("state") or "",
        address.get("country") or "",
    ]

    cleaned = [str(p).strip() for p in parts if str(p).strip()]
    return ", ".join(cleaned)


def build_event(ev):
    event_id = str(ev.get("id") or "").strip()

    return {
        "id": event_id,
        "slug": event_id,
        "name": ev.get("name"),
        "date": str(ev.get("date") or "")[:10],
        "location": event_location(ev),
        "status": "completed",
        "source": {
            "provider": "espn",
            "event_id": event_id
        },
        "fights": []
    }


def main():
    payload = load_events()
    existing_events = payload.get("events", []) or []

    schedule = fetch_schedule()
    if not schedule:
        print("No schedule data returned.")
        return

    past_events = []
    seen_ids = {str(ev.get("id") or "").strip() for ev in existing_events}

    # ESPN schedule events live at top-level "events"
    events_list = schedule.get("events") or []

    for ev in events_list:
        status = str(((ev.get("status") or {}).get("type") or {}).get("state") or "").lower()

        if status != "post":
            continue

        built = build_event(ev)
        if not built["id"] or built["id"] in seen_ids:
            continue

        past_events.append(built)

    # Keep only the most recent 10 completed events
    past_events = past_events[:10]

    # Merge: recent completed events first, then your existing current/future events
    payload["events"] = past_events + existing_events
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()

    save_events(payload)

    print(f"Added {len(past_events)} past events.")


if __name__ == "__main__":
    main()
