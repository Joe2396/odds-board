import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]

EVENTS_JSON = ROOT / "ufc" / "data" / "events.json"
FIGHTERS_JSON = ROOT / "ufc" / "data" / "fighters.json"
FIGHTS_DIR = ROOT / "ufc" / "fights"

BASE_PATH = "/odds-board/ufc"


def html_escape(s):
    if s is None or s == "":
        return "—"
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def slugify(name):
    name = str(name or "").strip().lower()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_events():
    data = load_json(EVENTS_JSON, {"events": []})
    return data.get("events", [])


def load_fighter_details():
    raw = load_json(FIGHTERS_JSON, {"fighters": []})
    fighters_raw = raw.get("fighters", [])

    fighters_by_slug = {}

    if isinstance(fighters_raw, dict):
        iterable = fighters_raw.values()
    elif isinstance(fighters_raw, list):
        iterable = fighters_raw
    else:
        iterable = []

    for fighter in iterable:
        if not isinstance(fighter, dict):
            continue

        name = fighter.get("name")
        if not name:
            continue

        fighters_by_slug[slugify(name)] = fighter

    return fighters_by_slug


def get_fight_id(fight):
    value = fight.get("id")
    return str(value).strip() if value is not None else ""


def get_corner_name(corner):
    if isinstance(corner, dict):
        return corner.get("name") or ""
    if isinstance(corner, str):
        return corner
    return ""


def normalize_corner(corner):
    name = get_corner_name(corner)
    slug = slugify(name)

    return {
        "name": name or "Fighter",
        "slug": slug,
    }


def enrich_fighter(fighter, fighters_by_slug):
    slug = fighter.get("slug", "")
    details = fighters_by_slug.get(slug, {})

    if not isinstance(details, dict):
        details = {}

    return {
        **fighter,
        **details,
        "slug": slug,
    }


def stat_value(stats, key):
    if not isinstance(stats, dict):
        return "—"

    return html_escape(stats.get(key))


def get_recent_form(recent_fights):
    if not isinstance(recent_fights, list) or not recent_fights:
        return "—"

    form = []

    for fight in recent_fights[:10]:
        result = str(fight.get("result") or "").upper()

        if result == "WIN":
            form.append("W")
        elif result == "LOSS":
            form.append("L")
        elif result:
            form.append(result[0])
        else:
            form.append("—")

    return " ".join(form) if form else "—"


def get_finish_rate(methods):
    if not isinstance(methods, dict):
        return "—"

    ko_w = int(methods.get("ko_tko_w", 0) or 0)
    sub_w = int(methods.get("sub_w", 0) or 0)
    dec_w = int(methods.get("dec_w", 0) or 0)
    other_w = int(methods.get("other_w", 0) or 0)

    total_wins = ko_w + sub_w + dec_w + other_w
    finishes = ko_w + sub_w

    if total_wins <= 0:
        return "—"

    return f"{round((finishes / total_wins) * 100)}%"


def render_methods(methods):
    if not isinstance(methods, dict):
        methods = {}

    return f"""
      <h3 class="muted">Method Breakdown</h3>
      <table>
        <tr><td>KO/TKO</td><td>{methods.get("ko_tko_w", 0)} W • {methods.get("ko_tko_l", 0)} L</td></tr>
        <tr><td>Submission</td><td>{methods.get("sub_w", 0)} W • {methods.get("sub_l", 0)} L</td></tr>
        <tr><td>Decision</td><td>{methods.get("dec_w", 0)} W • {methods.get("dec_l", 0)} L</td></tr>
        <tr><td>Other</td><td>{methods.get("other_w", 0)} W • {methods.get("other_l", 0)} L</td></tr>
      </table>
    """


def render_recent_fights(recent_fights):
    if not isinstance(recent_fights, list) or not recent_fights:
        return """
      <h3 class="muted">Recent Fights</h3>
      <p class="muted">Recent fight history not available yet.</p>
        """

    rows = []

    for fight in recent_fights[:10]:
        result = html_escape(fight.get("result"))
        opponent = html_escape(fight.get("opponent"))
        method = html_escape(fight.get("method"))
        round_num = html_escape(fight.get("round"))
        fight_time = html_escape(fight.get("time"))
        event = html_escape(fight.get("event"))

        rows.append(
            f"""
        <div class="recent-fight">
          <strong>{result}</strong> vs {opponent}
          <div class="muted">{method} • R{round_num} • {fight_time} • {event}</div>
        </div>
            """.rstrip()
        )

    return f"""
      <h3 class="muted">Recent Fights</h3>
      <div class="recent-list">
        {"".join(rows)}
      </div>
    """


