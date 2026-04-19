#!/usr/bin/env python3
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVENTS_PATH = os.path.join(ROOT, "ufc", "data", "events.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}

# ESPN event JSON pattern commonly reachable from event IDs
CORE_EVENT_URL = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/{event_id}"
SITE_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/summary?event={event_id}"


def load_events() -> Dict[str, Any]:
    if not os.path.exists(EVENTS_PATH):
        return {"generated_at": None, "events": []}

    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_events(payload: Dict[str, Any]) -> None:
    with open(EVENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def get_ref_json(ref: Optional[str]) -> Optional[Dict[str, Any]]:
    if not ref:
        return None
    try:
        resp = requests.get(ref, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def extract_id_from_ref(ref: Optional[str]) -> str:
    if not ref:
        return ""
    match = re.search(r"/(\d+)(?:\?.*)?$", ref)
    return match.group(1) if match else ""


def normalize_weight_class(text: str) -> str:
    return str(text or "").strip()


def build_bout_name(red_name: str, blue_name: str) -> str:
    red_name = str(red_name or "").strip()
    blue_name = str(blue_name or "").strip()
    if red_name and blue_name:
        return f"{red_name} vs {blue_name}"
    return red_name or blue_name or "TBD vs TBD"


def parse_competition_from_core(comp: Dict[str, Any], idx: int, event_id: str) -> Optional[Dict[str, Any]]:
    comp_id = str(comp.get("id") or extract_id_from_ref(comp.get("$ref"))).strip()
    competitors_ref = comp.get("competitors", {}).get("$ref") if isinstance(comp.get("competitors"), dict) else None
    status_ref = comp.get("status", {}).get("$ref") if isinstance(comp.get("status"), dict) else None
    notes_ref = comp.get("notes", {}).get("$ref") if isinstance(comp.get("notes"), dict) else None

    competitors_payload = get_ref_json(competitors_ref) if competitors_ref else None
    competitors_items = competitors_payload.get("items", []) if competitors_payload else []

    red = {"name": "", "espn_id": ""}
    blue = {"name": "", "espn_id": ""}

    # ESPN competitor order is not always guaranteed, but for your site
    # a stable left/right mapping is fine.
    if len(competitors_items) >= 1:
        c1 = competitors_items[0]
        athlete_ref = c1.get("athlete", {}).get("$ref") if isinstance(c1.get("athlete"), dict) else None
        athlete_payload = get_ref_json(athlete_ref) if athlete_ref else None
        red = {
            "name": str((athlete_payload or {}).get("displayName") or c1.get("displayName") or "").strip(),
            "espn_id": extract_id_from_ref(athlete_ref) or str(c1.get("id") or "").strip(),
        }

    if len(competitors_items) >= 2:
        c2 = competitors_items[1]
        athlete_ref = c2.get("athlete", {}).get("$ref") if isinstance(c2.get("athlete"), dict) else None
        athlete_payload = get_ref_json(athlete_ref) if athlete_ref else None
        blue = {
            "name": str((athlete_payload or {}).get("displayName") or c2.get("displayName") or "").strip(),
            "espn_id": extract_id_from_ref(athlete_ref) or str(c2.get("id") or "").strip(),
        }

    weight_class = ""
    if notes_ref:
        notes_payload = get_ref_json(notes_ref)
        note_items = notes_payload.get("items", []) if notes_payload else []
        if note_items:
            weight_class = str(note_items[0].get("headline") or "").strip()

    status = "scheduled"
    if status_ref:
        status_payload = get_ref_json(status_ref)
        state = str((status_payload or {}).get("type", {}).get("state") or "").lower()
        detail = str((status_payload or {}).get("type", {}).get("detail") or "").lower()
        if "post" in state or "final" in detail:
            status = "completed"
        elif "in" in state:
            status = "in_progress"

    bout = build_bout_name(red["name"], blue["name"])

    return {
        "id": comp_id or f"{event_id}-{idx}",
        "bout": bout,
        "red": red,
        "blue": blue,
        "weight_class": normalize_weight_class(weight_class),
        "order": idx,
        "status": status,
        "source": {
            "provider": "espn",
            "event_id": str(event_id),
        },
    }


def fetch_fights_from_core_event(event_id: str) -> List[Dict[str, Any]]:
    event_url = CORE_EVENT_URL.format(event_id=event_id)
    event_payload = get_json(event_url)
    if not event_payload:
        return []

    competitions_ref = None
    competitions_obj = event_payload.get("competitions")
    if isinstance(competitions_obj, dict):
        competitions_ref = competitions_obj.get("$ref")

    competitions_payload = get_ref_json(competitions_ref) if competitions_ref else None
    competitions = competitions_payload.get("items", []) if competitions_payload else []

    fights: List[Dict[str, Any]] = []
    for idx, comp in enumerate(competitions, start=1):
        parsed = parse_competition_from_core(comp, idx, event_id)
        if parsed:
            fights.append(parsed)
        time.sleep(0.15)

    return fights


def fetch_fights_from_site_summary(event_id: str) -> List[Dict[str, Any]]:
    summary_url = SITE_SUMMARY_URL.format(event_id=event_id)
    payload = get_json(summary_url)
    if not payload:
        return []

    fights: List[Dict[str, Any]] = []
    for idx, comp in enumerate(payload.get("header", {}).get("competitions", []) or [], start=1):
        comp_id = str(comp.get("id") or "").strip()
        competitors = comp.get("competitors", []) or []

        red = {"name": "", "espn_id": ""}
        blue = {"name": "", "espn_id": ""}

        if len(competitors) >= 1:
            c1 = competitors[0]
            athlete = c1.get("athlete", {}) or {}
            red = {
                "name": str(athlete.get("displayName") or c1.get("displayName") or "").strip(),
                "espn_id": str(athlete.get("id") or c1.get("id") or "").strip(),
            }

        if len(competitors) >= 2:
            c2 = competitors[1]
            athlete = c2.get("athlete", {}) or {}
            blue = {
                "name": str(athlete.get("displayName") or c2.get("displayName") or "").strip(),
                "espn_id": str(athlete.get("id") or c2.get("id") or "").strip(),
            }

        note = ""
        notes = comp.get("notes", []) or []
        if notes:
            note = str(notes[0].get("headline") or "").strip()

        status = "scheduled"
        comp_status = comp.get("status", {}) or {}
        state = str((comp_status.get("type", {}) or {}).get("state") or "").lower()
        detail = str((comp_status.get("type", {}) or {}).get("detail") or "").lower()
        if "post" in state or "final" in detail:
            status = "completed"
        elif "in" in state:
            status = "in_progress"

        fights.append({
            "id": comp_id or f"{event_id}-{idx}",
            "bout": build_bout_name(red["name"], blue["name"]),
            "red": red,
            "blue": blue,
            "weight_class": normalize_weight_class(note),
            "order": idx,
            "status": status,
            "source": {
                "provider": "espn",
                "event_id": str(event_id),
            },
        })

    return fights


def fetch_event_fights(event_id: str) -> List[Dict[str, Any]]:
    fights = fetch_fights_from_core_event(event_id)
    if fights:
        return fights

    return fetch_fights_from_site_summary(event_id)


def main() -> None:
    payload = load_events()
    events = payload.get("events", []) or []

    if not events:
        print("No events found in ufc/data/events.json")
        return

    updated_count = 0

    for ev in events:
        event_id = str(((ev.get("source") or {}).get("event_id")) or "").strip()
        name = str(ev.get("name") or "").strip()

        if not event_id:
            print(f"Skipping {name or '(unnamed event)'}: missing source.event_id")
            continue

        fights = fetch_event_fights(event_id)
        ev["fights"] = fights

        if fights:
            updated_count += 1
            print(f"Updated {name}: {len(fights)} fights")
        else:
            print(f"No fights found for {name} ({event_id})")

        time.sleep(0.4)

    save_events(payload)
    print(f"Done. Populated fight cards for {updated_count} event(s).")


if __name__ == "__main__":
    main()
