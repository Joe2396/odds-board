from playwright.sync_api import sync_playwright
from pathlib import Path
from datetime import datetime, timezone
import json
import re
import time

ROOT = Path(__file__).resolve().parents[2]

MATCHES_PATH = ROOT / "darts" / "data" / "paddypower_darts_matches.json"
OUT_PATH = ROOT / "darts" / "data" / "players_flashscore.json"
DEBUG_DIR = ROOT / "darts" / "debug" / "flashscore_players"

FLASHSCORE_DARTS_URL = "https://www.flashscore.com/darts/"

DEBUG_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def slugify(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def normalize_name(name):
    name = clean_text(name)
    name = re.sub(r"\bJr\b\.?", "Jr", name, flags=re.I)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def load_player_names():
    if not MATCHES_PATH.exists():
        print(f"Missing matches file: {MATCHES_PATH}")
        return []

    data = json.loads(MATCHES_PATH.read_text(encoding="utf-8"))

    names = set()

    for _, matches in data.get("competitions", {}).items():
        for match in matches:
            p1 = normalize_name(match.get("player_1"))
            p2 = normalize_name(match.get("player_2"))

            if p1:
                names.add(p1)

            if p2:
                names.add(p2)

    return sorted(names)


def accept_cookies(page):
    labels = [
        "I Accept",
        "Accept all",
        "Accept All",
        "Agree",
        "OK",
        "Allow all",
    ]

    for label in labels:
        try:
            page.get_by_text(label, exact=False).click(timeout=2500)
            time.sleep(1)
            return True
        except Exception:
            pass

    try:
        page.keyboard.press("Escape")
        time.sleep(1)
    except Exception:
        pass

    return False


def open_flashscore(page):
    print("Opening Flashscore darts...")
    page.goto(FLASHSCORE_DARTS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    accept_cookies(page)


def click_search(page):
    selectors = [
        "button[aria-label*='Search']",
        "button[title*='Search']",
        "[data-testid*='search']",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=3000)
            time.sleep(1)
            return True
        except Exception:
            pass

    try:
        page.get_by_text("Search", exact=False).click(timeout=3000)
        time.sleep(1)
        return True
    except Exception:
        pass

    # Fallback coordinate near top-right search icon
    try:
        page.mouse.click(1280, 195)
        time.sleep(1)
        return True
    except Exception:
        return False


def search_player(page, player_name):
    print(f"Searching Flashscore: {player_name}")

    page.goto(FLASHSCORE_DARTS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)
    accept_cookies(page)

    if not click_search(page):
        print("  Could not open search")
        return ""

    try:
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(player_name, delay=80)
        time.sleep(4)
    except Exception:
        print("  Could not type search")
        return ""

    try:
        text = page.locator("body").inner_text(timeout=15000)
        (DEBUG_DIR / f"{slugify(player_name)}_search.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass

    terms = []
    parts = player_name.split()

    terms.append(player_name)

    if len(parts) >= 2:
        first = parts[0]
        last = parts[-1]
        terms.extend([
            f"{first} {last}",
            f"{last} {first}",
            last,
            first,
        ])

    # Try clicking player result text
    for term in terms:
        try:
            page.get_by_text(term, exact=False).first.click(timeout=3500)
            time.sleep(5)

            url = page.url
            if "/player/" in url:
                print(f"  Found profile: {url}")
                return url
        except Exception:
            pass

    # Fallback: click first text result containing Darts
    try:
        page.get_by_text("Darts", exact=False).first.click(timeout=3500)
        time.sleep(5)

        url = page.url
        if "/player/" in url:
            print(f"  Found profile via fallback: {url}")
            return url
    except Exception:
        pass

    print(f"  No Flashscore profile found for {player_name}")
    return ""


def extract_country_age_from_text(text):
    country = ""
    age = ""

    countries = [
        "England", "Scotland", "Wales", "Northern Ireland", "Ireland",
        "USA", "United States", "Netherlands", "Germany", "Belgium",
        "Australia", "New Zealand", "Canada", "France", "Spain",
        "Poland", "Czech Republic", "South Africa", "Austria",
        "Sweden", "Norway", "Denmark", "Finland", "Italy",
    ]

    for c in countries:
        if re.search(rf"\b{re.escape(c)}\b", text, flags=re.I):
            country = c
            break

    m_age = re.search(r"\bAge:\s*(\d+)", text, flags=re.I)
    if m_age:
        age = m_age.group(1)

    return country, age


def parse_results_from_text(text, player_name):
    lines = [clean_text(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    results = []
    seen = set()

    # Flashscore result rows usually contain date/time, two names, scores and W/L badge.
    for i, line in enumerate(lines):
        if not re.match(r"^\d{1,2}\.\d{1,2}\.", line):
            continue

        window = lines[i: min(len(lines), i + 12)]
        joined = " | ".join(window)

        if joined.lower() in seen:
            continue

        seen.add(joined.lower())

        result = ""
        if re.search(r"\bW\b", joined):
            result = "W"
        elif re.search(r"\bL\b", joined):
            result = "L"

        # Score usually appears as separate digits. This is best-effort.
        nums = re.findall(r"\b\d+\b", joined)
        score = ""
        if len(nums) >= 2:
            score = f"{nums[-2]}-{nums[-1]}"

        opponent = ""
        player_parts = [p.lower() for p in player_name.split() if len(p) >= 3]

        names = []
        for w in window:
            wl = w.lower()
            if any(p in wl for p in player_parts):
                continue
            if re.search(r"[A-Za-z]", w) and not re.search(r"^\d", w):
                if w not in ["W", "L", "FT", "AOT"]:
                    names.append(w)

        if names:
            opponent = names[-1]

        results.append({
            "date": line,
            "result": result,
            "opponent": opponent,
            "score": score,
            "raw": joined,
        })

        if len(results) >= 10:
            break

    return results[:10]


def scrape_player_results(page, player_name, profile_url):
    if not profile_url:
        return {
            "name": player_name,
            "slug": slugify(player_name),
            "source": "flashscore",
            "profile_url": "",
            "status": "not_found",
            "country": "",
            "age": "",
            "recent_form": [],
            "last_10_results": [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    results_url = profile_url.rstrip("/") + "/results/"

    print(f"Scraping results: {results_url}")

    page.goto(results_url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)
    accept_cookies(page)

    for _ in range(3):
        page.mouse.wheel(0, 700)
        time.sleep(1)

    text = page.locator("body").inner_text(timeout=30000)

    debug_path = DEBUG_DIR / f"{slugify(player_name)}.txt"
    debug_path.write_text(text, encoding="utf-8")

    country, age = extract_country_age_from_text(text)
    results = parse_results_from_text(text, player_name)

    recent_form = [
        r.get("result")
        for r in results
        if r.get("result") in ["W", "L"]
    ][:10]

    return {
        "name": player_name,
        "slug": slugify(player_name),
        "source": "flashscore",
        "profile_url": profile_url,
        "results_url": results_url,
        "status": "ok",
        "country": country,
        "age": age,
        "recent_form": recent_form,
        "last_10_results": results,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    player_names = load_player_names()

    if not player_names:
        print("No player names found.")
        return

    print(f"Found {len(player_names)} unique darts players")

    players = []

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

        open_flashscore(page)

        for idx, name in enumerate(player_names, start=1):
            print(f"[{idx}/{len(player_names)}] {name}")

            try:
                profile_url = search_player(page, name)
                player_data = scrape_player_results(page, name, profile_url)

                players.append(player_data)

                print(
                    f"  Status: {player_data.get('status')}\n"
                    f"  URL: {player_data.get('profile_url') or 'not found'}\n"
                    f"  Country: {player_data.get('country') or 'unknown'}\n"
                    f"  Form: {' '.join(player_data.get('recent_form', [])) or 'none'}\n"
                    f"  Results: {len(player_data.get('last_10_results', []))}"
                )

            except Exception as e:
                print(f"  Failed: {name} — {e}")

                players.append({
                    "name": name,
                    "slug": slugify(name),
                    "source": "flashscore",
                    "profile_url": "",
                    "status": "error",
                    "country": "",
                    "age": "",
                    "recent_form": [],
                    "last_10_results": [],
                    "error": str(e),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })

        browser.close()

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "flashscore",
        "sport": "darts",
        "count": len(players),
        "players": players,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Saved {len(players)} players to {OUT_PATH}")


if __name__ == "__main__":
    main()