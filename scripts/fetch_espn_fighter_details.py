#!/usr/bin/env python3
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVENTS_PATH = os.path.join(ROOT, "ufc", "data", "events.json")
FIGHTERS_PATH = os.path.join(ROOT, "ufc", "data", "fighters.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}

ESPN_ATHLETE_API_URL = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes/{fighter_id}"
ESPN_FIGHTER_WEB_URL = "https://www.espn.com/mma/fighter/_/id/{fighter_id}"
ESPN_SEARCH_URL = "https://site.api.espn.com/apis/site/v2/search"


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def get_json(url: str, params: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def get_html(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def parse_event_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None

    candidates = [
        value,
        value.replace("Z", "+00:00"),
    ]

    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue

    return None


def is_upcoming_event(event: Dict[str, Any]) -> bool:
    status = str(event.get("status") or "").strip().lower()
    if status in {"upcoming", "today", "scheduled"}:
        return True
    if status in {"completed", "final", "post"}:
        return False

    event_date = (
        event.get("date")
        or event.get("event_date")
        or event.get("start_date")
        or ""
    )
    dt = parse_event_datetime(str(event_date))
    if not dt:
        return True

    now = datetime.now(timezone.utc)
    return dt >= now


def is_scheduled_fight(fight: Dict[str, Any]) -> bool:
    status = str(fight.get("status") or "").strip().lower()
    if not status:
        return True
    return status in {"scheduled", "upcoming", "today", "in_progress"}


def normalize_name(name: str) -> str:
    name = str(name or "").strip().lower()
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def load_events() -> List[Dict[str, Any]]:
    payload = load_json(EVENTS_PATH, {"events": []})
    events = payload.get("events", [])
    return events if isinstance(events, list) else []


def load_existing_fighters() -> Dict[str, Dict[str, Any]]:
    payload = load_json(FIGHTERS_PATH, {"fighters": []})
    fighters = payload.get("fighters", [])
    result: Dict[str, Dict[str, Any]] = {}

    if not isinstance(fighters, list):
        return result

    for fighter in fighters:
        fighter_id = str(fighter.get("espn_id") or "").strip()
        if fighter_id:
            result[fighter_id] = fighter

    return result


def collect_fighter_ids_from_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    fighter_ids: Set[str] = set()
    missing_names: Set[str] = set()
    upcoming_events = 0
    scheduled_fights = 0

    for event in events:
        if not is_upcoming_event(event):
            continue

        upcoming_events += 1
        fights = event.get("fights", []) or []

        for fight in fights:
            if not isinstance(fight, dict):
                continue
            if not is_scheduled_fight(fight):
                continue

            scheduled_fights += 1

            for side in ("red", "blue"):
                fighter = fight.get(side, {}) or {}
                fighter_id = str(fighter.get("espn_id") or "").strip()
                fighter_name = str(fighter.get("name") or "").strip()

                if fighter_id:
                    fighter_ids.add(fighter_id)
                elif fighter_name:
                    missing_names.add(fighter_name)

    return {
        "upcoming_events": upcoming_events,
        "scheduled_fights": scheduled_fights,
        "fighter_ids": fighter_ids,
        "missing_names": missing_names,
    }


def extract_stat_value_from_label(soup: BeautifulSoup, label_text: str) -> str:
    label_norm = normalize_name(label_text)

    for node in soup.find_all(text=True):
        text = str(node).strip()
        if normalize_name(text) != label_norm:
            continue

        parent = node.parent
        if not parent:
            continue

        nearby_text = " ".join(parent.parent.stripped_strings) if parent.parent else " ".join(parent.stripped_strings)
        pieces = [p.strip() for p in re.split(r"\s{2,}|\n", nearby_text) if p.strip()]
        if len(pieces) >= 2:
            for idx, piece in enumerate(pieces):
                if normalize_name(piece) == label_norm and idx + 1 < len(pieces):
                    return pieces[idx + 1]

    body_text = " ".join(soup.stripped_strings)
    pattern = rf"{re.escape(label_text)}\s+([A-Za-z0-9\.\-%'\"/ ]{{1,30}})"
    m = re.search(pattern, body_text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return ""


def extract_record_from_html(soup: BeautifulSoup) -> str:
    text = " ".join(soup.stripped_strings)

    patterns = [
        r"\bRecord\b\s*([0-9]+-[0-9]+-[0-9]+)",
        r"\bMMA Record\b\s*([0-9]+-[0-9]+-[0-9]+)",
        r"\b([0-9]+-[0-9]+-[0-9]+)\b",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

    return ""


def extract_name_from_html(soup: BeautifulSoup) -> str:
    for selector in ["h1", "title"]:
        node = soup.select_one(selector)
        if not node:
            continue
        text = " ".join(node.stripped_strings).strip()
        if not text:
            continue
        text = re.sub(r"\s*-\s*ESPN.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*\|\s*ESPN.*$", "", text, flags=re.IGNORECASE)
        if text:
            return text

    return ""


def fetch_fighter_from_api(fighter_id: str) -> Dict[str, Any]:
    payload = get_json(ESPN_ATHLETE_API_URL.format(fighter_id=fighter_id))
    if not payload:
        return {}

    display_name = str(
        payload.get("displayName")
        or payload.get("fullName")
        or payload.get("shortName")
        or ""
    ).strip()

    first_name = str(payload.get("firstName") or "").strip()
    last_name = str(payload.get("lastName") or "").strip()
    slug = str(payload.get("slug") or "").strip()

    return {
        "espn_id": fighter_id,
        "name": display_name,
        "first_name": first_name,
        "last_name": last_name,
        "slug": slug,
        "api_payload": payload,
    }


def fetch_fighter_from_html(fighter_id: str) -> Dict[str, Any]:
    html = get_html(ESPN_FIGHTER_WEB_URL.format(fighter_id=fighter_id))
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")

    name = extract_name_from_html(soup)
    record = extract_record_from_html(soup)

    fighter = {
        "espn_id": fighter_id,
        "name": name,
        "record": record,
        "height": extract_stat_value_from_label(soup, "Height"),
        "weight": extract_stat_value_from_label(soup, "Weight"),
        "reach": extract_stat_value_from_label(soup, "Reach"),
        "stance": extract_stat_value_from_label(soup, "Stance"),
        "dob": extract_stat_value_from_label(soup, "DOB"),
        "age": extract_stat_value_from_label(soup, "Age"),
        "association": extract_stat_value_from_label(soup, "Association"),
        "country": "",
        "profile_url": ESPN_FIGHTER_WEB_URL.format(fighter_id=fighter_id),
    }

    text = " ".join(soup.stripped_strings)
    country_match = re.search(r"\bNationality\b\s+([A-Za-z \-]{2,40})", text, flags=re.IGNORECASE)
    if country_match:
        fighter["country"] = country_match.group(1).strip()

    image = soup.find("meta", attrs={"property": "og:image"})
    if image and image.get("content"):
        fighter["image_url"] = image.get("content", "").strip()

    return fighter


def merge_fighter_data(existing: Dict[str, Any], api_data: Dict[str, Any], html_data: Dict[str, Any]) -> Dict[str, Any]:
    fighter_id = str(
        html_data.get("espn_id")
        or api_data.get("espn_id")
        or existing.get("espn_id")
        or ""
    ).strip()

    name = (
        html_data.get("name")
        or api_data.get("name")
        or existing.get("name")
        or ""
    )

    first_name = api_data.get("first_name") or existing.get("first_name") or ""
    last_name = api_data.get("last_name") or existing.get("last_name") or ""
    slug = api_data.get("slug") or existing.get("slug") or ""

    fighter = dict(existing)
    fighter.update(
        {
            "espn_id": fighter_id,
            "name": name,
            "first_name": first_name,
            "last_name": last_name,
            "slug": slug,
            "record": html_data.get("record") or existing.get("record") or "",
            "height": html_data.get("height") or existing.get("height") or "",
            "weight": html_data.get("weight") or existing.get("weight") or "",
            "reach": html_data.get("reach") or existing.get("reach") or "",
            "stance": html_data.get("stance") or existing.get("stance") or "",
            "dob": html_data.get("dob") or existing.get("dob") or "",
            "age": html_data.get("age") or existing.get("age") or "",
            "association": html_data.get("association") or existing.get("association") or "",
            "country": html_data.get("country") or existing.get("country") or "",
            "profile_url": html_data.get("profile_url") or existing.get("profile_url") or "",
            "image_url": html_data.get("image_url") or existing.get("image_url") or "",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    )

    if api_data.get("api_payload"):
        fighter["api_payload"] = api_data["api_payload"]

    return fighter


def search_fighter_id_by_name(name: str) -> str:
    """
    Best-effort fallback only.
    """
    if not name:
        return ""

    payload = get_json(ESPN_SEARCH_URL, params={"query": name, "limit": "10"})
    if not payload:
        return ""

    payload_text = json.dumps(payload)

    patterns = [
        r'"/mma/fighter/_/id/(\d+)',
        r'"id"\s*:\s*"(\d+)"',
    ]

    for pattern in patterns:
        m = re.search(pattern, payload_text)
        if m:
            return m.group(1)

    return ""


def build_fighters_payload(fighters_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    fighters = sorted(
        fighters_by_id.values(),
        key=lambda f: (
            str(f.get("name") or "").lower(),
            str(f.get("espn_id") or ""),
        ),
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(fighters),
        "fighters": fighters,
    }


def main() -> None:
    events = load_events()
    existing_fighters = load_existing_fighters()

    collected = collect_fighter_ids_from_events(events)
    fighter_ids: Set[str] = set(collected["fighter_ids"])
    missing_names: Set[str] = set(collected["missing_names"])

    print(f"Found {collected['upcoming_events']} upcoming events")
    print(f"Found {collected['scheduled_fights']} scheduled fights")
    print(f"Found {len(fighter_ids)} unique fighter IDs from scheduled fights")
    print(f"Found {len(missing_names)} fighter names missing IDs")

    resolved_missing = 0
    for name in sorted(missing_names):
        resolved_id = search_fighter_id_by_name(name)
        if resolved_id:
            fighter_ids.add(resolved_id)
            resolved_missing += 1
        time.sleep(0.15)

    print(f"Resolved {resolved_missing}/{len(missing_names)} missing fighter names to ESPN IDs")

    fighters_by_id = dict(existing_fighters)
    fetched_count = 0
    failed_ids: List[str] = []

    for fighter_id in sorted(fighter_ids, key=lambda x: int(x) if x.isdigit() else x):
        existing = fighters_by_id.get(fighter_id, {})

        api_data = fetch_fighter_from_api(fighter_id)
        html_data = fetch_fighter_from_html(fighter_id)

        if not api_data and not html_data:
            failed_ids.append(fighter_id)
            print(f"Failed to fetch fighter {fighter_id}")
            time.sleep(0.20)
            continue

        merged = merge_fighter_data(existing, api_data, html_data)

        if not merged.get("name"):
            failed_ids.append(fighter_id)
            print(f"Skipped fighter {fighter_id}: missing name")
            time.sleep(0.20)
            continue

        fighters_by_id[fighter_id] = merged
        fetched_count += 1
        print(f"Stored fighter {fighter_id}: {merged.get('name', '')}")
        time.sleep(0.20)

    payload = build_fighters_payload(fighters_by_id)
    save_json(FIGHTERS_PATH, payload)

    print(f"Fetched/stored {fetched_count} fighters this run")
    print(f"Total fighters stored: {payload['count']}")

    if failed_ids:
        print(f"Failed fighter IDs: {', '.join(failed_ids[:25])}")


if __name__ == "__main__":
    main()
