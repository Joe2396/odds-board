from playwright.sync_api import sync_playwright
import json
import time
import os
import re
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BOYLESPORTS MONEYLINES - ATTRIBUTE BASED")

ROOT = Path(__file__).resolve().parents[1]

URLS_PATH = ROOT / "ufc" / "data" / "boylesports_fight_urls.json"
OUT_PATH  = ROOT / "ufc" / "data" / "boylesports_moneylines.json"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def close_cookie_popup(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=2000):
                locator.click(force=True, timeout=3000)
                print(f"Accepted cookies via: {selector}")
                time.sleep(2)
                return
        except Exception:
            pass
    print("No cookie popup found")


def extract_moneylines(page):
    """
    BoyleSports renders each moneyline selection as:
      <a class="odds addSelection" data-name="Fighter Name" data-price="3/10">
    inside the 'To Win Fight' market group (a div.luf containing a header
    whose text is 'To Win Fight').

    Strategy:
      1. Find the header element whose text == 'To Win Fight' (or fallbacks).
      2. Climb to its market container (the enclosing div.luf).
      3. Read every a.addSelection[data-name][data-price] inside it.
    """
    return page.evaluate("""
        () => {
            const HEADER_LABELS = ["to win fight", "fight betting", "money line", "moneyline"];

            // 1. Find the market header
            let header = null;
            const headers = Array.from(document.querySelectorAll("header, .accordion, .h3, span"));
            for (const el of headers) {
                const t = (el.innerText || el.textContent || "").trim().toLowerCase();
                if (HEADER_LABELS.includes(t)) { header = el; break; }
            }

            if (!header) {
                return { prices: [], debug: "header not found" };
            }

            // 2. Climb to the market container (div.luf with a panel inside)
            let container = header;
            for (let i = 0; i < 8; i++) {
                if (!container.parentElement) break;
                container = container.parentElement;
                if (container.querySelector("a.addSelection[data-name][data-price]")) {
                    break;
                }
            }

            // 3. Read selections
            const links = Array.from(
                container.querySelectorAll("a.addSelection[data-name][data-price]")
            );

            const prices = [];
            const seen = new Set();
            for (const a of links) {
                const name  = (a.getAttribute("data-name") || "").trim();
                const price = (a.getAttribute("data-price") || "").trim().toUpperCase();
                if (!name || !price) continue;
                const key = name.toLowerCase();
                if (seen.has(key)) continue;     // dedupe
                seen.add(key);
                prices.push({ selection: name, odds: price });
            }

            return { prices, debug: { linkCount: links.length } };
        }
    """)


def scrape_moneyline(page, fight, cookie_accepted):
    fight_name = fight["fight"]
    fight_url  = fight["url"]

    print(f"\n============================")
    print(f"Scraping: {fight_name}")
    print(f"============================")

    page.goto(fight_url, timeout=70000, wait_until="domcontentloaded")
    time.sleep(7)

    if not cookie_accepted:
        close_cookie_popup(page)

    # Wait for the selection links to be present in the DOM
    try:
        page.wait_for_selector("a.addSelection[data-name][data-price]", timeout=8000)
    except Exception:
        print("No selection links appeared within timeout")

    result = extract_moneylines(page)
    prices = result.get("prices") or []
    debug  = result.get("debug")

    # We expect exactly 2 for a moneyline. If we got more, the market group
    # climb grabbed too much — keep only the first 2 (header order = fighter order).
    if len(prices) > 2:
        print(f"Got {len(prices)} selections, trimming to first 2")
        prices = prices[:2]

    if len(prices) != 2:
        print(f"WARNING: got {len(prices)} moneylines (expected 2)")
        print(f"Debug: {debug}")
        prices = []

    print(f"Moneylines extracted: {len(prices)}")
    for p in prices:
        print(f"  - {p['selection']}: {p['odds']}")

    return {
        "fight":      fight_name,
        "url":        fight_url,
        "bookmaker":  "BoyleSports",
        "scraped_at": now_iso(),
        "markets":    {"fight_betting": prices},
        "debug":      debug,
    }


def save_output(fights):
    output = {
        "updated_at": now_iso(),
        "source":     "boylesports",
        "bookmaker":  "BoyleSports",
        "count":      len(fights),
        "fights":     fights,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Saved to {OUT_PATH}")


def main():
    if not URLS_PATH.exists():
        print(f"Missing: {URLS_PATH}")
        return

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    fights = data.get("fights", [])
    if not fights:
        print("No fights found")
        return

    results = []
    cookie_accepted = False

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

        for index, fight in enumerate(fights, start=1):
            print(f"\nProgress: {index}/{len(fights)}")
            try:
                result = scrape_moneyline(page, fight, cookie_accepted)
                if not cookie_accepted:
                    cookie_accepted = True
                results.append(result)
                save_output(results)
            except Exception as e:
                print(f"ERROR scraping {fight.get('fight')}: {e}")
                save_output(results)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print("\nFinished BoyleSports moneylines")


if __name__ == "__main__":
    main()