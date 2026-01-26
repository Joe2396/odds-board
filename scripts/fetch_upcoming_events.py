#!/usr/bin/env python3
"""
Fetch upcoming UFC events + (if available) fight cards in a GitHub-friendly way.

Primary: UFC public data API (ufc-data-api.ufc.com)
Fallback: Wikipedia via MediaWiki API (scheduled events list)

Writes:
  - ufc/data/events.json          (normalized source of truth for site generators)
  - ufc/data/source_cache.json    (raw responses + diagnostics for debugging)
"""

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


# ---------- HTTP helpers ----------

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; odds-board-bot/1.0; +https://github.com/)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close",
}


def http_get(url: str, headers: dict | None = None, timeout: int = 20, retries: int = 2, sleep_s: float = 1.0) -> tuple[int, str]:
    """Simple GET with retries. Returns (status_code, body_text)."""
    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)

    last_err = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=h, method="GET")
            with urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read().decode("utf-8", errors="replace")
                return status, body
        except (HTTPError, URLError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(sleep_s * (attempt + 1))
            else:
                break

    # If we got here, it failed
    status = getattr(last_err, "code", 0) if last_err else 0
    return status, f"{type(last_err).__name__}: {last_err}"


def safe_json_loads(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


# ---------- Normalization ----------

def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "event"


def parse_iso_date(dt_str: str) -> str | None:
    if not dt_str:
        return None
    # common formats: "2026-02-10T00:00:00Z" etc.
    try:
        # handle trailing Z
        ds = dt_str.replace("Z", "+00:00")
        d = datetime.fromisoformat(ds)
        return d.date().isoformat()
    except Exception:
        # last resort: attempt to extract yyyy-mm-dd
        m = re.search(r"(\d{4}-\d{2}-\d{2})", dt_str)
        return m.group(1) if m else None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Source A: UFC data API ----------

def fetch_ufc_api_upcoming() -> tuple[list[dict], dict]:
    """
    Attempts to fetch upcoming events and, if possible, their fight cards
    from ufc-data-api.ufc.com.

    Returns (normalized_events, cache_info).
    """
    cache = {"source": "ufc-data-api", "fetched_at": now_iso(), "endpoints": {}, "notes": []}

    # These endpoints have existed historically; UFC may change them.
    # We treat any failure as non-fatal and fall back to Wikipedia.
    base = "https://ufc-data-api.ufc.com/api/v3/us"

    # 1) Upcoming events list
    events_url_candidates = [
        f"{base}/events",                 # often includes upcoming/past; we filter
        f"{base}/event",                  # sometimes used
        f"{base}/events/upcoming",        # sometimes exists
    ]

    events_payload = None
    events_status = None
    used_events_url = None

    for url in events_url_candidates:
        status, body = http_get(url)
        cache["endpoints"][url] = {"status": status, "body_preview": body[:500]}
        if status == 200:
            j = safe_json_loads(body)
            if isinstance(j, list) and len(j) > 0:
                events_payload = j
                events_status = status
                used_events_url = url
                break

    if not events_payload:
        cache["notes"].append("UFC API events list not available or returned empty.")
        return [], cache

    # Filter to upcoming by date when possible
    upcoming = []
    today = datetime.now(timezone.utc).date()

    for ev in events_payload:
        # common keys seen: "id", "name", "event_date", "start_time", "location", etc.
        ev_date = parse_iso_date(str(ev.get("event_date") or ev.get("start_time") or ev.get("date") or ""))
        if not ev_date:
            continue
        try:
            d = datetime.fromisoformat(ev_date).date()
        except Exception:
            continue
        if d >= today:
            upcoming.append(ev)

    # sort by date
    def key_date(e):
        return parse_iso_date(str(e.get("event_date") or e.get("start_time") or e.get("date") or "")) or "9999-12-31"

    upcoming.sort(key=key_date)

    normalized = []
    raw_cards = {}

    # 2) Attempt to fetch fight cards per event
    # Endpoints vary; we try a couple patterns.
    for ev in upcoming[:40]:  # cap for safety
        ev_id = ev.get("id") or ev.get("event_id") or ev.get("uuid")
        name = ev.get("name") or ev.get("title") or ev.get("event_name") or "UFC Event"
        ev_date = parse_iso_date(str(ev.get("event_date") or ev.get("start_time") or ev.get("date") or "")) or None

        location = ev.get("location") or ev.get("arena") or ev.get("venue") or ""
        city = ev.get("city") or ""
        country = ev.get("country") or ""
        pretty_location = ", ".join([p for p in [location, city, country] if p]) or str(ev.get("location") or "")

        event_slug = f"{ev_date or 'tbd'}-{slugify(str(name))}"
        event_key = str(ev_id) if ev_id is not None else event_slug

        fights = []

        if ev_id is not None:
            card_urls = [
                f"{base}/events/{ev_id}/fights",
                f"{base}/event/{ev_id}/fights",
                f"{base}/fights?eventId={ev_id}",
            ]
            card = None
            card_url_used = None
            for cu in card_urls:
                s, b = http_get(cu)
                cache["endpoints"][cu] = {"status": s, "body_preview": b[:500]}
                if s == 200:
                    jj = safe_json_loads(b)
                    if isinstance(jj, list):
                        card = jj
                        card_url_used = cu
                        break
            if isinstance(card, list):
                raw_cards[str(ev_id)] = {"url": card_url_used, "count": len(card)}
                fights = normalize_fights_from_ufc_api(card)

        normalized.append(
            {
                "id": event_key,
                "slug": event_slug,
                "name": str(name),
                "date": ev_date,  # "YYYY-MM-DD"
                "location": pretty_location,
                "status": "upcoming",
                "source": {
                    "provider": "ufc-data-api",
                    "events_url": used_events_url,
                },
                "fights": fights,  # can be empty if card endpoint unavailable
            }
        )

    cache["notes"].append(f"Normalized {len(normalized)} upcoming events from UFC API.")
    cache["cards_summary"] = raw_cards
    return normalized, cache


def normalize_fights_from_ufc_api(card_list: list[dict]) -> list[dict]:
    fights = []
    # We try to read common keys; if the API changes, we still output minimal matchups.
    for i, f in enumerate(card_list):
        # Common patterns:
        # - redCorner / blueCorner
        # - fighter1 / fighter2
        # - athlete1/athlete2 with names
        red = (
            f.get("redCorner") or f.get("red_corner") or f.get("fighter1") or f.get("athlete1") or {}
        )
        blue = (
            f.get("blueCorner") or f.get("blue_corner") or f.get("fighter2") or f.get("athlete2") or {}
        )

        def name_of(x):
            if isinstance(x, str):
                return x
            if not isinstance(x, dict):
                return ""
            return (
                x.get("name")
                or " ".join([p for p in [x.get("first_name"), x.get("last_name")] if p])
                or x.get("fullName")
                or x.get("full_name")
                or ""
            )

        red_name = name_of(red) or str(f.get("redName") or f.get("fighter_1_name") or "")
        blue_name = name_of(blue) or str(f.get("blueName") or f.get("fighter_2_name") or "")

        weight_class = (
            f.get("weight_class")
            or f.get("weightClass")
            or f.get("division")
            or f.get("weight")
            or ""
        )
        bout = f.get("bout") or f.get("fight_name") or f.get("name") or ""
        if not bout and red_name and blue_name:
            bout = f"{red_name} vs {blue_name}"

        fights.append(
            {
                "id": str(f.get("id") or f.get("fight_id") or f"{i}-{slugify(bout)}"),
                "bout": bout,
                "red": {"name": red_name},
                "blue": {"name": blue_name},
                "weight_class": str(weight_class),
                "order": int(f.get("order") or f.get("bout_order") or i),
                "status": "scheduled",
            }
        )

    # Sort by order if present
    fights.sort(key=lambda x: x.get("order", 9999))
    return fights


# ---------- Source B: Wikipedia scheduled events (fallback) ----------

def fetch_wikipedia_scheduled_events() -> tuple[list[dict], dict]:
    """
    Uses MediaWiki API to fetch the 'Scheduled events' section from Wikipedia's
    'List of UFC events' page.

    This is a fallback when UFC API is unavailable from GH runners.
    """
    cache = {"source": "wikipedia", "fetched_at": now_iso(), "notes": [], "endpoints": {}}

    # Get wikitext for the page
    params = {
        "action": "parse",
        "page": "List_of_UFC_events",
        "prop": "wikitext",
        "format": "json",
    }
    url = "https://en.wikipedia.org/w/api.php?" + urlencode(params)
    status, body = http_get(url, headers={"Accept": "application/json"})
    cache["endpoints"][url] = {"status": status, "body_preview": body[:500]}

    if status != 200:
        cache["notes"].append("Wikipedia API request failed.")
        return [], cache

    j = safe_json_loads(body)
    wikitext = (((j or {}).get("parse") or {}).get("wikitext") or {}).get("*", "")
    if not wikitext:
        cache["notes"].append("No wikitext returned from Wikipedia parse API.")
        return [], cache

    # Extract "Scheduled events" table rows from wikitext. This is best-effort.
    # We look for a wikitable after a header containing 'Scheduled events'.
    scheduled_block = ""
    m = re.search(r"==\s*Scheduled events\s*==(.+?)(==|\Z)", wikitext, flags=re.S)
    if m:
        scheduled_block = m.group(1)
    else:
        cache["notes"].append("Could not locate 'Scheduled events' section in wikitext.")
        return [], cache

    # Extract rows like: |-\n| date || Event || Venue || Location ...
    rows = re.findall(r"\|\-\s*(.+?)(?=\|\-|\Z)", scheduled_block, flags=re.S)
    events = []
    for r in rows:
        # split cells on || and strip wiki markup
        cells = [c.strip() for c in r.split("||")]
        if len(cells) < 3:
            continue

        date_cell = clean_wiki(cells[0].lstrip("|").strip())
        event_cell = clean_wiki(cells[1])
        venue_cell = clean_wiki(cells[2]) if len(cells) > 2 else ""
        loc_cell = clean_wiki(cells[3]) if len(cells) > 3 else ""

        # date_cell may be like "February 10, 2026"
        iso_date = to_iso_date_from_human(date_cell)
        if not iso_date:
            continue

        name = event_cell or "UFC Event"
        event_slug = f"{iso_date}-{slugify(name)}"
        events.append(
            {
                "id": event_slug,
                "slug": event_slug,
                "name": name,
                "date": iso_date,
                "location": ", ".join([p for p in [venue_cell, loc_cell] if p]).strip(", "),
                "status": "upcoming",
                "source": {"provider": "wikipedia"},
                "fights": [],  # Wikipedia scheduled table usually doesn't include full card
            }
        )

    # sort by date
    events.sort(key=lambda e: e.get("date") or "9999-12-31")
    cache["notes"].append(f"Normalized {len(events)} upcoming events from Wikipedia fallback.")
    return events, cache


def clean_wiki(s: str) -> str:
    # remove refs, templates, links
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"{{[^}]*}}", "", s)
    # [[Link|Text]] -> Text, [[Text]] -> Text
    s = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    # remove formatting quotes
    s = s.replace("''", "")
    return re.sub(r"\s+", " ", s).strip()


def to_iso_date_from_human(s: str) -> str | None:
    s = s.strip()
    # Try a couple common formats
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.isoformat()
        except Exception:
            continue
    # Try to extract "Month day, year" loosely
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", s)
    if m:
        try:
            d = datetime.strptime(f"{m.group(1)} {m.group(2)}, {m.group(3)}", "%B %d, %Y").date()
            return d.isoformat()
        except Exception:
            return None
    return None


# ---------- Write outputs ----------

def ensure_dirs():
    os.makedirs(UFC_DATA_DIR, exist_ok=True)


def write_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    ensure_dirs()

    all_cache = {"generated_at": now_iso(), "steps": []}

    # Try UFC API first
    events, cache = fetch_ufc_api_upcoming()
    all_cache["steps"].append(cache)

   def fetch_wikipedia_scheduled_events() -> tuple[list[dict], dict]:
    """
    Robust fallback: fetch rendered HTML for the 'Scheduled events' section and parse the table.
    """
    cache = {"source": "wikipedia", "fetched_at": now_iso(), "notes": [], "endpoints": {}}

    # MediaWiki parse endpoint (HTML)
    params = {
        "action": "parse",
        "page": "List_of_UFC_events",
        "prop": "text",
        "format": "json",
    }
    url = "https://en.wikipedia.org/w/api.php?" + urlencode(params)
    status, body = http_get(url, headers={"Accept": "application/json"})
    cache["endpoints"][url] = {"status": status, "body_preview": body[:500]}

    if status != 200:
        cache["notes"].append("Wikipedia API request failed.")
        return [], cache

    j = safe_json_loads(body)
    html = (((j or {}).get("parse") or {}).get("text") or {}).get("*", "")
    if not html:
        cache["notes"].append("No HTML returned from Wikipedia parse API.")
        return [], cache

    # Lazy HTML parsing without bs4 to keep deps minimal:
    # We locate the 'Scheduled events' header and then the next wikitable.
    # This is still much more stable than wikitext row parsing.
    idx = html.lower().find("scheduled events")
    if idx == -1:
        cache["notes"].append("Could not find 'Scheduled events' in parsed HTML.")
        return [], cache

    sub = html[idx:]
    # Find the first table after the section
    table_match = re.search(r"<table[^>]*class=\"[^\"]*wikitable[^\"]*\"[^>]*>.*?</table>", sub, flags=re.S | re.I)
    if not table_match:
        cache["notes"].append("Could not find scheduled events wikitable in HTML.")
        return [], cache

    table_html = table_match.group(0)

    # Extract rows
    row_html = re.findall(r"<tr[^>]*>.*?</tr>", table_html, flags=re.S | re.I)

    def strip_tags(s: str) -> str:
        s = re.sub(r"<sup[^>]*>.*?</sup>", "", s, flags=re.S | re.I)  # remove refs
        s = re.sub(r"<.*?>", "", s, flags=re.S)
        s = s.replace("&nbsp;", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    events = []
    for r in row_html[1:]:  # skip header
        cols = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S | re.I)
        cols = [strip_tags(c) for c in cols]
        if len(cols) < 2:
            continue

        date_cell = cols[0]
        name_cell = cols[1] if len(cols) > 1 else ""
        venue_cell = cols[2] if len(cols) > 2 else ""
        loc_cell = cols[3] if len(cols) > 3 else ""

        iso_date = to_iso_date_from_human(date_cell)
        if not iso_date:
            continue

        name = name_cell or "UFC Event"
        event_slug = f"{iso_date}-{slugify(name)}"
        events.append(
            {
                "id": event_slug,
                "slug": event_slug,
                "name": name,
                "date": iso_date,
                "location": ", ".join([p for p in [venue_cell, loc_cell] if p]).strip(", "),
                "status": "upcoming",
                "source": {"provider": "wikipedia"},
                "fights": [],
            }
        )

    events.sort(key=lambda e: e.get("date") or "9999-12-31")
    cache["notes"].append(f"Normalized {len(events)} upcoming events from Wikipedia HTML fallback.")
    return events, cache


    # Final output format (simple + generator-friendly)
    out = {
        "generated_at": now_iso(),
        "source_priority": ["ufc-data-api", "wikipedia"],
        "events": events,
    }

    write_json(EVENTS_OUT, out)
    write_json(CACHE_OUT, all_cache)

    print(f"Wrote {len(events)} events to {EVENTS_OUT}")
    print(f"Wrote cache to {CACHE_OUT}")

       # Exit code: don't fail scheduled workflows if sources are temporarily blocked
    if len(events) == 0:
        print("WARN: No upcoming events found from any source. Keeping workflow green.", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
