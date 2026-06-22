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

URL = "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/future/match-betting"

print("RUNNING WILLIAM HILL UFC SCRAPER")


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def is_fractional(text):
    return bool(re.fullmatch(r"\d+/\d+", str(text or "").strip()))


def main():
    fights = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_github_actions()
        )

        page = browser.new_page(
            viewport={"width": 1400, "height": 1200}
        )

        print("OPENING:", URL)

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=90000
        )

        page.wait_for_timeout(12000)

        text = page.locator("body").inner_text()

        lines = [
            clean(x)
            for x in text.splitlines()
            if clean(x)
        ]

        print(f"LINES FOUND: {len(lines)}")

        for i in range(len(lines) - 3):
            fighter1 = lines[i]
            fighter2 = lines[i + 1]
            odds1 = lines[i + 2]
            odds2 = lines[i + 3]

            if (
                len(fighter1.split()) >= 2
                and len(fighter2.split()) >= 2
                and is_fractional(odds1)
                and is_fractional(odds2)
            ):
                fight_name = f"{fighter1} vs {fighter2}"

                print("")
                print("MATCH FOUND")
                print(f"{fighter1} {odds1}")
                print(f"{fighter2} {odds2}")

                fights.append({
                    "bookmaker": "WilliamHill",
                    "fight_name": fight_name,
                    "url": URL,
                    "markets": {
                        "fight_betting": [
                            {
                                "selection": fighter1,
                                "odds": odds1,
                            },
                            {
                                "selection": fighter2,
                                "odds": odds2,
                            }
                        ]
                    }
                })

        browser.close()

    unique = {}

    for fight in fights:
        unique[fight["fight_name"]] = fight

    fights = list(unique.values())

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "williamhill",
        "bookmaker": "WilliamHill",
        "url": URL,
        "count": len(fights),
        "fights": fights,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    OUT_PATH.write_text(
        json.dumps(out, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("")
    print(f"✅ Saved {len(fights)} William Hill fights")
    print(f"📁 {OUT_PATH}")


if __name__ == "__main__":
    main()