from playwright.sync_api import sync_playwright
import time
import json
import re
import os
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING WILLIAM HILL UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "williamhill_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

HUB_URL = "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/today/match-betting"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def is_odds(x):
    x = str(x or "").strip().upper()
    if not x:
        return False
    if x == "EVS":
        return True
    if re.match(r"^\d+/\d+$", x):
        return True
    if re.match(r"^\d+\.\d+$", x):
        try:
            return float(x) > 1
        except Exception:
            return False
    return False


def empty_output():
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "williamhill",
        "bookmaker": "William Hill",
        "fights": [],
    }


def save_output(output):
    output["updated_at"] = datetime.now(timezone.utc).isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"  Saved to {OUT_PATH}")


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=True)
        print(f"  Debug: {label}")
    except Exception as e:
        print(f"  Debug failed: {e}")


def accept_cookies(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
    ]:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("  Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def get_fight_urls(page):
    """Extract individual fight URLs from William Hill UFC hub."""
    print("  Extracting fight URLs...")

    try:
        links = page.evaluate("""
            () => {
                const results = [];
                const seen = new Set();
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.href || '';
                    const text = (a.innerText || a.textContent || '').trim();
                    if (
                        href.includes('/ufc/') &&
                        (href.includes('OB_EV') || href.includes('-vs-') || href.includes('-v-'))
                        && !seen.has(href)
                        && href.includes('williamhill')
                    ) {
                        seen.add(href);
                        results.push({ href, text });
                    }
                });
                return results;
            }
        """)

        fights = []
        for link in links:
            href = link.get("href", "")
            text = link.get("text", "").strip()
            # Filter out nav/promo links
            if len(text) > 100:
                continue
            if any(x in href.lower() for x in ["competition", "match-betting", "coupon", "boost"]):
                continue
            fights.append({"url": href, "fight_name": text})

        print(f"  Found {len(fights)} fight URLs")
        for f in fights:
            print(f"    - {f['fight_name']} | {f['url']}")

        return fights

    except Exception as e:
        print(f"  URL extraction failed: {e}")
        return []


def get_fight_urls_from_html(page):
    """Fallback: extract fight URLs from page HTML."""
    try:
        content = page.content()
        # Find all OB_EV links
        pattern = r'href="(/betting/en-gb/ufc/OB_EV[^"]+)"'
        matches = re.findall(pattern, content)
        seen = set()
        fights = []
        for match in matches:
            full_url = f"https://sports.williamhill.com{match}"
            if full_url not in seen:
                seen.add(full_url)
                fights.append({"url": full_url, "fight_name": ""})
        print(f"  HTML fallback found {len(fights)} URLs")
        return fights
    except Exception as e:
        print(f"  HTML fallback failed: {e}")
        return []


def get_fight_name_from_page(page):
    try:
        h1 = page.locator("h1").first.inner_text(timeout=3000).strip()
        if h1 and (" v " in h1.lower() or " vs " in h1.lower()):
            return h1
    except Exception:
        pass
    try:
        title = page.title()
        if " v " in title.lower() or " vs " in title.lower():
            return title.split("|")[0].strip()
    except Exception:
        pass
    return ""


def normalize_lines(text):
    junk_contains = [
        "william hill", "log in", "join", "free to play",
        "in-play", "promotions", "all sports",
        "horse racing", "tennis", "media",
        "vegas", "live casino", "bingo", "poker",
        "request #yourodds", "trending #yourodds",
        "price boost", "best odds guaranteed",
        "acca boost", "bonus drop", "safer gambling",
        "privacy", "cookie", "terms and conditions",
        "jackpot drop", "plus card", "back to top",
        "find us on", "our app", "help",
    ]

    lines = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if any(j in low for j in junk_contains):
            continue
        if len(line) > 120:
            continue
        lines.append(line)

    return lines


def find_section_last(lines, start_terms, stop_terms):
    start_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if any(term.lower() == low or term.lower() in low for term in start_terms):
            start_idx = i

    if start_idx is None:
        return []

    end_idx = min(len(lines), start_idx + 100)
    for j in range(start_idx + 1, len(lines)):
        low = lines[j].lower()
        if any(term.lower() == low or term.lower() in low for term in stop_terms):
            end_idx = j
            break

    return lines[start_idx:end_idx]


def dedupe(results):
    seen = set()
    unique = []
    for item in results:
        sel = str(item.get("selection", "")).strip()
        odds = str(item.get("odds", "")).strip()
        if not sel or not odds or not is_odds(odds):
            continue
        key = (sel.lower(), odds.upper())
        if key in seen:
            continue
        seen.add(key)
        unique.append({"selection": sel, "odds": odds})
    return unique


def parse_bout_betting(lines, fight_name):
    fighters = []
    if " v " in fight_name.lower():
        parts = re.split(r"\s+v\s+", fight_name, flags=re.I)
        fighters = [p.strip() for p in parts if p.strip()]
    elif " vs " in fight_name.lower():
        parts = re.split(r"\s+vs\s+", fight_name, flags=re.I)
        fighters = [p.strip() for p in parts if p.strip()]

    if len(fighters) != 2:
        return []

    section = find_section_last(
        lines,
        ["Bout Betting", "Match Betting", "Fight Betting", "Fight Result"],
        ["Method of Result", "Method of Victory", "Total Rounds",
         "Go The Distance", "Round Betting", "Alternative", "Trending"],
    )

    if not section:
        section = lines[:60]

    fighter_positions = {}
    for i, line in enumerate(section):
        low = line.lower()
        for fighter in fighters:
            if fighter.lower() == low or fighter.lower() in low:
                if fighter not in fighter_positions:
                    fighter_positions[fighter] = i

    if len(fighter_positions) < 2:
        return []

    last_pos = max(fighter_positions.values())

    odds_after = []
    for i in range(last_pos + 1, len(section)):
        if is_odds(section[i]):
            odds_after.append(section[i])
        if len(odds_after) >= 2:
            break

    if len(odds_after) < 2:
        return []

    sorted_fighters = sorted(fighter_positions.items(), key=lambda x: x[1])
    results = []
    for (fighter, _), odds in zip(sorted_fighters, odds_after):
        results.append({"selection": fighter, "odds": odds})

    return dedupe(results)


def parse_method_of_result(lines):
    section = find_section_last(
        lines,
        ["Method of Result", "Method of Victory"],
        ["Alternative Method", "Round Betting", "Total Rounds",
         "Go The Distance", "Double Chance"],
    )

    results = []
    allowed = [" by ko", " by decision", " by submission", "draw", " ko", " tko", "submission", "decision"]

    for i in range(len(section) - 1):
        sel = section[i].strip()
        odds = section[i + 1].strip()
        if is_odds(sel) or not is_odds(odds):
            continue
        low = sel.lower()
        if any(term in low for term in allowed):
            results.append({"selection": sel, "odds": odds})

    return dedupe(results)


def parse_total_rounds(lines):
    section = find_section_last(
        lines,
        ["Total Rounds", "Round Betting"],
        ["Go The Distance", "Method of", "Double Chance", "Alternative"],
    )

    results = []
    for i in range(len(section) - 1):
        sel = section[i].strip()
        odds = section[i + 1].strip()
        if is_odds(sel) or not is_odds(odds):
            continue
        low = sel.lower()
        valid = "over" in low or "under" in low or re.search(r"\d+\.\d+", low)
        if valid:
            results.append({"selection": sel, "odds": odds})

    return dedupe(results)


def parse_go_distance(lines):
    section = find_section_last(
        lines,
        ["Go The Distance", "Will the fight go the distance"],
        ["Method of", "Round Betting", "Total Rounds", "Double Chance", "Alternative"],
    )

    results = []
    for i in range(len(section) - 1):
        sel = section[i].strip()
        odds = section[i + 1].strip()
        if is_odds(sel) or not is_odds(odds):
            continue
        low = sel.lower()
        valid = low in ["yes", "no"] or "distance" in low
        if valid:
            results.append({"selection": sel, "odds": odds})

    return dedupe(results)


def scrape_fight(page, fight_url, fight_name, index):
    print(f"\n{'='*50}")
    print(f"[{index}] {fight_name or fight_url}")
    print(f"{'='*50}")

    try:
        page.goto(fight_url, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"  Page load failed: {e}")
        return None

    print("  Waiting for page...")
    time.sleep(7)
    accept_cookies(page)
    time.sleep(1)

    for _ in range(5):
        page.mouse.wheel(0, 1200)
        time.sleep(0.6)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)

    if not fight_name or (
        " v " not in fight_name.lower() and " vs " not in fight_name.lower()
    ):
        fight_name = get_fight_name_from_page(page)

    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", fight_name or "unknown").strip("_").lower()
    save_debug(page, f"wh_{index}_{safe_label}")

    try:
        body_text = page.locator("body").inner_text(timeout=12000)
    except Exception:
        body_text = ""

    lines = normalize_lines(body_text)

    fight_betting = parse_bout_betting(lines, fight_name)
    method = parse_method_of_result(lines)
    total_rounds = parse_total_rounds(lines)
    go_distance = parse_go_distance(lines)

    has_props = bool(fight_betting or method or total_rounds or go_distance)

    print(f"\n  -- {fight_name} --")
    print(f"  Fight Betting:     {len(fight_betting)}")
    print(f"  Method of Result:  {len(method)}")
    print(f"  Total Rounds:      {len(total_rounds)}")
    print(f"  Go The Distance:   {len(go_distance)}")
    print(f"  Has props:         {has_props}")

    return {
        "fight": fight_name,
        "url": fight_url,
        "has_props": has_props,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markets": {
            "fight_betting": fight_betting,
            "method_of_victory": method,
            "rounds": total_rounds,
            "go_the_distance": go_distance,
        },
    }


