from playwright.sync_api import sync_playwright
from pathlib import Path
from datetime import datetime, timezone
import json
import re
import time

ROOT = Path(__file__).resolve().parents[2]

MATCHES_PATH = ROOT / "darts" / "data" / "paddypower_darts_matches.json"
OUT_PATH = ROOT / "darts" / "data" / "paddypower_darts_odds.json"
DEBUG_DIR = ROOT / "darts" / "debug" / "paddypower_darts_odds"

DARTS_URL = "https://www.paddypower.com/darts"

DEBUG_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

BASE_TARGET_MARKETS = [
    "Match Odds",
    "Leg Handicap",
    "Total Legs",
    "Total 180's",
]


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


def is_odds(value):
    value = clean_text(value).upper()
    return (
        value == "EVS"
        or bool(re.match(r"^\d+/\d+$", value))
        or bool(re.match(r"^\d+\.\d+$", value))
    )


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


def match_slug(p1, p2):
    return slugify(f"{p1} vs {p2}")


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

    return matches


def accept_cookies(page):
    for label in ["Accept All Cookies", "Accept All", "I Accept", "Accept", "Agree", "OK"]:
        try:
            page.get_by_text(label, exact=False).click(timeout=2000)
            time.sleep(1)
            return
        except Exception:
            pass


def open_darts_home(page):
    page.goto(DARTS_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)
    accept_cookies(page)

    for _ in range(7):
        page.mouse.wheel(0, 900)
        time.sleep(0.5)


