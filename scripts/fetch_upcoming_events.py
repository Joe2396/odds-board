#!/usr/bin/env python3
"""
Fetch upcoming UFC events + fight cards using ESPN APIs (GitHub Actions friendly).

Writes:
  ufc/data/events.json
  ufc/data/source_cache.json

Strategy:
  1) Pull upcoming events from ESPN scoreboard endpoint
  2) For each event, try to fetch event detail from ESPN Core API
  3) From event detail, resolve competitions (bouts) and extract competitors (fighters)
  4) Populate fights[] under each event
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, date
from urllib.request import Request, urlopen
from urllib.parse import urljoin

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "ufc", "data")
EVENTS_PATH = os.path.join(DATA_DIR, "events.json")
CACHE_PATH = os.path.join(DATA_DIR, "source_cache.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (odds-board-bot)",
    "Accept": "application/json, text/plain, */*",
}

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
ESPN_CORE_EVENT = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/{event_id}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_get(url: str, timeout: int = 25) -> tuple[int, str]:
    try:
        req = Request(url, headers=HEADERS, method="GET")
        with urlopen(req, timeout=timeout) as r:
            status = getattr(r, "status", 200)
            return status, r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        # urllib exceptions vary; capture as best-effort
        status = getattr(e, "code", 0) if hasattr(e, "code") else 0
        return status, str(e)


def safe_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def slugify(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "event"


def iso_date_from_espn(dt_str: str) -> str | None:
    if not dt_str:
        return None
    ds = str(dt_str).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ds).date().isoformat()
    except Exception:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(dt_str))
        return m.group(1) if m else None


def pick_event_location(ev: dict) -> str:
    # Best-effort: ESPN sometimes provides venue/address under competitions[0].venue
    comps = ev.get("competitions") or []
    if isinstance(comps, list) and comps:
        venue = comps[0].get("venue") or {}
        name = venue.get("fullName") or venue.get("name") or ""
        addr = venue.get("address") or {}
        parts = [addr.get("city"), addr.get("state"), addr.get("country")]
        parts = [p for p in parts if p]
        if name and parts:
            return ", ".join([name] + parts)
        if name:
            return name
        if parts:
            return ", ".join(parts)
    return ""


def find_core_api_url_from_links(ev: dict) -> str | None:
    # ESPN site API sometimes includes links with hrefs. We try to find an API-ish href.
    links = ev.get("links")
    if not isinstance(links, list):
        return None

    # Look for a rel that hints API or self
    for link in links:
        href = link.get("href")
        if not href:
            continue
        # Prefer core API URLs
        if "sports.core.api.espn.com" in href:
            return href
    return None


def ref_url(obj) -> str | None:
    # Core API uses {"$ref": "..."} or {"ref": "..."} sometimes.
    if isinstance(obj, dict):
        return obj.get("$ref") or obj.get("ref") or obj.get("href")
    if isinstance(obj, str):
        return obj
    return None


def get_display_name_from_athlete_ref(athlete_ref: str, cache: dict) -> tuple[str, str]:
    """
    Returns (name, athlete_id). Tries to avoid extra requests if possible,
    but core API usually requires resolving the athlete ref.
    """
    athlete_id = ""
    m = re.search(r"/athletes/(\d+)", athlete_ref)
    if m:
        athlete_id = m.group(1)

    status, body = http_get(athlete_ref)
    cache["requests"].append({"url": athlete_ref, "status": status, "preview": body[:200]})
    data = safe_json(body) if status == 200 else None

    if isinstance(data, dict):
        name = data.get("displayName") or data.get("shortName") or data.get("fullName") or ""
        if not athlete_id:
            athlete_id = str(data.get("id") or "")
        return name, athlete_id

    return "", athlete_id


def extract_weight_class_text(comp: dict) -> str:
    # Best-effort. ESPN varies; sometimes comp["type"]["text"] or comp["notes"] etc.
    t = comp.get("type")
    if isinstance(t, dict):
        txt = t.get("text") or t.get("abbreviation") or ""
        if txt:
            return txt

    notes = comp.get("notes")
    if isinstance(notes, list) and notes:
        # sometimes contains objects with "headline"/"type"
        for n in notes:
            if isinstance(n, dict):
                for k in ("headline", "type", "text"):
                    v = n.get(k)
                    if isinstance(v, str) and v:
                        return v
    return ""


def build_fights_for_event(event_id: str, cache: dict) -> list[dict]:
    """
    Uses ESPN core API to resolve event -> competitions -> competitors -> athlete names.
    Returns fights[] list.
    """
    fights: list[dict] = []

    core_url = ESPN_CORE_EVENT.format(event_id=event_id)
    status, body = http_get(core_url)
    cache["requests"].append({"url": core_url, "status": status, "preview": body[:200]})
    if status != 200:
        return fights

    ev_detail = safe_json(body)
    if not isinstance(ev_detail, dict):
        return fights

    competitions = ev_detail.get("competitions") or []
    # Core API competitions can be list of refs or dicts
    comp_refs = []
    if isinstance(competitions, list):
        for c in competitions:
            u = ref_url(c)
            if u:
                comp_refs.append(u)

    # If competitions are embedded directly
    embedded = []
    if isinstance(competitions, list) and competitions and isinstance(competitions[0], dict) and "competitors" in competitions[0]:
        embedded = competitions

    # Resolve comps (limit to avoid excessive requests)
    comps_data = []
    if embedded:
        comps_data = embedded
    else:
        for u in comp_refs[:30]:
            s, b = http_get(u)
            cache["requests"].append({"url": u, "status": s, "preview": b[:200]})
            if s == 200:
                d = safe_json(b)
                if isinstance(d, dict):
                    comps_data.append(d)

    # Parse each competition as a fight
    order = 0
    for comp in comps_data:
        competitors = comp.get("competitors") or []
        if not (isinstance(competitors, list) and len(competitors) >= 2):
            continue

        # For MMA, typically two competitors. Sometimes "home"/"away" ordering exists.
        # We'll sort by "order" if present, else keep as-is.
        def comp_key(x):
            try:
                return int(x.get("order", 9999))
            except Exception:
                return 9999

        competitors_sorted = sorted([c for c in competitors if isinstance(c, dict)], key=comp_key)

        # Try to map to red/blue using home/away if present
        home = next((c for c in competitors_sorted if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors_sorted if c.get("homeAway") == "away"), None)

        a = away or competitors_sorted[0]
        b = home or competitors_sorted[1]

        def competitor_name_and_id(c: dict) -> tuple[str, str]:
            athlete = c.get("athlete")
            # If embedded athlete object has displayName, use it
            if isinstance(athlete, dict):
                name = athlete.get("displayName") or athlete.get("shortName") or athlete.get("fullName") or ""
                aid = str(athlete.get("id") or "")
                ref = ref_url(athlete)
                if not name and ref:
                    name, aid2 = get_display_name_from_athlete_ref(ref, cache)
                    return name, aid2 or aid
                return name, aid
            # If it's a ref dict/string
            ref = ref_url(athlete)
            if ref:
                return get_display_name_from_athlete_ref(ref, cache)
            return "", ""

        a_name, a_id = competitor_name_and_id(a)
        b_name, b_id = competitor_name_and_id(b)

        if not a_name or not b_name:
            continue

        order += 1
        wc = extract_weight_class_text(comp)
        bout = f"{a_name} vs {b_name}"

        fight_id = str(comp.get("id") or f"{event_id}-{order}-{slugify(bout)}")

        fights.append(
            {
                "id": fight_id,
                "bout": bout,
                "red": {"name": a_name, "espn_id": a_id},
                "blue": {"name": b_name, "espn_id": b_id},
                "weight_class": wc,
                "order": order,
                "status": "scheduled",
                "source": {"provider": "espn", "event_id": event_id},
            }
        )

    return fights


def fetch_espn_upcoming_events_with_cards() -> tuple[list[dict], dict]:
    cache = {"source": "espn", "fetched_at": now_iso(), "requests": [], "notes": []}

    status, body = http_get(ESPN_SCOREBOARD)
    cache["requests"].append({"url": ESPN_SCOREBOARD, "status": status, "preview": body[:200]})
    if status != 200:
        cache["notes"].append("ESPN scoreboard request failed.")
        return [], cache

    data = safe_json(body)
    if not isinstance(data, dict) or "events" not in data:
        cache["notes"].append("ESPN scoreboard missing events[].")
        return [], cache

    events_out: list[dict] = []
    today = date.today()

    for ev in data.get("events", []):
        if not isinstance(ev, dict):
            continue

        ev_id = str(ev.get("id") or "").strip()
        name = ev.get("name") or ev.get("shortName") or "UFC Event"
        d = iso_date_from_espn(ev.get("date"))
        if not ev_id or not d:
            continue

        try:
            if datetime.fromisoformat(d).date() < today:
                continue
        except Exception:
            continue

        location = pick_event_location(ev)
        slug = f"{d}-{slugify(name)}"

        fights = build_fights_for_event(ev_id, cache)

        events_out.append(
            {
                "id": slug,
                "slug": slug,
                "name": name,
                "date": d,
                "location": location,
                "status": "upcoming",
                "source": {"provider": "espn", "event_id": ev_id},
                "fights": fights,
            }
        )

    events_out.sort(key=lambda x: x.get("date") or "9999-12-31")
    cache["notes"].append(f"Built {len(events_out)} upcoming events from ESPN (with fight cards when available).")
    return events_out, cache


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    events, cache = fetch_espn_upcoming_events_with_cards()

    out = {"generated_at": now_iso(), "events": events}
    with open(EVENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"generated_at": now_iso(), "steps": [cache]}, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(events)} upcoming events to ufc/data/events.json")
    # Never fail the workflow (data may be temporarily unavailable)
    sys.exit(0)


if __name__ == "__main__":
    main()
