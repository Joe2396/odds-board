from playwright.sync_api import sync_playwright
import json
import time
import re
import os
import unicodedata
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BETVICTOR UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]

URLS_PATH = ROOT / "ufc" / "data" / "betvictor_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "betvictor_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def clean_text(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()


def normalize_name(name):
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def last_name(name):
    parts = normalize_name(name).split()
    return parts[-1] if parts else ""


def fighter_line_match(line, fighter):
    line_n = normalize_name(line)
    fighter_n = normalize_name(fighter)
    fighter_last = last_name(fighter)

    if not line_n or not fighter_n:
        return False

    if fighter_n in line_n:
        return True

    return bool(fighter_last and fighter_last in line_n)


def is_odds(x):
    x = str(x or "").strip().upper()
    return (
        x == "EVS"
        or bool(re.match(r"^\d+/\d+$", x))
        or bool(re.match(r"^\d+\.\d+$", x))
    )


def empty_output():
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "betvictor",
        "bookmaker": "BetVictor",
        "fights": [],
    }


def save_output(output):
    output["updated_at"] = datetime.now(timezone.utc).isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved to {OUT_PATH}")


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=True)
        print(f"Debug screenshot: {label}")
    except Exception as e:
        print(f"Debug failed: {e}")


def accept_cookies(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
    ]:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def load_fight_urls():
    if not URLS_PATH.exists():
        print(f"ERROR: URL file missing: {URLS_PATH}")
        return []

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    fights = []

    for fight in data.get("fights", []):
        name = fight.get("fight_name") or fight.get("fight") or ""
        url = fight.get("url") or ""

        fighter1 = fight.get("fighter1", "")
        fighter2 = fight.get("fighter2", "")

        if not fighter1 or not fighter2:
            if " vs " in name:
                fighter1, fighter2 = name.split(" vs ", 1)

        if not name or not url or not fighter1 or not fighter2:
            continue

        fights.append({
            "fight": name,
            "fight_name": name,
            "url": url,
            "fighter1": fighter1,
            "fighter2": fighter2,
            "event_name": fight.get("event_name", ""),
            "date": fight.get("date", ""),
            "fight_id": fight.get("fight_id", ""),
        })

    print(f"BetVictor matched URLs loaded: {len(fights)}")
    for x in fights[:10]:
        print(f" - {x['fight_name']} -> {x['url']}")

    return fights


def get_page_lines(page):
    body_text = page.locator("body").inner_text(timeout=20000)
    return [clean_text(l) for l in body_text.splitlines() if clean_text(l)]


def extract_fight_betting(lines, fighter1, fighter2):
    # Format A: individual event/meeting pages list fighter1 and
    # fighter2 on separate lines, with odds following shortly after.
    for i, line in enumerate(lines):
        if not fighter_line_match(line, fighter1):
            continue

        second_index = None

        for j in range(i + 1, min(i + 8, len(lines))):
            if fighter_line_match(lines[j], fighter2):
                second_index = j
                break

        if second_index is None:
            continue

        window = lines[i:min(second_index + 20, len(lines))]
        odds = [x for x in window if is_odds(x)]

        if len(odds) >= 2:
            return [
                {"selection": fighter1, "odds": odds[0]},
                {"selection": fighter2, "odds": odds[1]},
            ]

    # Format B: hub/grid card pages show both fighters on a single
    # combined line, e.g. "Manel Kape v Kyoji Horiguchi", followed
    # later by index-labeled odds like "1  4/7  2  11/8".
    for i, line in enumerate(lines):
        if not (fighter_line_match(line, fighter1) and fighter_line_match(line, fighter2)):
            continue

        window = lines[i:min(i + 25, len(lines))]
        odds = [x for x in window if is_odds(x)]

        if len(odds) >= 2:
            return [
                {"selection": fighter1, "odds": odds[0]},
                {"selection": fighter2, "odds": odds[1]},
            ]

    return []


