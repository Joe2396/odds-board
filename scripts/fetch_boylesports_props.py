from playwright.sync_api import sync_playwright
import time
import json
import re
import os
from pathlib import Path
from datetime import datetime, timezone

print("RUNNING BOYLESPORTS ALL-FIGHTS PROPS SCRIPT")

ROOT = Path(__file__).resolve().parents[1]
URLS_PATH = ROOT / "ufc" / "data" / "boylesports_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "boylesports_props.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def is_odds(x):
    x = str(x).strip().upper()
    return (
        x == "EVS"
        or bool(re.match(r"^\d+/\d+$", x))
        or bool(re.match(r"^\d+\.\d+$", x))
        or bool(re.match(r"^\d+$", x))
    )


def empty_output():
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "boylesports",
        "bookmaker": "BoyleSports",
        "markets_scraped": [
            "fight_betting",
            "method_of_victory",
            "rounds",
            "go_the_distance",
        ],
        "fights": [],
    }


def save_output(output):
    output["updated_at"] = datetime.now(timezone.utc).isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved progress to {OUT_PATH}")


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        html_path = DEBUG_DIR / f"{label}.html"
        png_path = DEBUG_DIR / f"{label}.png"

        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(png_path), full_page=True)

        print(f"Saved debug HTML: {html_path}")
        print(f"Saved debug screenshot: {png_path}")
    except Exception as e:
        print(f"Could not save debug files: {e}")


def close_cookie_popup(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
        "button:has-text('Got it')",
    ]

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass

    print("No cookie popup found")


def wait_for_boylesports_page(page):
    print("Waiting for BoyleSports page to load...")
    time.sleep(8)

    try:
        page.wait_for_selector("body", timeout=15000)
    except Exception:
        pass


def normalize_text(text):
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_fighters_from_fight_name(fight_name):
    fight_name = str(fight_name or "").strip()

    if " vs " in fight_name.lower():
        fighters = re.split(r"\s+vs\s+", fight_name, flags=re.I)
    elif " v " in fight_name.lower():
        fighters = re.split(r"\s+v\s+", fight_name, flags=re.I)
    else:
        fighters = []

    return [f.strip() for f in fighters if f.strip()]


# ─────────────────────────────────────────────
# MONEYLINE: Direct DOM row extraction
# ─────────────────────────────────────────────

