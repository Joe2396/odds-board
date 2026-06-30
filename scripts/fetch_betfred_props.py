from pathlib import Path
from datetime import datetime, timezone
import json
import re
from playwright.sync_api import sync_playwright
import os

def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


ROOT = Path(__file__).resolve().parents[1]

OUT_PATH = ROOT / "ufc" / "data" / "betfred_props.json"

URL = "https://www.betfred.com/sports/ufc-mma"

print("RUNNING BETFRED UFC SCRAPER")


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def fractional_to_decimal(frac):
    frac = str(frac or "").strip()

    if "/" in frac:
        try:
            a, b = frac.split("/", 1)
            return round((float(a) / float(b)) + 1, 2)
        except Exception:
            return 0

    try:
        return float(frac)
    except Exception:
        return 0


def is_fractional_odds(text):
    text = str(text or "").strip()

    if re.fullmatch(r"\d+/\d+", text):
        return True

    return False


def main():
    fights = []

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(ROOT / "ufc" / "data" / "betfred_browser_profile"),
            headless=is_github_actions(),
            viewport={"width": 1400, "height": 900},
            locale="en-GB",
            timezone_id="Europe/Dublin",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={"Accept-Language": "en-GB,en;q=0.9"},
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = browser.new_page()

        print("OPENING:", URL)

        page.goto(URL, wait_until="domcontentloaded", timeout=90000)

        page.wait_for_timeout(10000)

        text = page.locator("body").inner_text(timeout=60000)

        lines = [clean(x) for x in text.splitlines() if clean(x)]

        print(f"LINES FOUND: {len(lines)}")

        for i in range(len(lines) - 3):
            fighter1 = lines[i]
            fighter2 = lines[i + 1]
            odds1 = lines[i + 2]
            odds2 = lines[i + 3]

            if (
                len(fighter1.split()) >= 2
                and len(fighter2.split()) >= 2
                and is_fractional_odds(odds1)
                and is_fractional_odds(odds2)
            ):
                print("")
                print("MATCH FOUND")
                print(fighter1, odds1)
                print(fighter2, odds2)

                fight_name = f"{fighter1} vs {fighter2}"

                fights.append({
                    "bookmaker": "Betfred",
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
                            },
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
        "source": "betfred",
        "bookmaker": "Betfred",
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
    print(f"✅ Saved {len(fights)} Betfred fights")
    print(f"📁 {OUT_PATH}")


if __name__ == "__main__":
    main()