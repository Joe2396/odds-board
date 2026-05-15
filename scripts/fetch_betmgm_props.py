from playwright.sync_api import sync_playwright
import json
import time
import re
import os
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BETMGM UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "betmgm_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

HUB_URL = "https://www.betmgm.co.uk/sports/mma/ufc"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def is_odds(x):
    x = str(x).strip().upper()
    return (
        x == "EVS"
        or bool(re.match(r"^\d+/\d+$", x))
        or bool(re.match(r"^\d+\.\d+$", x))
    )


def empty_output():
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "betmgm",
        "bookmaker": "BetMGM",
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
        "button:has-text('Agree')",
    ]:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("  Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def get_fight_event_ids(page):
    print("  Extracting fight event IDs from hub...")
    try:
        event_ids = page.evaluate("""
            () => {
                const ids = new Set();
                document.querySelectorAll('a[href]').forEach(a => {
                    const match = a.href.match(/#event\\/(\d+)/);
                    if (match) ids.add(match[1]);
                });
                document.querySelectorAll('[data-event-id]').forEach(el => {
                    ids.add(el.dataset.eventId);
                });
                return Array.from(ids);
            }
        """)
        if event_ids:
            print(f"  Found {len(event_ids)} event IDs from DOM")
            return event_ids
    except Exception as e:
        print(f"  DOM extraction failed: {e}")

    try:
        content = page.content()
        ids = list(set(re.findall(r'#event/(\d+)', content)))
        print(f"  Found {len(ids)} event IDs from HTML")
        return ids
    except Exception as e:
        print(f"  HTML extraction failed: {e}")

    return []


def parse_page_text(page):
    """
    BetMGM text structure (confirmed from debug):

    Bout Odds
    Fighter A          <- selection
    4/9                <- odds (next line)
    Fighter B
    7/4

    To go the distance
    Yes
    13/25
    No
    29/20

    Winning method
    Fighter A by Decision       <- all selections first
    Fighter A by KO, TKO or DQ
    Fighter A by Submission
    Draw
    Fighter B by Decision
    Fighter B by KO, TKO or DQ
    Fighter B by Submission
    Winner                      <- column header (skip)
    21/20                       <- then all odds in same order
    17/2
    6/1
    35/1
    4/1
    21/2
    6/1
    """
    try:
        body_text = page.locator("body").inner_text(timeout=15000)
    except Exception as e:
        print(f"  Could not get body text: {e}")
        return {}, ""

    lines = [l.strip() for l in body_text.splitlines() if l.strip()]
    print(f"  Text lines: {len(lines)}")

    # Section headings
    section_starts = {
        "bout odds": "fight_betting",
        "to go the distance": "go_the_distance",
        "winning method": "method_of_victory",
        "round betting": "rounds",
    }

    # Lines to skip entirely
    skip_lines = {
        "+0", "sports", "casino", "live casino", "log in", "sign up",
        "featured", "all sports", "in-play", "golden goals", "search",
        "my bets", "ufc/mma", "ufc", "mma", "outrights",
        "most popular", "fight parlays", "match events & statistics",
        "all", "method", "fight lines", "round", "winner",
        "previous", "next", "fight parlay", "fight lines",
        "match events & statistics",
    }

    # Try to get fight name from lines like "Alice Ardelean - Polyana Viana Mota"
    # It appears as three separate lines: name, "-", name
    fight_name = ""
    for idx, line in enumerate(lines):
        if line == "-" and idx > 0 and idx + 1 < len(lines):
            prev = lines[idx - 1].strip()
            nxt = lines[idx + 1].strip()
            if prev and nxt and not is_odds(prev) and not is_odds(nxt):
                fight_name = f"{prev} v {nxt}"
                break

    results = {
        "fight_betting": [],
        "method_of_victory": [],
        "rounds": [],
        "go_the_distance": [],
    }

    # Find section boundaries
    section_indices = []
    for i, line in enumerate(lines):
        lower = line.lower().strip()
        for heading, key in section_starts.items():
            if lower == heading:
                section_indices.append((i, key))
                break

    # Process each section
    for sec_num, (start_idx, section_key) in enumerate(section_indices):
        # Section content runs from start_idx+1 to the next section start (or end)
        if sec_num + 1 < len(section_indices):
            end_idx = section_indices[sec_num + 1][0]
        else:
            end_idx = len(lines)

        section_lines = lines[start_idx + 1:end_idx]

        print(f"  Section '{section_key}' has {len(section_lines)} lines")

        if section_key in ["fight_betting", "go_the_distance"]:
            # Simple alternating: selection, odds, selection, odds
            i = 0
            while i < len(section_lines) - 1:
                sel = section_lines[i].strip()
                odds = section_lines[i + 1].strip()
                sel_lower = sel.lower()

                if sel_lower in skip_lines or is_odds(sel):
                    i += 1
                    continue

                if is_odds(odds):
                    results[section_key].append({
                        "selection": sel,
                        "odds": odds,
                    })
                    i += 2
                else:
                    i += 1

        elif section_key == "method_of_victory":
            # BetMGM puts all selections first, then "Winner", then all odds
            # Collect selections (non-odds, non-junk lines before "Winner")
            selections = []
            odds_list = []
            past_winner = False

            for line in section_lines:
                lower = line.lower().strip()

                if lower in skip_lines:
                    if lower == "winner":
                        past_winner = True
                    continue

                if is_odds(line):
                    odds_list.append(line.strip())
                elif not past_winner:
                    selections.append(line.strip())

            print(f"    Selections: {len(selections)}, Odds: {len(odds_list)}")

            # Pair selections with odds in order
            for sel, odds in zip(selections, odds_list):
                results["method_of_victory"].append({
                    "selection": sel,
                    "odds": odds,
                })

        elif section_key == "rounds":
            # Round betting — try alternating first, then split approach
            i = 0
            while i < len(section_lines) - 1:
                sel = section_lines[i].strip()
                odds = section_lines[i + 1].strip()
                sel_lower = sel.lower()

                if sel_lower in skip_lines or is_odds(sel):
                    i += 1
                    continue

                if is_odds(odds):
                    results["rounds"].append({
                        "selection": sel,
                        "odds": odds,
                    })
                    i += 2
                else:
                    i += 1

    return results, fight_name


def scrape_fight(page, event_id, index):
    fight_url = f"https://www.betmgm.co.uk/sports/mma/ufc#event/{event_id}"

    print(f"\n{'='*50}")
    print(f"[{index}] Event ID: {event_id}")
    print(f"URL: {fight_url}")
    print(f"{'='*50}")

    try:
        page.goto(fight_url, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"  Page load failed: {e}")
        return None

    print("  Waiting for page...")
    time.sleep(8)
    accept_cookies(page)
    time.sleep(2)

    for _ in range(5):
        page.mouse.wheel(0, 1200)
        time.sleep(0.8)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)

    safe_label = f"betmgm_{index}_{event_id}"
    save_debug(page, safe_label)

    markets, fight_name = parse_page_text(page)

    if not fight_name:
        fight_name = f"BetMGM Event {event_id}"

    fight_betting = markets.get("fight_betting", [])
    method = markets.get("method_of_victory", [])
    rounds = markets.get("rounds", [])
    go_distance = markets.get("go_the_distance", [])

    has_props = bool(fight_betting or method or rounds or go_distance)

    print(f"\n  -- {fight_name} --")
    print(f"  Fight Betting:     {len(fight_betting)}")
    print(f"  Method of Victory: {len(method)}")
    print(f"  Rounds:            {len(rounds)}")
    print(f"  Go The Distance:   {len(go_distance)}")
    print(f"  Has props:         {has_props}")

    return {
        "fight": fight_name,
        "url": fight_url,
        "event_id": event_id,
        "has_props": has_props,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markets": {
            "fight_betting": fight_betting,
            "method_of_victory": method,
            "rounds": rounds,
            "go_the_distance": go_distance,
        },
    }


