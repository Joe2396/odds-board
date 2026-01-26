import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT_EVENTS = ROOT / "ufc" / "data" / "events.json"
CACHE_PATH = ROOT / "ufc" / "data" / "ufcstats_cache.json"

UPCOMING_URL = "https://ufcstats.com/statistics/events/upcoming"          # :contentReference[oaicite:1]{index=1}
COMPLETED_ALL_URL = "https://ufcstats.com/statistics/events/completed?page=all"  # :contentReference[oaicite:2]{index=2}

# Tweak these if you want to be even gentler
COMPLETED_LIMIT = 3
REQUEST_DELAY_SEC = 0.8
TIMEOUT_SEC = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UFC-Hub-Bot/1.0; +https://github.com/)"
}

def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "item"

def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {"fetched_at_utc": None, "events": {}, "fighters": {}}

def save_cache(cache: dict) -> None:
    cache["fetched_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")

def get_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SEC)
    r.raise_for_status()
    time.sleep(REQUEST_DELAY_SEC)
    return r.text

def parse_events_list(html: str) -> list[dict]:
    """
    UFCStats events list pages are tables with event links.
    We'll extract: name, date, location, url.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table.b-statistics__table-events tbody tr")
    events = []
    for tr in rows:
        a = tr.select_one("a.b-link.b-link_style_black")
        if not a:
            continue
        url = a.get("href", "").strip()
        name = a.get_text(strip=True)

        tds = tr.select("td")
        # Typically: [event name link], [date], [location]
        date = tds[1].get_text(strip=True) if len(tds) > 1 else ""
        location = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        events.append({"name": name, "date": date, "location": location, "url": url})
    return events

def parse_event_page(event_html: str) -> list[dict]:
    """
    Event page contains fight table; each fight row includes:
    - fight details link
    - two fighter links + names
    We'll extract fights with fighter URLs (for later fighter parsing).
    """
    soup = BeautifulSoup(event_html, "html.parser")
    rows = soup.select("table.b-fight-details__table tbody tr.b-fight-details__tr")
    fights = []
    for tr in rows:
        # Fight details link is on the row via <a ... href="fight-details/...">
        fight_link = tr.select_one('a.b-link.b-link_style_black[href*="fight-details"]')
        fight_url = fight_link.get("href", "").strip() if fight_link else ""

        # Fighter links
        fighter_links = tr.select('a.b-link.b-link_style_black[href*="fighter-details"]')
        if len(fighter_links) < 2:
            continue
        fa_url = fighter_links[0].get("href", "").strip()
        fb_url = fighter_links[1].get("href", "").strip()
        fa_name = fighter_links[0].get_text(strip=True)
        fb_name = fighter_links[1].get_text(strip=True)

        # Weight class + rounds are in table cells; we’ll grab what we can safely.
        tds = tr.select("td")
        weight_class = ""
        scheduled_rounds = None
        # UFCStats fight table usually has a weight_class cell and a round cell; positions can vary.
        # We'll do a loose search by text labels/classes.
        wc_td = tr.select_one("td.b-fight-details__table-col.l-page_align_left")
        if wc_td:
            # this td often contains weight class + sometimes other bits; keep it simple
            weight_class = wc_td.get_text(" ", strip=True)

        # Round count is usually the "RND" column (numeric). We'll attempt:
        rnd_td = tr.select_one("td:nth-of-type(9)")  # fallback-ish
        if rnd_td:
            txt = rnd_td.get_text(strip=True)
            if txt.isdigit():
                scheduled_rounds = int(txt)

        fights.append({
            "fight_url": fight_url,
            "fighter_a_url": fa_url,
            "fighter_b_url": fb_url,
            "fighter_a_name": fa_name,
            "fighter_b_name": fb_name,
            "weight_class": weight_class or "—",
            "scheduled_rounds": scheduled_rounds or 3,
            "is_main_event": False,  # we’ll set it later by position
        })

    # mark first fight as main event if list exists (UFCStats lists main card top-first typically)
    if fights:
        fights[0]["is_main_event"] = True
        fights[0]["scheduled_rounds"] = 5  # main event often 5; adjust later if you want smarter logic
    return fights

def parse_fighter_page(fighter_html: str) -> dict:
    """
    Fighter page includes name, nickname, record, height, reach, stance.
    Example fighter-details pages show these fields. :contentReference[oaicite:3]{index=3}
    """
    soup = BeautifulSoup(fighter_html, "html.parser")

    name = soup.select_one("span.b-content__title-highlight")
    name = name.get_text(" ", strip=True) if name else ""

    nickname = soup.select_one("p.b-content__Nickname")
    nickname = nickname.get_text(" ", strip=True) if nickname else ""
    nickname = nickname.replace('"', "").strip()

    record = soup.select_one("span.b-content__title-record")
    record = record.get_text(" ", strip=True).replace("Record:", "").strip() if record else ""

    # Bio list items
    stance = ""
    height_cm = None
    reach_cm = None

    # UFCStats stores Height / Reach in imperial text; we’ll keep simple:
    # - keep raw and only convert if inches are present
    bio_items = soup.select("ul.b-list__box-list li.b-list__box-list-item")
    for li in bio_items:
        label = li.get_text(" ", strip=True)
        if "STANCE:" in label.upper():
            stance = label.split(":")[-1].strip()
        if "HEIGHT:" in label.upper():
            h_txt = label.split(":")[-1].strip()
            # Try convert 5' 11" to cm
            m = re.search(r"(\d+)\s*'\s*(\d+)", h_txt)
            if m:
                ft, inch = int(m.group(1)), int(m.group(2))
                height_cm = round((ft * 12 + inch) * 2.54)
        if "REACH:" in label.upper():
            r_txt = label.split(":")[-1].strip()
            m = re.search(r"(\d+)\s*\"", r_txt)
            if m:
                reach_cm = round(int(m.group(1)) * 2.54)

    return {
        "name": name,
        "nickname": nickname,
        "record": record,
        "stance": stance,
        "height_cm": height_cm,
        "reach_cm": reach_cm,
        "country": "",  # UFCStats doesn’t reliably provide this; we can add later from other sources
        "methods": { "ko_tko_w": 0, "sub_w": 0, "dec_w": 0, "ko_tko_l": 0, "sub_l": 0, "dec_l": 0 },
        "quick": { "finish_rate": None, "avg_fight_min": None, "r1_win_share": None }
    }

def short_id_from_url(url: str) -> str:
    # fighter-details/<hex>
    m = re.search(r"/fighter-details/([a-f0-9]+)$", url)
    if not m:
        return "unknown"
    return m.group(1)[:6]

def main():
    cache = load_cache()

    # 1) Get upcoming + completed(all)
    upcoming = parse_events_list(get_html(UPCOMING_URL))
    completed_all = parse_events_list(get_html(COMPLETED_ALL_URL))
    completed = completed_all[:COMPLETED_LIMIT]

    selected_events = upcoming + completed

    out_events = []
    for e in selected_events:
        event_url = e["url"]
        # cache event fights
        if event_url in cache["events"]:
            fights = cache["events"][event_url]["fights"]
        else:
            fights = parse_event_page(get_html(event_url))
            cache["events"][event_url] = {"fights": fights}

        # Build event slug (stable-ish): name + date
        event_slug = slugify(f"{e['name']}-{e['date']}")
        event_obj = {
            "slug": event_slug,
            "name": e["name"],
            "date": e["date"],
            "location": e["location"],
            "fights": []
        }

        for f in fights:
            # Fighter slugs: slugify(name) + short id to prevent collisions
            fa_sid = short_id_from_url(f["fighter_a_url"])
            fb_sid = short_id_from_url(f["fighter_b_url"])
            fa_slug = slugify(f"{f['fighter_a_name']}-{fa_sid}")
            fb_slug = slugify(f"{f['fighter_b_name']}-{fb_sid}")

            # fetch fighter details (cached)
            if f["fighter_a_url"] in cache["fighters"]:
                fa_profile = cache["fighters"][f["fighter_a_url"]]
            else:
                fa_profile = parse_fighter_page(get_html(f["fighter_a_url"]))
                cache["fighters"][f["fighter_a_url"]] = fa_profile

            if f["fighter_b_url"] in cache["fighters"]:
                fb_profile = cache["fighters"][f["fighter_b_url"]]
            else:
                fb_profile = parse_fighter_page(get_html(f["fighter_b_url"]))
                cache["fighters"][f["fighter_b_url"]] = fb_profile

            # inject slugs
            fa_profile = {**fa_profile, "slug": fa_slug}
            fb_profile = {**fb_profile, "slug": fb_slug}

            fight_slug = slugify(f"{fa_profile['slug']}-vs-{fb_profile['slug']}")

            event_obj["fights"].append({
                "slug": fight_slug,
                "weight_class": f.get("weight_class", "—"),
                "scheduled_rounds": f.get("scheduled_rounds", 3),
                "is_main_event": f.get("is_main_event", False),
                "fighter_a": fa_profile,
                "fighter_b": fb_profile
            })

        out_events.append(event_obj)

    OUT_EVENTS.parent.mkdir(parents=True, exist_ok=True)
    OUT_EVENTS.write_text(json.dumps({"events": out_events}, indent=2), encoding="utf-8")
    save_cache(cache)

    print(f"Wrote {OUT_EVENTS} with {len(out_events)} events")
    print(f"Wrote cache {CACHE_PATH}")

if __name__ == "__main__":
    main()
