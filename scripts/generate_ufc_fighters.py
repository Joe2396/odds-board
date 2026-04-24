#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

EVENTS_JSON = ROOT / "ufc" / "data" / "events.json"
FIGHTERS_JSON = ROOT / "ufc" / "data" / "fighters.json"
OUT_DIR = ROOT / "ufc" / "fighters"

BASE_PATH = "/odds-board/ufc"


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def html_escape(s):
    if s is None or s == "":
        return "—"
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def slugify(name):
    name = str(name or "").lower().strip()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def normalize_fighter_record(f):
    return {
        "name": f.get("name") or f.get("displayName") or f.get("fullName"),
        "nickname": f.get("nickname"),
        "record": f.get("record"),
        "height": f.get("height") or f.get("height_cm"),
        "weight": f.get("weight") or f.get("weight_class"),
        "reach": f.get("reach") or f.get("reach_cm"),
        "stance": f.get("stance"),
        "age": f.get("age"),
        "country": f.get("country"),
        "tapology_url": f.get("tapology_url"),
        "image_url": f.get("image_url"),
        "recent_fights": f.get("recent_fights") or [],
        "methods": f.get("methods") or {},
    }


def load_fighters_db():
    raw = load_json(FIGHTERS_JSON, {"fighters": {}})
    fighters_raw = raw.get("fighters", {})

    fighters_by_slug = {}

    if isinstance(fighters_raw, dict):
        iterable = fighters_raw.values()
    elif isinstance(fighters_raw, list):
        iterable = fighters_raw
    else:
        iterable = []

    for f in iterable:
        if not isinstance(f, dict):
            continue

        fighter = normalize_fighter_record(f)
        name = fighter.get("name")
        if not name:
            continue

        fighters_by_slug[slugify(name)] = fighter

    return fighters_by_slug


def collect_scheduled_fighters():
    data = load_json(EVENTS_JSON, {"events": []})

    fighters = {}

    for event in data.get("events", []):
        event_name = event.get("name")
        event_date = event.get("date")
        event_slug = event.get("slug") or event.get("id")
        event_status = str(event.get("status") or "").lower()

        if event_status not in {"upcoming", "scheduled", "today"}:
            continue

        for fight in event.get("fights", []) or []:
            fight_status = str(fight.get("status") or "").lower()
            if fight_status not in {"scheduled", "upcoming", "in_progress", ""}:
                continue

            for side in ("red", "blue"):
                fighter = fight.get(side) or {}
                name = fighter.get("name")
                if not name:
                    continue

                slug = slugify(name)

                fighters.setdefault(slug, {
                    "name": name,
                    "slug": slug,
                    "scheduled_fights": [],
                })

                fighters[slug]["scheduled_fights"].append({
                    "event": event_name,
                    "event_date": event_date,
                    "event_slug": event_slug,
                    "bout": fight.get("bout"),
                    "weight_class": fight.get("weight_class"),
                    "fight_id": fight.get("id"),
                })

    return fighters


def render_recent_fights(fights):
    if not fights:
        return "<p class='muted'>Recent fight history not available yet.</p>"

    rows = []
    for f in fights[:10]:
        result = html_escape(f.get("result"))
        opponent = html_escape(f.get("opponent"))
        method = html_escape(f.get("method"))
        rnd = html_escape(f.get("round"))
        time = html_escape(f.get("time"))
        event = html_escape(f.get("event"))
        date = html_escape(f.get("date"))

        rows.append(f"""
        <div class="row" style="margin-top:10px;">
          <div>
            <strong>{result}</strong> vs {opponent}
            <p class="muted" style="margin:4px 0 0 0;">{method} • R{rnd} • {time} • {event} • {date}</p>
          </div>
        </div>
        """.rstrip())

    return "\n".join(rows)


def render_scheduled_fights(fights):
    if not fights:
        return "<p class='muted'>No scheduled fights found.</p>"

    rows = []
    for f in fights:
        event = html_escape(f.get("event"))
        date = html_escape(f.get("event_date"))
        bout = html_escape(f.get("bout"))
        weight = html_escape(f.get("weight_class"))
        event_slug = f.get("event_slug")

        event_link = ""
        if event_slug:
            event_link = f'<p><a href="{BASE_PATH}/events/{html_escape(event_slug)}/">View event →</a></p>'

        rows.append(f"""
        <div class="row" style="margin-top:12px;">
          <div>
            <h3 style="margin:0;">{bout}</h3>
            <p class="muted" style="margin:6px 0 0 0;">{date} • {event} • {weight}</p>
            {event_link}
          </div>
        </div>
        """.rstrip())

    return "\n".join(rows)


