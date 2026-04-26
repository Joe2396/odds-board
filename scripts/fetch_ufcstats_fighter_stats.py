import json
import string
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "ufcstats_fighter_matches.json"

EVENT_URLS = [
    "http://ufcstats.com/event-details/872b018076f831b0",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def normalize_name(name):
    return " ".join(str(name).lower().strip().split())


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
                    index[normalize_name(full_name)] = {
                        "name": full_name,
                        "ufcstats_url": href,
                    }

        time.sleep(0.5)

    return index


def get_fighter_names_from_event_page(event_url):
    print(f"Fetching UFCStats event page: {event_url}")

    response = requests.get(event_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    names = set()

    fighter_links = soup.select("a.b-link.b-link_style_black")

    for link in fighter_links:
        href = link.get("href", "")
        text = link.get_text(" ", strip=True)

        if "/fighter-details/" in href and text:
            names.add(text)

    return names


def main():
    ufcstats_index = build_ufcstats_index()
    print(f"Indexed {len(ufcstats_index)} UFCStats fighters")

    fighter_names = set()

    for event_url in EVENT_URLS:
        fighter_names.update(get_fighter_names_from_event_page(event_url))
        time.sleep(0.5)

    fighter_names = sorted(fighter_names)

    print(f"Found {len(fighter_names)} fighter names from UFCStats event pages")

    if fighter_names:
        print("Sample fighter names:")
        for name in fighter_names[:20]:
            print(f"- {name}")

    matches = {}
    missing = []

    for name in fighter_names:
        key = normalize_name(name)
        info = ufcstats_index.get(key)

        if info:
            matches[name] = {
                "name": info["name"],
                "ufcstats_url": info["ufcstats_url"],
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
        for name in missing:
            print(f"- {name}")


if __name__ == "__main__":
    main()
