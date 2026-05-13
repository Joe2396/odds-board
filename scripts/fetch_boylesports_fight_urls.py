from playwright.sync_api import sync_playwright
import json
import time
import os
import re
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING CURRENT BOYLESPORTS FIGHT URLS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "boylesports_fight_urls.json"
EVENTS_PATH = ROOT / "ufc" / "data" / "events.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

BOYLESPORTS_MMA_URLS = [
    "https://www.boylesports.com/sports/ufc-mma",
    "https://www.boylesports.com/sports/ufc-mma/day",
    "https://www.boylesports.com/sports/ufc-mma/competition",
]


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def fight_key(name):
    text = str(name or "").lower()
    text = text.replace(" versus ", " v ")
    text = text.replace(" vs ", " v ")
    text = text.replace("–", " ")
    text = text.replace("—", " ")
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if " v " in text:
        left, right = text.split(" v ", 1)
        fighters = sorted([left.strip(), right.strip()])
        return " v ".join(fighters)

    return text


def get_corner_name(corner):
    if isinstance(corner, dict):
        return corner.get("name") or ""
    if isinstance(corner, str):
        return corner
    return ""


def load_current_event_fight_keys():
    keys = set()

    if not EVENTS_PATH.exists():
        print(f"WARNING: Missing events file: {EVENTS_PATH}")
        return keys

    try:
        data = json.load(open(EVENTS_PATH, encoding="utf-8"))
    except Exception as e:
        print(f"WARNING: Could not read events.json: {e}")
        return keys

    for event in data.get("events", []) or []:
        for fight in event.get("fights", []) or []:
            red = get_corner_name(fight.get("red", {}))
            blue = get_corner_name(fight.get("blue", {}))

            if red and blue:
                keys.add(fight_key(f"{red} v {blue}"))

    print(f"Loaded {len(keys)} current ESPN fight keys")
    return keys


def close_cookie_popup(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
        "button:has-text('Got it')",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass

    print("No cookie popup found")


def clean_fight_name_from_text(text):
    text = str(text or "").strip()
    text = re.sub(r"\s+", " ", text)

    junk_phrases = [
        "Cash Out",
        "All Markets",
        "Popular",
        "UFC and MMA",
        "UFC",
        "MMA",
        "To Win Fight",
        "Show UFC Stats",
        "Bet Builder",
        "Specials",
        "Boost",
        "MVP",
        "Competition",
        "Day",
        "Today",
        "Tomorrow",
        "Live",
    ]

    for phrase in junk_phrases:
        text = text.replace(phrase, "")

    return text.strip(" -–—|").strip()


def clean_fight_name_from_url(url):
    slug = str(url or "").rstrip("/").split("/")[-1]
    slug = re.sub(r"\?.*$", "", slug)
    slug = slug.replace("-v-", "-vs-")
    slug = slug.replace("-vs.", "-vs-")
    slug = re.sub(r"-\d+$", "", slug)

    name = slug.replace("-", " ").title()
    name = re.sub(r"^Fights\s+", "", name, flags=re.I)
    name = re.sub(r"^Ufc\s+", "", name, flags=re.I)

    return re.sub(r"\s+", " ", name).strip()


def looks_like_fight_name(name):
    n = str(name or "").lower()

    if not name or len(name) < 5:
        return False

    bad_terms = [
        "ufc and mma",
        "competition",
        "in play",
        "fixtures",
        "popular",
        "all markets",
        "cash out",
        "to win fight",
        "show ufc stats",
        "specials",
        "boost",
        "mvp",
        "freedom fights",
        "day",
        "outright",
    ]

    if any(term in n for term in bad_terms):
        return False

    return " v " in n or " vs " in n or "\n" in str(name)


def normalize_fight_name(name):
    name = str(name or "").strip()
    name = name.replace("\r\n", "\n").replace("\r", "\n")

    parts = [p.strip() for p in name.split("\n") if p.strip()]

    if len(parts) >= 2:
        name = f"{parts[0]} vs {parts[1]}"
    else:
        name = " ".join(name.split())
        name = re.sub(r"\s+v\s+", " vs ", name, flags=re.I)

    return clean_fight_name_from_text(name)


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        html_path = DEBUG_DIR / f"{label}.html"
        png_path = DEBUG_DIR / f"{label}.png"

        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(png_path), full_page=True)

        print(f"Saved debug HTML: {html_path}")
        print(f"Saved debug screenshot: {png_path}")
    except Exception as e:
        print(f"Could not save debug files: {e}")


