import json
import re
import string
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]

MATCHES_OUT_PATH = ROOT / "ufc" / "data" / "ufcstats_fighter_matches.json"
FIGHTERS_OUT_PATH = ROOT / "ufc" / "data" / "fighters.json"

UPCOMING_EVENTS_URL = "http://ufcstats.com/statistics/events/upcoming"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def normalize_name(name):
    return " ".join(str(name).lower().strip().split())


def clean_text(value):
    return re.sub(r"\s+", " ", value).strip() if value else ""


def classify_method(method):
    method = clean_text(method).lower()

    if any(x in method for x in ["ko", "tko"]):
        return "ko_tko"

    if any(x in method for x in ["sub", "submission"]):
        return "sub"

    if any(x in method for x in ["dec", "decision"]):
        return "dec"

    return "other"


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

        time.sleep(0.4)

    return index


def get_upcoming_event_urls():
    print(f"Fetching UFCStats upcoming events: {UPCOMING_EVENTS_URL}")

    response = requests.get(UPCOMING_EVENTS_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    event_urls = []

    for link in soup.select("a.b-link.b-link_style_black"):
        href = link.get("href", "")

        if "/event-details/" in href:
            event_urls.append(href)

    event_urls = sorted(set(event_urls))

    print(f"Found {len(event_urls)} upcoming UFCStats events")

    for url in event_urls:
        print(f"- {url}")

    return event_urls


def get_fighter_names_from_event_page(event_url):
    print(f"Fetching UFCStats event page: {event_url}")

    response = requests.get(event_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    names = set()

    for link in soup.select("a.b-link.b-link_style_black"):
        href = link.get("href", "")
        text = link.get_text(" ", strip=True)

        if "/fighter-details/" in href and text:
            names.add(text)

    print(f"Found {len(names)} fighters on event page")

    return names


def parse_label_value_items(soup):
    data = {}

    for item in soup.select(".b-list__box-list-item"):
        text = clean_text(item.get_text(" ", strip=True))

        if ":" not in text:
            continue

        label, value = text.split(":", 1)
        label = clean_text(label).lower()
        value = clean_text(value)

        data[label] = value

    return data


def extract_fight_history(soup, fighter_name):
    recent_fights = []

    methods = {
        "ko_tko_w": 0,
        "sub_w": 0,
        "dec_w": 0,
        "other_w": 0,
        "ko_tko_l": 0,
        "sub_l": 0,
        "dec_l": 0,
        "other_l": 0,
    }

    rows = soup.select("tr.b-fight-details__table-row.b-fight-details__table-row__hover.js-fight-details-click")

    for row in rows:
        cols = row.select("td.b-fight-details__table-col")

        if len(cols) < 10:
            continue

        result = clean_text(cols[0].get_text(" ", strip=True)).upper()

        fighter_links = cols[1].select("a")
        fighters = [clean_text(a.get_text(" ", strip=True)) for a in fighter_links if clean_text(a.get_text(" ", strip=True))]

        opponent = ""

        if len(fighters) >= 2:
            if normalize_name(fighters[0]) == normalize_name(fighter_name):
                opponent = fighters[1]
            else:
                opponent = fighters[0]

        event = clean_text(cols[6].get_text(" ", strip=True))
        method = clean_text(cols[7].get_text(" ", strip=True))
        round_num = clean_text(cols[8].get_text(" ", strip=True))
        fight_time = clean_text(cols[9].get_text(" ", strip=True))

        method_type = classify_method(method)

        if result == "WIN":
            methods[f"{method_type}_w"] = methods.get(f"{method_type}_w", 0) + 1
        elif result == "LOSS":
            methods[f"{method_type}_l"] = methods.get(f"{method_type}_l", 0) + 1

        recent_fights.append(
            {
                "result": result,
                "opponent": opponent,
                "method": method,
                "round": round_num,
                "time": fight_time,
                "event": event,
            }
        )

    return recent_fights[:10], methods


def scrape_fighter_profile(name, url):
    print(f"Scraping fighter profile: {name}")

    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    fighter = {
        "name": name,
        "ufcstats_url": url,
        "record": "",
        "height": "",
        "weight": "",
        "reach": "",
        "stance": "",
        "dob": "",
        "stats": {},
        "recent_fights": [],
        "methods": {},
    }

    record_el = soup.select_one(".b-content__title-record")

    if record_el:
        fighter["record"] = clean_text(record_el.get_text()).replace("Record:", "").strip()

    fields = parse_label_value_items(soup)

    fighter["height"] = fields.get("height", "")
    fighter["weight"] = fields.get("weight", "")
    fighter["reach"] = fields.get("reach", "")
    fighter["stance"] = fields.get("stance", "")
    fighter["dob"] = fields.get("dob", "")

    fighter["stats"] = {
        "slpm": fields.get("slpm", ""),
        "str_acc": fields.get("str. acc.", ""),
        "sapm": fields.get("sapm", ""),
        "str_def": fields.get("str. def.", ""),
        "td_avg": fields.get("td avg.", ""),
        "td_acc": fields.get("td acc.", ""),
        "td_def": fields.get("td def.", ""),
        "sub_avg": fields.get("sub. avg.", ""),
    }

    recent_fights, methods = extract_fight_history(soup, name)

    fighter["recent_fights"] = recent_fights
    fighter["methods"] = methods

    return fighter


def main():
    ufcstats_index = build_ufcstats_index()
    print(f"Indexed {len(ufcstats_index)} UFCStats fighters")

    event_urls = get_upcoming_event_urls()

    fighter_names = set()

    for event_url in event_urls:
        fighter_names.update(get_fighter_names_from_event_page(event_url))
        time.sleep(0.5)

    fighter_names = sorted(fighter_names)

    print(f"Found {len(fighter_names)} booked fighter names from upcoming UFCStats event pages")

    matches = {}
    fighters = []

    for name in fighter_names:
        key = normalize_name(name)
        info = ufcstats_index.get(key)

        if not info:
            print(f"Missing match: {name}")
            continue

        matches[name] = {
            "name": info["name"],
            "ufcstats_url": info["ufcstats_url"],
        }

        fighter = scrape_fighter_profile(info["name"], info["ufcstats_url"])
        fighters.append(fighter)

        time.sleep(0.5)

    FIGHTERS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(MATCHES_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)

    with open(FIGHTERS_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"fighters": fighters}, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(matches)} matches to {MATCHES_OUT_PATH}")
    print(f"Saved {len(fighters)} fighters to {FIGHTERS_OUT_PATH}")

    print("\nSample fighters:")
    for fighter in fighters[:10]:
        print(
            "-",
            fighter["name"],
            "| record:",
            fighter["record"],
            "| KO/TKO wins:",
            fighter["methods"].get("ko_tko_w", 0),
            "| SUB wins:",
            fighter["methods"].get("sub_w", 0),
            "| DEC wins:",
            fighter["methods"].get("dec_w", 0),
            "| recent fights:",
            len(fighter.get("recent_fights", [])),
        )


if __name__ == "__main__":
    main()
