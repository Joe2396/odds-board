#!/usr/bin/env python3

from __future__ import annotations
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UFC_DATA_DIR = os.path.join(ROOT, "ufc", "data")
EVENTS_OUT = os.path.join(UFC_DATA_DIR, "events.json")
CACHE_OUT = os.path.join(UFC_DATA_DIR, "source_cache.json")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; odds-board-bot/1.0)",
    "Accept": "application/json, text/plain, */*",
}

# ---------------- HTTP ---------------- #

def http_get(url, timeout=20):
    try:
        req = Request(url, headers=DEFAULT_HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError) as e:
        return getattr(e, "code", 0), str(e)

def safe_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None

# ---------------- Helpers ---------------- #

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def slugify(s):
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "event"

def to_iso_date_from_human(s):
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except Exception:
            pass
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", s)
    if m:
        try:
            return datetime.strptime(m.group(0), "%B %d, %Y").date().isoformat()
        except Exception:
            return None
    return None

# ---------------- Wikipedia fallback ---------------- #

def fetch_wikipedia_scheduled_events():
    cache = {"source": "wikipedia", "fetched_at": now_iso(), "endpoints": {}, "notes": []}

    params = {
        "action": "parse",
        "page": "List_of_UFC_events",
        "prop": "text",
        "format": "json",
    }

    url = "https://en.wikipedia.org/w/api.php?" + urlencode(params)
    status, body = http_get(url)
    cache["endpoints"][url] = {"status": status, "preview": body[:300]}

    if status != 200:
        cache["notes"].append("Wikipedia request failed")
        return [], cache

    data = safe_json(body)
    html = (((data or {}).get("parse") or {}).get("text") or {}).get("*", "")
    if not html:
        cache["notes"].append("No HTML from Wikipedia")
        return [], cache

    idx = html.lower().find("scheduled events")
    if idx == -1:
        cache["notes"].append("No 'Scheduled events' section found")
        return [], cache

    sub = html[idx:]
    table_match = re.search(r"<table[^>]*wikitable[^>]*>.*?</table>", sub, flags=re.S | re.I)
    if not table_match:
        cache["notes"].append("No scheduled events table found")
        return [], cache

    table = table_match.group(0)
    rows = re.findall(r"<tr[^>]*>.*?</tr>", table, flags=re.S | re.I)

    def strip_tags(s):
        s = re.sub(r"<sup[^>]*>.*?</sup>", "", s, flags=re.S)
        s = re.sub(r"<.*?>", "", s)
        s = s.replace("&nbsp;", " ")
        return re.sub(r"\s+", " ", s).strip()

    events = []

    for r in rows[1:]:
        cols = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S | re.I)
        cols = [strip_tags(c) for c in cols]

        if len(cols) < 2:
            continue

        date_iso = to_iso_date_from_human(cols[0])
        if not date_iso:
            continue

        name = cols[1]
        venue = cols[2] if len(cols) > 2 else ""
        loc = cols[3] if len(cols) > 3 else ""

        slug = f"{date_iso}-{slugify(name)}"

        events.append({
            "id": slug,
            "slug": slug,
            "name": name,
            "date": date_iso,
            "location": ", ".join(x for x in [venue, loc] if x),
            "status": "upcoming",
            "source": {"provider": "wikipedia"},
            "fights": []
        })

    events.sort(key=lambda x: x["date"])
    cache["notes"].append(f"Parsed {len(events)} upcoming events from Wikipedia")

    return events, cache

# ---------------- Main ---------------- #

def ensure_dirs():
    os.makedirs(UFC_DATA_DIR, exist_ok=True)

def main():
    ensure_dirs()
    all_cache = {"generated_at": now_iso(), "steps": []}

    events, cache = fetch_wikipedia_scheduled_events()
    all_cache["steps"].append(cache)

    out = {
        "generated_at": now_iso(),
        "source": "wikipedia",
        "events": events
    }

    with open(EVENTS_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    with open(CACHE_OUT, "w", encoding="utf-8") as f:
        json.dump(all_cache, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(events)} events")

    if len(events) == 0:
        print("WARN: No upcoming events found. Keeping workflow green.")
        sys.exit(0)

if __name__ == "__main__":
    main()
