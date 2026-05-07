from playwright.sync_api import sync_playwright
import json
import time
import re
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BETVICTOR UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]

URLS_PATH = ROOT / "ufc" / "data" / "betvictor_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "betvictor_props.json"

with open(URLS_PATH, "r", encoding="utf-8") as f:
    fight_data = json.load(f)

fight_urls = fight_data.get("fights", [])


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


def clean_fight_name(name):
    name = re.sub(r"Sunday \d{2}:\d{2}", "", name)
    name = re.sub(r"Saturday \d{2}:\d{2}", "", name)
    name = re.sub(r"To Win the Bout \d+", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def extract_market_data(page):
    markets = []

    buttons = page.locator("button").all()

    for button in buttons:
        try:
            text = clean_text(button.inner_text(timeout=500))

            if not text:
                continue

            odds_match = re.search(r"\d+\/\d+|\d+\.\d+", text)

            if not odds_match:
                continue

            markets.append(text)

        except Exception:
            continue

    return list(set(markets))


all_fights = []

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

    accept_cookies(page)

    for fight in fight_urls:
        raw_name = fight.get("fight_name", "")
        fight_name = clean_fight_name(raw_name)
        url = fight.get("url")

        print("\n====================================")
        print("FIGHT:", fight_name)
        print("URL:", url)
        print("====================================")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            time.sleep(6)

            accept_cookies(page)

            for _ in range(6):
                page.mouse.wheel(0, 2500)
                time.sleep(1)

            html = page.content()

            market_keywords = [
                "Method",
                "Rounds",
                "Distance",
                "KO",
                "Submission",
                "Decision",
                "Round Betting",
                "Will the Fight Go the Distance",
            ]

            found_sections = []

            for keyword in market_keywords:
                if keyword.lower() in html.lower():
                    found_sections.append(keyword)

            market_data = extract_market_data(page)

            print("Found sections:", found_sections)
            print("Market rows:", len(market_data))

            all_fights.append({
                "bookmaker": "BetVictor",
                "fight_name": fight_name,
                "url": url,
                "market_sections": found_sections,
                "market_count": len(market_data),
                "markets": market_data,
            })

        except Exception as e:
            print("FAILED:", e)

    browser.close()

output = {
    "bookmaker": "BetVictor",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "fight_count": len(all_fights),
    "fights": all_fights,
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print("\nDONE")
print(f"Saved: {OUT_PATH}")
print(f"Total fights: {len(all_fights)}")