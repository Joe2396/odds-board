import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
EVENTS_JSON = ROOT / "ufc" / "data" / "events.json"
FIGHTERS_JSON = ROOT / "ufc" / "data" / "fighters.json"   # <-- new
OUT = ROOT / "ufc" / "fighters"

BASE_PATH = "/odds-board/ufc"


def html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def slugify(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def load_events():
    return json.loads(EVENTS_JSON.read_text(encoding="utf-8")).get("events", [])


def load_fighter_details():
    """
    Expected shape (from your fetch step):
      {"fighters": {"3949584": {...}, "4881999": {...}}}
    We keep it flexible and just store the dict.
    """
    if not FIGHTERS_JSON.exists():
        return {}
    data = json.loads(FIGHTERS_JSON.read_text(encoding="utf-8"))
    fighters = data.get("fighters", {})
    return fighters if isinstance(fighters, dict) else {}


def collect_fighters_from_events(events):
    fighters = {}  # key: espn_id or name

    for ev in events:
        for fight in ev.get("fights", []):
            for corner_key in ("red", "blue"):
                c = fight.get(corner_key) or {}
                name = (c.get("name") or "").strip()
                espn_id = str(c.get("espn_id") or "").strip()

                if not name and not espn_id:
                    continue

                slug = slugify(name) if name else (f"fighter-{espn_id}" if espn_id else "")
                key = f"espn:{espn_id}" if espn_id else f"name:{name.lower()}"

                fighters[key] = {
                    "name": name or "Fighter",
                    "slug": slug,
                    "espn_id": espn_id,
                    # placeholders; will be enriched
                    "record": "",
                    "stance": "",
                    "height": None,
                    "reach": None,
                }

    return fighters


def enrich_with_details(fighter: dict, details_by_espn: dict) -> dict:
    espn_id = fighter.get("espn_id", "")
    if not espn_id or espn_id not in details_by_espn:
        return fighter

    d = details_by_espn.get(espn_id, {}) or {}

    # We keep these flexible because ESPN field names can vary:
    # record, height, reach, stance might be strings or numbers.
    fighter["record"] = d.get("record") or fighter.get("record", "")
    fighter["stance"] = d.get("stance") or fighter.get("stance", "")
    fighter["height"] = d.get("height") if d.get("height") is not None else fighter.get("height")
    fighter["reach"] = d.get("reach") if d.get("reach") is not None else fighter.get("reach")

    # Prefer ESPN name if present
    fighter["name"] = d.get("name") or fighter.get("name", "Fighter")

    return fighter


def build_fighter_page(f):
    name = html_escape(f.get("name", "Fighter"))
    slug = f.get("slug", "")
    espn_id = html_escape(f.get("espn_id", ""))

    record = html_escape(f.get("record", ""))
    stance = html_escape(f.get("stance", ""))
    height = f.get("height")
    reach = f.get("reach")

    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Relative CSS works better inside fights/fighters too, but this is fine since BASE_PATH is stable.
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{name} — Fighter Profile</title>
<link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
<style>
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.panel{{border:1px solid var(--line);border-radius:12px;padding:14px;background:rgba(255,255,255,.02)}}
@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="card">
<p class="muted"><a href="{BASE_PATH}/">UFC Hub</a> / <a href="{BASE_PATH}/fighters/">Fighters</a></p>

<h1>{name}</h1>
<p class="muted">Record: {record or "—"} • Stance: {stance or "—"}</p>

<div class="panel">
<p><b>ESPN ID:</b> {espn_id or "—"}</p>
<p><b>Height:</b> {html_escape(str(height)) if height else "—"}</p>
<p><b>Reach:</b> {html_escape(str(reach)) if reach else "—"}</p>
</div>

<hr style="margin:24px 0;border-color:#1f2a3a">
<p class="muted">Generated: {generated}</p>
</div>
</body>
</html>
"""


def build_fighter_index(fighters_list):
    items = "\n".join(
        f'<li><a href="{BASE_PATH}/fighters/{f["slug"]}/">{html_escape(f.get("name","Fighter"))}</a></li>'
        for f in sorted(fighters_list, key=lambda x: (x.get("name") or "").lower())
        if f.get("slug")
    )

    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>UFC Fighters</title>
<link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
</head>
<body>
<div class="card">
<p class="muted"><a href="{BASE_PATH}/">UFC Hub</a></p>
<h1>Fighters</h1>
<ul>{items}</ul>
<hr style="margin:24px 0;border-color:#1f2a3a">
<p class="muted">Generated: {generated}</p>
</div>
</body>
</html>
"""


def main():
    events = load_events()
    details_by_espn = load_fighter_details()

    fighters_map = collect_fighters_from_events(events)
    fighters = []
    for f in fighters_map.values():
        fighters.append(enrich_with_details(f, details_by_espn))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ".keep").write_text("", encoding="utf-8")

    written = 0
    for f in fighters:
        slug = f.get("slug")
        if not slug:
            continue
        d = OUT / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_fighter_page(f), encoding="utf-8")
        written += 1

    (OUT / "index.html").write_text(build_fighter_index(fighters), encoding="utf-8")
    print(f"✅ Wrote {written} fighter pages (enriched where possible)")


if __name__ == "__main__":
    main()
