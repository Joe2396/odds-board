#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "paddypower_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "paddypower_worldcup_props"

LIST_URL = "https://www.paddypower.com/fifa-world-cup"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|Evens)$", re.I)

TARGET_MARKETS = [
    "Match Odds",
    "Over/Under Goals Markets",
    "1st Half Over/Under Goals",
    "Correct Score",
    "Player to Score",
    "Both Teams to Score Markets",
    "Result & Both to Score",
    "Handicap Betting",
    "Half Time/Full Time",
    "Double Chance",
    "Team To Score the First Goal",
]


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def normalize(s):
    s = clean(s).lower()
    s = s.replace("&", "and")
    s = s.replace("?", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def slugify(s):
    return normalize(s).replace("_", "-")


def selection_obj(selection, odds, extra=None):
    obj = {
        "selection": clean(selection),
        "normalized_selection": normalize(selection),
        "odds": clean(odds).upper(),
    }
    if extra:
        obj.update(extra)
    return obj


def market_obj(name, selections):
    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(selections),
        "selections": selections,
    }


def find_line(lines, title):
    wanted = clean(title).lower()
    for i, line in enumerate(lines):
        if clean(line).lower() == wanted:
            return i
    return -1


def next_market_index(lines, start):
    titles = {m.lower() for m in TARGET_MARKETS}
    for i in range(start + 1, len(lines)):
        if clean(lines[i]).lower() in titles:
            return i
    return len(lines)


def get_block(lines, title):
    start = find_line(lines, title)
    if start == -1:
        return []
    end = next_market_index(lines, start)
    return lines[start:end]


def parse_over_under(block, market_name, prefix=""):
    selections = []

    for i, line in enumerate(block):
        label = clean(line)

        if "Over/Under" not in label:
            continue

        if i + 2 >= len(block):
            continue

        over_odds = clean(block[i + 1])
        under_odds = clean(block[i + 2])

        if not is_odds(over_odds) or not is_odds(under_odds):
            continue

        threshold = label.replace("1st Half", "").replace("Over/Under", "").strip()

        if prefix:
            over_name = f"{prefix} Over {threshold}"
            under_name = f"{prefix} Under {threshold}"
        else:
            over_name = f"Over {threshold}"
            under_name = f"Under {threshold}"

        selections.append(selection_obj(over_name, over_odds, {
            "side": "over",
            "line": threshold,
        }))

        selections.append(selection_obj(under_name, under_odds, {
            "side": "under",
            "line": threshold,
        }))

    return market_obj(market_name, selections)


def parse_correct_score(block):
    selections = []

    for i, line in enumerate(block):
        label = clean(line)

        if not re.match(r"^\d+\s*-\s*\d+$", label):
            continue

        if i + 1 >= len(block):
            continue

        odds = clean(block[i + 1])

        if not is_odds(odds):
            continue

        selections.append(selection_obj(label, odds))

    return market_obj("Correct Score", selections)


def parse_player_to_score(block):
    selections = []

    skip = {
        "Player to Score",
        "Super Sub",
        "Own goals don't count here.",
        "First",
        "Anytime",
        "Show all selections",
    }

    for i, line in enumerate(block):
        player = clean(line)

        if not player or player in skip:
            continue

        if is_odds(player):
            continue

        if i + 2 >= len(block):
            continue

        first_odds = clean(block[i + 1])
        anytime_odds = clean(block[i + 2])

        if not is_odds(first_odds) or not is_odds(anytime_odds):
            continue

        selections.append(selection_obj(f"{player} First Goalscorer", first_odds, {
            "player": player,
            "prop_type": "first_goalscorer",
        }))

        selections.append(selection_obj(f"{player} Anytime Goalscorer", anytime_odds, {
            "player": player,
            "prop_type": "anytime_goalscorer",
        }))

    return market_obj("Player to Score", selections)


