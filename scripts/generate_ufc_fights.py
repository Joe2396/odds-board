import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ufc" / "data" / "events.json"
FIGHTS_DIR = ROOT / "ufc" / "fights"

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


def pct(x):
    if x is None:
        return "—"
    try:
        return f"{float(x) * 100:.0f}%"
    except:
        return "—"


def slugify(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def load_events():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return data.get("events", [])


def get_fight_id(fight: dict) -> str:
    # Your schema uses "id" like "401839016"
    v = fight.get("id")
    return str(v).strip() if v is not None else ""


def normalize_fighter_from_corner(corner: dict) -> dict:
    """
    Convert your corner object:
      {"name":"...", "espn_id":"..."}
    into the richer shape your UI expects.
    """
    name = corner.get("name", "") if isinstance(corner, dict) else ""
    espn_id = corner.get("espn_id", "") if isinstance(corner, dict) else ""
    slug = slugify(name) if name else ""

    return {
        "name": name or "Fighter",
        "slug": slug,
        "nickname": "",
        "record": "",
        "stance": "",
        "height_cm": None,
        "reach_cm": None,
        "country": "",
        "methods": {},  # will be filled later when you enrich fighters
        "quick": {},    # will be filled later when you enrich fighters
        "espn_id": espn_id,
    }


def fighter_panel(f: dict) -> str:
    name = html_escape(f.get("name", "Fighter"))
    slug = f.get("slug", "")
    nick = html_escape(f.get("nickname", ""))
    record = html_escape(f.get("record", ""))
    stance = html_escape(f.get("stance", ""))
    h = f.get("height_cm", None)
    r = f.get("reach_cm", None)
    country = html_escape(f.get("country", ""))

    methods = f.get("methods", {}) if isinstance(f.get("methods", {}), dict) else {}
    quick = f.get("quick", {}) if isinstance(f.get("quick", {}), dict) else {}

    fighter_href = f"{BASE_PATH}/fighters/{slug}/" if slug else "#"

    return f"""
    <div class="panel">
      <h2><a href="{fighter_href}">{name}</a></h2>
      <div class="muted">Nickname: {nick or "—"}</div>

      <div class="pillrow">
        <span class="pill">Record: {record or "—"}</span>
        <span class="pill">Stance: {stance or "—"}</span>
        <span class="pill">Height: {html_escape(str(h) + " cm") if h else "—"}</span>
        <span class="pill">Reach: {html_escape(str(r) + " cm") if r else "—"}</span>
        <span class="pill">Country: {country or "—"}</span>
      </div>

      <h3 class="muted">Methods</h3>
      <table>
        <tr><td>KO/TKO</td><td>{methods.get("ko_tko_w",0)} W • {methods.get("ko_tko_l",0)} L</td></tr>
        <tr><td>SUB</td><td>{methods.get("sub_w",0)} W • {methods.get("sub_l",0)} L</td></tr>
        <tr><td>DEC</td><td>{methods.get("dec_w",0)} W • {methods.get("dec_l",0)} L</td></tr>
      </table>

      <h3 class="muted">Quick Stats</h3>
      <table>
        <tr><td>Finish rate</td><td>{pct(quick.get("finish_rate"))}</td></tr>
        <tr><td>Avg fight length</td><td>{html_escape(str(quick.get("avg_fight_min")) + " min") if quick.get("avg_fight_min") is not None else "—"}</td></tr>
        <tr><td>Round 1 win share</td><td>{pct(quick.get("r1_win_share"))}</td></tr>
      </table>
    </div>
    """


def build_fight_page(event: dict, fight: dict, fight_id: str) -> str:
    event_slug = event.get("slug", "")
    event_name = html_escape(event.get("name", "Event"))

    red = normalize_fighter_from_corner(fight.get("red", {}))
    blue = normalize_fighter_from_corner(fight.get("blue", {}))

    title = f"{red.get('name','Fighter A')} vs {blue.get('name','Fighter B')}"
    weight = html_escape(fight.get("weight_class", "—"))
    rounds = "—"  # not present in your schema yet
    is_main = "Yes" if int(fight.get("order", 0)) == max(1, int(fight.get("order", 0))) and fight.get("order") == 14 else "No"
    # ^ we don't truly know main event from schema; leaving basic logic.
    # You can replace with real flag once you store it.

    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    css_href = "../../assets/ufc.css"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html_escape(title)}</title>
  <link rel="stylesheet" href="{css_href}">
  <style>
    .grid {{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:14px;
      margin-top:14px;
    }}
    .panel{{
      border:1px solid var(--line);
      border-radius:12px;
      padding:14px;
      background:rgba(255,255,255,0.02);
    }}
    .pillrow{{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
    .pill{{ border:1px solid var(--line); border-radius:999px; padding:6px 10px; color:var(--muted); font-size:13px; }}
    table{{ width:100%; border-collapse:collapse; margin-top:10px; }}
    td, th{{ padding:8px; border-bottom:1px solid var(--line); text-align:left; }}
    @media (max-width: 900px){{ .grid{{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="card">
    <p class="muted">
      <a href="{BASE_PATH}/">UFC Hub</a> /
      <a href="{BASE_PATH}/events/{event_slug}/">{event_name}</a> /
      Fight
    </p>

    <h1>{html_escape(title)}</h1>
    <p class="muted">{weight} • {rounds} rounds</p>

    <div class="grid">
      {fighter_panel(red)}
      {fighter_panel(blue)}
    </div>

    <div class="panel" style="margin-top:14px;">
      <h2>Fight Meta</h2>
      <table>
        <tr><td>Bout</td><td>{html_escape(fight.get("bout","—"))}</td></tr>
        <tr><td>Status</td><td>{html_escape(fight.get("status","—"))}</td></tr>
        <tr><td>Red ESPN ID</td><td>{html_escape(red.get("espn_id","—"))}</td></tr>
        <tr><td>Blue ESPN ID</td><td>{html_escape(blue.get("espn_id","—"))}</td></tr>
      </table>
    </div>

    <hr style="margin:24px 0; border-color:#1f2a3a;">
    <p class="muted">Fight ID: {html_escape(fight_id)} • Generated: {generated}</p>
  </div>
</body>
</html>
"""


def main():
    events = load_events()

    FIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    keep = FIGHTS_DIR / ".keep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")

    fights_written = 0
    missing_ids = 0

    for event in events:
        if not event.get("slug"):
            continue

        for fight in event.get("fights", []):
            fight_id = get_fight_id(fight)
            if not fight_id:
                missing_ids += 1
                continue

            out_dir = FIGHTS_DIR / fight_id
            out_dir.mkdir(parents=True, exist_ok=True)

            out_file = out_dir / "index.html"
            out_file.write_text(build_fight_page(event, fight, fight_id), encoding="utf-8")
            fights_written += 1

    print(f"✅ Wrote {fights_written} fight pages to {FIGHTS_DIR}")
    if missing_ids:
        print(f"⚠️ Skipped {missing_ids} fights with no id key")

    if fights_written == 0:
        raise SystemExit("❌ Generated 0 fight pages. Check events.json schema.")


if __name__ == "__main__":
    main()