def upsert_fight(output, fight_data):
    existing = output.get("fights", [])
    event_id = fight_data.get("event_id")
    updated = False
    for i, item in enumerate(existing):
        if item.get("event_id") == event_id:
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

        print(f"\nLoading hub: {HUB_URL}")
        try:
            page.goto(HUB_URL, timeout=60000, wait_until="domcontentloaded")
            print("  Waiting for hub page...")
            time.sleep(10)
            accept_cookies(page)
            time.sleep(2)

            for _ in range(6):
                page.mouse.wheel(0, 1200)
                time.sleep(0.8)

            save_debug(page, "betmgm_hub")
            event_ids = get_fight_event_ids(page)

        except Exception as e:
            print(f"  Hub page failed: {e}")
            event_ids = []

        if not event_ids:
            print("  No event IDs found.")
            save_output(output)
            if not is_github_actions():
                input("\nDone. Press Enter to close browser...")
            browser.close()
            return

        print(f"\nFound {len(event_ids)} fights to scrape")

        for index, event_id in enumerate(event_ids, start=1):
            print(f"\nProgress: {index}/{len(event_ids)}")
            try:
                fight_data = scrape_fight(page, event_id, index)
                if fight_data:
                    upsert_fight(output, fight_data)
                    save_output(output)
            except Exception as e:
                print(f"ERROR: event {event_id}: {e}")
                import traceback
                traceback.print_exc()
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()