def parse_btts(block):
    selections = []

    known_rows = [
        "Both teams to Score?",
        "Both Teams to Score in the First Half",
        "Both Teams to Score in Both Halves",
        "Both Teams Score No Draw",
        "Both Teams to Score Two or More Goals",
    ]

    for i, line in enumerate(block):
        label = clean(line)

        if label not in known_rows:
            continue

        if i + 2 >= len(block):
            continue

        yes_odds = clean(block[i + 1])
        no_odds = clean(block[i + 2])

        if not is_odds(yes_odds) or not is_odds(no_odds):
            continue

        base = "Both Teams To Score" if label == "Both teams to Score?" else label

        selections.append(selection_obj(f"{base} - Yes", yes_odds, {
            "side": "yes",
            "base_market": label,
        }))

        selections.append(selection_obj(f"{base} - No", no_odds, {
            "side": "no",
            "base_market": label,
        }))

    return market_obj("Both Teams to Score Markets", selections)


def parse_result_btts(block, home, away):
    selections = []

    for i in range(len(block) - 5):
        if clean(block[i]) != home:
            continue
        if clean(block[i + 1]) != "Draw":
            continue
        if clean(block[i + 2]) != away:
            continue

        home_odds = clean(block[i + 3])
        draw_odds = clean(block[i + 4])
        away_odds = clean(block[i + 5])

        if is_odds(home_odds):
            selections.append(selection_obj(f"{home} & Both Teams To Score", home_odds, {
                "team": home,
                "side": "home",
            }))
        if is_odds(draw_odds):
            selections.append(selection_obj("Draw & Both Teams To Score", draw_odds, {
                "team": "Draw",
                "side": "draw",
            }))
        if is_odds(away_odds):
            selections.append(selection_obj(f"{away} & Both Teams To Score", away_odds, {
                "team": away,
                "side": "away",
            }))

        break

    return market_obj("Result & Both to Score", selections)


def parse_match_odds(block, home, away):
    selections = []

    for i in range(len(block) - 5):
        a = clean(block[i])
        b = clean(block[i + 1])
        c = clean(block[i + 2])

        if a != home:
            continue
        if b not in ["The Draw", "Draw"]:
            continue
        if c != away:
            continue

        home_odds = clean(block[i + 3])
        draw_odds = clean(block[i + 4])
        away_odds = clean(block[i + 5])

        if is_odds(home_odds):
            selections.append(selection_obj(home, home_odds, {"side": "home"}))
        if is_odds(draw_odds):
            selections.append(selection_obj("Draw", draw_odds, {"side": "draw"}))
        if is_odds(away_odds):
            selections.append(selection_obj(away, away_odds, {"side": "away"}))

        break

    return market_obj("Match Odds", selections)


def parse_props_text(text, home, away):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    markets = []

    parsers = [
        ("Match Odds", lambda b: parse_match_odds(b, home, away)),
        ("Over/Under Goals Markets", lambda b: parse_over_under(b, "Over/Under Goals Markets")),
        ("1st Half Over/Under Goals", lambda b: parse_over_under(b, "1st Half Over/Under Goals", prefix="1st Half")),
        ("Correct Score", parse_correct_score),
        ("Player to Score", parse_player_to_score),
        ("Both Teams to Score Markets", parse_btts),
        ("Result & Both to Score", lambda b: parse_result_btts(b, home, away)),
    ]

    for title, parser in parsers:
        block = get_block(lines, title)
        if not block:
            continue

        market = parser(block)
        if market["selections"]:
            markets.append(market)

    return markets


def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


def expand_show_all_selections(page):
    """Click every 'Show all selections' button on the page to reveal hidden players."""
    try:
        buttons = page.get_by_text("Show all selections", exact=True)
        count = buttons.count()
        if count:
            print(f"  Expanding {count} 'Show all selections' button(s)...")
            for i in range(count):
                try:
                    buttons.nth(i).click(timeout=3000)
                    page.wait_for_timeout(800)
                except Exception:
                    pass
    except Exception:
        pass


