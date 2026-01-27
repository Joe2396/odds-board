import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

BASE = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes/{}"
HEADERS = {"User-Agent": "ufc-lab-bot/1.0"}


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


def compute_methods_from_overall_stats(overall_item: dict) -> dict:
    """
    ESPN puts method counts inside the overall record item stats, e.g.
      "tkos": 13, "tkoLosses": 3, "submissions": 3, "submissionLosses": 0, etc.

    We compute:
      KO/TKO wins = tkos + kos
      SUB wins    = submissions
      DEC wins    = wins - KO - SUB (fallback)

      KO/TKO losses = tkoLosses + koLosses
      SUB losses    = submissionLosses
      DEC losses    = losses - KO - SUB (fallback)
    """
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
    """
    athlete_payload["records"] resolves to a container with items refs.
    We resolve each item and return:
      - overall summary record string
      - methods dict (computed from overall stats list)
      - records_container (with items resolved)
    """
    records_container = resolve(session, athlete_payload.get("records"))
    if not isinstance(records_container, dict):
        return None, {}, records_container

    items = records_container.get("items")
    if not isinstance(items, list):
        return None, {}, records_container

    # Resolve each item ($ref) into the actual record objects
    resolved_items = []
    for it in items:
        rit = resolve(session, it)
        if isinstance(rit, dict):
            resolved_items.append(rit)

    # Overwrite container items with resolved items (helpful for debugging)
    records_container["items"] = resolved_items

    overall_item = None
    for rit in resolved_items:
        if (rit.get("name") or "").lower() == "overall":
            overall_item = rit
            break

    overall_summary = None
    if isinstance(overall_item, dict):
        overall_summary = overall_item.get("summary") or overall_item.get("displayValue")

        # fallback compute from wins/losses/draws
        if not overall_summary:
            sd = stats_list_to_dict(overall_item)
            w = sd.get("wins")
            l = sd.get("losses")
            d = sd.get("draws") or sd.get("ties")
            if w is not None and l is not None:
                overall_summary = f"{int(w)}-{int(l)}" + (f"-{int(d)}" if d is not None else "")

    methods = compute_methods_from_overall_stats(overall_item)

    return overall_summary, methods, records_container


def main():
    if not EVENTS.exists():
        raise SystemExit(f"Missing {EVENTS}")

    ids = load_ids()
    out = {"generated_at": time.time(), "fighters": {}}

    s = requests.Session()
    s.headers.update(HEADERS)

    ok = 0

    for i, fid in enumerate(ids, 1):
        url = BASE.format(fid)
        try:
            r = s.get(url, timeout=20)
        except Exception as e:
            print(f"⚠️ {fid}: request failed: {e}")
            continue

        if r.status_code != 200:
            print("⚠️", fid, f"HTTP {r.status_code}")
            continue

        p = r.json()

        # Keep statistics as a ref for later (we'll parse it in a future step)
        statistics_ref = p.get("statistics")

        record_summary, methods, records_container = extract_records(s, p)

        fighter = {
            "name": p.get("displayName"),
            "nickname": p.get("nickname"),
            # ESPN core height/reach are inches -> convert to cm
            "height_cm": inches_to_cm(p.get("height")),
            "reach_cm": inches_to_cm(p.get("reach")),
            "stance": (p.get("stance") or {}).get("text"),
            "country": p.get("citizenship"),
            "weight_class": (p.get("weightClass") or {}).get("text"),
            "record": record_summary,
            "methods": methods,
            "raw": {
                "statistics": statistics_ref,
                "records": records_container,
            },
        }

        out["fighters"][str(fid)] = fighter
        ok += 1
        print(f"✅ {i}/{len(ids)} {fighter.get('name','')} | record={fighter.get('record')}")

        time.sleep(0.25)

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n🔥 Wrote {ok} fighters to {OUT}")


if __name__ == "__main__":
    main()