def fighter_panel(fighter):
    name = html_escape(fighter.get("name"))
    slug = fighter.get("slug", "")

    record = html_escape(fighter.get("record"))
    stance = html_escape(fighter.get("stance"))
    height = html_escape(fighter.get("height"))
    reach = html_escape(fighter.get("reach"))
    weight = html_escape(fighter.get("weight"))
    dob = html_escape(fighter.get("dob"))
    ufcstats_url = fighter.get("ufcstats_url")

    stats = fighter.get("stats") or {}
    methods = fighter.get("methods") or {}
    recent_fights = fighter.get("recent_fights") or []

    form = html_escape(get_recent_form(recent_fights))
    finish_rate = html_escape(get_finish_rate(methods))

    fighter_href = f"{BASE_PATH}/fighters/{slug}/" if slug else "#"

    ufcstats_link = ""
    if ufcstats_url:
        ufcstats_link = f'<p><a href="{html_escape(ufcstats_url)}">UFCStats profile →</a></p>'

    return f"""
    <div class="panel">
      <h2><a href="{fighter_href}">{name}</a></h2>
      {ufcstats_link}

      <div class="pillrow">
        <span class="pill">Record: {record}</span>
        <span class="pill">Weight: {weight}</span>
        <span class="pill">Stance: {stance}</span>
        <span class="pill">Height: {height}</span>
        <span class="pill">Reach: {reach}</span>
        <span class="pill">DOB: {dob}</span>
      </div>

      <div class="quick-summary">
        <div>
          <span class="muted">Recent Form</span>
          <strong>{form}</strong>
        </div>
        <div>
          <span class="muted">Finish Rate</span>
          <strong>{finish_rate}</strong>
        </div>
      </div>

      <h3 class="muted">Striking</h3>
      <table>
        <tr><td>SLpM</td><td>{stat_value(stats, "slpm")}</td></tr>
        <tr><td>Str. Acc.</td><td>{stat_value(stats, "str_acc")}</td></tr>
        <tr><td>SApM</td><td>{stat_value(stats, "sapm")}</td></tr>
        <tr><td>Str. Def.</td><td>{stat_value(stats, "str_def")}</td></tr>
      </table>

      <h3 class="muted">Grappling</h3>
      <table>
        <tr><td>TD Avg.</td><td>{stat_value(stats, "td_avg")}</td></tr>
        <tr><td>TD Acc.</td><td>{stat_value(stats, "td_acc")}</td></tr>
        <tr><td>TD Def.</td><td>{stat_value(stats, "td_def")}</td></tr>
        <tr><td>Sub. Avg.</td><td>{stat_value(stats, "sub_avg")}</td></tr>
      </table>

      {render_methods(methods)}
      {render_recent_fights(recent_fights)}
    </div>
    """


def build_fight_page(event, fight, fight_id, fighters_by_slug):
    event_slug = event.get("slug", "")
    event_name = html_escape(event.get("name", "Event"))

    red = enrich_fighter(normalize_corner(fight.get("red", {})), fighters_by_slug)
    blue = enrich_fighter(normalize_corner(fight.get("blue", {})), fighters_by_slug)

    title = f"{red.get('name', 'Fighter A')} vs {blue.get('name', 'Fighter B')}"
    weight = html_escape(fight.get("weight_class"))
    bout = html_escape(fight.get("bout"))
    status = html_escape(fight.get("status"))

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
    .panel {{
      border:1px solid var(--line);
      border-radius:12px;
      padding:14px;
      background:rgba(255,255,255,0.02);
    }}
    .pillrow {{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:10px;
    }}
    .pill {{
      border:1px solid var(--line);
      border-radius:999px;
      padding:6px 10px;
      color:var(--muted);
      font-size:13px;
    }}
    .quick-summary {{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:10px;
      margin-top:14px;
    }}
    .quick-summary div {{
      border:1px solid var(--line);
      border-radius:10px;
      padding:10px;
      background:rgba(255,255,255,0.015);
    }}
    .quick-summary span {{
      display:block;
      font-size:12px;
      margin-bottom:4px;
    }}
    .quick-summary strong {{
      font-size:18px;
    }}
    table {{
      width:100%;
      border-collapse:collapse;
      margin-top:10px;
    }}
    td, th {{
      padding:8px;
      border-bottom:1px solid var(--line);
      text-align:left;
    }}
    .recent-list {{
      display:flex;
      flex-direction:column;
      gap:8px;
      margin-top:10px;
    }}
    .recent-fight {{
      border:1px solid var(--line);
      border-radius:10px;
      padding:10px;
      background:rgba(255,255,255,0.015);
    }}
    @media (max-width: 900px) {{
      .grid {{
        grid-template-columns:1fr;
      }}
      .quick-summary {{
        grid-template-columns:1fr;
      }}
    }}
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
    <p class="muted">{weight} • {bout}</p>

    <div class="grid">
      {fighter_panel(red)}
      {fighter_panel(blue)}
    </div>

    <div class="panel" style="margin-top:14px;">
      <h2>Fight Meta</h2>
      <table>
        <tr><td>Bout</td><td>{bout}</td></tr>
        <tr><td>Weight Class</td><td>{weight}</td></tr>
        <tr><td>Status</td><td>{status}</td></tr>
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
    fighters_by_slug = load_fighter_details()

    FIGHTS_DIR.mkdir(parents=True, exist_ok=True)

    keep = FIGHTS_DIR / ".keep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")

    fights_written = 0
    missing_ids = 0

    for event in events:
        if not event.get("slug"):
            continue

        for fight in event.get("fights", []) or []:
            fight_id = get_fight_id(fight)

            if not fight_id:
                missing_ids += 1
                continue

            out_dir = FIGHTS_DIR / fight_id
            out_dir.mkdir(parents=True, exist_ok=True)

            html = build_fight_page(event, fight, fight_id, fighters_by_slug)

            (out_dir / "index.html").write_text(html, encoding="utf-8")
            fights_written += 1

    print(f"✅ Wrote {fights_written} fight pages to {FIGHTS_DIR}")

    if missing_ids:
        print(f"⚠️ Skipped {missing_ids} fights with no id key")

    if fights_written == 0:
        raise SystemExit("❌ Generated 0 fight pages. Check events.json schema.")


if __name__ == "__main__":
    main()
