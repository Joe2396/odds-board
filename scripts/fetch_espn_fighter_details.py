import json
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (ufc-lab-bot)"}

# ESPN athlete endpoint (works for many sports; MMA can vary but this is the correct starting point)
URL = "https://site.web.api.espn.com/apis/v2/sports/mma/ufc/athletes/{athlete_id}"


def load_events():
    data = json.loads(EVENTS.read_text(encoding="utf-8"))
    return data.get("events", [])


def collect_espn_ids(events):
    ids = set()
    for ev in events:
        for fight in ev.get("fights", []):
            for corner in ("red", "blue"):
                c = fight.get(corner) or {}
                espn_id = str(c.get("espn_id") or "").strip()
                if espn_id:
                    ids.add(espn_id)
    return sorted(ids)


def safe_get(d, *keys):
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def parse_payload(payload: dict) -> dict:
    # ESPN sometimes wraps in athlete, sometimes not
    athlete = payload.get("athlete") if isinstance(payload.get("athlete"), dict) else payload

    name = athlete.get("displayName") or athlete.get("fullName") or ""

    # record can appear in multiple shapes
    record = safe_get(athlete, "record", "displayValue")
    if not record:
        recs = athlete.get("records")
        if isinstance(recs, list) and recs:
            record = recs[0].get("summary") or recs[0].get("displayValue")

    stance = athlete.get("stance") or ""

    # measurements can vary
    height = athlete.get("height") or safe_get(athlete, "measurements", "height")
    reach = athlete.get("reach") or safe_get(athlete, "measurements", "reach")
    country = safe_get(athlete, "birthPlace", "country") or athlete.get("citizenship") or ""

    return {
        "name": name,
        "record": record or "",
        "stance": stance or "",
        "height": height,
        "reach": reach,
        "country": country or "",
    }


def main():
    if not EVENTS.exists():
        raise SystemExit(f"Missing {EVENTS}")

    events = load_events()
    ids = collect_espn_ids(events)

    OUT.parent.mkdir(parents=True, exist_ok=True)

    out = {"generated_at": time.time(), "fighters": {}}

    s = requests.Session()
    s.headers.update(HEADERS)

    ok = 0
    for i, athlete_id in enumerate(ids, start=1):
        try:
            r = s.get(URL.format(athlete_id=athlete_id), timeout=20)
            if r.status_code != 200:
                print(f"⚠️ {athlete_id}: HTTP {r.status_code}")
                continue
            payload = r.json()
            out["fighters"][athlete_id] = parse_payload(payload)
            ok += 1
            print(f"✅ {i}/{len(ids)} {athlete_id}: {out['fighters'][athlete_id].get('name','')}")
        except Exception as e:
            print(f"⚠️ {athlete_id}: {e}")

        time.sleep(0.25)  # be polite

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"✅ Wrote {ok} fighters to {OUT}")


if __name__ == "__main__":
    main()
