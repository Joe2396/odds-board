import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ufc" / "data" / "events.json"
FIGHTS_DIR = ROOT / "ufc" / "fights"

# NEW: stats file produced by your fetch step
FIGHTERS_JSON = ROOT / "ufc" / "data" / "fighters.json"

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


def load_fighter_details():
    """
    Expected-ish shape:
      {"fighters": {"3949584": {...}, "4881999": {...}}}
    Returns: dict keyed by espn_id (string)
    """
    if not FIGHTERS_JSON.exists():
        return {}
    data = json.loads(FIGHTERS_JSON.read_text(encoding="utf-8"))
    fighters = data.get("fighters", {})
    return fighters if isinstance(fighters, dict) else {}


def pick_first(d: dict, keys: list):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, "", []):
            return d[k]
    return None


def normalize_height_to_cm(v):
    """
    Best-effort normalizer:
    - if already numeric, assume cm when >= 120 else unknown
    - if string like '5\'6"' or '5-6' etc, we won't parse here (keep raw)
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        # assume cm if plausible
        return float(v)
    # keep as-is (string) for display elsewhere; our UI expects cm numeric so we'll return None
    return None


def normalize_reach_to_cm(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def get_fight_id(fight: dict) -> str:
    v = fight.get("id")
    return str(v).strip() if v is not None else ""


def normalize_fighter_from_corner(corner: dict) -> dict:
    """
    Convert corner object:
      {"name":"...", "espn_id":"..."}
    to the richer shape expected by fighter_panel.
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
        "methods": {},
        "quick": {},
        "espn_id": str(espn_id).strip() if espn_id is not None else "",
    }


def enrich_fighter(f: dict, details_by_espn: dict) -> dict:
    """
    Merge stats from fighters.json into our UI fighter object.
    Tries multiple possible field names.
    """
    espn_id = str(f.get("espn_id", "")).strip()
    if not espn_id or espn_id not in details_by_espn:
        return f

    d = details_by_espn.get(espn_id, {}) or {}
    if not isinstance(d, dict):
        return f

    # Prefer ESPN-returned name if present
    name = pick_first(d, ["name", "displayName", "fullName"])
    if name:
        f["name"] = name
        f["slug"] = f.get("slug") or slugify(name)

    # Record / stance / country
    rec = pick_first(d, ["record", "summary", "record_display", "recordSummary"])
    if rec:
        f["record"] = rec

    stance = pick_first(d, ["stance", "fightingStance"])
    if stance:
        f["stance"] = stance

    country = pick_first(d, ["country", "nationality"])
    if country:
        f["country"] = country

    # Height/reach (try multiple keys)
    height_val = pick_first(d, ["height_cm", "heightCm", "height", "heightCM"])
    reach_val = pick_first(d, ["reach_cm", "reachCm", "reach", "reachCM"])

    # If height/reach come in as numbers, populate our cm fields
    f["height_cm"] = normalize_height_to_cm(height_val) if height_val is not None else f.get("height_cm")
    f["reach_cm"] = normalize_reach_to_cm(reach_val) if reach_val is not None else f.get("reach_cm")

    # Optional: if your fighters.json later includes these, they'll render automatically
    if isinstance(d.get("methods"), dict):
        f["methods"] = d["methods"]
    if isinstance(d.get("quick"), dict):
        f["quick"] = d["quick"]

    return f


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
        <span class="pill">Height: {html_escape(str(int(h)) + " cm") if isinstance(h,(int,float)) else ("—")}</span>
        <span class="pill">Reach: {html_escape(str(int(r)) + " cm") if isinstance(r,(int,float)) else ("—")}</span>
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


def build_fight_page(event: dict, fight: dict, fight_id: str, details_by_espn: dict) -> str:
    event_slug = event.get("slug", "")
    event_name = html_escape(event.get("name", "Event"))

    red = normalize_fighter_from_corner(fight.get("red", {}))
    blue = normalize_fighter_from_corner(fight.get("blue", {}))

    # NEW: enrich with fighters.json data
    red = enrich_fighter(red, details_by_espn)
    blue = enrich_fighter(blue, details_by_espn)

    title = f"{red.get('name','Fighter A')} vs {blue.get('name','Fighter B')}"
    weight = html_escape(fight.get("weight_class", "—"))
    rounds = "—"  # not present in your schema yet

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
    details_by_espn = load_fighter_details()

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
            out_file.write_text(build_fight_page(event, fight, fight_id, details_by_espn), encoding="utf-8")
            fights_written += 1

    print(f"✅ Wrote {fights_written} fight pages to {FIGHTS_DIR}")
    if missing_ids:
        print(f"⚠️ Skipped {missing_ids} fights with no id key")

    if fights_written == 0:
        raise SystemExit("❌ Generated 0 fight pages. Check events.json schema.")


if __name__ == "__main__":
    main()
