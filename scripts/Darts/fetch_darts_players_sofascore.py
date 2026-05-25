from playwright.sync_api import sync_playwright
from pathlib import Path
from datetime import datetime, timezone
import json
import re
import time

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "darts" / "data" / "players.json"
DEBUG_DIR = ROOT / "darts" / "debug" / "sofascore_players"

SOFASCORE_DARTS_URL = "https://www.sofascore.com/darts"

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


def short_name_to_guess(short_name):
    """
    SofaScore often shows:
      Lauby Jr D.
      Henderson J.
      Green S.

    We store that as the display name for now.
    Later we can map it back to PaddyPower full names.
    """
    return clean_text(short_name)


def accept_sofascore_cookies(page):
    labels = [
        "Consent",
        "Accept all",
        "Accept All",
        "I Accept",
        "Agree",
        "OK",
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


def get_sofascore_darts_page(page):
    print("Opening SofaScore darts page...")
    page.goto(SOFASCORE_DARTS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    accept_sofascore_cookies(page)

    # Scroll a bit so fixtures are definitely loaded
    for _ in range(3):
        page.mouse.wheel(0, 600)
        time.sleep(1)

    text = page.locator("body").inner_text(timeout=30000)
    (DEBUG_DIR / "darts_home_text.txt").write_text(text, encoding="utf-8")


def click_first_modus_match(page):
    """
    Clicks the first visible MODUS match on SofaScore darts page.
    We use the visible fixture list instead of search because search URLs
    are unreliable and sometimes 404.
    """
    print("Trying to open first visible MODUS match...")

    # Make sure we are near the fixture list
    page.mouse.wheel(0, 500)
    time.sleep(1)

    # First try clicking the competition area/player rows.
    # On SofaScore, clicking a match row usually opens the match detail page.
    candidate_texts = [
        "Modus Super Series",
        "Lauby",
        "Henderson",
        "Green",
        "Morris",
        "Cressey",
        "Uriot",
    ]

    for text in candidate_texts:
        try:
            page.get_by_text(text, exact=False).first.click(timeout=4000)
            time.sleep(5)

            if "/darts/match/" in page.url or "/match/" in page.url:
                print(f"Opened match page: {page.url}")
                return True

            # Sometimes the first click only focuses the row. Try enter.
            try:
                page.keyboard.press("Enter")
                time.sleep(3)
                if "/darts/match/" in page.url or "/match/" in page.url:
                    print(f"Opened match page: {page.url}")
                    return True
            except Exception:
                pass

        except Exception:
            pass

    # More aggressive fallback: click around fixture area
    try:
        page.mouse.click(310, 530)
        time.sleep(5)
        if "/darts/match/" in page.url or "/match/" in page.url:
            print(f"Opened match page: {page.url}")
            return True
    except Exception:
        pass

    print("Could not open a MODUS match page.")
    return False


def extract_player_links_from_match(page):
    """
    On a SofaScore match page, player names usually link to /darts/player/...
    """
    print("Extracting player profile links from match page...")

    time.sleep(3)
    accept_sofascore_cookies(page)

    html = page.content()

    links = re.findall(
        r'href="([^"]*/darts/player/[^"]+)"',
        html,
        flags=re.I,
    )

    cleaned_links = []

    for link in links:
        if link.startswith("/"):
            link = "https://www.sofascore.com" + link
        elif link.startswith("http"):
            pass
        else:
            link = "https://www.sofascore.com/" + link.lstrip("/")

        if link not in cleaned_links:
            cleaned_links.append(link)

    # Debug page text/html
    try:
        text = page.locator("body").inner_text(timeout=30000)
        (DEBUG_DIR / "match_page_text.txt").write_text(text, encoding="utf-8")
        (DEBUG_DIR / "match_page_html.html").write_text(html, encoding="utf-8")
    except Exception:
        pass

    print(f"Found {len(cleaned_links)} player profile links")

    return cleaned_links[:2]


def extract_country_from_text(text):
    common_countries = [
        "England",
        "Scotland",
        "Wales",
        "Northern Ireland",
        "Ireland",
        "USA",
        "United States",
        "Netherlands",
        "Germany",
        "Belgium",
        "Australia",
        "New Zealand",
        "Canada",
        "France",
        "Spain",
        "Poland",
        "Czech Republic",
        "South Africa",
        "Austria",
        "Sweden",
        "Norway",
        "Denmark",
        "Finland",
        "Italy",
    ]

    for country in common_countries:
        if re.search(rf"\b{re.escape(country)}\b", text, flags=re.I):
            return country

    return ""


def extract_profile_name(text):
    lines = [clean_text(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    # Profile name usually appears near the top and is not one of these headers.
    bad = {
        "sofascore",
        "darts",
        "favourite",
        "previous match",
        "next match",
        "matches",
        "details",
        "recent form",
    }

    for line in lines[:60]:
        low = line.lower()

        if low in bad:
            continue

        if len(line) < 3:
            continue

        if any(x in low for x in ["followers", "advertisement", "sign in"]):
            continue

        # Likely player name, e.g. "Lauby Jr, Dan"
        if "," in line or re.search(r"\b[A-Z][a-z]+", line):
            return line

    return ""


def extract_recent_form_from_text(text):
    lines = [clean_text(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    form = []

    for line in lines:
        if line in ["W", "L"]:
            form.append(line)

        if len(form) >= 10:
            break

    return form[:10]


def extract_last_10_results_from_text(text):
    lines = [clean_text(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    results = []
    seen = set()

    for i, line in enumerate(lines):
        # Look around date lines like 27/02/26
        if not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", line):
            continue

        window = lines[i: min(len(lines), i + 10)]
        joined = " | ".join(window)

        if joined.lower() in seen:
            continue

        seen.add(joined.lower())

        scores = re.findall(r"\b\d+\b", joined)
        score = ""

        if len(scores) >= 2:
            score = f"{scores[-2]}-{scores[-1]}"

        result = ""

        if " W " in f" {joined} ":
            result = "W"
        elif " L " in f" {joined} ":
            result = "L"

        results.append({
            "date": line,
            "result": result,
            "score": score,
            "raw": joined,
        })

        if len(results) >= 10:
            break

    return results


def scrape_player_profile(page, profile_url):
    print(f"Scraping profile: {profile_url}")

    page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    accept_sofascore_cookies(page)

    # Scroll through profile so match history/form loads
    for _ in range(6):
        page.mouse.wheel(0, 750)
        time.sleep(1)

    text = page.locator("body").inner_text(timeout=30000)

    profile_name = extract_profile_name(text)
    slug = slugify(profile_name or profile_url.split("/")[-2])

    (DEBUG_DIR / f"{slug}.txt").write_text(text, encoding="utf-8")

    country = extract_country_from_text(text)
    recent_form = extract_recent_form_from_text(text)
    last_10_results = extract_last_10_results_from_text(text)

    if not recent_form:
        recent_form = [
            r.get("result")
            for r in last_10_results
            if r.get("result") in ["W", "L"]
        ][:10]

    return {
        "name": profile_name,
        "slug": slug,
        "source": "sofascore",
        "profile_url": profile_url,
        "status": "ok",
        "country": country,
        "recent_form": recent_form[:10],
        "last_10_results": last_10_results[:10],
        "h2h": [],
        "stats": {
            "average_180s": None,
            "checkout_rate": None,
            "three_dart_average": None,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    print("Fetching darts player profiles from SofaScore match navigation...")

    players = []
    seen_urls = set()

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

        get_sofascore_darts_page(page)

        opened = click_first_modus_match(page)

        if not opened:
            print("No match opened. Saving empty player file.")
        else:
            player_links = extract_player_links_from_match(page)

            for link in player_links:
                if link in seen_urls:
                    continue

                seen_urls.add(link)

                try:
                    player = scrape_player_profile(page, link)
                    players.append(player)

                    print(
                        f"  Player: {player.get('name') or 'unknown'}\n"
                        f"  Country: {player.get('country') or 'unknown'}\n"
                        f"  Form: {' '.join(player.get('recent_form', [])) or 'none'}\n"
                        f"  Results: {len(player.get('last_10_results', []))}"
                    )

                except Exception as e:
                    print(f"Failed scraping {link}: {e}")

        browser.close()

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "sofascore",
        "sport": "darts",
        "method": "match_navigation",
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