def find_match_url(page, match):
    p1 = clean_text(match.get("player_1"))
    p2 = clean_text(match.get("player_2"))

    p1n = norm(p1)
    p2n = norm(p2)

    anchors = page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || ''
        }))
        """
    )

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
        return sorted(hits, key=len, reverse=True)[0]

    return ""


def open_match_page(page, match):
    open_darts_home(page)

    url = find_match_url(page, match)

    if url:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)
        accept_cookies(page)
        return page.url

    return ""


def click_tab(page, tab_name):
    try:
        loc = page.get_by_text(tab_name, exact=False).first
        loc.scroll_into_view_if_needed(timeout=3000)
        time.sleep(0.5)
        loc.click(timeout=3000)
        time.sleep(2)
        return True
    except Exception:
        return False


def click_market_caret(page, market_name):
    """
    PaddyPower accordions often do not expand by clicking the text.
    This clicks slightly LEFT of the market title where the caret/arrow lives.
    """
    try:
        loc = page.get_by_text(market_name, exact=False).first
        loc.scroll_into_view_if_needed(timeout=5000)
        time.sleep(0.6)

        box = loc.bounding_box()

        if not box:
            return False

        # Click the little caret/arrow to the left of the market title.
        x = max(5, box["x"] - 16)
        y = box["y"] + box["height"] / 2

        page.mouse.click(x, y)
        time.sleep(1.5)
        return True

    except Exception:
        pass

    return False


def click_market_row(page, market_name):
    """
    Fallback: click the market text/row itself.
    """
    try:
        loc = page.get_by_text(market_name, exact=False).first
        loc.scroll_into_view_if_needed(timeout=5000)
        time.sleep(0.6)
        loc.click(timeout=4000)
        time.sleep(1.5)
        return True
    except Exception:
        pass

    try:
        clicked = page.evaluate(
            """
            (marketName) => {
              const wanted = marketName.toLowerCase();
              const els = Array.from(document.querySelectorAll('button, div, span, p'));
              const el = els.find(e => {
                const txt = (e.innerText || e.textContent || '').trim().toLowerCase();
                return txt === wanted || txt.includes(wanted);
              });
              if (!el) return false;
              el.scrollIntoView({block: 'center'});
              el.click();
              return true;
            }
            """,
            market_name,
        )

        if clicked:
            time.sleep(1.5)
            return True

    except Exception:
        pass

    return False


def force_open_market(page, market_name):
    """
    Open market by trying:
    1. caret click
    2. row click
    3. caret click again
    """
    opened = False

    if click_market_caret(page, market_name):
        opened = True

    time.sleep(0.5)

    if click_market_row(page, market_name):
        opened = True

    time.sleep(0.5)

    if click_market_caret(page, market_name):
        opened = True

    time.sleep(1)

    return opened


def capture_targeted_markets(page, match):
    p1 = clean_text(match.get("player_1"))
    p2 = clean_text(match.get("player_2"))

    captured = {}

    player_markets = [
        f"{p1} Total 180's",
        f"{p2} Total 180's",
        f"{p1} Total 180s",
        f"{p2} Total 180s",
    ]

    target_markets = BASE_TARGET_MARKETS + player_markets

    # Capture Popular for Match Odds
    click_tab(page, "Popular")
    time.sleep(1)
    captured["Popular"] = page.locator("body").inner_text(timeout=30000)

    # Go to All Markets first
    click_tab(page, "All Markets")
    time.sleep(2)

    captured["All Markets Before"] = page.locator("body").inner_text(timeout=30000)

    for market in target_markets:
        print(f"    Opening market: {market}")

        # Some markets only exist under specific tabs.
        if market == "Leg Handicap":
            click_tab(page, "Handicap")
            time.sleep(1)

        elif "180" in market:
            click_tab(page, "180")
            time.sleep(1)

        else:
            click_tab(page, "All Markets")
            time.sleep(1)

        page.mouse.wheel(0, -2500)
        time.sleep(0.5)

        force_open_market(page, market)

        # Scroll a touch after opening so odds below are visible/loaded.
        page.mouse.wheel(0, 350)
        time.sleep(0.8)

        try:
            captured[market] = page.locator("body").inner_text(timeout=30000)
        except Exception:
            captured[market] = ""

    return "\n\n--- CAPTURE BREAK ---\n\n".join(
        f"### {k}\n{v}" for k, v in captured.items()
    )


def parse_text(text, match):
    lines = [clean_text(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    junk = [
        "login",
        "sign up",
        "search",
        "sports",
        "help & contact",
        "promotions",
        "responsible gambling",
        "shop exclusives",
        "paddy's rewards",
        "free",
        "cash out",
        "browse all",
    ]

    cleaned = []

    for line in lines:
        low = line.lower()

        if any(j in low for j in junk):
            continue

        if line in ["1", "2"]:
            continue

        if "£" in line:
            continue

        cleaned.append(line)

    markets = []

    market_names = [
        "Match Odds",
        "Leg Handicap",
        "Total Legs",
        "Total 180's",
        f"{match.get('player_1')} Total 180's",
        f"{match.get('player_2')} Total 180's",
        f"{match.get('player_1')} Total 180s",
        f"{match.get('player_2')} Total 180s",
    ]

    for market in market_names:
        parsed = parse_market(cleaned, match, market)

        if parsed and parsed.get("outcomes"):
            markets.append(parsed)

    return dedupe_markets(markets)


def base_market(match, market, outcomes):
    return {
        "market": market,
        "bookmaker": "PaddyPower",
        "match_slug": match.get("match_slug"),
        "competition": match.get("competition"),
        "day": match.get("day", ""),
        "time": match.get("time", ""),
        "player_1": match.get("player_1"),
        "player_2": match.get("player_2"),
        "outcomes": outcomes,
    }


def parse_market(lines, match, market_name):
    if market_name == "Match Odds":
        return parse_match_odds(lines, match)

    starts = []

    for i, line in enumerate(lines):
        if market_name.lower() == line.lower() or market_name.lower() in line.lower():
            starts.append(i)

    if not starts:
        return None

    best = []

    for start in starts:
        block = lines[start + 1:start + 80]
        outcomes = parse_outcomes(block)

        if len(outcomes) > len(best):
            best = outcomes

    if not best:
        return None

    return base_market(match, market_name, best)


def parse_match_odds(lines, match):
    p1 = clean_text(match.get("player_1"))
    p2 = clean_text(match.get("player_2"))

    p1n = norm(p1)
    p2n = norm(p2)

    for i, line in enumerate(lines):
        if norm(line) != p1n:
            continue

        window = lines[i:i + 16]

        if not any(norm(x) == p2n for x in window):
            continue

        odds = [x for x in window if is_odds(x)]

        if len(odds) >= 2:
            return base_market(match, "Match Odds", [
                {
                    "name": p1,
                    "price": odds[0],
                    "decimal": fractional_to_decimal(odds[0]),
                },
                {
                    "name": p2,
                    "price": odds[1],
                    "decimal": fractional_to_decimal(odds[1]),
                },
            ])

    return None


def parse_outcomes(block):
    outcomes = []

    stop_headers = [
        "Match Odds",
        "Leg Handicap",
        "Most 180's",
        "Total 180's",
        "Total 180s",
        "Total Legs",
        "Correct Score",
        "Popular",
        "All Markets",
        "Win",
        "Handicap",
        "180",
    ]

    i = 0

    while i < len(block):
        line = clean_text(block[i])

        if any(line.lower() == h.lower() for h in stop_headers):
            break

        if i + 1 < len(block) and not is_odds(line) and is_odds(block[i + 1]):
            outcomes.append({
                "name": line,
                "price": block[i + 1],
                "decimal": fractional_to_decimal(block[i + 1]),
            })
            i += 2
            continue

        if (
            i + 2 < len(block)
            and not is_odds(block[i])
            and not is_odds(block[i + 1])
            and is_odds(block[i + 2])
        ):
            outcomes.append({
                "name": clean_text(block[i] + " " + block[i + 1]),
                "price": block[i + 2],
                "decimal": fractional_to_decimal(block[i + 2]),
            })
            i += 3
            continue

        i += 1

    deduped = []
    seen = set()

    for o in outcomes:
        key = (o["name"].lower(), o["price"])

        if key in seen:
            continue

        seen.add(key)
        deduped.append(o)

    return deduped


def dedupe_markets(markets):
    out = []
    seen = set()

    for m in markets:
        key = (m.get("market"), json.dumps(m.get("outcomes", []), sort_keys=True))

        if key in seen:
            continue

        seen.add(key)
        out.append(m)

    return out


def scrape_one_match(page, match):
    p1 = clean_text(match.get("player_1"))
    p2 = clean_text(match.get("player_2"))

    print(f"Scraping {p1} vs {p2}")

    match_url = open_match_page(page, match)

    if not match_url:
        print("  Could not open match page")
        return {
            "match_slug": match.get("match_slug"),
            "player_1": p1,
            "player_2": p2,
            "bookmaker": "PaddyPower",
            "markets": [],
            "status": "match_not_opened",
        }

    text = capture_targeted_markets(page, match)

    debug_file = DEBUG_DIR / f"{match.get('match_slug')}.txt"
    debug_file.write_text(text, encoding="utf-8")

    markets = parse_text(text, match)

    print(f"  URL: {match_url}")
    print(f"  Markets found: {len(markets)}")

    for m in markets:
        print(f"    - {m.get('market')}: {len(m.get('outcomes', []))} outcomes")

    return {
        "match_slug": match.get("match_slug"),
        "competition": match.get("competition"),
        "day": match.get("day", ""),
        "time": match.get("time", ""),
        "player_1": p1,
        "player_2": p2,
        "bookmaker": "PaddyPower",
        "source_url": DARTS_URL,
        "match_url": match_url,
        "markets": markets,
        "status": "ok" if markets else "no_markets_found",
    }


def main():
    print("Fetching targeted PaddyPower darts odds/props...")

    matches = load_matches()

    if not matches:
        print("No matches found. Run fetch_paddypower_darts_matches.py first.")
        return

    print(f"Loaded {len(matches)} matches")

    results = []

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

        for idx, match in enumerate(matches, start=1):
            print(f"[{idx}/{len(matches)}]")

            try:
                results.append(scrape_one_match(page, match))
            except Exception as e:
                print(f"  Failed: {e}")
                results.append({
                    "match_slug": match.get("match_slug"),
                    "player_1": match.get("player_1"),
                    "player_2": match.get("player_2"),
                    "bookmaker": "PaddyPower",
                    "markets": [],
                    "status": "error",
                    "error": str(e),
                })

        browser.close()

    total_markets = sum(len(r.get("markets", [])) for r in results)
    ok_matches = sum(1 for r in results if r.get("status") == "ok")

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "paddypower",
        "sport": "darts",
        "source_url": DARTS_URL,
        "total_matches": len(results),
        "ok_matches": ok_matches,
        "total_markets": total_markets,
        "matches": results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved odds/props to {OUT_PATH}")
    print(f"OK matches: {ok_matches}/{len(results)}")
    print(f"Total markets: {total_markets}")


if __name__ == "__main__":
    main()