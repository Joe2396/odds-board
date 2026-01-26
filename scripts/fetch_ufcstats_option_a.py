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

UPCOMING_URL = "https://ufcstats.com/statistics/events/upcoming"
COMPLETED_ALL_URL = "https://ufcstats.com/statistics/events/completed?page=all"

# Option A settings
COMPLETED_LIMIT = 3

# Be nice / stable
REQUEST_DELAY_SEC = 1.2
TIMEOUT_SEC = 25
RETRIES = 5

SESSION = requests.Session()
SESSION.headers.update(
    {
        # Looks like a normal browser (important for cloud runners)
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
        "Referer": "https://ufcstats.com/",
    }
)


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "item"


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"fetched_at_utc": None, "events": {}, "fighters": {}}


def save_cache(cache: dict) -> None:
    cache["fetched_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def safe_get(url: str, retries: int = RETRIES) -> str:
    """
    Fetch HTML with retry + backoff. Helps with UFCStats refusing connections.
    """
    last_err = None
    for i in range(1, retries + 1):
        try:
            r = SESSION.get(url, timeout=TIMEOUT_SEC)
            # Rate-limit every request (including failures)
            time.sleep(REQUEST_DELAY_SEC)

            # UFCStats usually returns HTML > 1k chars; use sanity check
            if r.status_code == 200 and r.text and len(r.text) > 1000:
                return r.text

            last_err = f"Status {r.status_code}, len={len(r.text) if r.text else 0}"
        except Exception as e:
            last_err = repr(e)

        # Exponential-ish backoff
        sleep_s = 2 * i
        print(f"[WARN] Fetch failed ({i}/{retries}) for {url}: {last_err}. Sleeping {sleep_s}s")
        time.sleep(sleep_s)

    raise RuntimeError(f"Failed to fetch {url} after {retries} retries. Last error: {last_err}")


def parse_events_list(html: str) -> list[dict]:
    """
    Parse UFCStats events list (upcoming/completed) tables.
    Returns list of {name,date,location,url}
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table.b-statistics__table-events tbody tr")
    events = []

    for tr in rows:
        a = tr.select_one("a.b-link.b-link_style_black")
        if not a:
            continue

        url = (a.get("href") or "").strip()
        name = a.get_text(strip=True)

        tds = tr.select("td")
        date = tds[1].get_text(strip=True) if len(tds) > 1 else ""
        location = tds[2].get_text(strip=True) if len(tds) > 2 else ""

        if url and name:
            events.append(
                {
                    "name": name,
                    "date": date,
                    "location": location,
                    "url": url,
                }
            )

    return events


def parse_event_fight_card(event_html: str) -> list[dict]:
    """
    Parse an event page fight table:
    - fight details url
    - fighter A/B urls and names
    - weight class (best-effort)
    """
    soup = BeautifulSoup(event_html, "html.parser")
    rows = soup.select("table.b-fight-details__table tbody tr.b-fight-details__tr")
    fights = []

    for tr in rows:
        fight_link = tr.select_one('a[href*="fight-details"]')
        fight_url = (fight_link.get("href") or "").strip() if fight_link else ""

        fighter_links = tr.select('a[href*="fighter-details"]')
        if len(fighter_links) < 2:
            continue

        fa_url = (fighter_links[0].get("href") or "").strip()
        fb_url = (fighter_links[1].get("href") or "").strip()
        fa_name = fighter_links[0].get_text(strip=True)
        fb_name = fighter_links[1].get_text(strip=True)

        # Weight class: UFCStats often places it in a left-aligned cell
        weight_class = ""
        # best-effort pick: find first left aligned td, then use text
        wc_td = tr.select_one("td.b-fight-details__table-col.l-page_align_left")
        if wc_td:
            weight_class = wc_td.get_text(" ", strip=True)

        fights.append(
            {
                "fight_url": fight_url,
                "fighter_a_url": fa_url,
                "fighter_b_url": fb_url,
                "fighter_a_name": fa_name,
                "fighter_b_name": fb_name,
                "weight_class": weight_class or "—",
                "scheduled_rounds": 3,
                "is_main_event": False,
            }
        )

    # Mark top row as main event (UFCStats usually lists main first)
    if fights:
        fights[0]["is_main_event"] = True
        fights[0]["scheduled_rounds"] = 5

    return fights


def parse_fighter_page(fighter_html: str) -> dict:
    """
    Parse basic fighter fields from fighter-details page.
    """
    soup = BeautifulSoup(fighter_html, "html.parser")

    name_el = soup.select_one("span.b-content__title-highlight")
    name = name_el.get_text(" ", strip=True) if name_el else ""

    nick_el = soup.select_one("p.b-content__Nickname")
    nickname = nick_el.get_text(" ", strip=True).replace('"', "").strip() if nick_el else ""

    rec_el = soup.select_one("span.b-content__title-record")
    record = rec_el.get_text(" ", strip=True).replace("Record:", "").strip() if rec_el else ""

    stance = ""
    height_cm = None
    reach_cm = None

    # Bio list items
    bio_items = soup.select("ul.b-list__box-list li.b-list__box-list-item")
    for li in bio_items:
        text = li.get_text(" ", strip=True)
        up = text.upper()

        if "STANCE:" in up:
            stance = text.split(":", 1)[-1].strip()

        if "HEIGHT:" in up:
            h_txt = text.split(":", 1)[-1].strip()
            # Example: 5' 11"
            m = re.search(r"(\d+)\s*'\s*(\d+)", h_txt)
            if m:
                ft, inch = int(m.group(1)), int(m.group(2))
                height_cm = round((ft * 12 + inch) * 2.54)

        if "REACH:" in up:
            r_txt = text.split(":", 1)[-1].strip()
            # Example: 72"
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
        "country": "",
        # placeholders (we’ll compute full methods/quick stats in the next phase)
        "methods": {"ko_tko_w": 0, "sub_w": 0, "dec_w": 0, "ko_tko_l": 0, "sub_l": 0, "dec_l": 0},
        "quick": {"finish_rate": None, "avg_fight_min": None, "r1_win_share": None},
    }


def short_id_from_url(url: str) -> str:
    m = re.search(r"/fighter-details/([a-f0-9]+)$", url)
    if not m:
        return "unknown"
    return m.group(1)[:6]


def build_event_slug(name: str, date: str) -> str:
    # Add date to keep slugs stable across similarly named events
    return slugify(f"{name}-{date}")


def main():
    cache = load_cache()

    print("[INFO] Fetch upcoming events...")
    upcoming_html = safe_get(UPCOMING_URL)
    upcoming = parse_events_list(upcoming_html)
    print(f"[INFO] Upcoming events found: {len(upcoming)}")

    print("[INFO] Fetch completed events (all)...")
    completed_html = safe_get(COMPLETED_ALL_URL)
    completed_all = parse_events_list(completed_html)
    completed = completed_all[:COMPLETED_LIMIT]
    print(f"[INFO] Completed events selected: {len(completed)} (limit={COMPLETED_LIMIT})")

    selected_events = upcoming + completed
    out_events = []

    for e in selected_events:
        event_url = e["url"]
        print(f"[INFO] Event: {e['name']} ({e['date']})")

        # Cached fight card
        if event_url in cache["events"]:
            fights = cache["events"][event_url].get("fights", [])
        else:
            event_html = safe_get(event_url)
            fights = parse_event_fight_card(event_html)
            cache["events"][event_url] = {"fights": fights}

        event_slug = build_event_slug(e["name"], e["date"])
        event_obj = {
            "slug": event_slug,
            "name": e["name"],
            "date": e["date"],
            "location": e["location"],
            "fights": [],
        }

        for f in fights:
            fa_sid = short_id_from_url(f["fighter_a_url"])
            fb_sid = short_id_from_url(f["fighter_b_url"])
            fa_slug = slugify(f"{f['fighter_a_name']}-{fa_sid}")
            fb_slug = slugify(f"{f['fighter_b_name']}-{fb_sid}")

            # Cached fighter pages
            if f["fighter_a_url"] in cache["fighters"]:
                fa_profile = cache["fighters"][f["fighter_a_url"]]
            else:
                fa_html = safe_get(f["fighter_a_url"])
                fa_profile = parse_fighter_page(fa_html)
                cache["fighters"][f["fighter_a_url"]] = fa_profile

            if f["fighter_b_url"] in cache["fighters"]:
                fb_profile = cache["fighters"][f["fighter_b_url"]]
            else:
                fb_html = safe_get(f["fighter_b_url"])
                fb_profile = parse_fighter_page(fb_html)
                cache["fighters"][f["fighter_b_url"]] = fb_profile

            fa_profile = {**fa_profile, "slug": fa_slug}
            fb_profile = {**fb_profile, "slug": fb_slug}

            fight_slug = slugify(f"{fa_profile['slug']}-vs-{fb_profile['slug']}")

            event_obj["fights"].append(
                {
                    "slug": fight_slug,
                    "weight_class": f.get("weight_class", "—"),
                    "scheduled_rounds": f.get("scheduled_rounds", 3),
                    "is_main_event": f.get("is_main_event", False),
                    "fighter_a": fa_profile,
                    "fighter_b": fb_profile,
                }
            )

        out_events.append(event_obj)

    OUT_EVENTS.parent.mkdir(parents=True, exist_ok=True)
    OUT_EVENTS.write_text(json.dumps({"events": out_events}, indent=2), encoding="utf-8")
    save_cache(cache)

    print(f"[OK] Wrote {OUT_EVENTS} with {len(out_events)} events")
    print(f"[OK] Wrote cache {CACHE_PATH}")


if __name__ == "__main__":
    main()
