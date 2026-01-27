import json
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

# NOTE: ESPN has multiple JSON endpoints. This is a common pattern:
# If this exact URL doesn’t return JSON in your environment, we’ll adjust it based on what your event fetch already uses.
ESPN_ATHLETE_URL = "https://site.web.api.espn.com/apis/v2/sports/mma/ufc/athletes/{athlete_id}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ufc-lab-bot/1.0)"
}

def load_events():
    data = json.loads(EVENTS.read_text(encoding="utf-8"))
    return data.get("events", [])

def collect_espn_ids(events):
    ids = set()
    for ev in events:
        for fight in ev.get("fights", []):
            for corner in ("red", "blue"):
                c = fight.get(corner) or {}
                athlete_id = str(c.get("espn_id") or "").strip()
                if athlete_id:
                    ids.add(athlete_id)
    return sorted(ids)

def safe_get(d, *keys):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur

def parse_athlete(payload: dict) -> dict:
    """
    ESPN payloads vary. We store what we can safely extract.
    You can expand this once we confirm exact field names from your responses.
    """
    athlete = payload.get("athlete") if isinstance(payload.get("athlete"), dict) else payload

    name = safe_get(athlete, "displayName") or safe_get(athlete, "fullName") or ""
    # Common measurement locations differ; keep flexible
    height = safe_get(athlete, "height") or safe_get(athlete, "measurements", "height")
    weight = safe_get(athlete, "weight") or safe_get(athlete, "measurements", "weight")
    reach = safe_get(athlete, "reach") or safe_get(athlete, "measurements", "reach")
    stance = safe_get(athlete, "stance") or safe_get(athlete, "batting", "stance")  # may be None
    record = safe_get(athlete, "record", "displayValue") or safe_get(athlete, "records", 0, "summary")

    return {
        "name": name,
        "record": record or "",
        "height": height,
        "weight": weight,
        "reach": reach,
        "stance": stance or "",
        "raw": None,  # set to athlete if you want to debug
    }

def main():
    if not EVENTS.exists():
        raise SystemExit(f"Missing {EVENTS}")

    events = load_events()
    ids = collect_espn_ids(events)

    OUT.parent.mkdir(parents=True, exist_ok=True)

    out = {
        "generated_at": time.time(),
        "fighters": {}
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    for i, athlete_id in enumerate(ids, start=1):
        url = ESPN_ATHLETE_URL.format(athlete_id=athlete_id)
        try:
            r = session.get(url, timeout=20)
            if r.status_code != 200:
                print(f"⚠️ {athlete_id}: HTTP {r.status_code}")
                continue
            payload = r.json()
            parsed = parse_athlete(payload)
            out["fighters"][athlete_id] = parsed
            print(f"✅ {i}/{len(ids)} {athlete_id}: {parsed.get('name')}")
        except Exception as e:
            print(f"⚠️ {athlete_id}: {e}")

        time.sleep(0.25)  # light throttling

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"✅ Wrote {len(out['fighters'])} fighters to {OUT}")

if __name__ == "__main__":
    main()
