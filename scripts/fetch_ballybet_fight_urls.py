#!/usr/bin/env python3
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


print("FETCHING BALLYBET FIGHT URLS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "ballybet_fight_urls.json"

BALLYBET_URLS = [
    "https://www.ballybet.com/online-sports-betting/mma",
    "https://www.ballybet.com/",
]


FIGHT_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,3})\s+(?:v|vs|vs\.|@)\s+"
    r"([A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,3})\b"
)


JUNK_WORDS = [
    "responsible gambling",
    "terms",
    "privacy",
    "casino",
    "bonus",
    "promotions",
    "app store",
    "google play",
    "login",
    "sign up",
    "join",
    "cash out",
    "sportsbook",
    "questions",
    "faq",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def ensure_out_dir():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def looks_like_fight(text):
    text = clean_text(text)
    if not text:
        return False

    low = text.lower()

    if any(j in low for j in JUNK_WORDS):
        return False

    if len(text) > 90:
        return False

    return bool(FIGHT_PATTERN.search(text))


def normalize_fight_name(text):
    text = clean_text(text)
    match = FIGHT_PATTERN.search(text)
    if not match:
        return text

    a = clean_text(match.group(1))
    b = clean_text(match.group(2))
    return f"{a} vs {b}"


def close_cookie_popup(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
        "button:has-text('Agree')",
        "[data-testid='accept-cookies']",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=2500, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def wait_for_page(page):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    time.sleep(4 if is_github_actions() else 2)


def scroll_page(page):
    for _ in range(8):
        try:
            page.mouse.wheel(0, 1400)
            time.sleep(0.8)
        except Exception:
            pass


def extract_links(page):
    found = []

    try:
        links = page.locator("a").all()
    except Exception:
        return found

    for link in links:
        try:
            text = clean_text(link.inner_text(timeout=1000))
            href = link.get_attribute("href", timeout=1000)

            if not text or not href:
                continue

            if not looks_like_fight(text):
                continue

            full_url = urljoin(page.url, href)
            found.append(
                {
                    "fight": normalize_fight_name(text),
                    "url": full_url,
                    "source_text": text,
                    "capture_method": "href",
                }
            )
        except Exception:
            continue

    return found


def extract_text_candidates(page):
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
                text = clean_text(el.inner_text(timeout=700))
                if looks_like_fight(text):
                    candidates.append(
                        {
                            "fight": normalize_fight_name(text),
                            "text": text,
                            "selector": selector,
                        }
                    )
            except Exception:
                continue

    return candidates


def click_capture_urls(page):
    captured = []

    candidates = extract_text_candidates(page)
    print(f"Found {len(candidates)} possible fight text candidates")

    seen_texts = set()

    for candidate in candidates:
        fight = candidate["fight"]
        text = candidate["text"]

        if text in seen_texts:
            continue
        seen_texts.add(text)

        print(f"Trying click capture: {fight}")

        try:
            current_url = page.url

            locator = page.locator(f"text={text}").first
            locator.scroll_into_view_if_needed(timeout=3000)
            time.sleep(0.5)

            locator.click(timeout=5000, force=True)
            time.sleep(3)

            new_url = page.url

            if new_url != current_url:
                captured.append(
                    {
                        "fight": fight,
                        "url": new_url,
                        "source_text": text,
                        "capture_method": "click_url_change",
                    }
                )
                print(f"Captured URL: {fight} -> {new_url}")

                try:
                    page.go_back(timeout=15000)
                    wait_for_page(page)
                    scroll_page(page)
                except Exception:
                    pass

            else:
                print(f"No URL change for: {fight}")

        except Exception as e:
            print(f"Click failed for {fight}: {e}")
            continue

    return captured


def dedupe(items):
    seen = set()
    out = []

    for item in items:
        fight = clean_text(item.get("fight", ""))
        url = clean_text(item.get("url", ""))

        if not fight or not url:
            continue

        key = (fight.lower(), url.split("?")[0].lower())

        if key in seen:
            continue

        seen.add(key)
        item["fight"] = fight
        item["url"] = url
        out.append(item)

    out.sort(key=lambda x: x["fight"].lower())
    return out


def scrape():
    all_items = []

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
            viewport={"width": 1400, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        for url in BALLYBET_URLS:
            print(f"\nOpening: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                wait_for_page(page)
                close_cookie_popup(page)
                scroll_page(page)

                href_items = extract_links(page)
                print(f"Href fights found: {len(href_items)}")
                all_items.extend(href_items)

                click_items = click_capture_urls(page)
                print(f"Click-captured fights found: {len(click_items)}")
                all_items.extend(click_items)

            except PlaywrightTimeoutError:
                print(f"Timeout loading {url}")
            except Exception as e:
                print(f"Error loading {url}: {e}")

        browser.close()

    return dedupe(all_items)


def main():
    ensure_out_dir()

    fights = scrape()

    output = {
        "updated_at": utc_now(),
        "source": "ballybet",
        "count": len(fights),
        "fights": fights,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(fights)} BallyBet fight URLs to {OUT_PATH}")

    if fights:
        print("\nSample fights:")
        for item in fights[:10]:
            print(f"- {item['fight']} -> {item['url']}")
    else:
        print("\nNo BallyBet fights found yet.")


if __name__ == "__main__":
    main()