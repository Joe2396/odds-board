from playwright.sync_api import sync_playwright
import json
import time
import re
from pathlib import Path
from datetime import datetime, timezone
import os

def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


print("FETCHING CORAL UFC FIGHT URLS - CLICK CAPTURE REAL URLS")

ROOT = Path(__file__).resolve().parents[1]

OUT_PATH = ROOT / "ufc" / "data" / "coral_fight_urls.json"
DEBUG_PATH = ROOT / "ufc" / "data" / "coral_debug_elements.json"
PNG_PATH = ROOT / "ufc" / "data" / "coral_fight_urls_debug.png"

START_URL = "https://www.coral.co.uk/en/sports/competitions/ufc-mma/ufc-mma/mma-ufc"


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def accept_cookies(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def remove_time_odds_markets(text):
    text = clean_text(text)

    text = re.sub(r"\d{1,2}:\d{2},?\s*\d{1,2}\s+[A-Za-z]{3}", "", text)
    text = re.sub(r"\b\d+/\d+\b", "", text)
    text = re.sub(r"\+\d+\s*MARKETS?", "", text, flags=re.I)
    text = clean_text(text)

    return text


def fix_missing_v_spaces(text):
    text = clean_text(text)

    # Coral often reads "Jose OchoavClayton Carpenter"
    text = re.sub(r"([a-z])v([A-Z])", r"\1 v \2", text)

    return clean_text(text)


def normalise_fight_name(text):
    text = remove_time_odds_markets(text)
    text = fix_missing_v_spaces(text)

    parts = re.split(r"\s+v\s+", text, flags=re.I)

    if len(parts) != 2:
        return ""

    left = clean_text(parts[0])
    right = clean_text(parts[1])

    if len(left.split()) < 2 or len(right.split()) < 2:
        return ""

    return f"{left} v {right}"


def looks_like_fight_name(text):
    fight_name = normalise_fight_name(text)

    if not fight_name:
        return False

    lower = fight_name.lower()

    bad_bits = [
        "home",
        "betslip",
        "my bets",
        "your betslip",
        "log in",
        "join",
        "markets",
        "tomorrow",
        "today",
        "favourites",
        "mini games",
        "responsible gambling",
        "horse racing",
        "greyhound",
        "football",
        "casino",
    ]

    if any(bad in lower for bad in bad_bits):
        return False

    if len(fight_name) > 80:
        return False

    return True


def wait_for_competition_page(page):
    page.goto(START_URL, wait_until="domcontentloaded", timeout=80000)
    time.sleep(8)
    accept_cookies(page)
    time.sleep(3)

    # Let lazy rows render
    for _ in range(4):
        page.mouse.wheel(0, 1000)
        time.sleep(0.8)

    page.mouse.wheel(0, -9000)
    time.sleep(2)


def collect_fight_candidates(page):
    candidates = []
    debug_items = []
    seen_names = set()

    selectors = [
        "div",
        "a",
        "span",
        "button",
        "[class*='event']",
        "[class*='match']",
        "[class*='market']",
        "[class*='competition']",
    ]

    print("Collecting visible fight candidates...")

    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = loc.count()
            print(f"{selector} -> {count} elements")

            for i in range(min(count, 1000)):
                try:
                    raw_text = clean_text(loc.nth(i).inner_text(timeout=700))

                    if not raw_text:
                        continue

                    debug_items.append({
                        "selector": selector,
                        "index": i,
                        "text": raw_text,
                    })

                    if not looks_like_fight_name(raw_text):
                        continue

                    fight_name = normalise_fight_name(raw_text)

                    if not fight_name:
                        continue

                    key = fight_name.lower()

                    if key in seen_names:
                        continue

                    seen_names.add(key)

                    candidates.append({
                        "fight_name": fight_name,
                        "raw_text": raw_text,
                    })

                    print("CANDIDATE:", fight_name)

                except Exception:
                    continue

        except Exception as e:
            print(f"Selector failed {selector}: {e}")

    return candidates, debug_items


def click_candidate_and_capture_url(page, candidate):
    fight_name = candidate["fight_name"]

    print("\nTrying click for:", fight_name)

    # Coral text may appear as normal OR missing spaces around v
    compact = fight_name.replace(" v ", "v")
    left, right = fight_name.split(" v ", 1)

    click_selectors = [
        f"text={fight_name}",
        f"text={compact}",
        f"div:has-text('{left}'):has-text('{right}')",
        f"a:has-text('{left}'):has-text('{right}')",
        f"[class*='event']:has-text('{left}'):has-text('{right}')",
        f"[class*='match']:has-text('{left}'):has-text('{right}')",
        f"[class*='market']:has-text('{left}'):has-text('{right}')",
    ]

    before_url = page.url

    for selector in click_selectors:
        try:
            loc = page.locator(selector).first

            if loc.count() == 0:
                continue

            print("Click selector:", selector)

            loc.scroll_into_view_if_needed(timeout=5000)
            time.sleep(0.5)

            loc.click(timeout=7000, force=True)
            time.sleep(5)

            after_url = page.url

            if after_url != before_url and "/sports/event/ufc-mma/" in after_url:
                print("CAPTURED:", after_url)
                return after_url

            # Sometimes click expands markets but does not navigate.
            # Try clicking a nearby + markets text after selecting row.
            try:
                plus = page.locator("text=MARKETS").first
                if plus.count() > 0:
                    plus.click(timeout=4000, force=True)
                    time.sleep(5)
                    after_url = page.url

                    if after_url != before_url and "/sports/event/ufc-mma/" in after_url:
                        print("CAPTURED:", after_url)
                        return after_url
            except Exception:
                pass

            # Go back if it navigated somewhere unhelpful
            if page.url != before_url:
                try:
                    page.go_back(wait_until="domcontentloaded", timeout=30000)
                    time.sleep(4)
                except Exception:
                    wait_for_competition_page(page)

        except Exception:
            continue

    print("FAILED TO CLICK:", fight_name)
    return ""


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    captured_fights = []
    all_debug_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=is_github_actions())

        page = browser.new_page(
            viewport={"width": 1500, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        print("Opening competition page")
        wait_for_competition_page(page)

        try:
            page.screenshot(path=str(PNG_PATH), full_page=True)
            print(f"Saved screenshot: {PNG_PATH}")
        except Exception:
            pass

        candidates, debug_items = collect_fight_candidates(page)
        all_debug_items.extend(debug_items)

        print(f"\nCandidates found: {len(candidates)}")

        seen_urls = set()

        for idx, candidate in enumerate(candidates, start=1):
            print("\n==============================")
            print(f"{idx}/{len(candidates)}")
            print("==============================")

            # Reload page each time so rows are clickable from a clean state
            wait_for_competition_page(page)

            real_url = click_candidate_and_capture_url(page, candidate)

            if not real_url:
                continue

            if real_url in seen_urls:
                continue

            seen_urls.add(real_url)

            captured_fights.append({
                "bookmaker": "Coral",
                "fight_name": candidate["fight_name"],
                "url": real_url,
                "source_url": START_URL,
            })

        browser.close()

    output = {
        "bookmaker": "Coral",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(captured_fights),
        "fights": captured_fights,
    }

    debug_output = {
        "bookmaker": "Coral",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_debug_items),
        "items": all_debug_items,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    with open(DEBUG_PATH, "w", encoding="utf-8") as f:
        json.dump(debug_output, f, indent=2, ensure_ascii=False)

    print("\nDONE")
    print(f"Saved: {OUT_PATH}")
    print(f"Saved debug: {DEBUG_PATH}")
    print(f"Captured real URLs: {len(captured_fights)}")

    for fight in captured_fights:
        print("-", fight["fight_name"])
        print(" ", fight["url"])


if __name__ == "__main__":
    main()