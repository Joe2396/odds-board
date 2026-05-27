from playwright.sync_api import sync_playwright
from pathlib import Path
from datetime import datetime, timezone
import json
import re
import os
import time

print("RUNNING FAST PADDYPOWER DARTS ODDS + PROPS SCRAPER")

ROOT = Path(__file__).resolve().parents[2]

MATCHES_PATH = ROOT / "darts" / "data" / "paddypower_darts_matches.json"
OUT_PATH = ROOT / "darts" / "data" / "paddypower_darts_odds.json"
DEBUG_DIR = ROOT / "darts" / "debug" / "paddypower_darts_odds"

DARTS_URL = "https://www.paddypower.com/darts"

DEBUG_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def slugify(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def is_odds(x):
    x = str(x or "").strip().upper()

    if not x:
        return False

    if x == "EVS":
        return True

    if re.match(r"^\d+/\d+$", x):
        return True

    # Do not accept whole numbers like "180".
    # PaddyPower uses "180" as a market/tab label, not odds.
    if re.match(r"^\d+\.\d+$", x):
        try:
            value = float(x)
            return 1.01 <= value <= 100
        except Exception:
            return False

    return False


def fractional_to_decimal(value):
    value = clean_text(value).upper()

    if value == "EVS":
        return 2.0

    if "/" in value:
        try:
            a, b = value.split("/", 1)
            return round((float(a) / float(b)) + 1, 4)
        except Exception:
            return None

    try:
        return float(value)
    except Exception:
        return None


def match_slug(player_1, player_2):
    return slugify(f"{player_1} vs {player_2}")


def empty_output():
    return {
        "updated_at": now_iso(),
        "source": "paddypower",
        "bookmaker": "PaddyPower",
        "sport": "darts",
        "markets_scraped": [
            "match_odds",
            "leg_handicap",
            "player_total_180s",
            "total_legs",
            "total_180s",
        ],
        "matches": [],
    }


def save_output(output):
    output["updated_at"] = now_iso()
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved progress to {OUT_PATH}")


def load_matches():
    if not MATCHES_PATH.exists():
        print(f"Missing matches file: {MATCHES_PATH}")
        return []

    data = json.loads(MATCHES_PATH.read_text(encoding="utf-8"))
    matches = []

    for competition, rows in data.get("competitions", {}).items():
        for row in rows:
            p1 = clean_text(row.get("player_1"))
            p2 = clean_text(row.get("player_2"))

            if not p1 or not p2:
                continue

            item = dict(row)
            item["competition"] = competition
            item["match_slug"] = match_slug(p1, p2)
            matches.append(item)

    matches.sort(key=lambda m: (m.get("day", ""), m.get("time", ""), m.get("player_1", "")))
    return matches


def close_cookie_popup(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=2000, force=True)
            time.sleep(0.5)
            return
        except Exception:
            pass


def click_tab(page, tab_name, wait=1.4):
    selectors = [
        f"button:has-text('{tab_name}')",
        f"a:has-text('{tab_name}')",
        f"span:has-text('{tab_name}')",
        f"text={tab_name}",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(force=True, timeout=3000)
            time.sleep(wait)
            return True
        except Exception:
            pass

    return False


def expand_section(page, section_name, wait=0.9):
    selectors = [
        f"button:has-text('{section_name}')",
        f"span:has-text('{section_name}')",
        f"text={section_name}",
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector).first
            loc.scroll_into_view_if_needed(timeout=3000)
            time.sleep(0.2)
            loc.click(force=True, timeout=3000)
            time.sleep(wait)
            return True
        except Exception:
            pass

    return False


def get_body_text(page):
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


def normalize_lines(text):
    junk_contains = [
        "if you bet",
        "current odds",
        "odds of",
        "you would win",
        "gambling can be addictive",
        "please gamble responsibly",
        "privacy policy",
        "cookie policy",
        "underage gambling",
        "resolve a dispute",
        "give feedback",
        "paddy power rules",
        "shop exclusives",
        "racing results",
        "popular events",
        "bet on popular",
        "where can i bet",
        "how much could i win",
        "what are the other",
        "odds shown in the above",
        "ppb counterparty",
        "ppb entertainment",
        "ppb games",
        "malta gaming",
        "gambling commission",
        "show more",
        "help & contact",
        "promotions",
        "responsible gambling",
        "browse all",
        "sports betting",
        "darts betting",
        "popular fifa",
        "popular uefa",
        "cash out",
    ]

    lines = []

    for line in str(text or "").splitlines():
        line = clean_text(line)

        if not line:
            continue

        low = line.lower()

        if any(j in low for j in junk_contains):
            continue

        if len(line) > 130:
            continue

        lines.append(line)

    return lines


def find_section_after_last(lines, start_terms, stop_terms, window=90):
    start_idx = None

    for i, line in enumerate(lines):
        low = line.lower()

        if any(term.lower() == low or term.lower() in low for term in start_terms):
            start_idx = i

    if start_idx is None:
        return []

    end_idx = min(len(lines), start_idx + window)

    for j in range(start_idx + 1, min(len(lines), start_idx + window)):
        low = lines[j].lower()

        if any(term.lower() == low or term.lower() in low for term in stop_terms):
            end_idx = j
            break

    return lines[start_idx:end_idx]


def find_section_after_first(lines, start_terms, stop_terms, window=60):
    start_idx = None

    for i, line in enumerate(lines):
        low = line.lower()

        if any(term.lower() == low or term.lower() in low for term in start_terms):
            start_idx = i
            break

    if start_idx is None:
        return []

    end_idx = min(len(lines), start_idx + window)

    for j in range(start_idx + 1, min(len(lines), start_idx + window)):
        low = lines[j].lower()

        if any(term.lower() == low or term.lower() in low for term in stop_terms):
            end_idx = j
            break

    return lines[start_idx:end_idx]


def dedupe_results(results):
    seen = set()
    unique = []

    for item in results:
        selection = clean_text(item.get("selection", ""))
        odds = clean_text(item.get("odds", ""))

        if not selection or not odds or not is_odds(odds):
            continue

        key = (selection.lower(), odds.upper())

        if key in seen:
            continue

        seen.add(key)

        unique.append({
            "selection": selection,
            "odds": odds,
            "decimal": fractional_to_decimal(odds),
        })

    return unique


def parse_selection_odds_pairs(section, valid_selector=None):
    results = []

    for i in range(len(section) - 1):
        selection = clean_text(section[i])
        odds = clean_text(section[i + 1])

        if is_odds(selection) or not is_odds(odds):
            continue

        if valid_selector and not valid_selector(selection):
            continue

        results.append({
            "selection": selection,
            "odds": odds,
        })

    return dedupe_results(results)


def parse_match_odds_from_anywhere(lines, match):
    p1 = clean_text(match.get("player_1"))
    p2 = clean_text(match.get("player_2"))

    p1n = norm(p1)
    p2n = norm(p2)

    for i, line in enumerate(lines):
        if norm(line) not in [p1n, p2n]:
            continue

        window = lines[i:i + 20]

        has_p1 = any(norm(x) == p1n or p1n in norm(x) for x in window)
        has_p2 = any(norm(x) == p2n or p2n in norm(x) for x in window)

        if not has_p1 or not has_p2:
            continue

        odds = [x for x in window if is_odds(x)]

        if len(odds) >= 2:
            names = []

            for x in window:
                if norm(x) == p1n or p1n in norm(x):
                    names.append(p1)
                elif norm(x) == p2n or p2n in norm(x):
                    names.append(p2)

            ordered = []

            for n in names:
                if n not in ordered:
                    ordered.append(n)

            if len(ordered) == 2:
                return dedupe_results([
                    {"selection": ordered[0], "odds": odds[0]},
                    {"selection": ordered[1], "odds": odds[1]},
                ])

    return []


def parse_leg_handicap(lines):
    section = find_section_after_last(
        lines,
        ["Leg Handicap"],
        [
            "Most 180's",
            "Total 180's",
            "Total 180s",
            "Total Legs",
            "Correct Score",
            "To Win Leg",
            "1st Player to Score",
        ],
        window=70,
    )

    def valid(selection):
        low = selection.lower()
        return "+" in low or "-" in low or re.search(r"\d+\.\d+", low)

    return parse_selection_odds_pairs(section, valid)


def parse_total_legs(lines):
    section = find_section_after_last(
        lines,
        ["Total Legs"],
        [
            "Correct Score",
            "To Win Leg",
            "1st Player to Score",
            "180s Handicap",
            "Popular Events",
        ],
        window=70,
    )

    def valid(selection):
        low = selection.lower()
        return "over" in low or "under" in low or re.search(r"\d+\.\d+", low)

    return parse_selection_odds_pairs(section, valid)


def parse_total_180s(lines):
    section = find_section_after_last(
        lines,
        ["Total 180's", "Total 180s"],
        [
            "Total Legs",
            "Correct Score",
            "To Win Leg",
            "1st Player to Score",
            "180s Handicap",
            "Popular Events",
        ],
        window=70,
    )

    def valid(selection):
        low = selection.lower()
        return "over" in low or "under" in low or re.search(r"\d+\.\d+", low)

    return parse_selection_odds_pairs(section, valid)


def parse_player_total_180s(lines, player_name, other_player_name=None):
    stop_terms = [
        "To Win Leg",
        "1st Player to Score",
        "180s Handicap",
        "Popular Events",
        "Sports Betting",
        "Darts Betting",
    ]

    if other_player_name:
        stop_terms.extend([
            f"{other_player_name} Total 180's",
            f"{other_player_name} Total 180s",
        ])

    section = find_section_after_first(
        lines,
        [f"{player_name} Total 180's", f"{player_name} Total 180s"],
        stop_terms,
        window=45,
    )

    def valid(selection):
        low = selection.lower()
        return "over" in low or "under" in low or re.search(r"\d+\.\d+", low)

    return parse_selection_odds_pairs(section, valid)


def open_darts_home_and_collect_urls(page, matches):
    page.goto(DARTS_URL, timeout=70000, wait_until="domcontentloaded")
    time.sleep(5)
    close_cookie_popup(page)

    for _ in range(7):
        page.mouse.wheel(0, 1100)
        time.sleep(0.25)

    anchors = page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || ''
        }))
        """
    )

    url_map = {}

    for match in matches:
        p1 = clean_text(match.get("player_1"))
        p2 = clean_text(match.get("player_2"))
        p1n = norm(p1)
        p2n = norm(p2)

        hits = []

        for a in anchors:
            href = a.get("href", "")
            text = a.get("text", "")

            if "/darts/" not in href:
                continue

            combined = norm(text + " " + href)

            if p1n in combined and p2n in combined:
                hits.append(href)

        if hits:
            url_map[match["match_slug"]] = sorted(hits, key=len, reverse=True)[0]

    return url_map


def scrape_match(page, match, match_url):
    p1 = clean_text(match.get("player_1"))
    p2 = clean_text(match.get("player_2"))
    name = f"{p1} vs {p2}"

    print("\n==============================")
    print(f"Scraping: {name}")
    print("==============================")

    if not match_url:
        print("  No match URL")
        return {
            "match": name,
            "match_slug": match.get("match_slug"),
            "competition": match.get("competition"),
            "day": match.get("day", ""),
            "time": match.get("time", ""),
            "bookmaker": "PaddyPower",
            "url": "",
            "has_markets": False,
            "scraped_at": now_iso(),
            "markets": {
                "match_odds": [],
                "leg_handicap": [],
                "total_legs": [],
                "total_180s": [],
                "player_total_180s": {p1: [], p2: []},
            },
            "status": "match_url_not_found",
        }

    page.goto(match_url, timeout=70000, wait_until="domcontentloaded")
    time.sleep(4)
    close_cookie_popup(page)

    # Fresh Popular parse first.
    click_tab(page, "Popular", wait=1.2)
    text_popular = get_body_text(page)
    lines_popular = normalize_lines(text_popular)
    match_odds = parse_match_odds_from_anywhere(lines_popular, match)

    # Fresh All Markets parse.
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.3)
    click_tab(page, "All Markets", wait=1.2)

    # Stable props first.
    expand_section(page, "Leg Handicap", wait=0.8)

    # Try both apostrophe and no-apostrophe variants.
    expand_section(page, f"{p1} Total 180's", wait=0.8)
    expand_section(page, f"{p2} Total 180's", wait=0.8)
    expand_section(page, f"{p1} Total 180s", wait=0.8)
    expand_section(page, f"{p2} Total 180s", wait=0.8)

    # Missing props we now partially scrape.
    expand_section(page, "Total Legs", wait=0.8)
    expand_section(page, "Total 180's", wait=0.8)
    expand_section(page, "Total 180s", wait=0.8)

    for _ in range(2):
        page.mouse.wheel(0, 900)
        time.sleep(0.25)

    text_all = get_body_text(page)

    debug_path = DEBUG_DIR / f"{match.get('match_slug')}.txt"
    debug_path.write_text(
        text_popular + "\n\n--- ALL MARKETS ---\n\n" + text_all,
        encoding="utf-8",
    )

    lines_all = normalize_lines(text_all)

    leg_handicap = parse_leg_handicap(lines_all)
    total_legs = parse_total_legs(lines_all)
    total_180s = parse_total_180s(lines_all)
    p1_180s = parse_player_total_180s(lines_all, p1, p2)
    p2_180s = parse_player_total_180s(lines_all, p2, p1)

    print(f"  Match Odds: {len(match_odds)}")
    print(f"  Leg Handicap: {len(leg_handicap)}")
    print(f"  Total Legs: {len(total_legs)}")
    print(f"  Total 180s: {len(total_180s)}")
    print(f"  {p1} Total 180s: {len(p1_180s)}")
    print(f"  {p2} Total 180s: {len(p2_180s)}")

    has_markets = bool(
        match_odds
        or leg_handicap
        or total_legs
        or total_180s
        or p1_180s
        or p2_180s
    )

    return {
        "match": name,
        "match_slug": match.get("match_slug"),
        "competition": match.get("competition"),
        "day": match.get("day", ""),
        "time": match.get("time", ""),
        "bookmaker": "PaddyPower",
        "url": match_url,
        "has_markets": has_markets,
        "scraped_at": now_iso(),
        "markets": {
            "match_odds": match_odds,
            "leg_handicap": leg_handicap,
            "total_legs": total_legs,
            "total_180s": total_180s,
            "player_total_180s": {
                p1: p1_180s,
                p2: p2_180s,
            },
        },
        "status": "ok" if has_markets else "no_markets_found",
    }


def upsert_match(output, match_data):
    existing = output.get("matches", [])
    slug = match_data.get("match_slug")

    for i, item in enumerate(existing):
        if item.get("match_slug") == slug:
            existing[i] = match_data
            output["matches"] = existing
            return

    existing.append(match_data)
    output["matches"] = existing


def main():
    matches = load_matches()

    if not matches:
        output = empty_output()
        save_output(output)
        return

    output = empty_output()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_github_actions(),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )

        page = context.new_page()

        print("Collecting current PaddyPower match URLs once...")
        url_map = open_darts_home_and_collect_urls(page, matches)
        print(f"Found URLs for {len(url_map)}/{len(matches)} matches")

        for index, match in enumerate(matches, start=1):
            print(f"\nProgress: {index}/{len(matches)}")

            try:
                match_url = url_map.get(match["match_slug"], "")
                match_data = scrape_match(page, match, match_url)
                upsert_match(output, match_data)
                save_output(output)
            except Exception as e:
                print(f"ERROR scraping {match.get('player_1')} vs {match.get('player_2')}: {e}")
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved PaddyPower darts odds to {OUT_PATH}")


if __name__ == "__main__":
    main()