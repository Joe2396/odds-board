#!/usr/bin/env python3
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVENTS_PATH = os.path.join(ROOT, "ufc", "data", "events.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}

CORE_EVENT_URL = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/{event_id}"
SITE_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/summary?event={event_id}"
FIGHTCENTER_URL = "https://www.espn.com/mma/fightcenter/_/id/{event_id}/league/ufc"

STOP_MARKERS = {
    "latest videos",
    "mma news",
    "all mma news",
    "latest news",
    "title fights",
    "racing positions",
    "quick links",
}

SECTION_MARKERS = {
    "main card - final",
    "prelims - final",
    "preliminary card - final",
    "main card",
    "prelims",
    "preliminary card",
}

KNOWN_WEIGHT_CLASSES = {
    "heavyweight",
    "light heavyweight",
    "middleweight",
    "welterweight",
    "lightweight",
    "featherweight",
    "bantamweight",
    "flyweight",
    "women's bantamweight",
    "women's featherweight",
    "women's flyweight",
    "women's strawweight",
    "women's atomweight",
    "catch weight",
    "open weight",
}


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


def get_html(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.text
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


def extract_athlete_id(obj: Optional[Dict[str, Any]]) -> str:
    """
    ESPN sometimes gives a direct athlete id, and sometimes only a $ref/href.
    This helper tries both.
    """
    if not isinstance(obj, dict):
        return ""

    direct_id = obj.get("id")
    if direct_id:
        return str(direct_id).strip()

    for key in ("$ref", "href"):
        ref = obj.get(key)
        if isinstance(ref, str):
            # Prefer athlete-specific extraction
            m = re.search(r"/athletes/(\d+)", ref)
            if m:
                return m.group(1)

            # Fallback: final numeric segment
            fallback = extract_id_from_ref(ref)
            if fallback:
                return fallback

    return ""


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

    if len(competitors_items) >= 1:
        c1 = competitors_items[0]
        athlete_obj = c1.get("athlete", {}) if isinstance(c1.get("athlete"), dict) else {}
        athlete_payload = get_ref_json(athlete_obj.get("$ref")) if athlete_obj.get("$ref") else None

        red_name = (
            (athlete_payload or {}).get("displayName")
            or athlete_obj.get("displayName")
            or c1.get("displayName")
            or ""
        )

        red = {
            "name": str(red_name).strip(),
            "espn_id": (
                extract_athlete_id(athlete_payload)
                or extract_athlete_id(athlete_obj)
                or extract_athlete_id(c1)
            ),
        }

    if len(competitors_items) >= 2:
        c2 = competitors_items[1]
        athlete_obj = c2.get("athlete", {}) if isinstance(c2.get("athlete"), dict) else {}
        athlete_payload = get_ref_json(athlete_obj.get("$ref")) if athlete_obj.get("$ref") else None

        blue_name = (
            (athlete_payload or {}).get("displayName")
            or athlete_obj.get("displayName")
            or c2.get("displayName")
            or ""
        )

        blue = {
            "name": str(blue_name).strip(),
            "espn_id": (
                extract_athlete_id(athlete_payload)
                or extract_athlete_id(athlete_obj)
                or extract_athlete_id(c2)
            ),
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
        time.sleep(0.10)

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
            c1 = competitors[0] or {}
            athlete = c1.get("athlete", {}) or {}

            red = {
                "name": str(athlete.get("displayName") or c1.get("displayName") or "").strip(),
                "espn_id": extract_athlete_id(athlete) or extract_athlete_id(c1),
            }

        if len(competitors) >= 2:
            c2 = competitors[1] or {}
            athlete = c2.get("athlete", {}) or {}

            blue = {
                "name": str(athlete.get("displayName") or c2.get("displayName") or "").strip(),
                "espn_id": extract_athlete_id(athlete) or extract_athlete_id(c2),
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


def is_record_line(line: str) -> bool:
    return bool(re.fullmatch(r"\d{1,3}-\d{1,3}-\d{1,3}", line.strip()))


def is_round_time_line(line: str) -> bool:
    return bool(re.fullmatch(r"R\d+,\s*\d{1,2}:\d{2}", line.strip(), flags=re.IGNORECASE))


def is_weight_class_line(line: str) -> bool:
    s = line.strip().lower()
    return s in KNOWN_WEIGHT_CLASSES or "weight" in s


def is_name_candidate(line: str) -> bool:
    s = line.strip()
    if not s:
        return False

    lower = s.lower()

    if lower in STOP_MARKERS or lower in SECTION_MARKERS:
        return False
    if lower in {"final", "draw", "sub", "ko/tko", "u dec", "s dec", "m dec", "dq", "nc"}:
        return False
    if lower.startswith("victory by"):
        return False
    if is_record_line(s) or is_round_time_line(s):
        return False
    if re.fullmatch(r"\d+/\d+", s):
        return False
    if re.fullmatch(r"\d+:\d+", s):
        return False
    if re.fullmatch(r"\d+(?:\|\d+)+", s.replace(" ", "")):
        return False
    if len(s) > 40:
        return False
    if not re.fullmatch(r"[A-Za-zÀ-ÿ0-9'\-\. ]+", s):
        return False
    return True


def extract_profile_ids_in_order(soup: BeautifulSoup) -> List[str]:
    ids: List[str] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        match = re.search(r"/mma/fighter/_/id/(\d+)", href)
        if not match:
            continue
        fighter_id = match.group(1)
        if fighter_id in seen:
            continue
        seen.add(fighter_id)
        ids.append(fighter_id)

    return ids


def extract_clean_lines(soup: BeautifulSoup) -> List[str]:
    raw_lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    return [line for line in raw_lines if line]


def parse_fights_from_fightcenter_html(event_id: str) -> List[Dict[str, Any]]:
    html = get_html(FIGHTCENTER_URL.format(event_id=event_id))
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    lines = extract_clean_lines(soup)
    profile_ids = extract_profile_ids_in_order(soup)
    profile_idx = 0

    fights: List[Dict[str, Any]] = []
    idx = 1
    i = 0

    while i < len(lines):
        lower = lines[i].lower()
        if lower in SECTION_MARKERS:
            break
        i += 1

    while i < len(lines):
        line = lines[i].strip()
        lower = line.lower()

        if lower in STOP_MARKERS:
            break

        if lower in SECTION_MARKERS:
            i += 1
            continue

        if not is_weight_class_line(line):
            i += 1
            continue

        weight_class = line
        block: List[str] = []
        j = i + 1

        while j < len(lines):
            nxt = lines[j].strip()
            nxt_lower = nxt.lower()

            if nxt_lower in STOP_MARKERS:
                break
            if nxt_lower in SECTION_MARKERS:
                break
            if is_weight_class_line(nxt):
                break

            block.append(nxt)
            j += 1

        name_positions: List[int] = []
        for k in range(len(block) - 1):
            if is_name_candidate(block[k]) and is_record_line(block[k + 1]):
                name_positions.append(k)

        if len(name_positions) >= 2:
            red_name = block[name_positions[0]].strip()
            blue_name = block[name_positions[1]].strip()

            red_id = profile_ids[profile_idx] if profile_idx < len(profile_ids) else ""
            if profile_idx < len(profile_ids):
                profile_idx += 1

            blue_id = profile_ids[profile_idx] if profile_idx < len(profile_ids) else ""
            if profile_idx < len(profile_ids):
                profile_idx += 1

            fight_status = "scheduled"
            block_lower = [b.lower() for b in block]
            if "final" in block_lower:
                fight_status = "completed"

            fights.append({
                "id": f"{event_id}-{idx}",
                "bout": build_bout_name(red_name, blue_name),
                "red": {
                    "name": red_name,
                    "espn_id": red_id,
                },
                "blue": {
                    "name": blue_name,
                    "espn_id": blue_id,
                },
                "weight_class": normalize_weight_class(weight_class),
                "order": idx,
                "status": fight_status,
                "source": {
                    "provider": "espn",
                    "event_id": str(event_id),
                },
            })
            idx += 1

        i = j

    return fights


def fill_missing_ids_from_html(event_id: str, fights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    If JSON endpoints returned fights but missed many athlete IDs, try to enrich
    them from the public fightcenter page.
    """
    if not fights:
        return fights

    html_fights = parse_fights_from_fightcenter_html(event_id)
    if not html_fights:
        return fights

    html_map = {}
    for hf in html_fights:
        key = hf.get("bout", "").strip().lower()
        if key:
            html_map[key] = hf

    for fight in fights:
        key = fight.get("bout", "").strip().lower()
        if not key or key not in html_map:
            continue

        hf = html_map[key]

        if not (fight.get("red") or {}).get("espn_id"):
            fight.setdefault("red", {})["espn_id"] = (hf.get("red") or {}).get("espn_id", "")

        if not (fight.get("blue") or {}).get("espn_id"):
            fight.setdefault("blue", {})["espn_id"] = (hf.get("blue") or {}).get("espn_id", "")

    return fights


def fetch_event_fights(event_id: str) -> List[Dict[str, Any]]:
    fights = fetch_fights_from_core_event(event_id)
    if fights:
        return fill_missing_ids_from_html(event_id, fights)

    fights = fetch_fights_from_site_summary(event_id)
    if fights:
        return fill_missing_ids_from_html(event_id, fights)

    return parse_fights_from_fightcenter_html(event_id)


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
            with_ids = 0
            total_sides = 0
            for f in fights:
                for side in ("red", "blue"):
                    total_sides += 1
                    if (f.get(side) or {}).get("espn_id"):
                        with_ids += 1
            print(f"Updated {name}: {len(fights)} fights | fighter IDs: {with_ids}/{total_sides}")
        else:
            print(f"No fights found for {name} ({event_id})")

        time.sleep(0.25)

    save_events(payload)
    print(f"Done. Populated fight cards for {updated_count} event(s).")


if __name__ == "__main__":
    main()
