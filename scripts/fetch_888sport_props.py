from pathlib import Path
from datetime import datetime, timezone
import json
import re
import unicodedata
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

OUT_PATH = ROOT / "ufc" / "data" / "888sport_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"
FIGHTERS_JSON = ROOT / "ufc" / "data" / "fighters.json"

URL = "https://www.888sport.com/ufc-mma/"

print("RUNNING 888SPORT UFC SCRAPER")


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_name(name):
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = text.replace("'", "")
    text = text.replace("’", "")
    text = text.replace(".", "")
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_fractional(text):
    text = clean(text).upper()
    return bool(re.fullmatch(r"\d+/\d+", text)) or text == "EVS"


def parse_fighter_name(text):
    text = clean(text)

    # 888 usually shows "Surname, Initial" or "Surname, Firstname"
    if "," in text:
        last, first = [clean(x) for x in text.split(",", 1)]
        return clean(f"{first} {last}")

    return text


def load_known_fighters():
    raw = {}
    try:
        raw = json.loads(FIGHTERS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []

    fighters = raw.get("fighters", [])

    if isinstance(fighters, dict):
        fighters = list(fighters.values())

    names = []

    for fighter in fighters or []:
        if isinstance(fighter, dict) and fighter.get("name"):
            names.append(clean(fighter["name"]))

    return sorted(set(names))


KNOWN_FIGHTERS = load_known_fighters()


def expand_initial_name(short_name):
    """
    Turns:
      I Topuria -> Ilia Topuria
      J Gaethje -> Justin Gaethje
      S O'Malley -> Sean O'Malley
      L Lookboonmee -> Loma Lookboonmee
    using ufc/data/fighters.json.
    """
    short_name = clean(short_name)

    parts = short_name.split()
    if len(parts) < 2:
        return short_name

    first = parts[0].replace(".", "")
    surname = " ".join(parts[1:])

    # Only expand names that start with a single-letter initial
    if len(first) != 1:
        return short_name

    initial = normalize_name(first)
    surname_norm = normalize_name(surname)

    matches = []

    for full in KNOWN_FIGHTERS:
        full_norm = normalize_name(full)
        full_parts = full_norm.split()

        if not full_parts:
            continue

        full_first = full_parts[0]
        full_surname = " ".join(full_parts[1:])

        if full_first.startswith(initial) and surname_norm == full_surname:
            matches.append(full)

    if len(matches) == 1:
        return matches[0]

    # Fallback: allow matching on final surname token
    matches = []

    short_surname_last = surname_norm.split()[-1] if surname_norm.split() else ""

    for full in KNOWN_FIGHTERS:
        full_norm = normalize_name(full)
        full_parts = full_norm.split()

        if len(full_parts) < 2:
            continue

        if full_parts[0].startswith(initial) and full_parts[-1] == short_surname_last:
            matches.append(full)

    if len(matches) == 1:
        return matches[0]

    return short_name


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
    for _ in range(12):
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
                raw_left = parse_fighter_name(a)
                raw_right = parse_fighter_name(b)

                left = expand_initial_name(raw_left)
                right = expand_initial_name(raw_right)

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
                    },
                    "raw_fight_name": f"{raw_left} vs {raw_right}",
                })

                i += 8
                continue

        i += 1

    return fights


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print(f"KNOWN FIGHTERS LOADED: {len(KNOWN_FIGHTERS)}")

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

    for fight in fights:
        print(f" - {fight['fight_name']} ({fight.get('raw_fight_name')})")


if __name__ == "__main__":
    main()