def scrape_meeting_incremental(page, meeting_url, fights_for_url):
    """
    The BetVictor MMA hub page virtualizes its fight list: scrolling
    down to load fights further in the list unloads earlier fights
    from the DOM. A single end-of-scroll capture only ever contains
    whichever fights happen to be in the current viewport window.

    So instead we scroll in small steps and, after each step, try to
    match every fight that has not been found yet against the current
    page text. Each fight gets captured while it briefly passes
    through the loaded window.
    """
    print(f"\nOpening BetVictor meeting: {meeting_url}")

    page.goto(meeting_url, timeout=60000, wait_until="domcontentloaded")
    time.sleep(8)
    accept_cookies(page)

    results = {}
    remaining = list(fights_for_url)

    # Try matching against the initial (unscrolled) view first.
    lines = get_page_lines(page)
    still_remaining = []
    for fight in remaining:
        fb = extract_fight_betting(lines, fight["fighter1"], fight["fighter2"])
        if fb:
            results[fight["fight_name"]] = fb
            print(f"  Matched (initial view): {fight['fight_name']}")
        else:
            still_remaining.append(fight)
    remaining = still_remaining

    max_passes = 50
    scroll_step = 500

    for i in range(max_passes):
        if not remaining:
            print(f"  All fights matched after {i} scroll passes")
            break

        page.mouse.wheel(0, scroll_step)
        time.sleep(0.5)

        try:
            lines = get_page_lines(page)
        except Exception:
            continue

        still_remaining = []
        for fight in remaining:
            fb = extract_fight_betting(lines, fight["fighter1"], fight["fighter2"])
            if fb:
                results[fight["fight_name"]] = fb
                print(f"  Matched (scroll pass {i + 1}): {fight['fight_name']}")
            else:
                still_remaining.append(fight)
        remaining = still_remaining

    if remaining:
        print(f"  Could not find odds for {len(remaining)} fight(s) after {max_passes} passes:")
        for f in remaining:
            print(f"    - {f['fight_name']}")

    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", meeting_url).strip("_").lower()[-80:]
    save_debug(page, f"betvictor_meeting_{safe_label}")

    return results


def build_fight_result(fight, lines):
    fight_name = fight["fight_name"]
    fighter1 = fight["fighter1"]
    fighter2 = fight["fighter2"]

    fight_betting = extract_fight_betting(lines, fighter1, fighter2)

    markets = {
        "fight_betting": fight_betting,
        "method_of_victory": [],
        "rounds": [],
        "go_the_distance": [],
    }

    total = sum(len(v) for v in markets.values())

    print(f"\n{fight_name}")
    print(f"Fight Betting: {len(fight_betting)}")
    print(f"Total markets found: {total}")

    return {
        "bookmaker": "BetVictor",
        "fight": fight_name,
        "fight_name": fight_name,
        "url": fight["url"],
        "has_props": total > 0,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
    }


def find_header_index(lines, header_text, start=0):
    target = header_text.strip().lower()
    for i in range(start, len(lines)):
        if lines[i].strip().lower() == target:
            return i
    return None


def is_stop_line(line):
    low = line.strip().lower()
    return (
        "affiliates" in low
        or "gambling" in low
        or "terms &" in low
        or "safer gambling" in low
        or "cookies notice" in low
        or "gamcare" in low
    )


def parse_selection_rows(lines, start_idx, end_idx):
    rows = []
    i = start_idx
    while i < end_idx - 1:
        sel = lines[i]
        odds = lines[i + 1] if i + 1 < len(lines) else ""
        if is_odds(odds) and not is_odds(sel) and not is_stop_line(sel):
            rows.append({"selection": sel, "odds": odds.upper()})
            i += 2
        else:
            i += 1
    return rows


def parse_method_and_rounds(lines):
    """
    Individual BetVictor fight pages list markets as:
        Method Of Victory
        <selection>
        <odds>
        ...
        Round Betting
        <selection>
        <odds>
        ...
    """
    mov_idx = find_header_index(lines, "Method Of Victory")
    if mov_idx is None:
        return [], []

    round_idx = find_header_index(lines, "Round Betting", start=mov_idx + 1)

    if round_idx is None:
        round_idx = len(lines)
        for i in range(mov_idx + 1, len(lines)):
            if is_stop_line(lines[i]):
                round_idx = i
                break

    methods = parse_selection_rows(lines, mov_idx + 1, round_idx)

    end_idx = len(lines)
    for i in range(round_idx + 1, len(lines)):
        if is_stop_line(lines[i]):
            end_idx = i
            break

    rounds = parse_selection_rows(lines, round_idx + 1, end_idx)

    return methods, rounds


