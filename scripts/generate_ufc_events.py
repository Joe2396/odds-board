#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_PATH = os.path.join(ROOT, "ufc", "data", "events.json")
EVENTS_DIR = os.path.join(ROOT, "ufc", "events")

BASE = "/odds-board"  # GitHub Pages repo base path


def esc(s):
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def load_events():
    if not os.path.exists(DATA_PATH):
        return []

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("events", []) or []


def fight_id(fight):
    fid = fight.get("id") or ""
    return str(fid).strip()


def parse_event_date(value):
    """
    Accepts common formats like:
    - 2026-04-11
    - 2026-04-11T23:00Z
    - 2026-04-11T23:00:00Z
    Returns a datetime in UTC when possible, otherwise None.
    """
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        # Handle Zulu time
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


def format_event_date(value):
    """
    Keeps display simple and stable.
    If we can parse it, display YYYY-MM-DD.
    Otherwise fall back to raw text.
    """
    dt = parse_event_date(value)
    if dt:
        return dt.strftime("%Y-%m-%d")
    return str(value or "")


def get_event_status(value):
    dt = parse_event_date(value)
    if not dt:
        return "Unknown"

    now = datetime.now(timezone.utc)

    if dt.date() < now.date():
        return "Completed"
    if dt.date() == now.date():
        return "Today"
    return "Upcoming"


def sort_events(events):
    """
    Sort by parsed date ascending.
    Invalid/missing dates go last.
    """
    return sorted(
        events,
        key=lambda ev: parse_event_date(ev.get("date")) or datetime.max.replace(tzinfo=timezone.utc)
    )


def render_event_page(ev):
    raw_name = ev.get("name")
    raw_date = ev.get("date")
    raw_location = ev.get("location")
    raw_slug = ev.get("slug") or ev.get("id")

    name = esc(raw_name)
    date = esc(format_event_date(raw_date))
    location = esc(raw_location)
    slug = str(raw_slug or "").strip()
    fights = ev.get("fights", []) or []
    status = esc(get_event_status(raw_date))

    if not slug:
        return None, None

    if not fights:
        fights_html = "<p class='muted'>Fight card not available yet.</p>"
    else:
        rows = []
        for f in fights:
            bout = esc(f.get("bout") or "")
            red = esc((f.get("red") or {}).get("name"))
            blue = esc((f.get("blue") or {}).get("name"))
            wc = esc(f.get("weight_class") or "")
            fid = fight_id(f)

            title = bout or f"{red} vs {blue}".strip()

            if fid:
                link = f"{BASE}/ufc/fights/{esc(fid)}/"
                rows.append(
                    f"""
        <div class="row" style="margin-top:12px;">
          <div>
            <h3 style="margin:0;">{title}</h3>
            <p class="muted" style="margin:6px 0 0 0;">{wc}</p>
            <p style="margin:6px 0 0 0;"><a href="{link}">View fight →</a></p>
          </div>
          <div class="muted">→</div>
        </div>
                    """.rstrip()
                )
            else:
                rows.append(
                    f"""
        <div class="row" style="margin-top:12px;">
          <div>
            <h3 style="margin:0;">{title}</h3>
            <p class="muted" style="margin:6px 0 0 0;">{wc}</p>
          </div>
        </div>
                    """.rstrip()
                )

        fights_html = "\n".join(rows)

    location_line = f" • {location}" if location else ""

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{name} | UFC Event</title>
  <link rel="stylesheet" href="{BASE}/ufc/assets/ufc.css">
</head>
<body>
  <div class="card">
    <p><a href="{BASE}/ufc/">← Back to UFC Hub</a></p>
    <h1>{name}</h1>
    <p class="muted">{date}{location_line} • {status}</p>

    <h2>Fight Card</h2>
    {fights_html}

    <hr style="margin:24px 0; border-color:#1f2a3a;">
    <p class="muted">Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
  </div>
</body>
</html>
"""
    return slug, html


def main():
    ensure_dir(EVENTS_DIR)

    # Keep folder in git
    with open(os.path.join(EVENTS_DIR, ".keep"), "w", encoding="utf-8") as f:
        f.write("keep")

    events = sort_events(load_events())

    wrote = 0
    skipped = 0

    for ev in events:
        slug, html = render_event_page(ev)
        if not slug or not html:
            skipped += 1
            continue

        out_dir = os.path.join(EVENTS_DIR, slug)
        ensure_dir(out_dir)

        out_path = os.path.join(out_dir, "index.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        wrote += 1

    print(f"Generated {wrote} event pages into {EVENTS_DIR}")
    if skipped:
        print(f"Skipped {skipped} events with missing slug/id")


if __name__ == "__main__":
    main()
