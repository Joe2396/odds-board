#!/usr/bin/env python3
import json
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "ufc" / "data" / "events.json"
OUT = ROOT / "ufc" / "data" / "fighters.json"

HEADERS = {"User-Agent": "Mozilla/5.0"}


# -------------------------
# LOAD FIGHTER NAMES
# -------------------------
def load_fighter_names():
    data = json.loads(EVENTS.read_text(encoding="utf-8"))
    names = set()

    for ev in data.get("events", []):
        for f in ev.get("fights", []):
            if f.get("red", {}).get("name"):
                names.add(f["red"]["name"].strip())
            if f.get("blue", {}).get("name"):
                names.add(f["blue"]["name"].strip())

    return sorted(names)


# -------------------------
# FIND TAPOLOGY PROFILE
# -------------------------
def find_tapology_url(name):
    query = urllib.parse.quote(name)
    url = f"https://www.tapology.com/search?term={query}"

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Tapology fighter links look like:
        # /fightcenter/fighters/1234-name
        links = soup.select("a[href*='/fightcenter/fighters/']")

        for a in links:
            href = a.get("href")
            if "/fightcenter/fighters/" in href:
                return "https://www.tapology.com" + href

    except Exception:
        return None

    return None


# -------------------------
# SCRAPE FIGHTER PAGE
# -------------------------
def scrape_fighter(url, name):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # record
        record = None
        rec = soup.select_one(".record")
        if rec:
            record = rec.get_text(strip=True)

        # nickname
        nickname = None
        nick = soup.select_one(".fighterNickname")
        if nick:
            nickname = nick.get_text(strip=True)

        # stats block
        stats = soup.select(".details_two_columns .details")

        height = weight = reach = stance = None

        for s in stats:
            text = s.get_text(" ", strip=True)

            if "Height" in text:
                height = text.replace("Height", "").strip()
            elif "Weight" in text:
                weight = text.replace("Weight", "").strip()
            elif "Reach" in text:
                reach = text.replace("Reach", "").strip()
            elif "Stance" in text:
                stance = text.replace("Stance", "").strip()

        return {
            "name": name,
            "nickname": nickname,
            "record": record,
            "height": height,
            "weight": weight,
            "reach": reach,
            "stance": stance,
            "source_url": url,
        }

    except Exception:
        return None


# -------------------------
# MAIN
# -------------------------
def main():
    names = load_fighter_names()

    fighters = []
    print(f"Found {len(names)} fighters\n")

    for i, name in enumerate(names, 1):
        print(f"{i}/{len(names)} Searching: {name}")

        url = find_tapology_url(name)

        if not url:
            print(f"❌ No Tapology match for {name}")
            continue

        fighter = scrape_fighter(url, name)

        if fighter:
            fighters.append(fighter)
            print(f"✅ {name}")
        else:
            print(f"❌ Failed scrape for {name}")

        time.sleep(0.5)

    OUT.write_text(json.dumps({"fighters": fighters}, indent=2), encoding="utf-8")

    print(f"\n🔥 Done. {len(fighters)} fighters saved.")


if __name__ == "__main__":
    main()
