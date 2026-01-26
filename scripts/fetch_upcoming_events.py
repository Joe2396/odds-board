#!/usr/bin/env python3

import json, os, re, sys
from datetime import datetime, timezone, date
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urljoin

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "ufc", "data")
EVENTS_PATH = os.path.join(DATA_DIR, "events.json")
CACHE_PATH = os.path.join(DATA_DIR, "source_cache.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (odds-board-bot)"}
WIKI_BASE = "https://en.wikipedia.org"

def now():
    return datetime.now(timezone.utc).isoformat()

def get(url, accept="application/json"):
    h = dict(HEADERS)
    h["Accept"] = accept
    req = Request(url, headers=h)
    with urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="ignore")

def safe_json(s):
    try:
        return json.loads(s)
    except Exception:
        return None

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "event"

def to_iso_date_from_espn(dt):
    # ESPN dates are usually ISO like "2026-02-28T23:00Z" or with offset
    if not dt:
        return None
    ds = str(dt).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ds).date().isoformat()
    except Exception:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(dt))
        return m.group(1) if m else None

# ---------------- ESPN (primary) ---------------- #

def fetch_espn_upcoming():
    cache = {"source": "espn", "fetched_at": now(), "endpoints": {}, "notes": []}
    events = []

    # ESPN “scoreboard” JSON pattern (undocumented but widely used)
    # If this endpoint changes, we fall back to Wikipedia.
    url = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
    body = get(url)
    cache["endpoints"][url] = {"preview": body[:300]}
    data = safe_json(body)

    if not data or "events" not in data:
        cache["notes"].append("ESPN scoreboard missing events[].")
        return [], cache

    today = date.today()

    for ev in data.get("events", []):
        name = ev.get("name") or ev.get("shortName") or "UFC Event"
        ev_date = to_iso_date_from_espn(ev.get("date"))
        if not ev_date:
            continue

        try:
            d = datetime.fromisoformat(ev_date).date()
        except Exception:
            continue

        if d < today:
            continue

        # best-effort location (ESPN sometimes has venue in competitions[0].venue.fullName)
        location = ""
        comps = ev.get("competitions") or []
        if comps and isinstance(comps, list):
            venue = (comps[0].get("venue") or {})
            location = venue.get("fullName") or venue.get("name") or ""

            # city/state/country sometimes present
            addr = venue.get("address") or {}
            parts = [addr.get("city"), addr.get("state"), addr.get("country")]
            parts = [p for p in parts if p]
            if parts:
                location = ", ".join([p for p in [location] if p] + parts)

        slug = f"{ev_date}-{slugify(name)}"

        events.append({
            "id": slug,
            "slug": slug,
            "name": name,
            "date": ev_date,
            "location": location,
            "status": "upcoming",
            "source": {"provider": "espn"},
            "fights": []  # fight card can be added later from event detail endpoints
        })

    events.sort(key=lambda x: x["date"])
    cache["notes"].append(f"Parsed {len(events)} upcoming events from ESPN.")
    return events, cache

# ---------------- Wikipedia fallback ---------------- #

def to_iso_date_from_human(s):
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except Exception:
            pass
    return None

def fetch_wikipedia_event_pages():
    cache = {"source": "wikipedia", "fetched_at": now(), "events_checked": []}
    events = []

    index_html = get("https://en.wikipedia.org/wiki/List_of_UFC_events", accept="text/html")
    links = set(re.findall(r'href="(/wiki/UFC_\d+)"', index_html))
    links = sorted(links, key=lambda x: int(re.findall(r"\d+", x)[0]), reverse=True)[:15]

    today = date.today()

    def extract_infobox(html):
        box = re.search(r'(<table class="infobox[^"]*".*?</table>)', html, re.S)
        if not box:
            return {}
        t = box.group(1)

        def field(name):
            m = re.search(rf"<th[^>]*>{name}</th>.*?<td[^>]*>(.*?)</td>", t, re.S)
            if not m:
                return ""
            val = re.sub("<.*?>", "", m.group(1))
            return re.sub(r"\s+", " ", val).strip()

        return {"date": field("Date"), "venue": field("Venue"), "city": field("City"), "name": field("Event")}

    for link in links:
        url = urljoin(WIKI_BASE, link)
        html = get(url, accept="text/html")
        cache["events_checked"].append(url)
        info = extract_infobox(html)

        date_iso = to_iso_date_from_human(info.get("date", ""))
        if not date_iso:
            continue

        try:
            d = datetime.fromisoformat(date_iso).date()
        except Exception:
            continue

        if d < today:
            continue

        name = info.get("name") or link.replace("/wiki/", "").replace("_", " ")
        slug = f"{date_iso}-{slugify(name)}"

        events.append({
            "id": slug,
            "slug": slug,
            "name": name,
            "date": date_iso,
            "location": ", ".join(x for x in [info.get("venue"), info.get("city")] if x),
            "status": "upcoming",
            "source": {"provider": "wikipedia"},
            "fights": []
        })

    events.sort(key=lambda x: x["date"])
    return events, cache

# ---------------- Main ---------------- #

def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    cache = {"generated_at": now(), "steps": []}

    events, c1 = fetch_espn_upcoming()
    cache["steps"].append(c1)

    if not events:
        events, c2 = fetch_wikipedia_event_pages()
        cache["steps"].append(c2)

    out = {"generated_at": now(), "events": events}

    with open(EVENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(events)} upcoming events")
    sys.exit(0)

if __name__ == "__main__":
    main()
