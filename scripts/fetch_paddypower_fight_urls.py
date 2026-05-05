from playwright.sync_api import sync_playwright
import json
import time
import os
import re
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING PADDYPOWER FIGHT URLS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "paddypower_fight_urls.json"

PADDYPOWER_MMA_URLS = [
    "https://www.paddypower.com/mixed-martial-arts/ufc-matches",
    "https://www.paddypower.com/mixed-martial-arts",
]


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def close_cookie_popup(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
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
        "UFC Matches",
        "Mixed Martial Arts",
        "Fight Result",
    ]

    for phrase in junk_phrases:
        text = text.replace(phrase, "")

    text = text.strip(" -–—|")

    return text.strip()


def clean_fight_name_from_url(url):
    slug = str(url or "").rstrip("/").split("/")[-1]

    # Remove trailing PaddyPower numeric id
    slug = re.sub(r"-\d+$", "", slug)

    # Convert v to vs only when used as separator
    slug = slug.replace("-v-", "-vs-")

    name = slug.replace("-", " ").title()
    name = re.sub(r"\s+", " ", name).strip()

    return name


def looks_like_fight_name(name):
    n = str(name or "").lower()

    if not name or len(name) < 5:
        return False

    bad_terms = [
        "ufc matches",
        "mixed martial arts",
        "popular",
        "all markets",
        "cash out",
        "fight result",
        "method of victory",
        "total rounds",
        "go the distance",
    ]

    if any(term in n for term in bad_terms):
        return False

    return " v " in n or " vs " in n or "\n" in str(name)


def normalize_fight_name(name):
    name = str(name or "").strip()

    # PaddyPower sometimes returns fighter names on separate lines.
    name = name.replace("\r\n", "\n").replace("\r", "\n")
    parts = [p.strip() for p in name.split("\n") if p.strip()]

    if len(parts) >= 2:
        name = f"{parts[0]} vs {parts[1]}"
    else:
        name = " ".join(name.split())
        name = re.sub(r"\s+v\s+", " vs ", name, flags=re.I)

    name = clean_fight_name_from_text(name)

    return name


def scroll_page(page):
    print("Scrolling page to load fights...")

    last_height = 0

    for _ in range(12):
        page.mouse.wheel(0, 3000)
        time.sleep(1)

        try:
            height = page.evaluate("document.body.scrollHeight")
            if height == last_height:
                time.sleep(1)
            last_height = height
        except Exception:
            pass


def collect_links(page):
    hrefs = []

    locators = [
        "a[href*='/ufc-matches/']",
        "a[href*='ufc-matches']",
        "a[href*='/mixed-martial-arts/']",
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
                        href = "https://www.paddypower.com" + href

                    if "paddypower.com" not in href:
                        continue

                    if "/ufc-matches/" not in href:
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


def dedupe_fights(raw_links):
    fights = []
    seen_urls = set()

    for item in raw_links:
        url = item.get("url")
        text = item.get("text") or ""

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        name_from_text = normalize_fight_name(text)
        name_from_url = clean_fight_name_from_url(url)

        fight_name = name_from_text if looks_like_fight_name(name_from_text) else name_from_url

        fight_name = normalize_fight_name(fight_name)

        fights.append({
            "fight": fight_name,
            "url": url,
        })

    return fights


def save_output(fights):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "paddypower",
        "count": len(fights),
        "fights": fights,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved to {OUT_PATH}")


def main():
    all_raw_links = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_github_actions()
        )

        page = browser.new_page(
            viewport={"width": 1400, "height": 900}
        )

        for url in PADDYPOWER_MMA_URLS:
            try:
                print(f"\nOpening: {url}")
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                time.sleep(5)

                close_cookie_popup(page)
                scroll_page(page)

                raw_links = collect_links(page)
                print(f"Raw fight links found on page: {len(raw_links)}")

                all_raw_links.extend(raw_links)

            except Exception as e:
                print(f"Error fetching {url}: {e}")

        fights = dedupe_fights(all_raw_links)

        print(f"\nFound {len(fights)} unique fights")

        for fight in fights:
            print(f"- {fight['fight']}")

        save_output(fights)

        if not is_github_actions():
            input("\nPress Enter to close browser...")

        browser.close()


if __name__ == "__main__":
    main()