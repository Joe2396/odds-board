#!/usr/bin/env python3
import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


print("FETCHING LEOVEGAS FIGHT URLS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "leovegas_fight_urls.json"

LEOVEGAS_URLS = [
    "https://www.leovegas.com/en-row/sports",
    "https://www.leovegas.com/en-row/sports/ufc",
    "https://www.leovegas.com/en-row/sports/mixed-martial-arts",
    "https://www.leovegas.com/en-row/sports/mma",
    "https://www.leovegas.com/en-row/sports/search?query=ufc",
    "https://www.leovegas.com/en-row/sports/search?query=mma",
    "https://www.leovegas.com/",
]

FIGHT_RE = re.compile(
    r"\b([A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,3})\s+"
    r"(?:v|vs|vs\.|@)\s+"
    r"([A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,3})\b"
)

JUNK = [
    "casino",
    "slots",
    "roulette",
    "jackpot",
    "blackjack",
    "privacy",
    "terms",
    "promotion",
    "bonus",
    "app",
    "login",
    "sign up",
    "responsible",
    "support",
    "home",
    "open account",
    "page not found",
    "gotten lost",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def is_fight_text(text):
    text = clean(text)

    if not text:
        return False

    low = text.lower()

    if any(j in low for j in JUNK):
        return False

    if len(text) > 120:
        return False

    return bool(FIGHT_RE.search(text))


def normalize_fight(text):
    text = clean(text)
    m = FIGHT_RE.search(text)

    if not m:
        return text

    a = clean(m.group(1))
    b = clean(m.group(2))

    return f"{a} vs {b}"


def close_cookies(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept')",
        "button:has-text('Accept All')",
        "button:has-text('Allow all')",
        "button:has-text('I Accept')",
        "[data-testid='accept-cookies']",
    ]

    for sel in selectors:
        try:
            page.locator(sel).first.click(timeout=2000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def wait(page):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    time.sleep(4)


def scroll(page):
    for _ in range(10):
        try:
            page.mouse.wheel(0, 1500)
            time.sleep(0.7)
        except Exception:
            pass


def dump_debug_text(page, label):
    try:
        body = clean(page.locator("body").inner_text(timeout=5000))
    except Exception:
        body = ""

    print(f"\n--- PAGE DEBUG: {label} ---")
    print(f"URL: {page.url}")
    print(f"TITLE: {page.title()}")
    print(f"BODY SAMPLE: {body[:1000]}")
    print("--- END PAGE DEBUG ---\n")


def search_site(page, query):
    print(f"Trying on-page search for: {query}")

    selectors = [
        "input[type='search']",
        "input[placeholder*='Search']",
        "input[placeholder*='search']",
        "input",
    ]

    for sel in selectors:
        try:
            box = page.locator(sel).first
            box.click(timeout=3000, force=True)
            box.fill(query, timeout=3000)
            time.sleep(2)
            page.keyboard.press("Enter")
            time.sleep(4)
            return True
        except Exception:
            continue

    return False


def extract_links(page):
    found = []

    try:
        links = page.locator("a").all()
    except Exception:
        return found

    for link in links:
        try:
            text = clean(link.inner_text(timeout=1000))
            href = link.get_attribute("href")

            if not text or not href:
                continue

            if not is_fight_text(text):
                continue

            full_url = urljoin(page.url, href)

            found.append({
                "fight": normalize_fight(text),
                "url": full_url,
                "source_text": text,
                "capture_method": "href",
            })

        except Exception:
            continue

    return found


def extract_click_candidates(page):
    candidates = []

    selectors = [
        "button",
        "a",
        "div",
        "span",
        "li",
        "[role='button']",
        "[data-testid]",
    ]

    for selector in selectors:
        try:
            elements = page.locator(selector).all()
        except Exception:
            continue

        for el in elements:
            try:
                text = clean(el.inner_text(timeout=500))

                if is_fight_text(text):
                    candidates.append(text)

            except Exception:
                continue

    return list(set(candidates))


def click_capture(page):
    found = []
    candidates = extract_click_candidates(page)

    print(f"Found {len(candidates)} click candidates")

    for text in candidates:
        try:
            current = page.url
            fight = normalize_fight(text)

            print(f"Trying click: {fight}")

            locator = page.locator(f"text={text}").first
            locator.scroll_into_view_if_needed(timeout=3000)
            time.sleep(0.5)
            locator.click(timeout=4000, force=True)
            time.sleep(3)

            new_url = page.url

            if new_url != current:
                found.append({
                    "fight": fight,
                    "url": new_url,
                    "source_text": text,
                    "capture_method": "click",
                })

                print(f"Captured: {fight}")
                print(new_url)

                try:
                    page.go_back(timeout=10000)
                    wait(page)
                    scroll(page)
                except Exception:
                    pass
            else:
                print(f"No URL change: {fight}")

        except Exception:
            continue

    return found


def collect_from_current_page(page, label):
    scroll(page)

    dump_debug_text(page, label)

    found = []

    href_items = extract_links(page)
    print(f"Href fights found: {len(href_items)}")
    found.extend(href_items)

    click_items = click_capture(page)
    print(f"Click fights found: {len(click_items)}")
    found.extend(click_items)

    return found


def dedupe(items):
    seen = set()
    out = []

    for item in items:
        fight = clean(item.get("fight"))
        url = clean(item.get("url"))

        if not fight or not url:
            continue

        key = (fight.lower(), url.split("?")[0].lower())

        if key in seen:
            continue

        seen.add(key)

        out.append({
            "fight": fight,
            "url": url,
            "source": "leovegas",
            "capture_method": item.get("capture_method", ""),
            "source_text": item.get("source_text", ""),
        })

    out.sort(key=lambda x: x["fight"].lower())
    return out


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    all_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1400, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        for url in LEOVEGAS_URLS:
            print(f"\nOpening: {url}")

            try:
                page.goto(url, timeout=45000)
                wait(page)
                close_cookies(page)

                all_items.extend(collect_from_current_page(page, url))

                for query in ["ufc", "mma"]:
                    did_search = search_site(page, query)
                    if did_search:
                        wait(page)
                        all_items.extend(collect_from_current_page(page, f"search {query}"))

            except Exception as e:
                print(f"ERROR opening {url}: {e}")

        browser.close()

    fights = dedupe(all_items)

    output = {
        "updated_at": utc_now(),
        "source": "leovegas",
        "count": len(fights),
        "fights": fights,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(fights)} LeoVegas fights to {OUT_PATH}")

    if fights:
        print("\nSample fights:")
        for f in fights[:15]:
            print(f"- {f['fight']}")
            print(f"  {f['url']}")
    else:
        print("\nNo LeoVegas fights found.")


if __name__ == "__main__":
    main()