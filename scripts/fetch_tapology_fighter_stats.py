#!/usr/bin/env python3
import json
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_fighter_names():
    data = json.loads(EVENTS.read_text(encoding="utf-8"))
    names = set()

    for e in data.get("events", []):
        for f in e.get("fights", []):
            for side in ["red", "blue"]:
                fighter = f.get(side) or {}
                name = fighter.get("name")
                if name:
                    names.add(name.strip())

    return sorted(names)


def search_tapology(name):
    url = f"https://www.tapology.com/search?term={name.replace(' ', '+')}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # first fighter result
        link = soup.select_one("a[href*='/fightcenter/fighters/']")
        if link:
            return "https://www.tapology.com" + link.get("href")

    except Exception:
        return None

    return None


def scrape_fighter(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return {}

        soup = BeautifulSoup(r.text, "html.parser")

        def get_text(label):
            el = soup.find(text=re.compile(label, re.I))
            if el and el.parent:
                val = el.parent.find_next("td")
                if val:
                    return val.text.strip()
            return None

        name = soup.select_one("h1")
        record = soup.select_one(".record")

        return {
            "name": name.text.strip() if name else None,
            "record": record.text.strip() if record else None,
            "height": get_text("Height"),
            "weight": get_text("Weight"),
            "reach": get_text("Reach"),
            "stance": get_text("Stance"),
            "country": get_text("Nationality"),
            "tapology_url": url,
        }

    except Exception:
        return {}


def main():
    names = load_fighter_names()

    fighters = []
    success = 0

    for i, name in enumerate(names, 1):
        print(f"{i}/{len(names)} Searching: {name}")

        url = search_tapology(name)

        if not url:
            print(f"❌ No Tapology match for {name}")
            continue

        data = scrape_fighter(url)

        if data:
            fighters.append(data)
            success += 1
            print(f"✅ {name}")
        else:
            print(f"⚠️ Failed scrape {name}")

        time.sleep(1)  # avoid rate limit

    OUT.write_text(json.dumps({"fighters": fighters}, indent=2), encoding="utf-8")

    print(f"\n🔥 Done. {success} fighters saved.")


if __name__ == "__main__":
    main()
