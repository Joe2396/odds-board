from playwright.sync_api import sync_playwright
import time
import json
import re
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BOYLESPORTS UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "boylesports_props.json"
FILTERED_OUT_PATH = ROOT / "ufc" / "data" / "boylesports_props_filtered.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

HUB_URL = "https://www.boylesports.com/sports/ufc-mma"

NON_UFC_TERMS = [
    "pfl",
    "lfa",
    "bare-knuckle",
    "bare knuckle",
    "bkfc",
    "bellator",
    "one-championship",
    "one championship",
    "cage-warriors",
    "cage warriors",
    "oktagon",
    "boxing",
    "glory",
]


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_odds(x):
    x = str(x or "").strip().upper()
    return (
        x == "EVS"
        or bool(re.match(r"^\d+/\d+$", x))
        or bool(re.match(r"^\d+\.\d+$", x))
    )


def is_ufc_only_fight(fight_name, url):
    text = f"{fight_name} {url}".lower()

    if any(term in text for term in NON_UFC_TERMS):
        return False

    if "ufc" not in text:
        return False

    return True


def is_bad_selection(selection):
    sel = str(selection or "").strip()
    low = sel.lower()

    if not sel:
        return True

    if is_odds(sel):
        return True

    if len(sel) < 3:
        return True

    if re.match(r"^\d{1,2}:\d{2}$", sel):
        return True

    if re.match(r"^\d+\s*(min|mins|minute|minutes)$", low):
        return True

    if re.match(r"^\d+%$", sel):
        return True

    bad_exact = {
        "popular",
        "cash out",
        "all markets",
        "show more",
        "show less",
        "bet builder",
        "bet builder boost",
        "full t&cs",
        "close",
        "all competitions",
        "ufc and mma",
        "ufc",
        "mma",
        "in-play",
        "sports a-z",
        "safer gambling",
        "promotions",
        "casino",
        "home",
        "back",
        "draw no bet",
        "event",
        "today",
        "tomorrow",
    }

    if low in bad_exact:
        return True

    bad_contains = [
        "create your bet builder",
        "min odds",
        "apply on betslip",
        "enjoy your boosted",
        "gaming quick links",
        "home / ufc",
        "please add one",
        "ufc stats",
        "cookie",
        "privacy",
        "back to fight card",
        "matchup",
        "tape",
        "significant strikes",
        "grappling",
        "previous fights",
        "ufc wins by",
        "mins",
        "hours ago",
        "live now",
        "starting soon",
    ]

    if any(x in low for x in bad_contains):
        return True

    return False


def empty_output():
    return {
        "updated_at": now_iso(),
        "source": "boylesports",
        "bookmaker": "BoyleSports",
        "fights": [],
    }


def save_output(output):
    output["updated_at"] = now_iso()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    shutil.copyfile(OUT_PATH, FILTERED_OUT_PATH)

    print(f"  Saved to {OUT_PATH}")
    print(f"  Copied to {FILTERED_OUT_PATH}")


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=True)
        print(f"  Debug: {label}")
    except Exception:
        pass


