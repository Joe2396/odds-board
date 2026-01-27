#!/usr/bin/env python3
import json
import os
from datetime import datetime

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
    # events.json uses ISO, but be flexible
    if not ts:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return str(ts).replace("T", " ").replace("+00:00", " UTC")


def main():
    payload = load_events()
    events = payload.get("events", []) or []
    generated_at = payload.get("generated_at")

    # Sort by date ascending (YYYY-MM-DD)
    def key(ev):
        return ev.get("date") or "9999-12-31"

    events = sorted(events, key=key)

    rows_html = ""
    if not events:
        rows_html = "<p class='muted'>No upcoming events found.</p>"
    else:
        for ev in events:
            name = esc(ev.get("name"))
            date = esc(ev.get("date"))
            location = esc(ev.get("location"))
            slug = esc(ev.get("slug") or ev.get("id"))

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


if __name__ == "__main__":
    main()
