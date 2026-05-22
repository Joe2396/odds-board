from pathlib import Path
from datetime import datetime, timezone
import json
import re
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "888sport_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

URL = "https://www.888sport.com/ufc-mma/"

print("RUNNING 888SPORT UFC SCRAPER")


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def is_fractional(text):
    text = clean(text).upper()
    return bool(re.fullmatch(r"\d+/\d+", text)) or text == "EVS"


def parse_fighter_name(text):
    text = clean(text)
    if "," in text:
        last, first = [clean(x) for x in text.split(",", 1)]
        return clean(f"{first} {last}")
    return text


def looks_like_time(text):
    return bool(re.fullmatch(r"\d{1,2}:\d{2}", clean(text)))


def accept_cookies(page):
    for label in [
        "ACCEPT",
        "Accept",
        "Accept All",
        "Accept all",
        "ACCEPT ESSENTIAL COOKIES ONLY",
    ]:
        try:
            page.get_by_text(label, exact=True).click(timeout=2500)
            print("COOKIE CLICKED:", label)
            page.wait_for_timeout(1500)
            return
        except Exception:
            pass


def click_upcoming(page):
    try:
        page.get_by_text("Upcoming", exact=True).click(timeout=7000)
        print("CLICKED UPCOMING")
        page.wait_for_timeout(7000)
        return True
    except Exception as e:
        print("Could not click Upcoming:", e)
        return False


def scroll_page(page):
    print("SCROLLING PAGE TO LOAD MORE FIGHTS")
    for n in range(12):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(1000)


def extract_fights_from_lines(lines):
    fights = []
    i = 0

    while i < len(lines) - 4:
        a = clean(lines[i])
        b = clean(lines[i + 1])
        maybe_time = clean(lines[i + 2])

        if (
            a
            and b
            and looks_like_time(maybe_time)
            and not is_fractional(a)
            and not is_fractional(b)
            and "," in a
            and "," in b
        ):
            odds = []

            for j in range(i + 3, min(i + 16, len(lines))):
                if is_fractional(lines[j]):
                    odds.append(clean(lines[j]))

            if len(odds) >= 2:
                left = parse_fighter_name(a)
                right = parse_fighter_name(b)
                fight_name = f"{left} vs {right}"

                nearby = " ".join(lines[max(0, i - 20):min(len(lines), i + 35)]).lower()

                if "ufc" not in nearby:
                    i += 1
                    continue

                fights.append({
                    "bookmaker": "888Sport",
                    "fight": fight_name,
                    "fight_name": fight_name,
                    "url": URL,
                    "markets": {
                        "fight_betting": [
                            {"selection": left, "odds": odds[0]},
                            {"selection": right, "odds": odds[1]},
                        ]
                    }
                })

                i += 8
                continue

        i += 1

    return fights


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        page = browser.new_page(
            viewport={"width": 1500, "height": 1000}
        )

        print("OPENING:", URL)

        page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)

        accept_cookies(page)

        page.wait_for_timeout(2000)

        click_upcoming(page)

        scroll_page(page)

        text = page.locator("body").inner_text(timeout=30000)

        lines = [
            clean(x)
            for x in text.splitlines()
            if clean(x)
        ]

        (DEBUG_DIR / "888sport_lines.txt").write_text(
            "\n".join(f"{i}: {repr(x)}" for i, x in enumerate(lines)),
            encoding="utf-8"
        )

        print("LINES FOUND:", len(lines))

        fights = extract_fights_from_lines(lines)

        browser.close()

    unique = {}
    for fight in fights:
        unique[fight["fight_name"]] = fight

    fights = list(unique.values())

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "888sport",
        "bookmaker": "888Sport",
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
    print(f"✅ Saved {len(fights)} 888Sport UFC fights")
    print(f"📁 {OUT_PATH}")
    print(f"🧪 Debug lines: {DEBUG_DIR / '888sport_lines.txt'}")


if __name__ == "__main__":
    main()