def click_into_fight_and_get_props(page, hub_url, fighter1, fighter2, max_passes=40):
    """
    Reload the hub page, scroll until this fight's combined-name card
    becomes visible, click into it, and scrape Method of Victory +
    Round Betting from the resulting individual fight page.
    """
    print(f"  Clicking into fight page for props: {fighter1} vs {fighter2}")

    try:
        page.goto(hub_url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"    Failed to reload hub: {e}")
        return [], []

    time.sleep(6)
    accept_cookies(page)

    found = False

    for i in range(max_passes):
        try:
            lines = get_page_lines(page)
        except Exception:
            lines = []

        for line in lines:
            if fighter_line_match(line, fighter1) and fighter_line_match(line, fighter2):
                found = True
                break

        if found:
            break

        page.mouse.wheel(0, 500)
        time.sleep(0.5)

    if not found:
        print("    Could not locate fight card on hub page")
        return [], []

    # Build a regex matching the combined "FighterA v FighterB" line
    # specifically, since clicking a bare fighter1 name can be
    # ambiguous (last names, partial substrings, repeated mentions
    # in boost banners etc.) and miss or hit the wrong element.
    f1_esc = re.escape(fighter1)
    f2_esc = re.escape(fighter2)
    combined_pattern = re.compile(f"{f1_esc}.{{1,5}}{f2_esc}", re.I)

    click_targets = []

    try:
        combined_loc = page.get_by_text(combined_pattern)
        if combined_loc.count():
            click_targets.append(combined_loc.first)
    except Exception:
        pass

    try:
        click_targets.append(page.get_by_text(fighter1, exact=False).first)
    except Exception:
        pass

    # Last-resort: BetVictor may display a fighter under a different
    # full name than our events.json (e.g. "Bia Mesquita" vs the
    # page's "Beatriz Mesquita", or differing diacritics like
    # "Bolanos" vs "Bolaños"). Last name alone is far more reliable.
    f1_last = last_name(fighter1)
    f2_last = last_name(fighter2)

    if f1_last:
        try:
            last_pattern = re.compile(re.escape(f1_last), re.I)
            last_loc = page.get_by_text(last_pattern)
            if last_loc.count():
                click_targets.append(last_loc.first)
        except Exception:
            pass

    navigated = False

    for attempt, target in enumerate(click_targets):
        try:
            target.scroll_into_view_if_needed(timeout=4000)
            time.sleep(0.4)
            target.click(timeout=5000, force=True)
            time.sleep(5)

            if page.url != hub_url:
                navigated = True
                break

            print(f"    Click attempt {attempt + 1} did not navigate, trying next strategy")
        except Exception as e:
            print(f"    Click attempt {attempt + 1} failed: {e}")

    if not navigated:
        print("    Could not navigate to fight page after all attempts")
        return [], []

    try:
        detail_lines = get_page_lines(page)
    except Exception:
        return [], []

    methods, rounds = parse_method_and_rounds(detail_lines)
    print(f"    Method of Victory: {len(methods)} | Rounds: {len(rounds)}")

    return methods, rounds


def main():
    fights = load_fight_urls()

    if not fights:
        print("No BetVictor fight URLs found.")
        save_output(empty_output())
        return

    output = empty_output()

    unique_urls = sorted(set(f["url"] for f in fights))

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_github_actions(),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
        )

        page = context.new_page()

        for url in unique_urls:
            fights_for_url = [f for f in fights if f["url"] == url]

            try:
                matched = scrape_meeting_incremental(page, url, fights_for_url)
            except Exception as e:
                print(f"ERROR scraping meeting {url}: {e}")
                matched = {}

            for fight in fights_for_url:
                fight_betting = matched.get(fight["fight_name"], [])

                try:
                    method_of_victory, rounds = click_into_fight_and_get_props(
                        page, url, fight["fighter1"], fight["fighter2"]
                    )
                except Exception as e:
                    print(f"    ERROR getting props for {fight['fight_name']}: {e}")
                    method_of_victory, rounds = [], []

                markets = {
                    "fight_betting": fight_betting,
                    "method_of_victory": method_of_victory,
                    "rounds": rounds,
                    "go_the_distance": [],
                }

                has_any = bool(fight_betting or method_of_victory or rounds)

                fight_data = {
                    "bookmaker": "BetVictor",
                    "fight": fight["fight_name"],
                    "fight_name": fight["fight_name"],
                    "url": fight["url"],
                    "has_props": has_any,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "markets": markets,
                }

                print(f"\n{fight['fight_name']}")
                print(f"Fight Betting: {len(fight_betting)}")
                print(f"Method of Victory: {len(method_of_victory)}")
                print(f"Rounds: {len(rounds)}")

                output["fights"].append(fight_data)
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()