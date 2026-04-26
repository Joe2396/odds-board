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
    return " ".join(name.lower().strip().split())


def get_fighter_names_from_events():
    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        events = json.load(f)

    names = set()

    for event in events:
        for fight in event.get("fights", []):
            for key in ["fighter1", "fighter2", "red_corner", "blue_corner"]:
                value = fight.get(key)
                if value:
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
                index[normalize_name(full_name)] = href

        time.sleep(0.5)

    return index


def main():
    fighter_names = get_fighter_names_from_events()
    print(f"Found {len(fighter_names)} fighter names from events.json")

    ufcstats_index = build_ufcstats_index()
    print(f"Indexed {len(ufcstats_index)} UFCStats fighters")

    matches = {}
    missing = []

    for name in fighter_names:
        key = normalize_name(name)
        url = ufcstats_index.get(key)

        if url:
            matches[name] = {"ufcstats_url": url}
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