def extract_moneyline_dom(page, fight_name):
    """
    Primary method: walk every visible DOM element.
    Find rows where a fighter name appears on the LEFT
    and a fractional/decimal odd appears on the RIGHT,
    both sharing roughly the same vertical position.

    This matches the BoyleSports layout seen in the screenshot:
      [Alice Ardelean]          [4/9]
      [Polyana Viana]           [13/8]

    No tab clicking needed — "To Win Fight" is open by default.
    """
    fighters = get_fighters_from_fight_name(fight_name)

    if len(fighters) < 2:
        print(f"  Could not parse fighters from: {fight_name}")
        return []

    print(f"  Looking for fighters: {fighters}")

    try:
        elements = page.evaluate("""
            () => {
                const results = [];

                function isVisible(el) {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                        rect.width > 0 &&
                        rect.height > 0 &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none' &&
                        style.opacity !== '0'
                    );
                }

                function getLeafText(el) {
                    // Get text only from this element, not children
                    let text = '';
                    for (const node of el.childNodes) {
                        if (node.nodeType === Node.TEXT_NODE) {
                            text += node.textContent;
                        }
                    }
                    return text.trim() || el.innerText?.trim() || '';
                }

                document.querySelectorAll('*').forEach(el => {
                    if (!isVisible(el)) return;

                    const text = (el.innerText || el.textContent || '').trim();
                    if (!text || text.length > 200) return;

                    const rect = el.getBoundingClientRect();

                    // Exclude nav/header/sidebar elements
                    if (rect.y < 200) return;
                    if (rect.x < 150) return;    // sidebar
                    if (rect.x > 960) return;    // betslip panel

                    results.push({
                        tag: el.tagName,
                        text: text,
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                        cx: Math.round(rect.x + rect.width / 2),
                        cy: Math.round(rect.y + rect.height / 2),
                    });
                });

                return results;
            }
        """)
    except Exception as e:
        print(f"  DOM evaluation failed: {e}")
        return []

    if not elements:
        print("  No DOM elements returned")
        return []

    print(f"  DOM elements found: {len(elements)}")

    # Separate into fighter name candidates and odds candidates
    fighter_nodes = []
    odds_nodes = []

    for el in elements:
        text = str(el.get("text") or "").strip()
        norm = normalize_text(text)

        if is_odds(text):
            odds_nodes.append(el)
            continue

        for fighter in fighters:
            fighter_norm = normalize_text(fighter)
            # Match if fighter name is contained in or matches the element text
            if (
                norm == fighter_norm
                or fighter_norm in norm
                and len(norm) < len(fighter_norm) + 20
            ):
                fighter_nodes.append({**el, "fighter": fighter})
                break

    print(f"  Fighter nodes found: {len(fighter_nodes)}")
    print(f"  Odds nodes found: {len(odds_nodes)}")

    # For each fighter, find the odds element on the SAME ROW (similar Y)
    # and to the RIGHT of the fighter name
    results = []
    used_odds = set()

    for fighter in fighters:
        candidates = [n for n in fighter_nodes if n.get("fighter") == fighter]

        if not candidates:
            print(f"  No node found for fighter: {fighter}")
            continue

        # Pick the highest fighter node (closest to top of "To Win Fight" section)
        fighter_node = sorted(candidates, key=lambda n: n.get("y", 999999))[0]
        fy = fighter_node.get("cy", 0)
        fx_right = fighter_node.get("x", 0) + fighter_node.get("w", 0)

        print(f"  Fighter '{fighter}' at y={fy}, right edge x={fx_right}")

        # Find odds on same row: within 60px vertically, to the right of fighter
        same_row_odds = []

        for odds_node in odds_nodes:
            oy = odds_node.get("cy", 0)
            ox = odds_node.get("x", 0)
            node_id = (odds_node.get("x"), odds_node.get("y"), odds_node.get("text"))

            if node_id in used_odds:
                continue

            # Must be on roughly the same row
            if abs(oy - fy) > 60:
                continue

            # Must be to the right of fighter name
            if ox < fx_right - 20:
                continue

            same_row_odds.append(odds_node)

        if not same_row_odds:
            print(f"  No same-row odds found for: {fighter}")
            continue

        # Pick the leftmost (closest to fighter name) odds on this row
        best_odds_node = sorted(same_row_odds, key=lambda n: n.get("x", 0))[0]
        odds_text = best_odds_node.get("text", "").strip()

        node_id = (best_odds_node.get("x"), best_odds_node.get("y"), odds_text)
        used_odds.add(node_id)

        print(f"  Matched: {fighter} → {odds_text}")
        results.append({"selection": fighter, "odds": odds_text})

    return results


def extract_moneyline_fallback_text(page, fight_name):
    """
    Fallback: grab all page text, strip to the 'To Win Fight' section,
    then do conservative line-pair matching.
    Only used if DOM method fails.
    """
    fighters = get_fighters_from_fight_name(fight_name)

    if len(fighters) < 2:
        return []

    try:
        body_text = page.locator("body").inner_text(timeout=10000)
    except Exception:
        return []

    # Find the To Win Fight section
    lower = body_text.lower()
    start = lower.find("to win fight")

    if start == -1:
        # Try other headings
        for heading in ["match betting", "fight betting", "fight result", "winner"]:
            idx = lower.find(heading)
            if idx != -1:
                start = idx
                break

    if start == -1:
        print("  Fallback: Could not locate moneyline section in page text")
        return []

    # Take a short snippet after the heading (300 chars is enough for 2 fighters)
    snippet = body_text[start:start + 600]
    lines = [l.strip() for l in snippet.splitlines() if l.strip()]

    results = []

    for fighter in fighters:
        fighter_norm = normalize_text(fighter)

        for i, line in enumerate(lines):
            if fighter_norm in normalize_text(line):
                # Next odds line after fighter name
                for j in range(i + 1, min(i + 5, len(lines))):
                    candidate = lines[j].strip()
                    if is_odds(candidate):
                        results.append({"selection": fighter, "odds": candidate})
                        break
                break

    seen = set()
    unique = []
    for r in results:
        if r["selection"] not in seen:
            seen.add(r["selection"])
            unique.append(r)

    return unique