def build_fighter_page(fighter):
    name = html_escape(fighter.get("name"))
    nickname = html_escape(fighter.get("nickname"))
    record = html_escape(fighter.get("record"))
    height = html_escape(fighter.get("height"))
    weight = html_escape(fighter.get("weight"))
    reach = html_escape(fighter.get("reach"))
    stance = html_escape(fighter.get("stance"))
    age = html_escape(fighter.get("age"))
    country = html_escape(fighter.get("country"))
    tapology_url = fighter.get("tapology_url")
    image = fighter.get("image_url") or ""

    recent_html = render_recent_fights(fighter.get("recent_fights") or [])
    scheduled_html = render_scheduled_fights(fighter.get("scheduled_fights") or [])

    tapology_link = ""
    if tapology_url:
        tapology_link = f'<p><a href="{html_escape(tapology_url)}">Tapology profile →</a></p>'

    image_html = f"<img src='{html_escape(image)}' width='200' style='border-radius:16px;'>" if image else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{name} | UFC Fighter</title>
  <link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
</head>
<body>
  <div class="card">
    <p><a href="{BASE_PATH}/fighters/">← Back to fighters</a></p>

    <h1>{name}</h1>
    <p class="muted">Nickname: {nickname}</p>
    {image_html}
    {tapology_link}

    <h2>Profile</h2>
    <p><strong>Record:</strong> {record}</p>
    <p><strong>Weight class:</strong> {weight}</p>
    <p><strong>Height:</strong> {height}</p>
    <p><strong>Reach:</strong> {reach}</p>
    <p><strong>Stance:</strong> {stance}</p>
    <p><strong>Age:</strong> {age}</p>
    <p><strong>Country:</strong> {country}</p>

    <h2>Scheduled Fights</h2>
    {scheduled_html}

    <h2>Recent Fights</h2>
    {recent_html}

    <hr style="margin:24px 0; border-color:#1f2a3a;">
    <p class="muted">Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
  </div>
</body>
</html>
"""


def build_index_page(fighters):
    rows = []

    for fighter in sorted(fighters.values(), key=lambda f: f.get("name", "")):
        name = html_escape(fighter.get("name"))
        slug = fighter.get("slug")
        record = html_escape(fighter.get("record"))
        next_fight = ""

        scheduled = fighter.get("scheduled_fights") or []
        if scheduled:
            next_fight = html_escape(scheduled[0].get("bout"))

        rows.append(f"""
        <div class="row" style="margin-top:12px;">
          <div>
            <h3 style="margin:0;"><a href="{BASE_PATH}/fighters/{slug}/">{name}</a></h3>
            <p class="muted" style="margin:6px 0 0 0;">Record: {record} • Next: {next_fight}</p>
          </div>
          <div class="muted">→</div>
        </div>
        """.rstrip())

    rows_html = "\n".join(rows) if rows else "<p class='muted'>No fighters found.</p>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>UFC Fighters</title>
  <link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
</head>
<body>
  <div class="card">
    <p><a href="{BASE_PATH}/">← Back to UFC Hub</a></p>
    <h1>UFC Fighters</h1>
    <p class="muted">Fighters with currently scheduled UFC fights.</p>

    {rows_html}

    <hr style="margin:24px 0; border-color:#1f2a3a;">
    <p class="muted">Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
  </div>
</body>
</html>
"""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    existing_stats = load_fighters_db()
    scheduled_fighters = collect_scheduled_fighters()

    final_fighters = {}

    for slug, scheduled in scheduled_fighters.items():
        stats = existing_stats.get(slug, {})
        merged = {
            **stats,
            **scheduled,
        }
        final_fighters[slug] = merged

    count = 0

    for slug, fighter in final_fighters.items():
        html = build_fighter_page(fighter)
        out_dir = OUT_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / "index.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        count += 1

    index_html = build_index_page(final_fighters)
    with open(OUT_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"Wrote {count} fighter pages by name slug")


if __name__ == "__main__":
    main()
