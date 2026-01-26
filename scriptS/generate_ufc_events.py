import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ufc" / "data" / "events.json"
EVENTS_DIR = ROOT / "ufc" / "events"

BASE_PATH = "/odds-board/ufc"  # your GitHub Pages repo path


def html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def load_events():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return data.get("events", [])


def build_event_page(event: dict) -> str:
    name = html_escape(event.get("name", "Event"))
    date = html_escape(event.get("date", ""))
    loc = html_escape(event.get("location", ""))
    slug = event.get("slug", "")

    fights = event.get("fights", [])
    fight_rows = []

    for f in fights:
        f_slug = f.get("slug", "")
        a = f.get("fighter_a", {}).get("name", "Fighter A")
        b = f.get("fighter_b", {}).get("name", "Fighter B")
        weight = f.get("weight_class", "—")
        rounds = f.get("scheduled_rounds", "—")
        main = "Main Event" if f.get("is_main_event") else ""

        # link points to your EXISTING fight page structure
        fight_url = f"{BASE_PATH}/events/{slug}/fights/{f_slug}/"

        fight_rows.append(f"""
        <div class="row" style="margin-top:16px;">
          <div>
            <h3>{html_escape(a)} vs {html_escape(b)} {f"<span class='muted'>({html_escape(main)})</span>" if main else ""}</h3>
            <p class="muted">{html_escape(weight)} • {html_escape(str(rounds))} rounds</p>
            <p><a href="{fight_url}">View fight →</a></p>
          </div>
          <div class="muted">→</div>
        </div>
        """)

    fights_html = "\n".join(fight_rows) if fight_rows else "<p class='muted'>No fights added yet.</p>"
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{name}</title>
  <link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
</head>
<body>
  <div class="card">
    <p class="muted"><a href="{BASE_PATH}/">← Back to UFC Hub</a></p>

    <h1>{name}</h1>
    <p class="muted">{date} • {loc}</p>

    <h2>Fight Card</h2>

    {fights_html}

    <hr style="margin:24px 0; border-color:#1f2a3a;">
    <p class="muted">Generated: {generated}</p>
  </div>
</body>
</html>
"""


def main():
    events = load_events()
    if not events:
        print("No events in events.json")
        return

    for event in events:
        slug = event.get("slug")
        if not slug:
            continue

        out_dir = EVENTS_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "index.html"

        out_file.write_text(build_event_page(event), encoding="utf-8")
        print(f"Wrote {out_file}")


if __name__ == "__main__":
    main()
