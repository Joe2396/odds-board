import json
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


def load_events():
    return json.loads(DATA.read_text(encoding="utf-8")).get("events", [])


def collect_fighters(events):
    fighters = {}
    for ev in events:
        for fight in ev.get("fights", []):
            for side in ("fighter_a", "fighter_b"):
                f = fight.get(side)
                if not f:
                    continue
                slug = f.get("slug")
                if slug:
                    fighters[slug] = f
    return fighters


def build_fighter_page(f):
    name = html_escape(f.get("name", "Fighter"))
    nick = html_escape(f.get("nickname", ""))
    record = html_escape(f.get("record", ""))
    stance = html_escape(f.get("stance", ""))
    country = html_escape(f.get("country", ""))
    height = f.get("height_cm")
    reach = f.get("reach_cm")

    methods = f.get("methods", {})
    quick = f.get("quick", {})

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
<p class="muted">{nick} • {record}</p>

<div class="panel">
<p>Stance: {stance or "—"}</p>
<p>Height: {str(height)+" cm" if height else "—"}</p>
<p>Reach: {str(reach)+" cm" if reach else "—"}</p>
<p>Country: {country or "—"}</p>
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
    items = "\n".join(
        f'<li><a href="{BASE_PATH}/fighters/{slug}/">{html_escape(f.get("name","Fighter"))}</a></li>'
        for slug, f in sorted(fighters.items(), key=lambda x: x[1].get("name",""))
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

    for slug, f in fighters.items():
        d = OUT / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_fighter_page(f), encoding="utf-8")

    (OUT / "index.html").write_text(build_fighter_index(fighters), encoding="utf-8")
    print(f"Wrote {len(fighters)} fighters")


if __name__ == "__main__":
    main()
