import json
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

BASE_ATHLETE = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes/{}"
SEARCH_URL = "https://site.api.espn.com/apis/site/v2/search?q={}"
HEADERS = {"User-Agent": "ufc-lab-bot/1.0"}

RECENT_ENDPOINTS = [
    "https://site.web.api.espn.com/apis/common/v3/sports/mma/ufc/athletes/{}/gamelog",
    "https://site.web.api.espn.com/apis/common/v3/sports/mma/ufc/athletes/{}/eventlog",
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


def load_existing_fighters():
    if not OUT.exists():
        return {"generated_at": time.time(), "fighters": {}}

    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {"generated_at": time.time(), "fighters": {}}


def is_upcoming_event(event):
    status = str(event.get("status") or "").strip().lower()
    return status in {"upcoming", "today", "scheduled"}


def is_scheduled_fight(fight):
    status = str(fight.get("status") or "").strip().lower()
    return status in {"scheduled", "in_progress", "upcoming", ""}


def load_targets():
    """
    Returns:
      ids: set of known espn fighter ids
      names: set of fighter names that are missing ids
    """
    data = json.loads(EVENTS.read_text(encoding="utf-8"))
    ids = set()
    names = set()

    upcoming_event_count = 0
    upcoming_fight_count = 0

    for e in data.get("events", []):
        if not is_upcoming_event(e):
            continue

        upcoming_event_count += 1

        for f in e.get("fights", []):
            if not is_scheduled_fight(f):
                continue

            upcoming_fight_count += 1

            for side in ("red", "blue"):
                side_obj = f.get(side) or {}
                fid = str(side_obj.get("espn_id") or "").strip()
                name = str(side_obj.get("name") or "").strip()

                if fid:
                    ids.add(fid)
                elif name:
                    names.add(name)

    print(f"Found {upcoming_event_count} upcoming events")
    print(f"Found {upcoming_fight_count} scheduled fights")
    print(f"Found {len(ids)} unique fighter IDs from scheduled fights")
    print(f"Found {len(names)} fighter names missing IDs")

    return ids, names


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
        "ko_tko_w": 0,
        "ko_tko_l": 0,
        "sub_w": 0,
        "sub_l": 0,
        "dec_w": 0,
        "dec_l": 0,
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


def iter_dicts(obj):
    """Yield all nested dicts inside a JSON structure."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from iter_dicts(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_dicts(item)


def resolve_name_to_id(session: requests.Session, fighter_name: str):
    """
    Search ESPN by fighter name and try to find an MMA/UFC athlete id.
    """
    if not fighter_name:
        return ""

    try:
        r = session.get(SEARCH_URL.format(requests.utils.quote(fighter_name)), timeout=20)
    except Exception:
        return ""

    if r.status_code != 200:
        return ""

    try:
        data = r.json()
    except Exception:
        return ""

    target = fighter_name.strip().lower()

    exact_candidates = []
    loose_candidates = []

    for d in iter_dicts(data):
        candidate_id = str(d.get("id") or "").strip()
        candidate_name = str(d.get("displayName") or d.get("fullName") or "").strip()

        if not candidate_id or not candidate_name:
            continue

        blob = json.dumps(d, ensure_ascii=False).lower()

        score = 0
        if candidate_name.lower() == target:
            score += 100
        elif target in candidate_name.lower():
            score += 25

        if "mma" in blob or "ufc" in blob:
            score += 50

        if "athlete" in blob or "player" in blob:
            score += 10

        if score >= 100:
            exact_candidates.append((score, candidate_id, candidate_name))
        elif score > 0:
            loose_candidates.append((score, candidate_id, candidate_name))

    if exact_candidates:
        exact_candidates.sort(reverse=True)
        return exact_candidates[0][1]

    if loose_candidates:
        loose_candidates.sort(reverse=True)
        return loose_candidates[0][1]

    return ""


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

        try:
            data = r.json()
        except Exception:
            continue

        fights = []

        candidates = []
        if isinstance(data.get("events"), list):
            candidates = data["events"]
        elif isinstance(data.get("items"), list):
            candidates = data["items"]
        else:
            gl = data.get("gamelog") or data.get("eventlog") or {}
            if isinstance(gl, dict) and isinstance(gl.get("events"), list):
                candidates = gl["events"]

        for ev in candidates:
            ev = resolve(session, ev) or ev
            if not isinstance(ev, dict):
                continue

            date = ev.get("date") or ev.get("startDate") or _pick(ev, "event", "date")
            event_name = (
                ev.get("name")
                or ev.get("shortName")
                or _pick(ev, "event", "name")
                or _pick(ev, "event", "shortName")
            )

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
                competitors = comp.get("competitors")
                if isinstance(competitors, list) and competitors:
                    me = None
                    opp = None
                    for c in competitors:
                        c = resolve(session, c) or c
                        if str(c.get("id") or "") == fid or str(_pick(c, "athlete", "id") or "") == fid:
                            me = c
                        else:
                            opp = c

                    if opp:
                        opponent = (
                            _pick(opp, "athlete", "displayName")
                            or _pick(opp, "athlete", "fullName")
                            or opp.get("displayName")
                        )

                    if me:
                        winner = me.get("winner")
                        outc = me.get("outcome") or me.get("result")
                        if isinstance(outc, dict):
                            result = outc.get("type") or outc.get("displayValue")
                        elif isinstance(outc, str):
                            result = outc
                        elif isinstance(winner, bool):
                            result = "W" if winner else "L"

                method = (
                    _pick(comp, "status", "type", "detail")
                    or _pick(comp, "status", "result")
                    or _pick(comp, "status", "type", "name")
                )
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

    existing = load_existing_fighters()

    s = requests.Session()
    s.headers.update(HEADERS)

    ids, missing_names = load_targets()

    resolved_names = 0
    for name in sorted(missing_names):
        fid = resolve_name_to_id(s, name)
        if fid:
            ids.add(fid)
            resolved_names += 1
        time.sleep(0.15)

    print(f"Resolved {resolved_names}/{len(missing_names)} missing fighter names to ESPN IDs")

    ids = sorted(ids)

    out = {
        "generated_at": time.time(),
        "fighters": existing.get("fighters", {}).copy(),
    }

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

        try:
            p = r.json()
        except Exception:
            print("⚠️", fid, "invalid JSON")
            continue

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
        time.sleep(0.20)

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n🔥 Updated {ok} fighters in {OUT}")
    print(f"🔥 Total fighters stored: {len(out['fighters'])}")


if __name__ == "__main__":
    main()
