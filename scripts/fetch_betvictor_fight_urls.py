from playwright.sync_api import sync_playwright
import json
import time
import re
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BETVICTOR FIGHT URLS - DEBUG MODE")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "betvictor_fight_urls.json"
DEBUG_PATH = ROOT / "ufc" / "data" / "betvictor_debug_links.json"

BETVICTOR_URLS = [
    "https://www.betvictor.com/en-ie/sports/1327866",
    "https://www.betvictor.com/en-ie/sports/1327866/meetings/726971410/all",
    "https://www.betvictor.com/en-ie/sports/1327866/meetings/726971510/all",
    "https://www.betvictor.com/en-ie/sports/1327866/meetings/727049210/all",
    "https://www.betvictor.com/en-ie/sports/1327866/meetings/727019710/all",
]


def accept_cookies(page):
    selectors = [
        "button:has-text('Accept All')",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept')",
        "#onetrust-accept-btn-handler",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def looks_like_fight_name(text):
    text = clean_text(text)
    lower = text.lower()

    if not text:
        return False

    bad_words = [
        "more",
        "all",
        "in-play",
        "popular",
        "competitions",
        "terms",
        "privacy",
        "cookies",
        "safer gambling",
        "free bets",
        "ufc betting",
        "mma betting",
        "sports",
        "casino",
        "live casino",
        "promotions",
        "responsible gambling",
        "help",
        "login",
        "join",
    ]

    if any(bad in lower for bad in bad_words):
        return False

    if not re.search(r"[A-Za-z]", text):
        return False

    fight_patterns = [
        r"\b[a-zA-Z.'-]+\s+[a-zA-Z.'-]+\s+v\s+[a-zA-Z.'-]+\s+[a-zA-Z.'-]+\b",
        r"\b[a-zA-Z.'-]+\s+[a-zA-Z.'-]+\s+vs\s+[a-zA-Z.'-]+\s+[a-zA-Z.'-]+\b",
        r"\b[a-zA-Z.'-]+\s+[a-zA-Z.'-]+\s+versus\s+[a-zA-Z.'-]+\s+[a-zA-Z.'-]+\b",
        r"\b[a-zA-Z.'-]+\s+[a-zA-Z.'-]+\s*-\s*[a-zA-Z.'-]+\s+[a-zA-Z.'-]+\b",
    ]

    for pattern in fight_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True

    words = text.split()

    if 3 <= len(words) <= 12 and (" v " in lower or " vs " in lower or " versus " in lower):
        return True

    return False


def extract_fights_from_page(page, source_url):
    fights = []
    debug_links = []

    links = page.locator("a").all()
    print(f"Found {len(links)} links on page")

    for i, link in enumerate(links):
        try:
            href = link.get_attribute("href")
            text = clean_text(link.inner_text(timeout=1000))

            debug_links.append({
                "index": i,
                "text": text,
                "href": href,
                "source_url": source_url,
            })

            if i < 70:
                print("\nLINK", i)
                print("TEXT:", repr(text))
                print("HREF:", href)

            if not href:
                continue

            full_href = href

            if full_href.startswith("/"):
                full_href = "https://www.betvictor.com" + full_href

            if "sports/1327866" not in full_href:
                continue

            if not looks_like_fight_name(text):
                if i < 70:
                    print("REJECTED:", repr(text))
                continue

            print("ACCEPTED FIGHT:", text)

            fights.append({
                "bookmaker": "BetVictor",
                "fight_name": text,
                "url": full_href,
                "source_url": source_url,
            })

        except Exception as e:
            print("Link error:", e)
            continue

    return fights, debug_links


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    all_fights = []
    all_debug_links = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        page = browser.new_page(
            viewport={"width": 1400, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        for url in BETVICTOR_URLS:
            print("\n========================================")
            print(f"Opening: {url}")
            print("========================================")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(6)

                accept_cookies(page)
                time.sleep(3)

                for _ in range(4):
                    page.mouse.wheel(0, 2500)
                    time.sleep(1)

                fights, debug_links = extract_fights_from_page(page, url)

                print(f"\nExtracted {len(fights)} possible fights from this page")

                all_fights.extend(fights)
                all_debug_links.extend(debug_links)

            except Exception as e:
                print(f"Failed page: {url}")
                print(e)

        browser.close()

    seen = set()
    unique_fights = []

    for fight in all_fights:
        key = fight["url"]

        if key in seen:
            continue

        seen.add(key)
        unique_fights.append(fight)

    output = {
        "bookmaker": "BetVictor",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(unique_fights),
        "fights": unique_fights,
    }

    debug_output = {
        "bookmaker": "BetVictor",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_debug_links),
        "links": all_debug_links,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    with open(DEBUG_PATH, "w", encoding="utf-8") as f:
        json.dump(debug_output, f, indent=2, ensure_ascii=False)

    print("\nDONE")
    print(f"Saved fights: {OUT_PATH}")
    print(f"Saved debug links: {DEBUG_PATH}")
    print(f"Unique fights: {len(unique_fights)}")

    for fight in unique_fights:
        print("-", fight["fight_name"], fight["url"])


if __name__ == "__main__":
    main()