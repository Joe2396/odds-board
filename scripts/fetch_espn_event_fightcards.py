#!/usr/bin/env python3
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

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
    if not isinstance(obj, dict):
        return ""

    direct_id = obj.get("id")
    if direct_id:
        return str(direct_id).strip()

    for key in ("$ref", "href"):
        ref = obj.get(key)
        if isinstance(ref, str):
            m = re.search(r"/athletes/(\d+)", ref)
            if m:
                return m.group(1)

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


def normalize_name(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^a-z0-9à-ÿ ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def name_tokens(text: str) -> List[str]:
    return [t for t in normalize_name(text).split() if t]


def extract_profile_ids_from_tag(tag: Tag) -> List[str]:
    ids: List[str] = []
    seen = set()

    for a in tag.find_all("a", href=True):
        href = a.get("href", "")
        m = re.search(r"/mma/fighter/_/id/(\d+)", href)
        if not m:
            continue
        fid = m.group(1)
        if fid in seen:
            continue
        seen.add(fid)
        ids.append(fid)

    return ids


def extract_profile_links_from_tag(tag: Tag) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    seen = set()

    for a in tag.find_all("a", href=True):
        href = a.get("href", "")
        m = re.search(r"/mma/fighter/_/id/(\d+)(?:/([^/?#]+))?", href)
        if not m:
            continue
        fid = m.group(1)
        slug = (m.group(2) or "").strip().lower()

        key = (fid, slug)
        if key in seen:
            continue
        seen.add(key)

        links.append({"espn_id": fid, "href": href, "slug": slug})

    return links


def slug_matches_name(slug: str, fighter_name: str) -> bool:
    if not slug:
        return False
    slug_norm = slug.replace("-", " ").strip().lower()
    slug_tokens = set(slug_norm.split())
    fighter_tokens = set(name_tokens(fighter_name))
    if not slug_tokens or not fighter_tokens:
        return False

    if fighter_tokens & slug_tokens:
        return True

    fighter_parts = name_tokens(fighter_name)
    if fighter_parts and fighter_parts[-1] in slug_tokens:
        return True

    return False


def find_name_nodes(soup: BeautifulSoup, fighter_name: str) -> List[Tag]:
    target = normalize_name(fighter_name)
    if not target:
        return []

    out: List[Tag] = []
    seen = set()

    for node in soup.find_all(string=True):
        if not isinstance(node, NavigableString):
            continue
        text = str(node).strip()
        if not text:
            continue
        if normalize_name(text) != target:
            continue

        parent = node.parent
        if isinstance(parent, Tag) and id(parent) not in seen:
            out.append(parent)
            seen.add(id(parent))

    return out


def nearest_profile_id_for_name_node(name_node: Tag, fighter_name: str, max_depth: int = 8) -> str:
    current: Optional[Tag] = name_node
    depth = 0

    while isinstance(current, Tag) and depth <= max_depth:
        links = extract_profile_links_from_tag(current)

        if len(links) == 1:
            return links[0]["espn_id"]

        if len(links) > 1:
            matched = [x for x in links if slug_matches_name(x["slug"], fighter_name)]
            if len(matched) == 1:
                return matched[0]["espn_id"]
            if matched:
                return matched[0]["espn_id"]

        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
        depth += 1

    return ""


def extract_local_fighter_ids(soup: BeautifulSoup, red_name: str, blue_name: str) -> tuple[str, str]:
    red_nodes = find_name_nodes(soup, red_name)
    blue_nodes = find_name_nodes(soup, blue_name)

    red_id = ""
    blue_id = ""

    for node in red_nodes:
        red_id = nearest_profile_id_for_name_node(node, red_name)
        if red_id:
            break

    for node in blue_nodes:
        blue_id = nearest_profile_id_for_name_node(node, blue_name)
        if blue_id:
            break

    if red_id and blue_id and red_id != blue_id:
        return red_id, blue_id

    # fallback: find a small shared ancestor with both names and local fighter links
    red_norm = normalize_name(red_name)
    blue_norm = normalize_name(blue_name)
    candidates: List[tuple[int, Tag]] = []

    for tag in soup.find_all(["section", "article", "div", "li"]):
        try:
            text = " ".join(tag.stripped_strings)
        except Exception:
            continue

        text_norm = normalize_name(text)
        if red_norm not in text_norm or blue_norm not in text_norm:
            continue

        ids = extract_profile_ids_from_tag(tag)
        if len(ids) < 2:
            continue

        candidates.append((len(text), tag))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        ids = extract_profile_ids_from_tag(candidates[0][1])
        if len(ids) >= 2 and ids[0] != ids[1]:
            return ids[0], ids[1]

    return red_id, blue_id


def extract_fighter(competitor: Dict[str, Any], session: requests.Session) -> Dict[str, str]:
    competitor = competitor or {}
    competitor = get_ref_json(competitor.get("$ref")) or competitor

    athlete_obj = competitor.get("athlete") or {}
    if isinstance(athlete_obj, dict):
        athlete_payload = get_ref_json(athlete_obj.get("$ref")) if athlete_obj.get("$ref") else None
    else:
        athlete_obj = {}
        athlete_payload = None

    fid = (
        extract_athlete_id(athlete_payload)
        or extract_athlete_id(athlete_obj)
        or extract_athlete_id(competitor)
        or str(competitor.get("id") or "").strip()
    )

    name = (
        (athlete_payload or {}).get("displayName")
        or (athlete_payload or {}).get("fullName")
        or athlete_obj.get("displayName")
        or athlete_obj.get("fullName")
        or competitor.get("displayName")
        or competitor.get("shortName")
        or ""
    )

    return {
        "name": str(name).strip(),
        "espn_id": str(fid).strip(),
    }


def parse_competition_from_core(comp: Dict[str, Any], idx: int, event_id: str, session: requests.Session) -> Optional[Dict[str, Any]]:
    comp_id = str(comp.get("id") or extract_id_from_ref(comp.get("$ref"))).strip()
    competitors_ref = comp.get("competitors", {}).get("$ref") if isinstance(comp.get("competitors"), dict) else None
    status_ref = comp.get("status", {}).get("$ref") if isinstance(comp.get("status"), dict) else None
    notes_ref = comp.get("notes", {}).get("$ref") if isinstance(comp.get("notes"), dict) else None

    competitors_payload = get_ref_json(competitors_ref) if competitors_ref else None
    competitors_items = competitors_payload.get("items", []) if competitors_payload else []

    red = {"name": "", "espn_id": ""}
    blue = {"name": "", "espn_id": ""}

    if len(competitors_items) >= 1:
        red = extract_fighter(competitors_items[0], session)

    if len(competitors_items) >= 2:
        blue = extract_fighter(competitors_items[1], session)

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

    return {
        "id": comp_id or f"{event_id}-{idx}",
        "bout": build_bout_name(red["name"], blue["name"]),
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


def fetch_fights_from_core_event(event_id: str, session: requests.Session) -> List[Dict[str, Any]]:
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
        parsed = parse_competition_from_core(comp, idx, event_id, session)
        if parsed:
            fights.append(parsed)
        time.sleep(0.10)

    return fights


def fetch_fights_from_site_summary(event_id: str, session: requests.Session) -> List[Dict[str, Any]]:
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
            red = extract_fighter(competitors[0], session)

        if len(competitors) >= 2:
            blue = extract_fighter(competitors[1], session)

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

        fights.append(
            {
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
            }
        )

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


def extract_clean_lines(soup: BeautifulSoup) -> List[str]:
    raw_lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    return [line for line in raw_lines if line]


def parse_fights_from_fightcenter_html(event_id: str) -> List[Dict[str, Any]]:
    html = get_html(FIGHTCENTER_URL.format(event_id=event_id))
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    lines = extract_clean_lines(soup)

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

            red_id, blue_id = extract_local_fighter_ids(soup, red_name, blue_name)

            fight_status = "scheduled"
            block_lower = [b.lower() for b in block]
            if "final" in block_lower:
                fight_status = "completed"

            fights.append(
                {
                    "id": f"{event_id}-{idx}",
                    "bout": build_bout_name(red_name, blue_name),
                    "red": {"name": red_name, "espn_id": red_id},
                    "blue": {"name": blue_name, "espn_id": blue_id},
                    "weight_class": normalize_weight_class(weight_class),
                    "order": idx,
                    "status": fight_status,
                    "source": {
                        "provider": "espn",
                        "event_id": str(event_id),
                    },
                }
            )
            idx += 1

        i = j

    return fights


def fill_missing_ids_from_html(event_id: str, fights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    html_fights = parse_fights_from_fightcenter_html(event_id)
    if not html_fights:
        return fights

    min_len = min(len(fights), len(html_fights))

    for i in range(min_len):
        f = fights[i]
        hf = html_fights[i]

        if not (f.get("red") or {}).get("espn_id"):
            f.setdefault("red", {})["espn_id"] = (hf.get("red") or {}).get("espn_id", "")

        if not (f.get("blue") or {}).get("espn_id"):
            f.setdefault("blue", {})["espn_id"] = (hf.get("blue") or {}).get("espn_id", "")

        if not (f.get("red") or {}).get("name"):
            f.setdefault("red", {})["name"] = (hf.get("red") or {}).get("name", "")

        if not (f.get("blue") or {}).get("name"):
            f.setdefault("blue", {})["name"] = (hf.get("blue") or {}).get("name", "")

        if not f.get("bout"):
            f["bout"] = hf.get("bout", "")

        if not f.get("weight_class"):
            f["weight_class"] = hf.get("weight_class", "")

    return fights


def fetch_event_fights(event_id: str, session: requests.Session) -> List[Dict[str, Any]]:
    fights = fetch_fights_from_core_event(event_id, session)
    if fights:
        return fill_missing_ids_from_html(event_id, fights)

    fights = fetch_fights_from_site_summary(event_id, session)
    if fights:
        return fill_missing_ids_from_html(event_id, fights)

    return parse_fights_from_fightcenter_html(event_id)


def looks_suspicious(existing_fights: List[Dict[str, Any]], new_fights: List[Dict[str, Any]]) -> bool:
    if not new_fights:
        return True

    if existing_fights and len(new_fights) < max(1, len(existing_fights) // 2):
        return True

    valid_bouts = sum(1 for f in new_fights if isinstance(f, dict) and f.get("bout"))
    if valid_bouts == 0:
        return True

    return False


def main() -> None:
    payload = load_events()
    events = payload.get("events", []) or []

    if not events:
        print("No events found in ufc/data/events.json")
        return

    session = requests.Session()
    session.headers.update(HEADERS)

    updated_count = 0

    for ev in events:
        event_id = str(((ev.get("source") or {}).get("event_id")) or "").strip()
        name = str(ev.get("name") or "").strip()

        if not event_id:
            print(f"Skipping {name or '(unnamed event)'}: missing source.event_id")
            continue

        existing_fights = ev.get("fights", []) or []
        new_fights = fetch_event_fights(event_id, session)

        print(f"{name}: existing fights={len(existing_fights)} | new fights={len(new_fights)}")

        if looks_suspicious(existing_fights, new_fights):
            print(f"Keeping existing fights for {name}: new scrape looked suspicious")
            fights = existing_fights
        else:
            fights = new_fights

        ev["fights"] = fights

        if fights:
            updated_count += 1
            with_ids = 0
            total_sides = 0
            for fight in fights:
                for side in ("red", "blue"):
                    total_sides += 1
                    if (fight.get(side) or {}).get("espn_id"):
                        with_ids += 1
            print(f"Updated {name}: {len(fights)} fights | fighter IDs: {with_ids}/{total_sides}")
        else:
            print(f"No fights found for {name} ({event_id})")

        time.sleep(0.25)

    save_events(payload)
    print(f"Done. Populated fight cards for {updated_count} event(s).")


if __name__ == "__main__":
    main()
