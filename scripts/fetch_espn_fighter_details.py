import json, time, requests
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

BASE = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes/{}"
HEADERS = {"User-Agent": "ufc-lab-bot/1.0"}


def resolve(session, obj):
    """Resolve ESPN core $ref objects."""
    if isinstance(obj, dict) and "$ref" in obj and isinstance(obj["$ref"], str):
        r = session.get(obj["$ref"])
        if r.status_code == 200:
            return r.json()
        return None
    return obj


def inches_to_cm(x):
    try:
        if x is None:
            return None
        return round(float(x) * 2.54, 1)
    except:
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


def stats_list_to_dict(item):
    """
    ESPN record items often have:
      "stats": [{"name":"wins","value":26}, {"name":"losses","value":4}, ...]
    Convert to dict.
    """
    out = {}
    if not isinstance(item, dict):
        return out
    stats = item.get("stats")
    if isinstance(stats, list):
        for s in stats:
            if isinstance(s, dict) and "name" in s:
                out[s["name"]] = s.get("value")
    return out


def extract_records(session, athlete_payload):
    """
    athlete_payload["records"] resolves to a container with items refs.
    We resolve each item and try to extract:
      - overall summary (record string)
      - method breakdowns (ko/sub/dec) if present
    """
    records_container = resolve(session, athlete_payload.get("records"))
    if not isinstance(records_container, dict):
        return None, {}, records_container

    items = records_container.get("items")
    if not isinstance(items, list):
        return None, {}, records_container

    overall_summary = None
    methods = {
        "ko_tko_w": 0, "ko_tko_l": 0,
        "sub_w": 0, "sub_l": 0,
        "dec_w": 0, "dec_l": 0,
    }

    # Try resolve each record item
    resolved_items = []
    for it in items:
        rit = resolve(session, it)  # item might be a $ref or already expanded
        if isinstance(rit, dict):
            resolved_items.append(rit)

    # 1) Find "overall"
    for rit in resolved_items:
        name = (rit.get("name") or "").lower()
        if name == "overall":
            # Many shapes: summary/displayValue, or computed from stats
            overall_summary = rit.get("summary") or rit.get("displayValue")
            if not overall_summary:
                sd = stats_list_to_dict(rit)
                w = sd.get("wins")
                l = sd.get("losses")
                d = sd.get("draws") or sd.get("ties")
                if w is not None and l is not None:
                    overall_summary = f"{w}-{l}" + (f"-{d}" if d is not None else "")
            break

    # 2) Method splits (if ESPN provides them as separate record items)
    # Names vary; we match loosely.
    def apply_method(key_prefix, rit):
        sd = stats_list_to_dict(rit)
        w = sd.get("wins") or 0
        l = sd.get("losses") or 0
        methods[f"{key_prefix}_w"] = int(w) if w is not None else 0
        methods[f"{key_prefix}_l"] = int(l) if l is not None else 0

    for rit in resolved_items:
        nm = (rit.get("name") or "").lower()

        # Common possibilities: "knockouts", "ko/tko", "tko/ko"
        if "ko" in nm or "tko" in nm or "knock" in nm:
            apply_method("ko_tko", rit)

        # "submissions", "submission"
        if "sub" in nm:
            apply_method("sub", rit)

        # "decisions", "decision"
        if "dec" in nm or "decision" in nm:
            apply_method("dec", rit)

    return overall_summary, methods, records_container


def main():
    ids = load_ids()
    out = {"generated_at": time.time(), "fighters": {}}

    s = requests.Session()
    s.headers.update(HEADERS)

    ok = 0

    for i, fid in enumerate(ids, 1):
        url = BASE.format(fid)
        r = s.get(url, timeout=20)

        if r.status_code != 200:
            print("⚠️", fid, r.status_code)
            continue

        p = r.json()

        # Resolve top-level refs we care about (statistics stays as ref for now)
        statistics_ref = p.get("statistics")  # keep ref (or resolve later)
        overall_record, methods, records_container = extract_records(s, p)

        fighter = {
            "name": p.get("displayName"),
            "nickname": p.get("nickname"),
            # ESPN core height/reach are INCHES → convert to cm
            "height_cm": inches_to_cm(p.get("height")),
            "reach_cm": inches_to_cm(p.get("reach")),
            "stance": (p.get("stance") or {}).get("text"),
            "country": p.get("citizenship"),
            "weight_class": (p.get("weightClass") or {}).get("text"),
            "record": overall_record,
            "methods": methods,
            "raw": {
                "statistics": statistics_ref,     # keep as ref for later parsing
                "records": records_container      # container w/ items already expanded
            }
        }

        out["fighters"][fid] = fighter
        ok += 1
        print(f"✅ {i}/{len(ids)} {fighter.get('name','')} | record={fighter.get('record')}")
        time.sleep(0.25)

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n🔥 Wrote {ok} fighters to {OUT}")


if __name__ == "__main__":
    main()
