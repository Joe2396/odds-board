import json
import string
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = ROOT / "ufc" / "data" / "events.json"
OUT_PATH = ROOT / "ufc" / "data" / "ufcstats_fighter_matches.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def normalize_name(name):
    return " ".join(str(name).lower().strip().split())


def get_fighter_names_from_events():
    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("events", []) if isinstance(data, dict) else data

    names = set()

    for event in events:
        if not isinstance(event, dict):
            continue

        fights = event.get("fights", [])

        for fight in fights:
            if not isinstance(fight, dict):
                continue

            # Common formats
            for key in [
                "fighter1",
                "fighter2",
                "red_corner",
                "blue_corner",
                "red",
                "blue",
                "fighter_a",
                "fighter_b",
            ]:
                value = fight.get(key)
                if isinstance(value, str) and value.strip():
                    names.add(value.strip())

            # Array format: fighters: ["Name A", "Name B"]
            fighters = fight.get("fighters")
            if isinstance(fighters, list):
                for fighter in fighters:
                    if isinstance(fighter, str) and fighter.strip():
                        names.add(fighter.strip())
                    elif isinstance(fighter, dict):
                        for key in ["name", "fullName", "displayName"]:
                            value = fighter.get(key)
                            if isinstance(value, str) and value.strip():
                                names.add(value.strip())

            # Nested format: competitors / athletes
            for list_key in ["competitors", "athletes"]:
                people = fight.get(list_key)
                if isinstance(people, list):
                    for person in people:
                        if isinstance(person, dict):
                            for key in ["name", "fullName", "displayName"]:
                                value = person.get(key)
                                if isinstance(value, str) and value.strip():
                                    names.add(value.strip())

    return sorted(names)


def build_ufcstats_index():
    index = {}

    for char in string.ascii_lowercase:
        url = f"http://ufcstats.com/statistics/fighters?char={char}&page=all"
        print(f"Fetching UFCStats index: {char}")

        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("tr.b-statistics__table-row")

        for row in rows:
            links = row.select("a.b-link")
            if len(links) >= 2:
                first = links[0].get_text(strip=True)
                last = links[1].get_text(strip=True)
                href = links[0].get("href")

                full_name = f"{first} {last}".strip()

                if full_name and href:
                    index[normalize_name(full_name)] = href

        time.sleep(0.5)

    return index


def main():
    fighter_names = get_fighter_names_from_events()
    print(f"Found {len(fighter_names)} fighter names from events.json")

    if fighter_names:
        print("Sample fighter names:")
        for name in fighter_names[:10]:
            print(f"- {name}")

    ufcstats_index = build_ufcstats_index()
    print(f"Indexed {len(ufcstats_index)} UFCStats fighters")

    matches = {}
    missing = []

    for name in fighter_names:
        key = normalize_name(name)
        url = ufcstats_index.get(key)

        if url:
            matches[name] = {
                "name": name,
                "ufcstats_url": url
            }
        else:
            missing.append(name)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(matches)} matches to {OUT_PATH}")
    print(f"Missing {len(missing)} fighters")

    if missing:
        print("Missing fighters:")
        for name in missing[:50]:
            print(f"- {name}")


if __name__ == "__main__":
    main()