def accept_cookies(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
        "button:has-text('Got it')",
        "button:has-text('Essential Only')",
    ]:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("  Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def get_fight_urls_from_hub(page):
    print(f"Loading hub: {HUB_URL}")

    try:
        page.goto(HUB_URL, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"  Hub load failed: {e}")
        return []

    time.sleep(4)
    accept_cookies(page)
    time.sleep(2)

    for _ in range(8):
        page.mouse.wheel(0, 1500)
        time.sleep(0.8)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(2)

    save_debug(page, "boylesports_hub")

    blocked_terms = [
        "special",
        "boost",
        "mvp",
        "outright",
        "in-play",
        "competition",
    ]

    blocked_exact = {
        "https://www.boylesports.com/sports/ufc-mma",
        "https://www.boylesports.com/sports/ufc-mma/day",
        "https://www.boylesports.com/sports/ufc-mma/in-play",
    }

    try:
        links = page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.href || '';
                    const text = (a.innerText || a.textContent || '').trim();
                    if (href.includes('/sports/ufc-mma/event/')) {
                        results.push({ href, text });
                    }
                });
                return results;
            }
        """)
    except Exception as e:
        print(f"  Link extraction failed: {e}")
        return []

    seen = set()
    fights = []

    for link in links:
        href = str(link.get("href", "")).split("?")[0].rstrip("/")
        text = str(link.get("text", "")).strip()

        if not href or href in blocked_exact:
            continue

        href_low = href.lower()
        text_low = text.lower()

        if any(t in href_low or t in text_low for t in blocked_terms):
            continue

        if "/event/" not in href_low:
            continue

        if href in seen:
            continue

        slug = href.rstrip("/").split("/")[-1]
        fight_name = slug.replace("-v-", " vs ").replace("-", " ").title()

        if not is_ufc_only_fight(fight_name, href):
            print(f"  Skipping non-UFC: {fight_name}")
            continue

        seen.add(href)
        fights.append({"fight": fight_name, "url": href})

    print(f"Found {len(fights)} UFC fight URLs from hub")
    for f in fights:
        print(f"  - {f['fight']}")

    return fights


def get_body_text(page):
    try:
        return page.locator("body").inner_text(timeout=15000)
    except Exception:
        return ""


def normalize_lines(text):
    lines = []

    for line in str(text or "").splitlines():
        line = line.strip()

        if not line:
            continue

        if len(line) > 120:
            continue

        if is_bad_selection(line) and not is_odds(line):
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

        if is_bad_selection(sel):
            continue

        if not odds or not is_odds(odds):
            continue

        key = (sel.lower(), odds.upper())

        if key in seen:
            continue

        seen.add(key)
        unique.append({"selection": sel, "odds": odds})

    return unique


def parse_fight_betting(lines):
    section = find_section_last(
        lines,
        ["To Win Fight", "Fight Betting", "Match Betting", "Fight Result", "Bout Betting"],
        [
            "Method of Victory",
            "Method Of Victory",
            "Winning Method",
            "Rounds",
            "Total Rounds",
            "Go The Distance",
            "Round Betting",
        ],
    )

    if not section:
        section = lines[:60]

    results = []
    i = 0

    while i < len(section) - 1:
        sel = section[i].strip()
        odds = section[i + 1].strip()

        if not is_bad_selection(sel) and is_odds(odds):
            results.append({"selection": sel, "odds": odds})
            i += 2
        else:
            i += 1

    return dedupe(results)[:2]


def parse_method_of_victory(lines):
    section = find_section_last(
        lines,
        ["Method Of Victory", "Method of Victory", "Winning Method", "Method of Result"],
        [
            "Rounds",
            "Total Rounds",
            "Go The Distance",
            "Round Betting",
            "Double Chance",
            "To Win Fight",
        ],
    )

    results = []
    allowed = [
        " by ",
        "draw",
        "ko/tko",
        "ko,",
        "submission",
        "decision",
        "disqualification",
    ]

    for i in range(len(section) - 1):
        sel = section[i].strip()
        odds = section[i + 1].strip()

        if is_bad_selection(sel) or not is_odds(odds):
            continue

        if any(term in sel.lower() for term in allowed):
            results.append({"selection": sel, "odds": odds})

    return dedupe(results)


def parse_go_distance(lines):
    section = find_section_last(
        lines,
        ["Go The Distance", "Fight Goes The Distance", "To Go The Distance"],
        ["Round Betting", "Total Rounds", "Method", "Double Chance"],
    )

    results = []

    for i in range(len(section) - 1):
        sel = section[i].strip()
        odds = section[i + 1].strip()

        if not is_odds(odds):
            continue

        if sel.lower() in ["yes", "no"]:
            results.append({"selection": sel, "odds": odds})

    return dedupe(results)


def parse_rounds(lines):
    section = find_section_last(
        lines,
        ["Rounds", "Total Rounds", "Round Betting"],
        ["Go The Distance", "Method", "Double Chance", "To Win Fight"],
    )

    results = []

    for i in range(len(section) - 1):
        sel = section[i].strip()
        odds = section[i + 1].strip()

        if is_bad_selection(sel) or not is_odds(odds):
            continue

        low = sel.lower()
        valid = (
            "round" in low
            or "over" in low
            or "under" in low
            or re.search(r"\d+\.\d+", low)
        )

        if valid:
            results.append({"selection": sel, "odds": odds})

    return dedupe(results)


def click_tab(page, tab_name):
    for selector in [
        f"button:has-text('{tab_name}')",
        f"a:has-text('{tab_name}')",
        f"div[role='tab']:has-text('{tab_name}')",
        f"text={tab_name}",
    ]:
        try:
            page.locator(selector).first.click(force=True, timeout=4000)
            print(f"  Clicked: {tab_name}")
            time.sleep(3)
            return True
        except Exception:
            pass

    return False


def scrape_fight(page, fight_name, fight_url, index):
    if not is_ufc_only_fight(fight_name, fight_url):
        print(f"SKIPPING NON-UFC BEFORE SCRAPE: {fight_name}")
        return None

    print(f"\n{'=' * 50}")
    print(f"[{index}] {fight_name}")
    print(f"URL: {fight_url}")
    print(f"{'=' * 50}")

    try:
        page.goto(fight_url, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"  Page load failed: {e}")
        return None

    print("  Waiting for page...")
    time.sleep(8)
    accept_cookies(page)
    time.sleep(2)

    for _ in range(4):
        page.mouse.wheel(0, 1200)
        time.sleep(0.8)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)

    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", fight_name).strip("_").lower()
    save_debug(page, f"boylesports_{index}_{safe_label}")

    text = get_body_text(page)
    lines = normalize_lines(text)

    fight_betting = parse_fight_betting(lines)
    print(f"  Fight Betting: {len(fight_betting)}")

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)

    clicked = click_tab(page, "Method Of Victory")
    if not clicked:
        clicked = click_tab(page, "Method of Victory")

    if clicked:
        text = get_body_text(page)
        method = parse_method_of_victory(normalize_lines(text))
    else:
        method = []

    print(f"  Method of Victory: {len(method)}")

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)

    clicked = click_tab(page, "Rounds")

    if clicked:
        text = get_body_text(page)
        lines_rounds = normalize_lines(text)
        rounds = parse_rounds(lines_rounds)
        go_distance = parse_go_distance(lines_rounds)
    else:
        rounds = []
        go_distance = []

    print(f"  Rounds: {len(rounds)}")
    print(f"  Go The Distance: {len(go_distance)}")

    has_props = bool(fight_betting or method or rounds or go_distance)
    print(f"  Has props: {has_props}")

    return {
        "bookmaker": "BoyleSports",
        "fight": fight_name,
        "fight_name": fight_name,
        "url": fight_url,
        "has_props": has_props,
        "scraped_at": now_iso(),
        "markets": {
            "fight_betting": fight_betting,
            "method_of_victory": method,
            "rounds": rounds,
            "go_the_distance": go_distance,
        },
    }


def upsert_fight(output, fight_data):
    existing = output.get("fights", [])
    url = fight_data.get("url")

    for i, item in enumerate(existing):
        if item.get("url") == url:
            existing[i] = fight_data
            return

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
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )

        page = context.new_page()

        fight_links = get_fight_urls_from_hub(page)

        if not fight_links:
            print("No UFC fight URLs found on hub page.")
            save_output(output)
            if not is_github_actions():
                input("\nDone. Press Enter to close browser...")
            browser.close()
            return

        print(f"\nUFC fights to scrape: {len(fight_links)}")

        for index, fight in enumerate(fight_links, start=1):
            if not is_ufc_only_fight(fight["fight"], fight["url"]):
                print(f"SKIPPING NON-UFC: {fight['fight']}")
                continue

            print(f"\nProgress: {index}/{len(fight_links)}")

            try:
                fight_data = scrape_fight(page, fight["fight"], fight["url"], index)
                if fight_data:
                    upsert_fight(output, fight_data)
                    save_output(output)
            except Exception as e:
                print(f"ERROR on {fight['fight']}: {e}")
                import traceback
                traceback.print_exc()
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()