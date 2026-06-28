import json
import re
import string
import time
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

EVENTS_JSON = ROOT / "ufc" / "data" / "events.json"
MATCHES_OUT_PATH = ROOT / "ufc" / "data" / "ufcstats_fighter_matches.json"
FIGHTERS_OUT_PATH = ROOT / "ufc" / "data" / "fighters.json"

UPCOMING_EVENTS_URL = "http://ufcstats.com/statistics/events/upcoming"

MIN_INDEXED_FIGHTERS = 100
MIN_SAVED_FIGHTERS = 20


def strip_accents(text):
    """Strip accented characters — e.g. Benoît -> Benoit"""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def normalize_name(name):
    name = str(name or "").lower().strip()
    name = strip_accents(name)
    return " ".join(name.split())


def clean_text(value):
    return re.sub(r"\s+", " ", value).strip() if value else ""


def get_corner_name(corner):
    if isinstance(corner, dict):
        return corner.get("name") or ""
    if isinstance(corner, str):
        return corner
    return ""


def collect_names_from_events_json():
    data = {}
    if EVENTS_JSON.exists():
        data = json.loads(EVENTS_JSON.read_text(encoding="utf-8"))

    names = set()
    for event in data.get("events", []) or []:
        for fight in event.get("fights", []) or []:
            red = clean_text(get_corner_name(fight.get("red")))
            blue = clean_text(get_corner_name(fight.get("blue")))
            if red and red.upper() != "TBA":
                names.add(red)
            if blue and blue.upper() != "TBA":
                names.add(blue)

    print(f"Found {len(names)} fighter names from events.json")
    return names


def classify_method(method):
    method = clean_text(method).lower()
    if any(x in method for x in ["ko", "tko"]):
        return "ko_tko"
    if any(x in method for x in ["sub", "submission"]):
        return "sub"
    if any(x in method for x in ["dec", "decision"]):
        return "dec"
    return "other"


def build_ufcstats_index(page):
    index = {}

    for char in string.ascii_lowercase:
        url = f"http://ufcstats.com/statistics/fighters?char={char}&page=all"
        print(f"Fetching UFCStats index: {char}")

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            html = page.content()
        except Exception as e:
            print(f"Warning: failed index {char}: {e}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("tr.b-statistics__table-row")

        for row in rows:
            links = row.select("a.b-link")
            if len(links) >= 2:
                first = links[0].get_text(strip=True)
                last = links[1].get_text(strip=True)
                href = links[0].get("href")
                full_name = f"{first} {last}".strip()

                if full_name and href and "/fighter-details/" in href:
                    index[normalize_name(full_name)] = {
                        "name": full_name,
                        "ufcstats_url": href,
                    }

        time.sleep(0.4)

    return index


def get_upcoming_event_urls(page):
    print(f"Fetching UFCStats upcoming events: {UPCOMING_EVENTS_URL}")
    page.goto(UPCOMING_EVENTS_URL, wait_until="networkidle", timeout=30000)
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    event_urls = []

    for link in soup.select("a.b-link.b-link_style_black"):
        href = link.get("href", "")
        if "/event-details/" in href:
            event_urls.append(href)

    event_urls = sorted(set(event_urls))
    print(f"Found {len(event_urls)} upcoming UFCStats events")
    return event_urls


def get_fighter_names_from_event_page(page, event_url):
    print(f"Fetching UFCStats event page: {event_url}")
    page.goto(event_url, wait_until="networkidle", timeout=30000)
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    names = set()

    for link in soup.select("a.b-link.b-link_style_black"):
        href = link.get("href", "")
        text = link.get_text(" ", strip=True)
        if "/fighter-details/" in href and text:
            names.add(text)

    print(f"Found {len(names)} fighters on UFCStats event page")
    return names


def parse_label_value_items(soup):
    data = {}
    for item in soup.select(".b-list__box-list-item"):
        text = clean_text(item.get_text(" ", strip=True))
        if ":" not in text:
            continue
        label, value = text.split(":", 1)
        data[clean_text(label).lower()] = clean_text(value)
    return data


def extract_fight_history(soup, fighter_name):
    recent_fights = []
    methods = {
        "ko_tko_w": 0, "sub_w": 0, "dec_w": 0, "other_w": 0,
        "ko_tko_l": 0, "sub_l": 0, "dec_l": 0, "other_l": 0,
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

        recent_fights.append({
            "result": result,
            "opponent": opponent,
            "method": method,
            "round": round_num,
            "time": fight_time,
            "event": event,
        })

    return recent_fights[:10], methods


def scrape_fighter_profile(page, name, url):
    print(f"Scraping fighter profile: {name}")
    page.goto(url, wait_until="networkidle", timeout=30000)
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        ufcstats_index = build_ufcstats_index(page)
        print(f"Indexed {len(ufcstats_index)} UFCStats fighters")

        if len(ufcstats_index) < MIN_INDEXED_FIGHTERS:
            print(f"❌ Refusing to continue: UFCStats index only returned {len(ufcstats_index)} fighters")
            print("Existing fighters.json has NOT been overwritten.")
            browser.close()
            raise SystemExit(1)

        fighter_names = set()
        fighter_names.update(collect_names_from_events_json())

        try:
            event_urls = get_upcoming_event_urls(page)
            for event_url in event_urls:
                fighter_names.update(get_fighter_names_from_event_page(page, event_url))
                time.sleep(0.5)
        except Exception as e:
            print(f"Warning: UFCStats upcoming scrape failed: {e}")

        fighter_names = sorted(fighter_names)
        print(f"Found {len(fighter_names)} total booked fighter names")

        matches = {}
        fighters = []

        for name in fighter_names:
            key = normalize_name(name)
            info = ufcstats_index.get(key)

            if not info:
                print(f"Missing UFCStats match: {name}")
                continue

            matches[name] = {
                "name": info["name"],
                "ufcstats_url": info["ufcstats_url"],
            }

            try:
                fighter = scrape_fighter_profile(page, info["name"], info["ufcstats_url"])
                fighters.append(fighter)
            except Exception as e:
                print(f"Warning: failed fighter profile {name}: {e}")

            time.sleep(0.5)

        browser.close()

    if len(fighters) < MIN_SAVED_FIGHTERS:
        print(f"❌ Refusing to overwrite fighters.json with only {len(fighters)} fighters")
        print("Existing fighters.json has NOT been overwritten.")
        raise SystemExit(1)

    FIGHTERS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(MATCHES_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)

    with open(FIGHTERS_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"fighters": fighters}, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(matches)} matches to {MATCHES_OUT_PATH}")
    print(f"Saved {len(fighters)} fighters to {FIGHTERS_OUT_PATH}")

    print("\nSample fighters:")
    for fighter in fighters[:5]:
        print(
            "-", fighter["name"],
            "| record:", fighter["record"],
            "| KO/TKO wins:", fighter["methods"].get("ko_tko_w", 0),
            "| recent fights:", len(fighter.get("recent_fights", [])),
        )


if __name__ == "__main__":
    main()