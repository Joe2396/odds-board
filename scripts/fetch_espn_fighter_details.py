import json
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

BASE_ATHLETE = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes/{}"
HEADERS = {"User-Agent": "ufc-lab-bot/1.0"}

# Try a couple "recent fights" endpoints (ESPN uses different shapes depending on sport/product)
RECENT_ENDPOINTS = [
    # Sometimes exists for athletes (common API family used by fightcenter)
    "https://site.web.api.espn.com/apis/common/v3/sports/mma/ufc/athletes/{}/gamelog",
    "https://site.web.api.espn.com/apis/common/v3/sports/mma/ufc/athletes/{}/eventlog",
    # Core API sometimes exposes per-athlete events/eventlog
    "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes/{}/events?limit=10",
    "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes/{}/eventlog?limit=10",
]

def resolve(session: requests.Session, obj):
    """Resolve ESPN core $ref objects."""
    if isinstance(obj, dict) and "$ref" in obj and isinstance(obj["$ref"], str):
        try:
            r = session.get(obj["$ref"], timeout=20)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None
    return obj

def inches_to_cm(x):
    try:
        if x is None:
            return None
        return round(float(x) * 2.54, 1)
    except Exception:
        return None

def load_ids():
    data = json.loads(EVENTS.read_text(encoding="utf-8"))
    ids = set()
    for e in data.get("events", []):
        for f in e.get("fights", []):
            for side in ("red", "blue"):
                v = (f.get(side) or {}).get("espn_id")
                if v:
                    ids.add(str(v).strip())
    return sorted(ids)

def stats_list_to_dict(item: dict) -> dict:
    out = {}
    if not isinstance(item, dict):
        return out
    stats = item.get("stats")
    if isinstance(stats, list):
        for s in stats:
            if isinstance(s, dict) and "name" in s:
                out[s["name"]] = s.get("value")
    return out

def compute_methods_from_overall_stats(overall_item: dict) -> dict:
    methods = {
        "ko_tko_w": 0, "ko_tko_l": 0,
        "sub_w": 0, "sub_l": 0,
        "dec_w": 0, "dec_l": 0,
    }
    if not isinstance(overall_item, dict):
        return methods

    stats = stats_list_to_dict(overall_item)
    wins = int(stats.get("wins") or 0)
    losses = int(stats.get("losses") or 0)

    ko_w = int((stats.get("tkos") or 0) + (stats.get("kos") or 0))
    sub_w = int(stats.get("submissions") or 0)
    ko_l = int((stats.get("tkoLosses") or 0) + (stats.get("koLosses") or 0))
    sub_l = int(stats.get("submissionLosses") or 0)

    dec_w = max(0, wins - ko_w - sub_w)
    dec_l = max(0, losses - ko_l - sub_l)

    methods["ko_tko_w"] = ko_w
    methods["sub_w"] = sub_w
    methods["dec_w"] = dec_w
    methods["ko_tko_l"] = ko_l
    methods["sub_l"] = sub_l
    methods["dec_l"] = dec_l
    return methods

def extract_records(session: requests.Session, athlete_payload: dict):
    records_container = resolve(session, athlete_payload.get("records"))
    if not isinstance(records_container, dict):
        return None, {}, records_container

    items = records_container.get("items")
    if not isinstance(items, list):
        return None, {}, records_container

    resolved_items = []
    for it in items:
        rit = resolve(session, it)
        if isinstance(rit, dict):
            resolved_items.append(rit)

    records_container["items"] = resolved_items

    overall_item = None
    for rit in resolved_items:
        if (rit.get("name") or "").lower() == "overall":
            overall_item = rit
            break

    overall_summary = None
    if isinstance(overall_item, dict):
        overall_summary = overall_item.get("summary") or overall_item.get("displayValue")

    methods = compute_methods_from_overall_stats(overall_item)
    return overall_summary, methods, records_container

def _pick(d, *keys):
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur

