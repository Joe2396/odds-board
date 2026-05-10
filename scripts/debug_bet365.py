#!/usr/bin/env python3
import re
import time
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


print("DEBUGGING BET365 UFC / MMA")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "bet365_debug.txt"

URLS = [
    "https://www.bet365.com/hub/en-gb/mma/ufc",
    "https://www.bet365.com/#/AS/B18/",
    "https://www.bet365.com/",
]

KEYWORDS = [
    "ufc",
    "mma",
    "mixed martial arts",
    "periera",
    "pereira",
    "gane",
    "topuria",
    "gaethje",
    "omalley",
    "zahabi",
    "lewis",
    "hokit",
]

ODDS_RE = re.compile(r"\b\d+/\d+\b|\bEVS\b|\b[0-9]+\.[0-9]{2}\b", re.I)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def wait(page, seconds=8):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    time.sleep(seconds)


def close_popups(page):
    selectors = [
        "button:has-text('Accept')",
        "button:has-text('Accept All')",
        "button:has-text('I Accept')",
        "button:has-text('Agree')",
        "button:has-text('Continue')",
        "button:has-text('Allow')",
        "text=Accept",
    ]

    for sel in selectors:
        try:
            page.locator(sel).first.click(timeout=2500, force=True)
            print(f"Clicked popup: {sel}")
            time.sleep(1)
        except Exception:
            pass


def scroll(page):
    for _ in range(10):
        try:
            page.mouse.wheel(0, 1200)
            time.sleep(1)
        except Exception:
            pass


def dump_page(page, label):
    try:
        title = page.title()
    except Exception:
        title = ""

    try:
        body = clean(page.locator("body").inner_text(timeout=8000))
    except Exception:
        body = ""

    keyword_hits = [k for k in KEYWORDS if k.lower() in body.lower()]
    odds_hits = ODDS_RE.findall(body)

    block = []
    block.append("=" * 100)
    block.append(f"TIME: {datetime.now(timezone.utc).isoformat()}")
    block.append(f"LABEL: {label}")
    block.append(f"URL: {page.url}")
    block.append(f"TITLE: {title}")
    block.append(f"BODY LENGTH: {len(body)}")
    block.append(f"KEYWORD HITS: {keyword_hits}")
    block.append(f"ODDS COUNT: {len(odds_hits)}")
    block.append(f"ODDS SAMPLE: {odds_hits[:50]}")
    block.append("-" * 100)
    block.append(body[:12000])
    block.append("\n")

    text = "\n".join(block)

    print("\n--- BET365 DEBUG SAMPLE ---")
    print(text[:2500])
    print("--- END DEBUG SAMPLE ---\n")

    with open(OUT_PATH, "a", encoding="utf-8") as f:
        f.write(text)


def try_search(page, query):
    print(f"Trying search: {query}")

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
            time.sleep(1)
            page.keyboard.press("Enter")
            wait(page, 8)
            return True
        except Exception:
            continue

    return False


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if OUT_PATH.exists():
        OUT_PATH.unlink()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1450, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-GB",
            timezone_id="Europe/London",
        )

        page = context.new_page()

        for url in URLS:
            print(f"\nOpening: {url}")

            try:
                page.goto(url, timeout=70000)
                wait(page, 10)
                close_popups(page)
                scroll(page)
                dump_page(page, url)

                for query in ["ufc", "mma"]:
                    if try_search(page, query):
                        close_popups(page)
                        scroll(page)
                        dump_page(page, f"search {query}")

            except Exception as e:
                print(f"ERROR opening {url}: {e}")

        input("Press ENTER to close browser...")
        browser.close()

    print(f"\nSaved debug output to {OUT_PATH}")


if __name__ == "__main__":
    main()