#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_PATH = os.path.join(ROOT, "ufc", "data", "events.json")
EVENTS_DIR = os.path.join(ROOT, "ufc", "events")

BASE = "/odds-board"

FREEDOM_250_FIGHTS = [
    ("600058854-1", "Ilia Topuria", "Justin Gaethje", "Lightweight - Main Event - Title Fight"),
    ("600058854-2", "Alex Pereira", "Ciryl Gane", "Heavyweight - Interim Title Fight"),
    ("600058854-3", "Sean O'Malley", "Aiemann Zahabi", "Bantamweight"),
    ("600058854-4", "Josh Hokit", "Derrick Lewis", "Heavyweight"),
    ("600058854-5", "Mauricio Ruffy", "Michael Chandler", "Lightweight"),
    ("600058854-6", "Bo Nickal", "Kyle Daukaus", "Middleweight"),
    ("600058854-7", "Diego Lopes", "Steve Garcia", "Featherweight"),
]


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
    return str(fight.get("id") or "").strip()


def parse_event_date(value):
    if not value:
        return None

    raw = str(value).strip()

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


def format_event_date(value):
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
    return sorted(
        events,
        key=lambda ev: parse_event_date(ev.get("date")) or datetime.max.replace(tzinfo=timezone.utc)
    )


def fallback_fights_for_event(ev):
    name = str(ev.get("name") or "").lower()

    if "freedom 250" not in name and "topuria" not in name:
        return []

    fights = []

    for idx, red, blue, weight_class in FREEDOM_250_FIGHTS:
        fights.append(
            {
                "id": idx,
                "bout": f"{red} vs {blue}",
                "red": {"name": red},
                "blue": {"name": blue},
                "weight_class": weight_class,
                "status": "scheduled",
            }
        )

    return fights


def get_event_fights(ev):
    fights = ev.get("fights", []) or []

    if fights:
        return fights

    return fallback_fights_for_event(ev)


def render_event_page(ev):
    raw_name = ev.get("name")
    raw_date = ev.get("date")
    raw_location = ev.get("location")
    raw_slug = ev.get("slug") or ev.get("id")

    name = esc(raw_name)
    date = esc(format_event_date(raw_date))
    location = esc(raw_location)
    slug = str(raw_slug or "").strip()
    fights = get_event_fights(ev)
    status = esc(get_event_status(raw_date))

    if not slug:
        return None, None

    if not fights:
        fights_html = "<p class='muted'>Fight card not available yet.</p>"
    else:
        rows = []

        for f in fights:
            red = esc((f.get("red") or {}).get("name"))
            blue = esc((f.get("blue") or {}).get("name"))
            bout = esc(f.get("bout") or f"{red} vs {blue}")
            wc = esc(f.get("weight_class") or "")
            fid = fight_id(f)

            if fid:
                link = f"{BASE}/ufc/fights/{esc(fid)}/"
                action = f'<a class="fight-link" href="{link}">View fight odds →</a>'
            else:
                action = ""

            rows.append(
                f"""
        <article class="fight-row">
          <div>
            <h3>{bout}</h3>
            <p class="muted">{wc}</p>
          </div>
          <div>
            {action}
          </div>
        </article>
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
  <style>
    body {{
      background:#0F1621;
    }}

    .event-page {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 36px 22px 64px;
    }}

    .event-card {{
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 28px;
      background: rgba(255,255,255,0.025);
    }}

    .event-card h1 {{
      font-size: clamp(34px, 5vw, 58px);
      line-height: 1.03;
      margin: 20px 0 12px;
      letter-spacing: -0.04em;
    }}

    .fight-grid {{
      display: grid;
      gap: 14px;
      margin-top: 18px;
    }}

    .fight-row {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      background: rgba(15,22,33,0.8);
    }}

    .fight-row h3 {{
      margin: 0;
      font-size: 22px;
    }}

    .fight-row p {{
      margin: 8px 0 0;
    }}

    .fight-link {{
      display: inline-flex;
      border: 1px solid rgba(96,165,250,0.45);
      background: rgba(96,165,250,0.12);
      color: #93c5fd;
      border-radius: 999px;
      padding: 10px 14px;
      font-weight: 800;
      text-decoration: none;
      white-space: nowrap;
    }}

    .fight-link:hover {{
      background: rgba(96,165,250,0.22);
    }}

    @media (max-width: 700px) {{
      .fight-row {{
        flex-direction: column;
        align-items: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <main class="event-page">
    <section class="event-card">
      <p><a href="{BASE}/ufc/">← Back to UFC Hub</a></p>
      <h1>{name}</h1>
      <p class="muted">{date}{location_line} • {status}</p>

      <h2>Fight Card</h2>
      <div class="fight-grid">
        {fights_html}
      </div>

      <hr style="margin:24px 0; border-color:#1f2a3a;">
      <p class="muted">Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
    </section>
  </main>
</body>
</html>
"""
    return slug, html


def main():
    ensure_dir(EVENTS_DIR)

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