def collect_match_links(page):
    print(f"Opening list page: {LIST_URL}")
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)
    accept_cookies(page)

    for i in range(35):
        print(f"Scrolling list page {i + 1}/35...")
        page.mouse.wheel(0, 850)
        page.wait_for_timeout(450)

    links = page.evaluate("""
        () => Array.from(document.querySelectorAll('a'))
          .map(a => ({ href: a.href, text: a.innerText }))
          .filter(x => x.href && x.href.includes('/football/fifa-world-cup/'))
    """)

    out = []
    seen = set()

    for item in links:
        href = clean(item.get("href"))
        text = clean(item.get("text"))

        if not href:
            continue

        if "-v-" not in href:
            continue

        if href in seen:
            continue

        seen.add(href)
        out.append({
            "url": href,
            "text": text,
        })

    print(f"Found {len(out)} possible PaddyPower match links")
    return out


def get_match_name_from_page(text):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    for line in lines:
        if " v " in line and len(line) < 80:
            return line

    return ""


def scrape_match(page, url, fallback_text=""):
    print(f"\nOpening match page: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6500)
    accept_cookies(page)

    for tab in ["Popular", "Goals", "Other Markets"]:
        try:
            loc = page.get_by_text(tab, exact=True)
            if loc.count():
                print(f"Clicking tab: {tab}")
                loc.first.click(timeout=3000)
                page.wait_for_timeout(1200)
        except Exception:
            pass

    try:
        loc = page.get_by_text("Popular", exact=True)
        if loc.count():
            loc.first.click(timeout=3000)
            page.wait_for_timeout(1200)
    except Exception:
        pass

    for market in TARGET_MARKETS:
        try:
            loc = page.get_by_text(market, exact=True)
            count = loc.count()
            if count:
                print(f"{market}: found {count}")
            for i in range(min(count, 3)):
                try:
                    loc.nth(i).click(timeout=2000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass
        except Exception:
            pass

    # ── NEW: expand hidden goalscorer selections ──────────────────────────────
    expand_show_all_selections(page)
    # ─────────────────────────────────────────────────────────────────────────

    text = page.locator("body").inner_text(timeout=30000)

    match_name = get_match_name_from_page(text)
    if not match_name:
        match_name = fallback_text

    if " v " in match_name:
        home, away = [clean(x) for x in match_name.split(" v ", 1)]
    else:
        home, away = "", ""

    markets = parse_props_text(text, home, away) if home and away else []

    debug_file = DEBUG_DIR / f"{slugify(match_name or url[-30:])}.txt"
    debug_file.write_text(text, encoding="utf-8")

    return {
        "match": match_name,
        "home_team": home,
        "away_team": away,
        "source_url": url,
        "market_count": len(markets),
        "markets": markets,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    matches = []
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        links = collect_match_links(page)

        MAX_MATCHES = 15
        links = links[:MAX_MATCHES]

        for index, item in enumerate(links, start=1):
            url = item["url"]
            fallback_text = item.get("text") or ""

            print(f"\n==============================")
            print(f"PaddyPower props {index}/{len(links)}")
            print(f"==============================")

            try:
                match = scrape_match(page, url, fallback_text=fallback_text)
                matches.append(match)
                print(f"Saved match: {match['match']} | markets: {match['market_count']}")
            except Exception as e:
                print(f"ERROR scraping {url}: {e}")
                errors.append({
                    "url": url,
                    "error": str(e),
                })
                continue

        browser.close()

    good_matches = [m for m in matches if m.get("market_count", 0) > 0]

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "PaddyPower",
        "market_type": "props",
        "source_url": LIST_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(matches),
        "matches_with_markets": len(good_matches),
        "error_count": len(errors),
        "errors": errors,
        "matches": matches,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n==============================")
    print("PaddyPower World Cup props complete")
    print("==============================")
    print(f"Match links scraped: {len(matches)}")
    print(f"Matches with markets: {len(good_matches)}")
    print(f"Errors: {len(errors)}")
    print(f"Wrote: {OUT_PATH}")


if __name__ == "__main__":
    main()