def scrape_moneyline(page, fight_name, index):
    """
    Main moneyline extraction.
    Tries DOM method first, falls back to text parsing.
    No tab clicking needed — To Win Fight is open by default on BoyleSports fight pages.
    """
    print(f"\n  --- Moneyline extraction for: {fight_name} ---")

    # Scroll to top so the To Win Fight section is in the viewport
    try:
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
    except Exception:
        pass

    # Primary: DOM position method
    result = extract_moneyline_dom(page, fight_name)

    if len(result) == 2 and all(is_odds(r.get("odds")) for r in result):
        print(f"  ✅ DOM method succeeded: {result}")
        return result

    print(f"  ⚠️ DOM method returned {len(result)} results, trying fallback...")

    # Fallback: text parsing
    result = extract_moneyline_fallback_text(page, fight_name)

    if len(result) == 2 and all(is_odds(r.get("odds")) for r in result):
        print(f"  ✅ Fallback method succeeded: {result}")
        return result

    print(f"  ❌ Both methods failed. Got: {result}")
    return result


# ─────────────────────────────────────────────
# PROPS: Tab-based scraping (unchanged logic, cleaned up)
# ─────────────────────────────────────────────

def click_tab(page, tab_name):
    print(f"  Clicking tab: {tab_name}")

    selectors = [
        f"button:has-text('{tab_name}')",
        f"a:has-text('{tab_name}')",
        f"div[role='tab']:has-text('{tab_name}')",
        f"text={tab_name}",
    ]

    for selector in selectors:
        try:
            tab = page.locator(selector).first
            tab.scroll_into_view_if_needed(timeout=5000)
            time.sleep(0.5)
            tab.click(force=True, timeout=5000)
            print(f"  Clicked: {tab_name}")
            time.sleep(3)
            page.mouse.wheel(0, 1200)
            time.sleep(2)
            return True
        except Exception:
            pass

    print(f"  Could not click tab: {tab_name}")
    return False


def get_body_text(page):
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


def parse_pairs_from_text(text):
    """
    Generic: walk lines, yield (selection, odds) pairs where
    selection is NOT odds and the next line IS odds.
    """
    junk = {
        "", "Popular", "Cash Out", "All Markets",
        "Method of Victory", "Method Of Victory", "Winning Method",
        "Rounds", "Total Rounds", "Go The Distance?",
        "Fight Goes The Distance", "Fight To Go The Distance",
        "To Go Distance", "Go The Distance", "Round Betting",
        "Show More", "Show Less", "Bet Builder", "To Win Fight",
        "Fight Betting", "Match Betting", "Fight Result",
        "Show UFC Stats", "Hide UFC Stats", "Bet Builder Boost",
        "Full T&Cs", "Close", "All competitions",
    }

    junk_contains = [
        "create your bet builder", "min odds for boost", "apply on betslip",
        "enjoy your boosted", "gaming quick links", "home / ufc",
        "please add one or more", "ufc stats", "promotions",
        "casino", "sports a-z", "safer gambling",
    ]

    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line in junk:
            continue
        low = line.lower()
        if any(j in low for j in junk_contains):
            continue
        if re.match(r"^\d+%$", line):
            continue
        if re.match(r"^\d+\s*-\s*\d+\s*-\s*\d+$", line):
            continue
        lines.append(line)

    results = []
    for i in range(len(lines) - 1):
        selection = lines[i]
        odds = lines[i + 1]
        if not is_odds(selection) and is_odds(odds):
            results.append({"selection": selection, "odds": odds})

    return results


def parse_method_of_victory(text):
    pairs = parse_pairs_from_text(text)
    results = []

    for item in pairs:
        sel = item["selection"].lower()
        if (
            " by " in sel
            or "draw" in sel
            or "ko/tko" in sel
            or "submission" in sel
            or "decision" in sel
            or "disqualification" in sel
        ):
            results.append(item)

    return results


def parse_go_distance(text):
    pairs = parse_pairs_from_text(text)
    results = []

    for item in pairs:
        sel = item["selection"].strip().lower()
        if sel in ["yes", "no"]:
            results.append(item)

    return results


