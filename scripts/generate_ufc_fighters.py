import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]

EVENTS_JSON = ROOT / "ufc" / "data" / "events.json"
FIGHTERS_JSON = ROOT / "ufc" / "data" / "fighters.json"
OUT_DIR = ROOT / "ufc" / "fighters"

BASE_PATH = "/odds-board/ufc"


def html_escape(s) -> str:
    if s is None:
        return "—"
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


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def methods_table(methods: dict) -> str:
    if not isinstance(methods, dict):
        methods = {}
    ko = f"{methods.get('ko_tko_w',0)} W • {methods.get('ko_tko_l',0)} L"
    sub = f"{methods.get('sub_w',0)} W • {methods.get('sub_l',0)} L"
    dec = f"{methods.get('dec_w',0)} W • {methods.get('dec_l',0)} L"
    return f"""
      <table>
        <tr><td>KO/TKO</td><td>{html_escape(ko)}</td></tr>
        <tr><td>SUB</td><td>{html_escape(sub)}</td></tr>
        <tr><td>DEC</td><td>{html_escape(dec)}</td></tr>
      </table>
    """


def recent_fights_table(recent: list) -> str:
    if not isinstance(recent, list):
        recent = []

    rows = []
    for rf in recent[:10]:
        if not isinstance(rf, dict):
            continue
        date = html_escape(rf.get("date", "—"))
        event = html_escape(rf.get("event", "—"))
        result = html_escape(rf.get("result", "—"))
        opp = html_escape(rf.get("opponent", "—"))
        method = html_escape(rf.get("method", "—"))
        rnd = html_escape(rf.get("round", "—"))
        tme = html_escape(rf.get("time", "—"))
        rows.append(
            f"<tr>"
            f"<td>{date}</td>"
            f"<td>{event}</td>"
            f"<td>{result}</td>"
            f"<td>vs {opp}</td>"
            f"<td>{method}</td>"
            f"<td>{rnd}</td>"
            f"<td>{tme}</td>"
            f"</tr>"
        )

    body = "\n".join(rows) if rows else '<tr><td colspan="7" class="muted">No recent fights found yet.</td></tr>'
    return f"""
      <table>
        <tr>
          <th>Date</th><th>Event</th><th>Result</th><th>Opponent</th><th>Method</th><th>R</th><th>Time</th>
        </tr>
        {body}
      </table>
    """


def build_fighter_page(name: str, slug: str, fid: str, data: dict) -> str:
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    nickname = html_escape(data.get("nickname"))
    record = html_escape(data.get("record"))
    stance = html_escape(data.get("stance"))
    country = html_escape(data.get("country"))
    wc = html_escape(data.get("weight_class"))
    height_cm = data.get("height_cm")
    reach_cm = data.get("reach_cm")

    methods = data.get("methods") or {}
    recent = data.get("recent_fights") or []

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{html_escape(name)} — Fighter Profile</title>
<link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
<style>
.panel{{border:1px solid var(--line);border-radius:12px;padding:14px;background:rgba(255,255,255,.02)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
table{{width:100%;border-collapse:collapse;margin-top:10px}}
td,th{{padding:8px;border-bottom:1px solid var(--line);text-align:left}}
</style>
</head>
<body>
<div class="card">
  <p class="muted">
    <a href="{BASE_PATH}/">UFC Hub</a> /
    <a href="{BASE_PATH}/fighters/">Fighters</a>
  </p>

  <h1>{html_escape(name)}</h1>
  <p class="muted">{nickname}</p>

  <div class="panel">
    <p><b>Record:</b> {record}</p>
    <p><b>Weight class:</b> {wc}</p>
    <p><b>Stance:</b> {stance}</p>
    <p><b>Height:</b> {html_escape(height_cm)} cm</p>
    <p><b>Reach:</b> {html_escape(reach_cm)} cm</p>
    <p><b>Country:</b> {country}</p>
    <p><b>ESPN ID:</b> {html_escape(fid)}</p>
  </div>

  <div class="panel" style="margin-top:14px;">
    <h2>Win/Loss Methods</h2>
    {methods_table(methods)}
  </div>

  <div class="panel" style="margin-top:14px;">
    <h2>Last 10 fights</h2>
    {recent_fights_table(recent)}
  </div>

  <hr style="margin:24px 0;border-color:#1f2a3a;">
  <p class="muted">Generated: {generated}</p>
</div>
</body>
</html>
"""


def build_fighters_index(items: list) -> str:
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lis = "\n".join(
        f'<li><a href="{BASE_PATH}/fighters/{html_escape(it["slug"])}/">{html_escape(it["name"])}</a></li>'
        for it in items
    )
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
  <ul>{lis}</ul>
  <hr style="margin:24px 0;border-color:#1f2a3a;">
  <p class="muted">Generated: {generated}</p>
</div>
</body>
</html>
"""


def main():
    events = load_json(EVENTS_JSON)
    fighters_db = load_json(FIGHTERS_JSON).get("fighters", {})

    # Collect unique fighters from upcoming events
    seen = {}  # fid -> name
    for ev in events.get("events", []):
        for fight in ev.get("fights", []):
            for side in ("red", "blue"):
                c = fight.get(side) or {}
                fid = str(c.get("espn_id") or "").strip()
                nm = (c.get("name") or "").strip()
                if fid and nm:
                    seen[fid] = nm

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / ".keep").write_text("", encoding="utf-8")

    index_items = []
    written = 0

    for fid, nm in sorted(seen.items(), key=lambda x: x[1].lower()):
        data = fighters_db.get(str(fid))
        if not isinstance(data, dict):
            continue

        slug = slugify(nm)
        if not slug:
            continue

        d = OUT_DIR / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_fighter_page(nm, slug, fid, data), encoding="utf-8")

        index_items.append({"name": nm, "slug": slug})
        written += 1

    (OUT_DIR / "index.html").write_text(build_fighters_index(index_items), encoding="utf-8")
    print(f"✅ Wrote {written} fighter pages")


if __name__ == "__main__":
    main()
