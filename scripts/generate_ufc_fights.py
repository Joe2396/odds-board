import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ufc" / "data" / "events.json"
EVENTS_DIR = ROOT / "ufc" / "events"

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
        return f"{float(x)*100:.0f}%"
    except:
        return "—"


def load_events():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return data.get("events", [])


def fighter_panel(f: dict) -> str:
    name = html_escape(f.get("name", "Fighter"))
    slug = f.get("slug", "")
    nick = html_escape(f.get("nickname", ""))
    record = html_escape(f.get("record", ""))
    stance = html_escape(f.get("stance", ""))
    h = f.get("height_cm", None)
    r = f.get("reach_cm", None)
    country = html_escape(f.get("country", ""))

    methods = f.get("methods", {})
    quick = f.get("quick", {})

    return f"""
    <div class="panel">
      <h2><a href="{BASE_PATH}/fighters/{slug}/">{name}</a></h2>
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


def build_fight_page(event: dict, fight: dict) -> str:
    event_slug = event.get("slug", "")
    event_name = html_escape(event.get("name", "Event"))
    fight_slug = fight.get("slug", "")

    a = fight.get("fighter_a", {})
    b = fight.get("fighter_b", {})

    title = f"{a.get('name','Fighter A')} vs {b.get('name','Fighter B')}"
    weight = html_escape(fight.get("weight_class", "—"))
    rounds = html_escape(str(fight.get("scheduled_rounds", "—")))
    is_main = "Yes" if fight.get("is_main_event") else "No"

    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html_escape(title)}</title>
  <link rel="stylesheet" href="{BASE_PATH}/assets/ufc.css">
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
    <p class="muted">{weight} • {rounds} rounds • Main event: {is_main}</p>

    <div class="grid">
      {fighter_panel(a)}
      {fighter_panel(b)}
    </div>

    <div class="panel" style="margin-top:14px;">
      <h2>Result</h2>
      <p class="muted">Scheduled / not final.</p>
    </div>

    <hr style="margin:24px 0; border-color:#1f2a3a;">
    <p class="muted">Generated: {generated}</p>
  </div>
</body>
</html>
"""


def main():
    events = load_events()
    for event in events:
        event_slug = event.get("slug")
        if not event_slug:
            continue

        fights = event.get("fights", [])
        for fight in fights:
            fight_slug = fight.get("slug")
            if not fight_slug:
                continue

            out_dir = EVENTS_DIR / event_slug / "fights" / fight_slug
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / "index.html"
            out_file.write_text(build_fight_page(event, fight), encoding="utf-8")
            print(f"Wrote {out_file}")


if __name__ == "__main__":
    main()