def fetch_recent_fights(session: requests.Session, fid: str, limit: int = 10):
    """
    Return a list of dicts:
      [{"date":"YYYY-MM-DD", "opponent":"...", "result":"W/L/D", "method":"DEC/KO/SUB", "round":"", "time":"", "event":"..."}]
    """
    fid = str(fid).strip()
    for tmpl in RECENT_ENDPOINTS:
        url = tmpl.format(fid)
        try:
            r = session.get(url, timeout=20)
        except Exception:
            continue
        if r.status_code != 200:
            continue

        data = r.json()
        fights = []

        # Common patterns we might see:
        # - data["events"] list
        # - data["items"] list
        # - data["gamelog"]["events"] etc
        candidates = []
        if isinstance(data.get("events"), list):
            candidates = data["events"]
        elif isinstance(data.get("items"), list):
            candidates = data["items"]
        else:
            # try nested possibilities
            gl = data.get("gamelog") or data.get("eventlog") or {}
            if isinstance(gl, dict) and isinstance(gl.get("events"), list):
                candidates = gl["events"]

        # Try to normalize each entry
        for ev in candidates:
            # Some entries are $ref objects
            ev = resolve(session, ev) or ev
            if not isinstance(ev, dict):
                continue

            # Try to find opponent/result fields (varies by shape)
            date = ev.get("date") or ev.get("startDate") or _pick(ev, "event", "date")
            event_name = ev.get("name") or ev.get("shortName") or _pick(ev, "event", "name") or _pick(ev, "event", "shortName")

            # competition / competitors
            opponent = None
            result = None
            method = None
            rnd = None
            tme = None

            comp = None
            if isinstance(ev.get("competition"), dict):
                comp = ev["competition"]
            elif isinstance(ev.get("competitions"), list) and ev["competitions"]:
                comp = ev["competitions"][0]

            if isinstance(comp, dict):
                # attempt competitors list
                competitors = comp.get("competitors")
                if isinstance(competitors, list) and competitors:
                    # find "me" by athlete id
                    me = None
                    opp = None
                    for c in competitors:
                        c = resolve(session, c) or c
                        cid = str(_pick(c, "athlete", "id") or _pick(c, "athlete", "$ref") or "")
                        # cid matching is hard; prefer explicit id field if present
                        if str(c.get("id") or "") == fid or str(_pick(c, "athlete", "id") or "") == fid:
                            me = c
                        else:
                            opp = c

                    if opp:
                        opponent = _pick(opp, "athlete", "displayName") or _pick(opp, "athlete", "fullName") or opp.get("displayName")

                    # outcome fields
                    if me:
                        winner = me.get("winner")
                        # some shapes: outcome -> "W"/"L"
                        outc = me.get("outcome") or me.get("result")
                        if isinstance(outc, dict):
                            result = outc.get("type") or outc.get("displayValue")
                        elif isinstance(outc, str):
                            result = outc
                        elif isinstance(winner, bool):
                            result = "W" if winner else "L"

                # method / round / time (if present)
                method = _pick(comp, "status", "type", "detail") or _pick(comp, "status", "result") or _pick(comp, "status", "type", "name")
                rnd = _pick(comp, "status", "period") or _pick(comp, "status", "periods")
                tme = _pick(comp, "status", "displayClock") or _pick(comp, "status", "clock")

            fights.append({
                "date": date,
                "event": event_name,
                "opponent": opponent,
                "result": result,
                "method": method,
                "round": rnd,
                "time": tme,
            })

            if len(fights) >= limit:
                break

        if fights:
            return fights[:limit]

    return []

def main():
    if not EVENTS.exists():
        raise SystemExit(f"Missing {EVENTS}")

    ids = load_ids()
    out = {"generated_at": time.time(), "fighters": {}}

    s = requests.Session()
    s.headers.update(HEADERS)

    ok = 0
    for i, fid in enumerate(ids, 1):
        url = BASE_ATHLETE.format(fid)
        try:
            r = s.get(url, timeout=20)
        except Exception as e:
            print(f"⚠️ {fid}: request failed: {e}")
            continue

        if r.status_code != 200:
            print("⚠️", fid, f"HTTP {r.status_code}")
            continue

        p = r.json()

        record_summary, methods, records_container = extract_records(s, p)

        recent = fetch_recent_fights(s, fid, limit=10)

        fighter = {
            "name": p.get("displayName"),
            "nickname": p.get("nickname"),
            "height_cm": inches_to_cm(p.get("height")),
            "reach_cm": inches_to_cm(p.get("reach")),
            "stance": (p.get("stance") or {}).get("text"),
            "country": p.get("citizenship"),
            "weight_class": (p.get("weightClass") or {}).get("text"),
            "record": record_summary,
            "methods": methods,
            "recent_fights": recent,
            "raw": {
                "statistics": p.get("statistics"),
                "records": records_container,
            },
        }

        out["fighters"][str(fid)] = fighter
        ok += 1
        print(f"✅ {i}/{len(ids)} {fighter.get('name','')} | recent={len(recent)}")
        time.sleep(0.25)

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n🔥 Wrote {ok} fighters to {OUT}")

if __name__ == "__main__":
    main()
