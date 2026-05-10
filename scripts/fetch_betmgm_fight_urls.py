#!/usr/bin/env python3
import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


print("FETCHING BETMGM FIGHT URLS / EVENTS")

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "betmgm_fight_urls.json"
DEBUG_PATH = ROOT / "ufc" / "data" / "betmgm_debug.txt"

BETMGM_URLS = [
    "https://www.betmgm.co.uk/sports/mma/ufc",
    "https://www.betmgm.co.uk/sports/mma",
]

ODDS_RE = re.compile(r"^(?:EVS|\d+/\d+)$", re.I)

TIME_TOKEN_RE = re.compile(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)$")
CLOCK_RE = re.compile(r"^\d{1,2}:\d{2}$")

JUNK = {
    "UFC",
    "MMA",
    "MVP",
    "Outrights",
    "Bout",
    "Odds",
    "Distance",
    "Total",
    "Rounds",
    "Round",
    "Method",
    "Victory",
    "Search",
    "My",
    "Bets",
    "Bet",
    "Casino",
    "Live",
    "Sports",
    "Featured",
    "All",
    "In-Play",
    "Golden",
    "Goals",
    "More",
    "Yes",
    "No",
    "Over",
    "Under",
    "EVS",
    "LOG",
    "IN",
    "SIGN",
    "UP",
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
            page.mouse.wheel(0, 1000)
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
    block.append("=" * 90)
    block.append(f"TIME: {utc_now()}")
    block.append(f"LABEL: {label}")
    block.append(f"URL: {page.url}")
    block.append(f"TITLE: {title}")
    block.append(f"BODY LENGTH: {len(body)}")
    block.append("-" * 90)
    block.append(body[:12000])
    block.append("\n")

    with open(DEBUG_PATH, "a", encoding="utf-8") as f:
        f.write("\n".join(block))

    print("\n--- DEBUG SAMPLE ---")
    print("\n".join(block)[:2200])
    print("--- END DEBUG SAMPLE ---\n")


def is_name_token(token):
    if not token:
        return False

    token = token.strip()

    if token in JUNK:
        return False

    if ODDS_RE.match(token):
        return False

    if TIME_TOKEN_RE.match(token):
        return False

    if CLOCK_RE.match(token):
        return False

    if re.fullmatch(r"\d+", token):
        return False

    if re.fullmatch(r"\d+\.\d+", token):
        return False

    # Names like O'Malley, Álvarez, Cortes-Acosta
    return bool(re.match(r"^[A-ZÁÉÍÓÚÑÄËÏÖÜ][A-Za-zÁÉÍÓÚáéíóúÑñÄËÏÖÜäëïöü.'\-]+$", token))


def is_market_word(token):
    if not token:
        return True

    if token in JUNK:
        return True

    if ODDS_RE.match(token):
        return True

    if TIME_TOKEN_RE.match(token):
        return True

    if CLOCK_RE.match(token):
        return True

    if re.fullmatch(r"\d+", token):
        return True

    if re.fullmatch(r"\d+\.\d+", token):
        return True

    return False


def split_repeated_names(pre_tokens):
    """
    BetMGM text usually has:
    Fighter A Fighter B Fighter A ODDS Fighter B ODDS

    Example:
    Clayton Carpenter Jose Ochoa Clayton Carpenter 29/20 Jose Ochoa 11/20

    The tokens before first odds are:
    [Clayton, Carpenter, Jose, Ochoa, Clayton, Carpenter]

    We find the repeated suffix:
    [Clayton, Carpenter]
    Then the remaining prefix is:
    [Clayton, Carpenter, Jose, Ochoa]
    So fighter A = repeated suffix
    fighter B = prefix minus fighter A
    """
    if len(pre_tokens) < 3:
        return "", ""

    best = None

    max_len = min(4, len(pre_tokens) // 2)

    for name_len in range(max_len, 0, -1):
        suffix = pre_tokens[-name_len:]
        prefix = pre_tokens[:-name_len]

        if len(prefix) <= name_len:
            continue

        if prefix[:name_len] == suffix:
            fighter_a = " ".join(suffix)
            fighter_b = " ".join(prefix[name_len:])

            if fighter_a and fighter_b:
                best = (fighter_a, fighter_b)
                break

    if best:
        return best

    return "", ""


def find_event_time(tokens, idx):
    for i in range(idx, max(-1, idx - 25), -1):
        if i + 1 < len(tokens):
            if TIME_TOKEN_RE.match(tokens[i]) and CLOCK_RE.match(tokens[i + 1]):
                return f"{tokens[i]} {tokens[i + 1]}"
    return ""


def parse_fights_from_text(body):
    tokens = body.split()

    odds_positions = []
    for i, tok in enumerate(tokens):
        if ODDS_RE.match(tok):
            odds_positions.append(i)

    print(f"Found odds tokens: {len(odds_positions)}")

    parsed = []

    for pos_idx in range(len(odds_positions) - 1):
        first_odd_i = odds_positions[pos_idx]
        second_odd_i = odds_positions[pos_idx + 1]

        gap = second_odd_i - first_odd_i

        # BetMGM moneyline format is usually:
        # Fighter A ODD Fighter B ODD
        # so gap is typically 2-5
        if gap < 2 or gap > 6:
            continue

        odd_a = tokens[first_odd_i]
        odd_b = tokens[second_odd_i]

        between_tokens = tokens[first_odd_i + 1:second_odd_i]

        if not between_tokens:
            continue

        if not all(is_name_token(t) for t in between_tokens):
            continue

        fighter_b = " ".join(between_tokens)

        # Now collect clean name tokens before first odds until market/time junk
        pre_tokens = []
        i = first_odd_i - 1

        while i >= 0 and len(pre_tokens) < 10:
            tok = tokens[i]

            if is_name_token(tok):
                pre_tokens.insert(0, tok)
                i -= 1
                continue

            break

        if not pre_tokens:
            continue

        fighter_a, listed_fighter_b = split_repeated_names(pre_tokens)

        if not fighter_a:
            # fallback: use last 1-3 words before odds as fighter A
            for name_len in [3, 2, 1]:
                if len(pre_tokens) >= name_len:
                    maybe_a = " ".join(pre_tokens[-name_len:])
                    if maybe_a and maybe_a != fighter_b:
                        fighter_a = maybe_a
                        break

        if listed_fighter_b and listed_fighter_b != fighter_b:
            # keep the actual name between odds as fighter B
            pass

        if not fighter_a or not fighter_b:
            continue

        if fighter_a == fighter_b:
            continue

        if len(fighter_a.split()) > 4 or len(fighter_b.split()) > 4:
            continue

        if len(fighter_a) < 3 or len(fighter_b) < 3:
            continue

        bad_fight_bits = [
            "Yes",
            "No",
            "Over",
            "Under",
            "More",
            "Bets",
            "Total",
            "Rounds",
            "Distance",
        ]

        if any(b in fighter_a.split() for b in bad_fight_bits):
            continue

        if any(b in fighter_b.split() for b in bad_fight_bits):
            continue

        fight = f"{fighter_a} vs {fighter_b}"
        event_time = find_event_time(tokens, first_odd_i)

        parsed.append({
            "fight": fight,
            "fighter_a": fighter_a,
            "fighter_b": fighter_b,
            "odds": {
                fighter_a: odd_a,
                fighter_b: odd_b,
            },
            "event_time": event_time,
            "source": "betmgm",
            "capture_method": "text_moneyline_parse",
            "url": "https://www.betmgm.co.uk/sports/mma/ufc#sports-hub/ufc_mma",
        })

    return parsed


def dedupe(items):
    seen = set()
    out = []

    for item in items:
        fight = clean(item.get("fight", ""))

        if not fight:
            continue

        bad_bits = [
            "Yes vs No",
            "Over vs Under",
            "More vs Bets",
            "UFC vs",
            "MMA vs",
            "Sports vs",
        ]

        if any(b.lower() in fight.lower() for b in bad_bits):
            continue

        key_names = sorted([
            clean(item.get("fighter_a", "")).lower(),
            clean(item.get("fighter_b", "")).lower(),
        ])

        key = " | ".join(key_names)

        if key in seen:
            continue

        seen.add(key)
        out.append(item)

    out.sort(key=lambda x: x.get("event_time", "") + x["fight"].lower())
    return out


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DEBUG_PATH.exists():
        DEBUG_PATH.unlink()

    all_items = []

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

                items = parse_fights_from_text(body)
                print(f"Parsed fights from text: {len(items)}")

                all_items.extend(items)

            except Exception as e:
                print(f"ERROR opening {url}: {e}")

        input("Press ENTER to close browser...")
        browser.close()

    fights = dedupe(all_items)

    output = {
        "updated_at": utc_now(),
        "source": "betmgm",
        "count": len(fights),
        "fights": fights,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(fights)} BetMGM fights to {OUT_PATH}")

    if fights:
        print("\nParsed fights:")
        for f in fights:
            print(f"- {f.get('event_time', '')} {f['fight']} | {f['odds']}")
    else:
        print("\nNo BetMGM fights parsed.")
        print(f"Check debug file: {DEBUG_PATH}")


if __name__ == "__main__":
    main()