def scroll_page(page):
    print("Scrolling page to load fights...")

    last_height = 0

    for _ in range(12):
        page.mouse.wheel(0, 2500)
        time.sleep(1)

        try:
            height = page.evaluate("document.body.scrollHeight")
            print(f"Page height: {height}")

            if height == last_height:
                time.sleep(1)

            last_height = height
        except Exception:
            pass


def collect_links(page):
    hrefs = []

    locators = [
        "a[href*='/sports/ufc-mma/competition/']",
        "a[href*='/sports/ufc-mma/']",
        "a[href*='ufc-mma']",
    ]

    blocked_exact = {
        "https://www.boylesports.com/sports/ufc-mma",
        "https://www.boylesports.com/sports/ufc-mma/day",
        "https://www.boylesports.com/sports/ufc-mma/in-play",
        "https://www.boylesports.com/sports/ufc-mma/competition",
    }

    blocked_terms = [
        "special",
        "boost",
        "mvp",
        "outright",
        "freedom-fights",
        "in-play",
    ]

    for selector in locators:
        try:
            links = page.locator(selector)
            count = links.count()
            print(f"{selector}: {count} links")

            for i in range(count):
                try:
                    link = links.nth(i)
                    href = link.get_attribute("href")
                    text = link.inner_text(timeout=2000)

                    if not href:
                        continue

                    if href.startswith("/"):
                        href = "https://www.boylesports.com" + href

                    href = href.split("?")[0].rstrip("/")

                    if "boylesports.com" not in href:
                        continue

                    if "/sports/ufc-mma/" not in href:
                        continue

                    if href in blocked_exact:
                        continue

                    if any(term in href.lower() for term in blocked_terms):
                        continue

                    hrefs.append({
                        "url": href,
                        "text": text,
                    })

                except Exception:
                    continue

        except Exception:
            continue

    return hrefs


def dedupe_and_filter_fights(raw_links, current_fight_keys):
    fights = []
    seen_urls = set()
    seen_keys = set()

    for item in raw_links:
        url = item.get("url")
        text = item.get("text") or ""

        if not url or url in seen_urls:
            continue

        lower_name = text.lower()
        lower_url = url.lower()

        skip_terms = [
            "special",
            "boost",
            "mvp",
            "day",
            "competition",
            "outright",
            "freedom-fights",
            "in-play",
        ]

        if any(term in lower_name for term in skip_terms):
            continue

        if any(term in lower_url for term in skip_terms):
            continue

        name_from_text = normalize_fight_name(text)
        name_from_url = clean_fight_name_from_url(url)

        fight_name = name_from_text if looks_like_fight_name(name_from_text) else name_from_url
        fight_name = normalize_fight_name(fight_name)

        key = fight_key(fight_name)

        if not key or " v " not in key:
            continue

        if current_fight_keys and key not in current_fight_keys:
            print(f"Skipping stale/non-current BoyleSports fight: {fight_name}")
            continue

        if key in seen_keys:
            continue

        seen_urls.add(url)
        seen_keys.add(key)

        fights.append({
            "fight": fight_name,
            "url": url,
        })

    return fights


def save_output(fights):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "updated_at": now_iso(),
        "source": "boylesports",
        "count": len(fights),
        "fights": fights,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved to {OUT_PATH}")


def main():
    current_fight_keys = load_current_event_fight_keys()
    all_raw_links = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_github_actions(),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1365, "height": 768},
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )

        page = context.new_page()

        for index, url in enumerate(BOYLESPORTS_MMA_URLS, start=1):
            try:
                print(f"\nOpening: {url}")
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                time.sleep(8)

                close_cookie_popup(page)
                time.sleep(2)

                scroll_page(page)
                save_debug(page, f"boylesports_page_{index}")

                raw_links = collect_links(page)
                print(f"Raw fight links found on page: {len(raw_links)}")

                all_raw_links.extend(raw_links)

            except Exception as e:
                print(f"Error fetching {url}: {e}")
                save_debug(page, f"boylesports_error_{index}")

        fights = dedupe_and_filter_fights(all_raw_links, current_fight_keys)

        print(f"\nFound {len(fights)} current BoyleSports fights")

        for fight in fights:
            print(f"- {fight['fight']}")

        save_output(fights)

        if not is_github_actions():
            input("\nPress Enter to close browser...")

        browser.close()


if __name__ == "__main__":
    main()