def parse_rounds(text):
    pairs = parse_pairs_from_text(text)
    results = []

    for item in pairs:
        sel = item["selection"].strip().lower()
        # Round selections look like "Round 1", "Over 1.5", "Under 2.5", etc.
        if (
            re.match(r"^round\s+\d", sel)
            or re.match(r"^over\s+[\d\.]+", sel)
            or re.match(r"^under\s+[\d\.]+", sel)
            or re.match(r"^\d+\s*-\s*\d+", sel)
            or "round" in sel
        ):
            results.append(item)

    return results


def scrape_prop_tab(page, tab_name, fight_name, index, market_key):
    clicked = click_tab(page, tab_name)

    if not clicked:
        return []

    text = get_body_text(page)

    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", fight_name).strip("_").lower()
    save_debug(page, f"boylesports_{index}_{safe_label}_{market_key}")

    if market_key == "method_of_victory":
        return parse_method_of_victory(text)
    elif market_key == "go_the_distance":
        return parse_go_distance(text)
    elif market_key == "rounds":
        parsed = parse_rounds(text)
        return parsed
    else:
        return parse_pairs_from_text(text)


# ─────────────────────────────────────────────
# Main fight scraper
# ─────────────────────────────────────────────

def scrape_fight(page, fight, index):
    fight_name = fight["fight"]
    fight_url = fight["url"]

    print(f"\n{'='*50}")
    print(f"Scraping: {fight_name}")
    print(f"URL: {fight_url}")
    print(f"{'='*50}")

    page.goto(fight_url, timeout=60000, wait_until="domcontentloaded")
    wait_for_boylesports_page(page)
    close_cookie_popup(page)
    time.sleep(2)

    # Save initial debug screenshot
    safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", fight_name).strip("_").lower()
    save_debug(page, f"boylesports_{index}_{safe_label}_initial")

    # ── Moneyline (To Win Fight is open by default — no tab click needed) ──
    fight_betting = scrape_moneyline(page, fight_name, index)

    print(f"\n  Fight Betting result: {fight_betting}")

    # ── Props: scroll back up before each tab click ──
    try:
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
    except Exception:
        pass

    method = scrape_prop_tab(page, "Method Of Victory", fight_name, index, "method_of_victory")

    try:
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
    except Exception:
        pass

    rounds = scrape_prop_tab(page, "Rounds", fight_name, index, "rounds")

    # Go The Distance is usually inside the Rounds tab on BoyleSports
    go_distance = parse_go_distance(get_body_text(page)) if rounds else []

    if not go_distance:
        # Try a dedicated tab if it exists
        try:
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)
        except Exception:
            pass
        go_distance = scrape_prop_tab(page, "Go The Distance", fight_name, index, "go_the_distance")

    has_props = bool(fight_betting or method or rounds or go_distance)

    print(f"\n  ── Summary for {fight_name} ──")
    print(f"  Fight Betting:      {len(fight_betting)}")
    print(f"  Method Of Victory:  {len(method)}")
    print(f"  Rounds:             {len(rounds)}")
    print(f"  Go The Distance:    {len(go_distance)}")
    print(f"  Has props:          {has_props}")

    if not has_props:
        body_text = get_body_text(page)
        print("  No props parsed. Body text sample:")
        print(body_text[:1500])

    return {
        "fight": fight_name,
        "url": fight_url,
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
    if not URLS_PATH.exists():
        print(f"Missing fight URL file: {URLS_PATH}")
        output = empty_output()
        save_output(output)
        return

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        url_data = json.load(f)

    fights = url_data.get("fights", [])
    print(f"Fights to scrape: {len(fights)}")

    if not fights:
        print("No fights in boylesports_fight_urls.json")
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

        for index, fight in enumerate(fights, start=1):
            print(f"\nProgress: {index}/{len(fights)}")

            try:
                fight_data = scrape_fight(page, fight, index)
                upsert_fight(output, fight_data)
                save_output(output)
            except Exception as e:
                print(f"ERROR scraping {fight.get('fight')}: {e}")
                import traceback
                traceback.print_exc()
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()