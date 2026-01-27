import json, time, requests
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

BASE = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes/{}"
HEADERS = {"User-Agent": "ufc-lab-bot/1.0"}


def resolve(session, obj):
    if isinstance(obj, dict) and "$ref" in obj:
        r = session.get(obj["$ref"])
        if r.status_code == 200:
            return r.json()
    return obj


def load_ids():
    data = json.loads(EVENTS.read_text())
    ids = set()
    for e in data.get("events", []):
        for f in e.get("fights", []):
            for side in ("red", "blue"):
                v = f.get(side, {}).get("espn_id")
                if v:
                    ids.add(str(v))
    return sorted(ids)


def main():
    ids = load_ids()
    out = {"generated_at": time.time(), "fighters": {}}

    s = requests.Session()
    s.headers.update(HEADERS)

    ok = 0

    for i, fid in enumerate(ids, 1):
        url = BASE.format(fid)
        r = s.get(url)

        if r.status_code != 200:
            print("⚠️", fid, r.status_code)
            continue

        p = r.json()

        stats = resolve(s, p.get("statistics"))
        records = resolve(s, p.get("records"))

        fighter = {
            "name": p.get("displayName"),
            "nickname": p.get("nickname"),
            "height_cm": p.get("height"),
            "reach_cm": p.get("reach"),
            "stance": (p.get("stance") or {}).get("text"),
            "country": p.get("citizenship"),
            "record": (records or {}).get("summary"),
            "raw": {
                "statistics": stats,
                "records": records
            }
        }

        out["fighters"][fid] = fighter
        ok += 1
        print(f"✅ {i}/{len(ids)} {fighter['name']}")
        time.sleep(0.25)

    OUT.write_text(json.dumps(out, indent=2))
    print(f"\n🔥 Wrote {ok} fighters to {OUT}")


if __name__ == "__main__":
    main()
