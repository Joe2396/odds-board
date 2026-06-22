#!/usr/bin/env python3
"""
fetch_livescorebet_ufc_props.py

Scrapes Method of Victory, Round Betting, and Go The Distance props
from LiveScoreBet individual UFC fight pages.

Output : ufc/data/livescorebet_props.json
Debug  : ufc/data/debug/livescorebet_props/
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT             = Path(__file__).resolve().parents[1]
MONEYLINES_PATH  = ROOT / "ufc" / "data" / "livescorebet_moneylines.json"
OUT_PATH         = ROOT / "ufc" / "data" / "livescorebet_props.json"
DEBUG_DIR        = ROOT / "ufc" / "data" / "debug" / "livescorebet_props"

HUB_URL  = "https://www.livescorebet.com/ie/sports/mma/ufc/SBTC3_9034/"
ODDS_RE  = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)

# Lines that are never selection names — used to avoid parsing junk
JUNK = {
    "Method of Victory", "Round Betting", "Round Group Betting",
    "Go The Distance", "Fight Distance", "Goes The Distance",
    "Winner", "Fight Betting", "Total Rounds", "Rounds Betting",
    "View more", "View less", "Add to Betslip", "Bet Builder",
    "Over", "Under", "Yes", "No", "Draw",
    "KO/TKO", "Submission", "Decision", "Technical Decision",
    "1st Round", "2nd Round", "3rd Round", "4th Round", "5th Round",
    "Favourite", "Odds",
}

# Market headings that signal we've left the current section
STOP_HEADINGS = {
    "Method of Victory", "Round Betting", "Round Group Betting",
    "Go The Distance", "Fight Distance", "Winner", "Fight Betting",
    "Total Rounds", "Both Teams to Score", "Correct Score",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "_", clean(s).lower()).strip("_")


# ── Browser helpers ───────────────────────────────────────────────────────────

def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "Got it"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass

def expand_view_more(page):
    try:
        buttons = page.get_by_text("View more", exact=True)
        count = buttons.count()
        if count:
            print(f"    Expanding {count} 'View more' button(s)...")
            for i in range(count):
                try:
                    buttons.nth(i).scroll_into_view_if_needed(timeout=2000)
                    buttons.nth(i).click(timeout=3000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass
    except Exception:
        pass

def get_page_text(page, url, scroll_steps=22):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookies(page)

    for _ in range(scroll_steps):
        page.mouse.wheel(0, 650)
        page.wait_for_timeout(250)

    expand_view_more(page)
    page.keyboard.press("Control+Home")
    page.wait_for_timeout(400)

    return page.locator("body").inner_text(timeout=30000)


# ── Fight link discovery ──────────────────────────────────────────────────────

def get_fight_links(page):
    """Open UFC hub page, scroll, extract individual fight page links."""
    print(f"Opening hub: {HUB_URL}")
    page.goto(HUB_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    accept_cookies(page)

    for _ in range(22):
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(300)

    page.wait_for_timeout(2000)

    links = page.evaluate("""
        () => [...new Set(
            Array.from(document.querySelectorAll('a'))
                .map(a => a.href)
                .filter(h =>
                    h &&
                    h.includes('/mma/ufc/') &&
                    h.includes('/SBTE_')
                )
        )]
    """)

    fights = []
    seen = set()
    for url in links:
        base_url = url.split("?")[0].rstrip("/")
        if base_url in seen:
            continue
        seen.add(base_url)

        # Derive a human-readable name from the slug between competition and event IDs
        # e.g. /mma/ufc/SBTC3_9034/manel-kape-v-kyoji-horiguchi/SBTE_12345678/
        parts = base_url.split("/")
        slug = ""
        for j, part in enumerate(parts):
            if part.startswith("SBTC") and j + 1 < len(parts):
                slug = parts[j + 1]
                break
        name = slug.replace("-", " ").title() if slug else base_url.split("/")[-1]
        fights.append({"url": base_url, "name": name})

    print(f"Found {len(fights)} fight link(s)")
    return fights


# ── Text parsers ──────────────────────────────────────────────────────────────

def detect_fighters(lines):
    """
    Try to find fighter names from the page text.
    Looks for "FighterA v FighterB" combined line first,
    then falls back to checking adjacent lines around a 'v' token.
    """
    for line in lines:
        m = re.match(r"^(.+?)\s+v\s+(.+)$", line, re.I)
        if m:
            f1, f2 = m.group(1).strip(), m.group(2).strip()
            if 3 < len(f1) < 45 and 3 < len(f2) < 45:
                return f1, f2
    return "", ""


def parse_method_of_victory(lines):
    """
    Parses Method of Victory market.
    Typical LiveScoreBet format after the heading:
        Fighter1 by KO/TKO   <odds>
        Fighter1 by Submission  <odds>
        Fighter1 by Decision  <odds>
        Fighter2 by KO/TKO   <odds>
        ...  (sometimes also "Draw" or "No Contest")
    """
    idx = next(
        (i for i, l in enumerate(lines)
         if clean(l).lower() in {"method of victory", "method of winning"}),
        -1,
    )
    if idx == -1:
        return []

    selections = []
    i = idx + 1
    limit = min(idx + 80, len(lines))

    while i < limit:
        line = clean(lines[i])

        # Stop when we hit another known heading
        if line in STOP_HEADINGS and i > idx + 2:
            break

        # Selection + odds pair
        if (
            line
            and line not in JUNK
            and not is_odds(line)
            and not re.match(r"^\d+(?:\.\d+)?$", line)
            and 2 < len(line) < 80
        ):
            if i + 1 < limit and is_odds(lines[i + 1]):
                selections.append({
                    "selection": line,
                    "odds": clean(lines[i + 1]).upper(),
                })
                i += 2
                continue

        i += 1

    return selections


def parse_round_betting(lines):
    """
    Parses Round Betting / Round Group Betting market.
    Format varies:
        Round 1  <odds>
        Round 2  <odds>
        ...
    or grouped:
        Rounds 1-2  <odds>
        Rounds 3-5  <odds>
    """
    idx = next(
        (i for i, l in enumerate(lines)
         if clean(l).lower() in {"round betting", "round group betting", "rounds betting"}),
        -1,
    )
    if idx == -1:
        return []

    selections = []
    i = idx + 1
    limit = min(idx + 60, len(lines))

    while i < limit:
        line = clean(lines[i])

        if line in STOP_HEADINGS and i > idx + 2:
            break

        if (
            line
            and line not in JUNK
            and not is_odds(line)
            and 2 < len(line) < 60
            and re.search(r"\d", line)   # round entries always contain a digit
        ):
            if i + 1 < limit and is_odds(lines[i + 1]):
                selections.append({
                    "selection": line,
                    "odds": clean(lines[i + 1]).upper(),
                })
                i += 2
                continue

        i += 1

    return selections


def parse_go_the_distance(lines):
    """
    Parses Go The Distance (Yes / No) market.
    """
    heading_idx = next(
        (i for i, l in enumerate(lines)
         if clean(l).lower() in {
             "go the distance", "fight distance",
             "goes the distance", "go the distance?",
         }),
        -1,
    )
    if heading_idx == -1:
        return []

    block = lines[heading_idx: heading_idx + 20]
    yes_odds = no_odds = None

    for j, line in enumerate(block):
        label = clean(line)
        if label.lower() == "yes" and j + 1 < len(block) and is_odds(block[j + 1]):
            yes_odds = clean(block[j + 1]).upper()
        elif label.lower() == "no" and j + 1 < len(block) and is_odds(block[j + 1]):
            no_odds = clean(block[j + 1]).upper()

    selections = []
    if yes_odds:
        selections.append({"selection": "Yes", "odds": yes_odds})
    if no_odds:
        selections.append({"selection": "No", "odds": no_odds})
    return selections


def parse_total_rounds(lines):
    """Parses Total Rounds over/under if present."""
    idx = next(
        (i for i, l in enumerate(lines)
         if clean(l).lower() in {"total rounds", "rounds over/under"}),
        -1,
    )
    if idx == -1:
        return []

    block = lines[idx: idx + 40]
    selections = []

    for j, line in enumerate(block):
        label = clean(line)
        if re.match(r"^\d+(?:\.\d+)?$", label) and j + 2 < len(block):
            over_odds = clean(block[j + 1])
            under_odds = clean(block[j + 2])
            if is_odds(over_odds) and is_odds(under_odds):
                selections.append({
                    "selection": f"Over {label}",
                    "odds": over_odds.upper(),
                    "line": label,
                    "side": "over",
                })
                selections.append({
                    "selection": f"Under {label}",
                    "odds": under_odds.upper(),
                    "line": label,
                    "side": "under",
                })

    return selections


# ── Per-fight scraper ─────────────────────────────────────────────────────────

def scrape_fight(page, fight_info):
    url  = fight_info["url"]
    name = fight_info["name"]
    print(f"\n  [{name}]  {url}")

    text  = get_page_text(page, url)
    lines = [clean(l) for l in text.splitlines() if clean(l)]

    # Debug dump
    debug_file = DEBUG_DIR / f"{slugify(name)}.txt"
    debug_file.write_text(text, encoding="utf-8")

    fighter1, fighter2 = detect_fighters(lines)
    print(f"  Fighters: {fighter1!r} v {fighter2!r}")

    # Parse all markets
    method_sels      = parse_method_of_victory(lines)
    round_sels       = parse_round_betting(lines)
    gtd_sels         = parse_go_the_distance(lines)
    total_round_sels = parse_total_rounds(lines)

    markets = []
    if method_sels:
        markets.append({"market": "Method of Victory",
                        "selection_count": len(method_sels),
                        "selections": method_sels})
    if round_sels:
        markets.append({"market": "Round Betting",
                        "selection_count": len(round_sels),
                        "selections": round_sels})
    if gtd_sels:
        markets.append({"market": "Go The Distance",
                        "selection_count": len(gtd_sels),
                        "selections": gtd_sels})
    if total_round_sels:
        markets.append({"market": "Total Rounds",
                        "selection_count": len(total_round_sels),
                        "selections": total_round_sels})

    print(f"  Markets: {[m['market'] for m in markets]}")

    return {
        "fighter1":     fighter1,
        "fighter2":     fighter2,
        "fight_url":    url,
        "market_count": len(markets),
        "markets":      markets,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LIVESCOREBET UFC PROPS SCRAPER")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=is_github_actions())
        page    = browser.new_page(viewport={"width": 1700, "height": 1000})

        fight_links = get_fight_links(page)

        if not fight_links:
            print("WARNING: no fight links found — hub page may not have loaded fully")

        results = []
        for i, fight_info in enumerate(fight_links):
            print(f"\n[{i+1}/{len(fight_links)}]")
            try:
                result = scrape_fight(page, fight_info)
                results.append(result)
            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({
                    "fighter1":     "",
                    "fighter2":     "",
                    "fight_url":    fight_info["url"],
                    "market_count": 0,
                    "markets":      [],
                })

        browser.close()

    output = {
        "sport":        "ufc",
        "bookmaker":    "LiveScoreBet",
        "market_type":  "props",
        "source_url":   HUB_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fight_count":  len(results),
        "fights":       results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved → {OUT_PATH}")

    print("\n── Summary ─────────────────────────────────────────────")
    for r in results:
        label = f"{r['fighter1']} v {r['fighter2']}" if r["fighter1"] else r["fight_url"]
        print(f"  {label:<50} {r['market_count']} markets")
        for m in r.get("markets", []):
            print(f"      - {m['market']} ({m['selection_count']})")
    print("─" * 60)

    input("Press ENTER to exit...")


if __name__ == "__main__":
    main()