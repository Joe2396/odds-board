import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "index.html"

BASE_PATH = "/odds-board/ufc"  # adjust later if you change repo name / domain


def load_events():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    events = data.get("events", [])
    # newest first by date string YYYY-MM-DD
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    return events


def html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def build():
    events = load_events()
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    cards = []
    for e in events:
        name = html_escape(e.get("name", "Event"))
        date = html_escape(e.get("date", ""))
        loc = html_escape(e.get("location", ""))
        slug = e.get("slug", "")
        url = f"{BASE_PATH}/events/{slug}/"

        cards.append(f"""
        <div class="row" style="margin-top:16px;">
          <div>
            <h3>{name}</h3>
            <p class="muted">{date} • {loc}</p>
            <p><a href="{url}">View event →</a></p>
          </div>
          <div class="muted">→</div>
        </div>
        """)

    cards_html = "\n".join(cards) if cards else "<p class='muted'>No events yet.</p>"

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>UFC Hub</title>
  <link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
</head>
<body>

  <div class="card">
    <h1>🥊 UFC Hub</h1>
    <p class="muted">UFC events, fight cards and fighter research tools.</p>

    <p><a href="{BASE_PATH}/fighters/">Browse fighters →</a></p>

    <h2>Upcoming Events</h2>

    {cards_html}

    <hr style="margin:24px 0; border-color:#1f2a3a;">
    <p class="muted">Generated: {generated}</p>
    <p><a href="/">← Back to home</a></p>
  </div>

</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
