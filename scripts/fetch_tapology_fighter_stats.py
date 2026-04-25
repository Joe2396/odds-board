#!/usr/bin/env python3
import json
import time
import re
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UFCStatsBot/1.0)"
}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def load_fighter_names():
    data = json.loads(EVENTS.read_text(encoding="utf-8"))
    names = set()

    for event in data.get("events", []):
        for fight in event.get("fights", []) or []:
            for side in ("red", "blue"):
                fighter = fight.get(side) or {}
                name = fighter.get("name")
                if name:
                    names.add(name.strip())

    return sorted(names)


def find_tapology_url(name):
    query = urllib.parse.quote(name)
    url = f"https://www.tapology.com/search?term={query}"

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)

        if r.status_code != 200:
            print(f"⚠️ Tapology search HTTP {r.status_code} for {name}")
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Main Tapology search results container
        results = soup.select("div.searchResults a")

        # Fallback: search all links if container selector changes
        if not results:
            results = soup.select("a[href*='/fightcenter/fighters/']")

        for a in results:
            href = a.get("href", "")
            text = a.get_text(" ", strip=True)

            if "/fightcenter/fighters/" not in href:
                continue

            full_url = href
            if href.startswith("/"):
                full_url = "https://www.tapology.com" + href

            print(f"✅ Tapology match for {name}: {text} -> {full_url}")
            return full_url

    except Exception as e:
        print(f"⚠️ Search error for {name}: {e}")

    return None


def clean_text(value):
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def scrape_fighter(url, fallback_name):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)

        if r.status_code != 200:
            print(f"⚠️ Fighter page HTTP {r.status_code}: {url}")
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        name = fallback_name
        h1 = soup.select_one("h1")
        if h1:
            name = clean_text(h1.get_text(" ", strip=True)) or fallback_name

        record = None
        record_el = soup.select_one(".record")
        if record_el:
            record = clean_text(record_el.get_text(" ", strip=True))

        nickname = None
        nick_el = soup.select_one(".fighterNickname")
        if nick_el:
            nickname = clean_text(nick_el.get_text(" ", strip=True))

        page_text = soup.get_text("\n")

        def find_field(label):
            pattern = rf"{label}\s*[:\-]?\s*([^\n]+)"
            m = re.search(pattern, page_text, flags=re.IGNORECASE)
            if m:
                return clean_text(m.group(1))
            return None

        height = find_field("Height")
        weight = find_field("Weight")
        reach = find_field("Reach")
        stance = find_field("Stance")
        age = find_field("Age")
        country = find_field("Nationality") or find_field("Fighting out of")

        return {
            "name": name,
            "slug": slugify(fallback_name),
            "nickname": nickname,
            "record": record,
            "height": height,
            "weight": weight,
            "reach": reach,
            "stance": stance,
            "age": age,
            "country": country,
            "tapology_url": url,
            "recent_fights": []
        }

    except Exception as e:
        print(f"⚠️ Failed scrape for {fallback_name}: {e}")
        return None


def main():
    names = load_fighter_names()
    fighters = []

    print(f"Found {len(names)} fighter names from events.json\n")

    for i, name in enumerate(names, 1):
        print(f"{i}/{len(names)} Searching: {name}")

        url = find_tapology_url(name)

        if not url:
            print(f"❌ No Tapology match for {name}")
            continue

        fighter = scrape_fighter(url, name)

        if fighter:
            fighters.append(fighter)
            print(f"✅ Saved {fighter.get('name')} | record={fighter.get('record')}")
        else:
            print(f"❌ Failed to scrape {name}")

        time.sleep(0.75)

    OUT.write_text(
        json.dumps(
            {
                "generated_at": time.time(),
                "fighters": fighters
            },
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print(f"\n🔥 Done. {len(fighters)} fighters saved to {OUT}")


if __name__ == "__main__":
    main()
