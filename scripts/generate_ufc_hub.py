#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_PATH = os.path.join(ROOT, "ufc", "data", "events.json")
OUT_PATH = os.path.join(ROOT, "ufc", "index.html")

BASE = "/odds-board"  # GitHub Pages repo base path


def load_events():
    if not os.path.exists(DATA_PATH):
        return {"generated_at": None, "events": []}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def esc(s):
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def fmt_generated(ts):
    if not ts:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(ts).replace("T", " ").replace("+00:00", " UTC")


def parse_event_date(value):
    """
    Accepts values like:
    - 2026-04-18
    - 2026-04-18T23:00Z
    - 2026-04-18T23:00:00Z
    Returns UTC datetime or None.
    """
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        raw_iso = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def is_upcoming_event(ev):
    """
    Event is upcoming if:
    - status is explicitly 'upcoming', OR
    - date is today or in the future
    We still require a valid date to safely render/sort on the hub.
    """
    dt = parse_event_date(ev.get("date"))
    if not dt:
        return False

    today = datetime.now(timezone.utc).date()
    status = str(ev.get("status") or "").strip().lower()

    if status == "upcoming":
        return dt.date() >= today

    return dt.date() >= today


def sort_key(ev):
    dt = parse_event_date(ev.get("date"))
    return dt or datetime.max.replace(tzinfo=timezone.utc)


def main():
    payload = load_events()
    events = payload.get("events", []) or []
    generated_at = payload.get("generated_at")

    upcoming_events = [ev for ev in events if is_upcoming_event(ev)]
    upcoming_events = sorted(upcoming_events, key=sort_key)

    rows_html = ""
    if not upcoming_events:
        rows_html = "<p class='muted'>No upcoming events found.</p>"
    else:
        for ev in upcoming_events:
            name = esc(ev.get("name"))
            date = esc(ev.get("date"))
            location = esc(ev.get("location"))
            slug = esc(ev.get("slug") or ev.get("id"))

            if not slug:
                continue

            rows_html += f"""
        <div class="row" style="margin-top:16px;">
          <div>
            <h3>{name}</h3>
            <p class="muted">{date} • {location}</p>
            <p><a href="{BASE}/ufc/events/{slug}/">View event →</a></p>
          </div>
          <div class="muted">→</div>
        </div>
            """.rstrip()

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>UFC Hub</title>
  <link rel="stylesheet" href="{BASE}/ufc/assets/ufc.css">
</head>
<body>

  <div class="card">
    <h1>🥊 UFC Hub</h1>
    <p class="muted">UFC events, fight cards and fighter research tools.</p>

    <p><a href="{BASE}/ufc/fighters/">Browse fighters →</a></p>

    <h2>Upcoming Events</h2>

    {rows_html}

    <hr style="margin:24px 0; border-color:#1f2a3a;">
    <p class="muted">Generated: {esc(fmt_generated(generated_at))}</p>
    <p><a href="{BASE}/">← Back to home</a></p>
  </div>

</body>
</html>
"""

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Wrote UFC hub: {OUT_PATH}")
    print(f"Upcoming events shown: {len(upcoming_events)}")


if __name__ == "__main__":
    main()
