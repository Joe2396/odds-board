from pathlib import Path
from datetime import datetime, timezone
import json
import re
from playwright.sync_api import sync_playwright
import os

def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


ROOT = Path(__file__).resolve().parents[1]

OUT_PATH = ROOT / "ufc" / "data" / "williamhill_props.json"

# Scrape all day tabs to catch both near-term and future events
URLS = [
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/today/match-betting",
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/tomorrow/match-betting",
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/saturday/match-betting",
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/sunday/match-betting",
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/future/match-betting",
]

print("RUNNING WILLIAM HILL UFC SCRAPER")


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def is_fractional(text):
    return bool(re.fullmatch(r"\d+/\d+", str(text or "").strip()))


def scrape_url(page, url):
    fights = []
    print(f"\nOPENING: {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
    except Exception as e:
        print(f"  Failed to load: {e}")
        return fights

    text = page.locator("body").inner_text()
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    print(f"  Lines found: {len(lines)}")

    for i in range(len(lines) - 3):
        fighter1 = lines[i]
        fighter2 = lines[i + 1]
        odds1    = lines[i + 2]
        odds2    = lines[i + 3]

        if (
            len(fighter1.split()) >= 2
            and len(fighter2.split()) >= 2
            and is_fractional(odds1)
            and is_fractional(odds2)
        ):
            fight_name = f"{fighter1} vs {fighter2}"
            print(f"  MATCH: {fighter1} {odds1} | {fighter2} {odds2}")

            fights.append({
                "bookmaker": "WilliamHill",
                "fight_name": fight_name,
                "url": url,
                "markets": {
                    "fight_betting": [
                        {"selection": fighter1, "odds": odds1},
                        {"selection": fighter2, "odds": odds2},
                    ]
                },
            })

    return fights


def main():
    all_fights = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=is_github_actions())
        page = browser.new_page(viewport={"width": 1400, "height": 1200})

        for url in URLS:
            fights = scrape_url(page, url)
            for fight in fights:
                # dedupe by fight name, first seen wins
                if fight["fight_name"] not in all_fights:
                    all_fights[fight["fight_name"]] = fight

        browser.close()

    fights = list(all_fights.values())

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "williamhill",
        "bookmaker": "WilliamHill",
        "url": URLS[0],
        "count": len(fights),
        "fights": fights,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ Saved {len(fights)} William Hill fights")
    print(f"📁 {OUT_PATH}")


if __name__ == "__main__":
    main()