def upsert_fight(output, fight_data):
    existing = output.get("fights", [])
    url = fight_data.get("url")
    updated = False
    for i, item in enumerate(existing):
        if item.get("url") == url:
            existing[i] = fight_data
            updated = True
            break
    if not updated:
        existing.append(fight_data)
    output["fights"] = existing


def main():
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
            locale="en-GB",
            timezone_id="Europe/London",
        )

        page = context.new_page()

        # Load hub
        print(f"\nLoading hub: {HUB_URL}")
        try:
            page.goto(HUB_URL, timeout=60000, wait_until="domcontentloaded")
            print("  Waiting for hub...")
            time.sleep(10)
            accept_cookies(page)
            time.sleep(2)

            for _ in range(5):
                page.mouse.wheel(0, 1200)
                time.sleep(0.6)

            save_debug(page, "wh_hub")

            fight_links = get_fight_urls(page)

            # Fallback to HTML parsing if DOM approach found nothing
            if not fight_links:
                print("  Trying HTML fallback...")
                fight_links = get_fight_urls_from_html(page)

        except Exception as e:
            print(f"  Hub failed: {e}")
            fight_links = []

        if not fight_links:
            print("  No fight URLs found. Check wh_hub.png debug screenshot.")
            save_output(output)
            if not is_github_actions():
                input("\nDone. Press Enter to close browser...")
            browser.close()
            return

        print(f"\nFound {len(fight_links)} fights to scrape")

        for index, fight in enumerate(fight_links, start=1):
            print(f"\nProgress: {index}/{len(fight_links)}")
            try:
                fight_data = scrape_fight(
                    page,
                    fight["url"],
                    fight.get("fight_name", ""),
                    index,
                )
                if fight_data:
                    upsert_fight(output, fight_data)
                    save_output(output)
            except Exception as e:
                print(f"ERROR: {e}")
                import traceback
                traceback.print_exc()
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()