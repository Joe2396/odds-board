import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ufc" / "data" / "events.json"
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
    return json.loads(DATA.read_text(encoding="utf-8")).get("events", [])


def collect_fighters(events):
    """
    events.json schema:
      fight.red:  { name, espn_id }
      fight.blue: { name, espn_id }
    We'll dedupe by espn_id when available, else by name.
    """
    fighters = {}  # key -> fighter dict

    for ev in events:
        for fight in ev.get("fights", []):
            for corner_key in ("red", "blue"):
                c = fight.get(corner_key) or {}
                name = (c.get("name") or "").strip()
                espn_id = (c.get("espn_id") or "").strip()

                if not name and not espn_id:
                    continue

                slug = slugify(name) if name else (f"fighter-{espn_id}" if espn_id else "")
                key = f"espn:{espn_id}" if espn_id else f"name:{name.lower()}"

                # Minimal fighter object (stats will be filled later when you integrate UFCStats)
                fighters[key] = {
                    "name": name or "Fighter",
                    "slug": slug,
                    "espn_id": espn_id,
                    "nickname": "",
                    "record": "",
                    "stance": "",
                    "country": "",
                    "height_cm": None,
                    "reach_cm": None,
                    "methods": {},
                    "quick": {},
                }

    return fighters


def build_fighter_page(f):
    name = html_escape(f.get("name", "Fighter"))
    slug = f.get("slug", "")
    espn_id = html_escape(f.get("espn_id", ""))

    nick = html_escape(f.get("nickname", ""))
    record = html_escape(f.get("record", ""))
    stance = html_escape(f.get("stance", ""))
    country = html_escape(f.get("country", ""))
    height = f.get("height_cm")
    reach = f.get("reach_cm")

    methods = f.get("methods", {}) if isinstance(f.get("methods", {}), dict) else {}
    quick = f.get("quick", {}) if isinstance(f.get("quick", {}), dict) else {}

    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

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
<p class="muted">{nick or "—"} • {record or "—"}</p>

<div class="panel">
<p><b>ESPN ID:</b> {espn_id or "—"}</p>
<p><b>Stance:</b> {stance or "—"}</p>
<p><b>Height:</b> {str(height)+" cm" if height else "—"}</p>
<p><b>Reach:</b> {str(reach)+" cm" if reach else "—"}</p>
<p><b>Country:</b> {country or "—"}</p>
</div>

<h2>Methods</h2>
<div class="grid">
<div class="panel">KO/TKO: {methods.get("ko_tko_w",0)} W / {methods.get("ko_tko_l",0)} L</div>
<div class="panel">SUB: {methods.get("sub_w",0)} W / {methods.get("sub_l",0)} L</div>
<div class="panel">DEC: {methods.get("dec_w",0)} W / {methods.get("dec_l",0)} L</div>
</div>

<h2>Quick stats</h2>
<div class="grid">
<div class="panel">Finish rate: {quick.get("finish_rate","—")}</div>
<div class="panel">Avg fight length: {quick.get("avg_fight_min","—")} min</div>
<div class="panel">Round 1 win share: {quick.get("r1_win_share","—")}</div>
</div>

<hr style="margin:24px 0;border-color:#1f2a3a">
<p class="muted">Generated: {generated}</p>
</div>
</body>
</html>
"""


def build_fighter_index(fighters):
    # fighters is dict keyed by espn/name; index by name
    rows = sorted(fighters.values(), key=lambda x: (x.get("name") or "").lower())

    items = "\n".join(
        f'<li><a href="{BASE_PATH}/fighters/{f.get("slug","")}/">{html_escape(f.get("name","Fighter"))}</a></li>'
        for f in rows
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
    fighters = collect_fighters(events)

    OUT.mkdir(parents=True, exist_ok=True)

    # Ensure folder exists in git even if empty (optional)
    keep = OUT / ".keep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")

    written = 0
    for f in fighters.values():
        slug = f.get("slug")
        if not slug:
            continue
        d = OUT / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_fighter_page(f), encoding="utf-8")
        written += 1

    (OUT / "index.html").write_text(build_fighter_index(fighters), encoding="utf-8")
    print(f"✅ Wrote {written} fighter pages")


if __name__ == "__main__":
    main()
