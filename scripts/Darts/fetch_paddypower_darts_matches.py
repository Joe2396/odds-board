from playwright.sync_api import sync_playwright
from pathlib import Path
from datetime import datetime, timezone
import json
import re
import time

ROOT = Path(__file__).resolve().parents[2]

OUT_DIR = ROOT / "darts" / "data"
OUT_PATH = OUT_DIR / "paddypower_darts_matches.json"
DEBUG_DIR = ROOT / "darts" / "debug"

DARTS_URL = "https://www.paddypower.com/darts"

OUT_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

IGNORE_COMPETITIONS = [
    "Premier League Darts",
    "Premier League Darts 2026",
    "Premier League Darts 2026 Power Price",
]

TARGET_COMPETITIONS = {
    "MODUS Super Series": "MODUS Super Series",
    "PDC International Darts Open": "European Tour / PDC International Darts Open",
    "European Tour": "European Tour / PDC International Darts Open",
    "World Cup": "World Cup of Darts",
    "World Championship": "World Championship",
}


def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def is_time(value):
    return bool(re.match(r"^\d{1,2}:\d{2}$", value or ""))


def is_odds(value):
    value = (value or "").strip().upper()

    if re.match(r"^\d+/\d+$", value):
        return True

    if value == "EVS":
        return True

    return False


def should_ignore_competition(name):
    name_l = name.lower()
    return any(x.lower() in name_l for x in IGNORE_COMPETITIONS)


def map_competition(name):
    for key, mapped in TARGET_COMPETITIONS.items():
        if key.lower() in name.lower():
            return mapped
    return None


def extract_matches_from_text(text):
    lines = [clean_text(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    competitions = {}
    current_comp = None
    current_day = None

    skip_words = [
        "login",
        "sign up",
        "search",
        "sports",
        "in-play",
        "accas",
        "popular",
        "competitions",
        "top markets",
        "more markets",
        "help & contact",
        "promotions",
        "free bet",
        "boost",
        "responsible gambling",
        "cash out",
    ]

    cleaned = []

    for line in lines:
        low = line.lower()

        if any(w in low for w in skip_words):
            continue

        if line in ["1", "2"]:
            continue

        if "£" in line or "free bet" in low:
            continue

        if is_odds(line):
            continue

        cleaned.append(line)

    i = 0

    while i < len(cleaned):
        line = cleaned[i]

        if line in [
            "Today",
            "Tomorrow",
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]:
            current_day = line
            i += 1
            continue

        mapped = map_competition(line)

        if mapped and not should_ignore_competition(line):
            current_comp = mapped
            competitions.setdefault(current_comp, [])
            i += 1
            continue

        if should_ignore_competition(line):
            current_comp = None
            i += 1
            continue

        if current_comp and i + 2 < len(cleaned):
            player_1 = cleaned[i]
            player_2 = cleaned[i + 1]
            maybe_time = cleaned[i + 2]

            bad_player_terms = [
                "darts matches",
                "darts outright",
                "power price",
                "winner",
                "to win",
                "markets",
            ]

            if (
                is_time(maybe_time)
                and not any(t in player_1.lower() for t in bad_player_terms)
                and not any(t in player_2.lower() for t in bad_player_terms)
                and player_1 != player_2
            ):
                match = {
                    "competition": current_comp,
                    "day": current_day or "",
                    "time": maybe_time,
                    "player_1": player_1,
                    "player_2": player_2,
                    "bookmaker": "PaddyPower",
                    "source_url": DARTS_URL,
                }

                competitions.setdefault(current_comp, []).append(match)

                i += 3
                continue

        i += 1

    return competitions


def main():
    print("Fetching PaddyPower darts matches...")

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

        page.goto(DARTS_URL, wait_until="domcontentloaded", timeout=60000)

        time.sleep(5)

        try:
            page.get_by_text("Accept All Cookies", exact=False).click(timeout=3000)
            time.sleep(2)
        except Exception:
            pass

        # Scroll to load more fixtures
        for _ in range(8):
            page.mouse.wheel(0, 1000)
            time.sleep(1)

        text = page.locator("body").inner_text(timeout=30000)

        debug_text_path = DEBUG_DIR / "paddypower_darts_page_text.txt"
        debug_text_path.write_text(text, encoding="utf-8")

        competitions = extract_matches_from_text(text)

        total_matches = sum(len(v) for v in competitions.values())

        output = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "paddypower",
            "sport": "darts",
            "source_url": DARTS_URL,
            "total_matches": total_matches,
            "competitions": competitions,
        }

        OUT_PATH.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"Saved {total_matches} matches to {OUT_PATH}")

        for comp, matches in competitions.items():
            print(f"- {comp}: {len(matches)} matches")

        browser.close()


if __name__ == "__main__":
    main()