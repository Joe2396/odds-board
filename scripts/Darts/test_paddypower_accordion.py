from playwright.sync_api import sync_playwright
from pathlib import Path
import time
import re

ROOT = Path(__file__).resolve().parents[2]

DEBUG_PATH = ROOT / "darts" / "debug" / "accordion_test.txt"
DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

DARTS_URL = "https://www.paddypower.com/darts"


def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def save_debug(page, label):
    text = page.locator("body").inner_text(timeout=30000)

    with open(DEBUG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n\n==================== {label} ====================\n\n")
        f.write(text)


def accept_cookies(page):
    for label in [
        "Accept All Cookies",
        "Accept All",
        "I Accept",
        "Accept",
        "Agree",
        "OK",
    ]:
        try:
            page.get_by_text(label, exact=False).click(timeout=2000)
            time.sleep(1)
            return
        except Exception:
            pass


def open_first_modus_match_by_link(page):
    print("Opening PaddyPower darts home...")

    page.goto(DARTS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    accept_cookies(page)

    for _ in range(8):
        page.mouse.wheel(0, 900)
        time.sleep(0.5)

    print("Looking for current MODUS match links...")

    anchors = page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || ''
        }))
        """
    )

    links = []

    for a in anchors:
        href = a.get("href", "")
        text = clean_text(a.get("text", ""))

        if "/darts/modus-super-series/" in href and href not in links:
            links.append(href)
            print("Found:", href, "|", text[:100])

    if not links:
        return False

    page.goto(links[0], wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    accept_cookies(page)

    print("Opened:", page.url)

    return True


def click_text(page, text):
    try:
        loc = page.get_by_text(text, exact=False).first
        loc.scroll_into_view_if_needed(timeout=4000)
        time.sleep(0.6)
        loc.click(timeout=4000)
        time.sleep(1.5)
        print("Clicked text:", text)
        return True
    except Exception as e:
        print("Failed text click:", text, e)
        return False


def click_fixed_market_positions(page):
    """
    This assumes 1600x1000 viewport.

    The goal is to click the actual visible accordion rows by rough screen position.
    PaddyPower row clicks are weird, so we try several x positions across each market row.
    """

    # Make sure market list is visible.
    click_text(page, "All Markets")
    time.sleep(1)

    save_debug(page, "BEFORE FIXED CLICKS")

    # Based on the screenshot layout:
    # market rows are around left content column.
    # These y positions may need tiny adjustment.
    market_rows = [
        ("Leg Handicap row", 455),
        ("Most 180s row", 505),
        ("Total 180s row", 555),
        ("Total Legs row", 605),
        ("Correct Score row", 655),
        ("Player Total 180s row 1", 710),
        ("Player Total 180s row 2", 760),
    ]

    # Try across the row: arrow area, text area, right side
    x_positions = [305, 335, 390, 540, 850]

    for label, y in market_rows:
        print(f"\nTrying {label}")

        for x in x_positions:
            print(f"Clicking x={x}, y={y}")
            page.mouse.click(x, y)
            time.sleep(1.2)
            save_debug(page, f"AFTER {label} CLICK {x},{y}")

    # Scroll down after opening to force lazy props into text
    for _ in range(3):
        page.mouse.wheel(0, 500)
        time.sleep(0.8)

    save_debug(page, "AFTER ALL FIXED CLICKS AND SCROLL")


def main():
    if DEBUG_PATH.exists():
        DEBUG_PATH.unlink()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        page = browser.new_page(
            viewport={"width": 1600, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        opened = open_first_modus_match_by_link(page)

        if not opened:
            print("Could not open current MODUS match page.")
            browser.close()
            return

        save_debug(page, "MATCH PAGE OPENED")

        click_fixed_market_positions(page)

        print(f"Saved debug output to: {DEBUG_PATH}")
        print("Open accordion_test.txt and search for: Over, Under, +5.5, 4/7, 5/4, 180.")

        input("Press ENTER to close browser...")

        browser.close()


if __name__ == "__main__":
    main()