#!/usr/bin/env python3
"""
Fetch upcoming UFC events + fight cards using ESPN scoreboard API.
Uses calendar[] to find upcoming events, then fetches each event's
fight card using the scoreboard?dates= endpoint which returns full
competitor data with fighter names directly.

Writes:
  ufc/data/events.json
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, date
from urllib.request import Request, urlopen

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "ufc", "data")
EVENTS_PATH = os.path.join(DATA_DIR, "events.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (odds-board-bot)",
    "Accept": "application/json",
}

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def http_get(url, timeout=25):
    try:
        req = Request(url, headers=HEADERS, method="GET")
        with urlopen(req, timeout=timeout) as r:
            return getattr(r, "status", 200), r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return getattr(e, "code", 0) if hasattr(e, "code") else 0, str(e)


def safe_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def slugify(s):
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-{2,}", "-", s).strip("-") or "event"


def parse_date(dt_str):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(str(dt_str).replace("Z", "+00:00")).date().isoformat()
    except Exception:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(dt_str))
        return m.group(1) if m else None


def extract_event_id(ref_url):
    m = re.search(r"/events/(\d+)", str(ref_url or ""))
    return m.group(1) if m else None


def extract_fights_from_event(ev_data):
    """Pull fights from an ESPN event dict (competitions array with competitors)."""
    fights = []
    competitions = ev_data.get("competitions") or []
    order = 0

    for comp in competitions:
        if not isinstance(comp, dict):
            continue

        competitors = comp.get("competitors") or []
        if len(competitors) < 2:
            continue

        def get_name(c):
            athlete = c.get("athlete") or {}
            return (
                athlete.get("displayName") or
                athlete.get("fullName") or
                c.get("displayName") or ""
            )

        competitors_sorted = sorted(competitors, key=lambda x: int(x.get("order", 99)))
        a = competitors_sorted[0]
        b = competitors_sorted[1]

        a_name = get_name(a)
        b_name = get_name(b)

        if not a_name or not b_name:
            continue

        order += 1
        wc = (comp.get("type") or {}).get("text") or (comp.get("type") or {}).get("abbreviation") or ""
        bout = f"{a_name} vs {b_name}"
        fight_id = str(comp.get("id") or f"{ev_data.get('id', '')}-{order}")

        fights.append({
            "id": fight_id,
            "bout": bout,
            "red": {"name": a_name, "espn_id": str(a.get("id") or "")},
            "blue": {"name": b_name, "espn_id": str(b.get("id") or "")},
            "weight_class": wc,
            "order": order,
            "status": "scheduled",
            "source": {"provider": "espn", "event_id": str(ev_data.get("id") or "")},
        })

    return fights


def fetch_fights_for_date(event_date_str):
    """
    Fetch the ESPN scoreboard for a specific date (YYYYMMDD).
    Returns dict of {event_id: [fights]} for events on that date.
    """
    date_key = event_date_str.replace("-", "")
    url = f"{ESPN_SCOREBOARD}?dates={date_key}"
    status, body = http_get(url)
    if status != 200:
        print(f"  Scoreboard fetch failed for {event_date_str}: {status}")
        return {}

    data = safe_json(body)
    if not isinstance(data, dict):
        return {}

    result = {}
    for ev in data.get("events") or []:
        ev_id = str(ev.get("id") or "")
        if ev_id:
            result[ev_id] = extract_fights_from_event(ev)

    return result


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    today = date.today()

    # Step 1: Fetch scoreboard to get calendar
    print("Fetching ESPN scoreboard calendar...")
    status, body = http_get(ESPN_SCOREBOARD)
    if status != 200:
        print(f"ESPN scoreboard failed: {status}")
        sys.exit(0)

    data = safe_json(body)
    if not isinstance(data, dict):
        print("ESPN scoreboard returned invalid JSON")
        sys.exit(0)

    # Step 2: Get calendar from leagues
    leagues = data.get("leagues") or []
    calendar = []
    for league in leagues:
        if isinstance(league, dict):
            cal = league.get("calendar") or []
            if cal:
                calendar = cal
                break

    print(f"Calendar entries found: {len(calendar)}")

    # Step 3: Filter upcoming, group by date
    upcoming = []
    for entry in calendar:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label") or ""
        start_date = parse_date(entry.get("startDate"))
        if not start_date:
            continue
        try:
            if datetime.fromisoformat(start_date).date() < today:
                continue
        except Exception:
            continue

        event_ref = entry.get("event") or {}
        ref_url = event_ref.get("$ref") or event_ref.get("href") or ""
        event_id = extract_event_id(ref_url)
        if not event_id:
            continue

        upcoming.append({
            "label": label,
            "date": start_date,
            "event_id": event_id,
        })

    print(f"Upcoming events: {len(upcoming)}")

    # Step 4: Fetch fight cards — group by date to minimise API calls
    dates_needed = sorted(set(e["date"] for e in upcoming))
    fights_by_event = {}

    for d in dates_needed:
        print(f"  Fetching scoreboard for {d}...")
        day_fights = fetch_fights_for_date(d)
        fights_by_event.update(day_fights)
        total = sum(len(v) for v in day_fights.values())
        print(f"    -> {len(day_fights)} events, {total} fights")

    # Step 5: Build output
    events_out = []
    for entry in upcoming:
        event_id = entry["event_id"]
        label = entry["label"]
        start_date = entry["date"]
        fights = fights_by_event.get(event_id, [])
        slug = f"{start_date}-{slugify(label)}"

        events_out.append({
            "id": slug,
            "slug": slug,
            "name": label,
            "date": start_date,
            "location": "",
            "status": "upcoming",
            "source": {"provider": "espn", "event_id": event_id},
            "fights": fights,
        })

    events_out.sort(key=lambda x: x.get("date") or "9999-12-31")

    out = {"generated_at": now_iso(), "events": events_out}
    with open(EVENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(events_out)} upcoming events to ufc/data/events.json")
    for ev in events_out:
        print(f"  {ev['date']} - {ev['name']} ({len(ev['fights'])} fights)")

    sys.exit(0)


if __name__ == "__main__":
    main()