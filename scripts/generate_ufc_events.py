#!/usr/bin/env python3
import json
import os
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_PATH = os.path.join(ROOT, "ufc", "data", "events.json")
EVENTS_DIR = os.path.join(ROOT, "ufc", "events")

BASE = "/odds-board"  # GitHub Pages base path


def esc(s):
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def load_events():
    if not os.path.exists(DATA_PATH):
        return []
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("events", []) or []


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def fight_slug(fight):
    # Prefer fight id from your scraper/generator pipeline
    fid = fight.get("id") or ""
    return str(fid).strip()


def render_event_page(ev):
    name = esc(ev.get("name"))
    date = esc(ev.get("date"))
    location = esc(ev.get("location"))
    slug = esc(ev.get("slug") or ev.get("id"))
    fights = ev.get("fights", []) or []

    fights_html = ""
    if not fights:
        fights_html = "<p class='muted'>Fight card not available yet.</p>"
    else:
        rows = []
        for f in fights:
            bout = esc(f.get("bout") or "")
            red = esc((f.get("red") or {}).get("name"))
            blue = esc((f.get("blue") or {}).get("name"))
            wc = esc(f.get("weight_class") or "")
            f_id = fight_slug(f)

            # Link to fight page if your fights generator created it under /ufc/fights/<id>/
            if f_id:
                fight_link = f"{BASE}/ufc/fights/{esc(f_id)}/"
                rows.append(
                    f"""
                    <div class="row" style="margin-top:12px;">
                      <div>
                        <h3 style="margin:0;">{bout or (red + " vs " + blue)}</h3>
                        <p class="muted" style="margin:6px 0 0 0;">{wc}</p>
                        <p style="margin:6px 0 0 0;"><a href="{fight_link}">View fight →</a></p>
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
                        <h3 style="margin:0;">{bout or (red + " vs " + blue)}</h3>
                        <p class="muted" style="margin:6px 0 0 0;">{wc}</p>
                      </div>
                    </div>
                    """.rstrip()
                )
        fights_html = "\n".join(rows)

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
    <p class="muted">{date} • {location}</p>

    <h2>Fight Card</h2>
    {fights_html}

    <hr style="margin:24px 0; border-color:#1f2a3a;">
    <p class="muted">Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</p>
  </div>
</body>
</html>
"""
    return slug, html


def main():
    events = load_events()
    ensure_dir(EVENTS_DIR)

    # Generate a folder for each event in events.json
    wrote = 0
    for ev in events:
        slug, html = render_event_page(ev)
        if not slug:
            continue
        out_dir = os.path.join(EVENTS_DIR, slug)
        ensure_dir(out_dir)
        out_path = os.path.join(out_dir, "index.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        wrote += 1

    print(f"Generated {wrote} event pages into {EVENTS_DIR}")


if __name__ == "__main__":
    main()
