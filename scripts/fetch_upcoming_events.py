#!/usr/bin/env python3
"""
Fetch upcoming UFC events + fight cards using ESPN calendar API.
Uses the calendar[] array from the scoreboard endpoint which contains
all upcoming events, then fetches fight cards for each.

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
ESPN_EVENT = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/summary?event={event_id}"


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
    """Pull numeric event ID from ESPN $ref URL."""
    m = re.search(r"/events/(\d+)", str(ref_url or ""))
    return m.group(1) if m else None


def fetch_fight_card(event_id):
    """
    Use ESPN site summary API to get fight card for an event.
    Returns list of fight dicts.
    """
    url = ESPN_EVENT.format(event_id=event_id)
    status, body = http_get(url)
    if status != 200:
        print(f"  Fight card fetch failed for {event_id}: {status}")
        return []

    data = safe_json(body)
    if not isinstance(data, dict):
        return []

    fights = []
    order = 0

    # Summary API returns competitors under header.competitions
    competitions = []
    header = data.get("header") or {}
    competitions = header.get("competitions") or []

    # Also try top-level competitions
    if not competitions:
        competitions = data.get("competitions") or []

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

        # Sort by order field
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
        fight_id = str(comp.get("id") or f"{event_id}-{order}")

        fights.append({
            "id": fight_id,
            "bout": bout,
            "red": {"name": a_name, "espn_id": str(a.get("id") or "")},
            "blue": {"name": b_name, "espn_id": str(b.get("id") or "")},
            "weight_class": wc,
            "order": order,
            "status": "scheduled",
            "source": {"provider": "espn", "event_id": event_id},
        })

    return fights


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    today = date.today()

    # Step 1: Fetch scoreboard to get calendar
    print(f"Fetching ESPN scoreboard...")
    status, body = http_get(ESPN_SCOREBOARD)
    if status != 200:
        print(f"ESPN scoreboard failed: {status}")
        sys.exit(0)

    data = safe_json(body)
    if not isinstance(data, dict):
        print("ESPN scoreboard returned invalid JSON")
        sys.exit(0)

    # Step 2: Use calendar array (has ALL upcoming events, not just today)
    leagues = data.get("leagues") or []
    calendar = []
    for league in leagues:
        if isinstance(league, dict):
            calendar = league.get("calendar") or []
            if calendar:
                break

    print(f"Calendar entries found: {len(calendar)}")

    events_out = []

    for entry in calendar:
        if not isinstance(entry, dict):
            continue

        label = entry.get("label") or ""
        start_date = parse_date(entry.get("startDate"))

        if not start_date:
            continue

        # Skip past events
        try:
            if datetime.fromisoformat(start_date).date() < today:
                continue
        except Exception:
            continue

        # Get event ID from $ref
        event_ref = entry.get("event") or {}
        ref_url = event_ref.get("$ref") or event_ref.get("href") or ""
        event_id = extract_event_id(ref_url)

        if not event_id:
            continue

        slug = f"{start_date}-{slugify(label)}"

        print(f"  Fetching fight card: {label} ({start_date}, id={event_id})")
        fights = fetch_fight_card(event_id)
        print(f"    -> {len(fights)} fights found")

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