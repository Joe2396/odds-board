import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
FIGHTERS = ROOT / "ufc" / "data" / "fighters.json"
OUT = ROOT / "ufc" / "fighters"

BASE_PATH = "/odds-board/ufc"


def html_escape(s):
    if s is None:
        return "—"
    return (
        str(s).replace("&","&amp;")
              .replace("<","&lt;")
              .replace(">","&gt;")
              .replace('"',"&quot;")
              .replace("'","&#39;")
    )


def slugify(name):
    return (
        name.lower()
        .replace(" ", "-")
        .replace(".", "")
        .replace("'", "")
    )


def main():
    events = json.loads(EVENTS.read_text())
    fighters_db = json.loads(FIGHTERS.read_text()).get("fighters", {})

    fighters = {}

    for e in events.get("events", []):
        for f in e.get("fights", []):
            for side in ("red", "blue"):
                p = f.get(side, {})
                if "espn_id" in p:
                    fighters[p["espn_id"]] = p.get("name")

    OUT.mkdir(parents=True, exist_ok=True)

    links = []

    for fid, name in fighters.items():
        data = fighters_db.get(str(fid))
        if not data:
            continue

        slug = slugify(name)
        d = OUT / slug
        d.mkdir(parents=True, exist_ok=True)

        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html_escape(name)}</title>
<link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
</head>
<body>
<div class="card">
<p class="muted"><a href="{BASE_PATH}/">UFC Hub</a> / <a href="{BASE_PATH}/fighters/">Fighters</a></p>

<h1>{html_escape(name)}</h1>
<p class="muted">{html_escape(data.get("nickname"))}</p>

<div class="panel">
<p><b>Record:</b> {html_escape(data.get("record"))}</p>
<p><b>Stance:</b> {html_escape(data.get("stance"))}</p>
<p><b>Height:</b> {html_escape(data.get("height_cm"))} cm</p>
<p><b>Reach:</b> {html_escape(data.get("reach_cm"))} cm</p>
<p><b>Country:</b> {html_escape(data.get("country"))}</p>
</div>

<hr>
<p class="muted">Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</p>
</div>
</body>
</html>
"""
        (d / "index.html").write_text(page, encoding="utf-8")
        links.append(f'<li><a href="{BASE_PATH}/fighters/{slug}/">{html_escape(name)}</a></li>')

    index = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Fighters</title>
<link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
</head>
<body>
<div class="card">
<h1>UFC Fighters</h1>
<ul>{"".join(sorted(links))}</ul>
</div>
</body>
</html>
"""

    (OUT / "index.html").write_text(index, encoding="utf-8")
    print("✅ Built fighter pages:", len(links))


if __name__ == "__main__":
    main()
