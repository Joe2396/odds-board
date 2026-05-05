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
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

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

    return text.strip(" -–—|").strip()


def clean_fight_name_from_url(url):
    slug = str(url or "").rstrip("/").split("/")[-1]
    slug = re.sub(r"-\d+$", "", slug)
    slug = slug.replace("-v-", "-vs-")

    name = slug.replace("-", " ").title()
    return re.sub(r"\s+", " ", name).strip()


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

    for _ in range(15):
        page.mouse.wheel(0, 3000)
        time.sleep(1)

        try:
            height = page.evaluate("document.body.scrollHeight")
            print(f"Page height: {height}")

            if height == last_height:
                time.sleep(2)

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

        if not url or url in seen_urls:
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

        for index, url in enumerate(PADDYPOWER_MMA_URLS, start=1):
            try:
                print(f"\nOpening: {url}")
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                time.sleep(8)

                close_cookie_popup(page)
                time.sleep(3)

                scroll_page(page)
                save_debug(page, f"paddypower_page_{index}")

                raw_links = collect_links(page)
                print(f"Raw fight links found on page: {len(raw_links)}")

                all_raw_links.extend(raw_links)

            except Exception as e:
                print(f"Error fetching {url}: {e}")
                save_debug(page, f"paddypower_error_{index}")

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