#!/usr/bin/env python3
import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


print("FETCHING BETMGM UFC PROPS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "betmgm_props.json"
DEBUG_PATH = ROOT / "ufc" / "data" / "betmgm_props_debug.txt"

BETMGM_URLS = [
    "https://www.betmgm.co.uk/sports/mma/ufc",
    "https://www.betmgm.co.uk/sports/mma",
]

ODDS_RE = re.compile(r"^(?:EVS|\d+/\d+)$", re.I)

DATE_RE = re.compile(r"^(?:\d{1,2})$")
MONTH_RE = re.compile(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$", re.I)
CLOCK_RE = re.compile(r"^\d{1,2}:\d{2}$")

MARKET_WORDS = {
    "Yes",
    "No",
    "Over",
    "Under",
}

STOP_WORDS = {
    "SPORTS",
    "CASINO",
    "LIVE",
    "LOG",
    "IN",
    "SIGN",
    "UP",
    "FEATURED",
    "ALL",
    "IN-PLAY",
    "GOLDEN",
    "GOALS",
    "SEARCH",
    "MY",
    "BETS",
    "UFC/MMA",
    "UFC",
    "MVP",
    "MMA",
    "Outrights",
    "Bout",
    "Odds",
    "Distance",
    "Total",
    "Rounds",
    "Method",
    "Victory",
    "MORE",
    "BETS",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def wait(page):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    time.sleep(5)


def close_popups(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept')",
        "button:has-text('Accept All')",
        "button:has-text('I Accept')",
        "button:has-text('Agree')",
        "button:has-text('Continue')",
    ]

    for sel in selectors:
        try:
            page.locator(sel).first.click(timeout=2500, force=True)
            print(f"Clicked popup: {sel}")
            time.sleep(1)
        except Exception:
            pass


def scroll(page):
    for _ in range(8):
        try:
            page.mouse.wheel(0, 1100)
            time.sleep(0.7)
        except Exception:
            pass


def get_body_text(page):
    try:
        return clean(page.locator("body").inner_text(timeout=8000))
    except Exception:
        return ""


def save_debug(label, page, body):
    try:
        title = page.title()
    except Exception:
        title = ""

    block = []
    block.append("=" * 100)
    block.append(f"TIME: {utc_now()}")
    block.append(f"LABEL: {label}")
    block.append(f"URL: {page.url}")
    block.append(f"TITLE: {title}")
    block.append(f"BODY LENGTH: {len(body)}")
    block.append("-" * 100)
    block.append(body[:16000])
    block.append("\n")

    with open(DEBUG_PATH, "a", encoding="utf-8") as f:
        f.write("\n".join(block))

    print("\n--- DEBUG SAMPLE ---")
    print("\n".join(block)[:2500])
    print("--- END DEBUG SAMPLE ---\n")


def is_name_token(tok):
    if not tok:
        return False

    if tok in STOP_WORDS:
        return False

    if ODDS_RE.match(tok):
        return False

    if tok in MARKET_WORDS:
        return False

    if DATE_RE.match(tok):
        return False

    if MONTH_RE.match(tok):
        return False

    if CLOCK_RE.match(tok):
        return False

    if re.fullmatch(r"\d+\.\d+", tok):
        return False

    return bool(re.match(r"^[A-ZÁÉÍÓÚÑÄËÏÖÜ][A-Za-zÁÉÍÓÚáéíóúÑñÄËÏÖÜäëïöü.'\-]+$", tok))


def find_event_time(tokens, idx):
    for i in range(idx, max(-1, idx - 30), -1):
        if i + 2 < len(tokens):
            if DATE_RE.match(tokens[i]) and MONTH_RE.match(tokens[i + 1]) and CLOCK_RE.match(tokens[i + 2]):
                return f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}"
        if i + 1 < len(tokens):
            if tokens[i] in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] and CLOCK_RE.match(tokens[i + 1]):
                return f"{tokens[i]} {tokens[i + 1]}"
    return ""


def collect_name_before(tokens, idx, max_words=4):
    words = []
    i = idx - 1

    while i >= 0 and len(words) < max_words:
        if is_name_token(tokens[i]):
            words.insert(0, tokens[i])
            i -= 1
        else:
            break

    return " ".join(words)


def parse_distance_and_totals(tokens):
    """
    Parses visible market blocks like:
    Fighter A 6/5 Fighter B 4/6 1 MORE BETS
    Yes 21/10 No 7/20 Over 2.5 4/5 Under 2.5 23/25

    This creates simple prop entries for:
    - Goes Distance / Distance
    - Total Rounds
    """
    props = []

    for i, tok in enumerate(tokens):
        # Goes distance / distance market
        if tok == "Yes" and i + 3 < len(tokens):
            yes_odd = tokens[i + 1]
            no_word = tokens[i + 2]
            no_odd = tokens[i + 3]

            if ODDS_RE.match(yes_odd) and no_word == "No" and ODDS_RE.match(no_odd):
                props.append({
                    "market": "Goes The Distance",
                    "selection": "Yes",
                    "odds": yes_odd,
                    "event_time": find_event_time(tokens, i),
                    "raw_index": i,
                    "source": "betmgm",
                })
                props.append({
                    "market": "Goes The Distance",
                    "selection": "No",
                    "odds": no_odd,
                    "event_time": find_event_time(tokens, i),
                    "raw_index": i,
                    "source": "betmgm",
                })

        # Total rounds market
        if tok in ["Over", "Under"] and i + 2 < len(tokens):
            line = tokens[i + 1]
            odd = tokens[i + 2]

            if re.fullmatch(r"\d+\.\d+", line) and ODDS_RE.match(odd):
                props.append({
                    "market": "Total Rounds",
                    "selection": f"{tok} {line}",
                    "odds": odd,
                    "event_time": find_event_time(tokens, i),
                    "raw_index": i,
                    "source": "betmgm",
                })

    return props


def parse_moneyline_fights(tokens):
    """
    Lightweight fight detector to help attach props nearby later.
    """
    fights = []

    odds_positions = [i for i, t in enumerate(tokens) if ODDS_RE.match(t)]

    for p in range(len(odds_positions) - 1):
        a_odd_i = odds_positions[p]
        b_odd_i = odds_positions[p + 1]

        gap = b_odd_i - a_odd_i
        if gap < 2 or gap > 6:
            continue

        between = tokens[a_odd_i + 1:b_odd_i]
        if not between or not all(is_name_token(t) for t in between):
            continue

        fighter_b = " ".join(between)
        fighter_a = collect_name_before(tokens, a_odd_i, max_words=4)

        if not fighter_a or not fighter_b:
            continue

        if fighter_a == fighter_b:
            continue

        if len(fighter_a.split()) > 4 or len(fighter_b.split()) > 4:
            continue

        fights.append({
            "fight": f"{fighter_a} vs {fighter_b}",
            "fighter_a": fighter_a,
            "fighter_b": fighter_b,
            "event_time": find_event_time(tokens, a_odd_i),
            "moneyline": {
                fighter_a: tokens[a_odd_i],
                fighter_b: tokens[b_odd_i],
            },
            "raw_index": a_odd_i,
        })

    return fights


def attach_props_to_nearest_fight(props, fights):
    if not fights:
        return props

    for prop in props:
        idx = prop.get("raw_index", 0)

        nearest = None
        nearest_dist = 999999

        for fight in fights:
            dist = abs(idx - fight.get("raw_index", 0))
            if dist < nearest_dist:
                nearest = fight
                nearest_dist = dist

        if nearest and nearest_dist < 35:
            prop["fight"] = nearest["fight"]
            prop["fighter_a"] = nearest["fighter_a"]
            prop["fighter_b"] = nearest["fighter_b"]
        else:
            prop["fight"] = ""
            prop["fighter_a"] = ""
            prop["fighter_b"] = ""

    return props


def dedupe_props(props):
    seen = set()
    out = []

    for p in props:
        key = (
            p.get("fight", ""),
            p.get("event_time", ""),
            p.get("market", ""),
            p.get("selection", ""),
            p.get("odds", ""),
        )

        if key in seen:
            continue

        seen.add(key)

        p.pop("raw_index", None)
        out.append(p)

    return out


def parse_props_from_text(body):
    tokens = body.split()

    fights = parse_moneyline_fights(tokens)
    print(f"Detected nearby fights: {len(fights)}")

    props = parse_distance_and_totals(tokens)
    print(f"Detected raw props: {len(props)}")

    props = attach_props_to_nearest_fight(props, fights)
    props = dedupe_props(props)

    return fights, props


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DEBUG_PATH.exists():
        DEBUG_PATH.unlink()

    all_fights = []
    all_props = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1450, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        for url in BETMGM_URLS:
            print(f"\nOpening: {url}")

            try:
                page.goto(url, timeout=60000)
                wait(page)
                close_popups(page)
                scroll(page)

                body = get_body_text(page)
                save_debug(url, page, body)

                fights, props = parse_props_from_text(body)

                print(f"Parsed fights: {len(fights)}")
                print(f"Parsed props: {len(props)}")

                all_fights.extend(fights)
                all_props.extend(props)

            except Exception as e:
                print(f"ERROR opening {url}: {e}")

        input("Press ENTER to close browser...")
        browser.close()

    all_props = dedupe_props(all_props)

    output = {
        "updated_at": utc_now(),
        "source": "betmgm",
        "count": len(all_props),
        "props": all_props,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(all_props)} BetMGM props to {OUT_PATH}")

    if all_props:
        print("\nSample props:")
        for p in all_props[:40]:
            fight = p.get("fight") or "UNKNOWN FIGHT"
            print(f"- {fight} | {p['market']} | {p['selection']} | {p['odds']}")
    else:
        print("\nNo BetMGM props found.")
        print(f"Check debug file: {DEBUG_PATH}")


if __name__ == "__main__":
    main()