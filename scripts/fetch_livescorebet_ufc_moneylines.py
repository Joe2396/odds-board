#!/usr/bin/env python3
"""
fetch_livescorebet_ufc_moneylines.py

Scrapes UFC "To Win Fight" moneylines from LiveScoreBet's UFC hub page.
Replaces BetMGM (no longer reliable) in the UFC bookmaker lineup.

Page layout (one page, all fights):
    Fighter 1
    Fighter 2
    <odds1>
    <odds2>
    Today, 22:15      <- or "Tomorrow, HH:MM" / "Sat, 21 Jun, HH:MM" etc.
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
import os

def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


ROOT = Path(__file__).resolve().parents[1]

OUT_PATH = ROOT / "ufc" / "data" / "livescorebet_moneylines.json"
DEBUG_PATH = ROOT / "ufc" / "data" / "debug" / "livescorebet_ufc_text_debug.txt"

URL = "https://www.livescorebet.com/ie/sports/mma/ufc/SBTC3_9034/"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)

# Matches: "Today, 22:15" / "Tomorrow, 14:00" / "Sat, 21 Jun, 14:00" etc.
DATE_LINE_RE = re.compile(
    r"^(Today|Tomorrow|Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-zA-Z]*,?.*\d{1,2}:\d{2}$",
    re.I,
)

# UI/junk lines that should never be treated as a fighter name
JUNK_LINES = {
    "home", "my bets", "in-play", "promotions", "vegas", "live casino",
    "daily free game", "squads", "safer gambling", "more", "football",
    "horse racing", "tennis", "greyhounds", "virtual sports", "world cup 2026",
    "featured", "winner", "total rounds", "matches", "outrights & specials",
    "login", "join", "bet slip", "single", "acca", "multiples",
    "your bet slip is empty", "to return", "place bet", "today",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_date_line(s):
    return bool(DATE_LINE_RE.match(clean(s)))


def looks_like_fighter_name(s):
    s = clean(s)
    if not s or len(s) > 40:
        return False
    if s.lower() in JUNK_LINES:
        return False
    if is_odds(s) or is_date_line(s):
        return False
    if re.search(r"\d", s):
        return False
    # Needs at least one letter
    if not re.search(r"[A-Za-z]", s):
        return False
    return True


def parse_livescorebet_ufc_text(text):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    fights = []
    i = 0

    while i < len(lines) - 4:
        fighter1 = lines[i]
        fighter2 = lines[i + 1]
        odds1 = lines[i + 2]
        odds2 = lines[i + 3]
        date_line = lines[i + 4]

        if (
            looks_like_fighter_name(fighter1)
            and looks_like_fighter_name(fighter2)
            and is_odds(odds1)
            and is_odds(odds2)
            and is_date_line(date_line)
        ):
            fight_name = f"{fighter1} vs {fighter2}"

            fights.append({
                "bookmaker": "LiveScoreBet",
                "fight": fight_name,
                "fight_name": fight_name,
                "fighter1": fighter1,
                "fighter2": fighter2,
                "date_label": date_line,
                "url": URL,
                "markets": {
                    "fight_betting": [
                        {"selection": fighter1, "odds": odds1.upper()},
                        {"selection": fighter2, "odds": odds2.upper()},
                    ]
                },
            })

            i += 5
            continue

        i += 1

    # Deduplicate by fight name
    seen = {}
    for f in fights:
        seen[f["fight_name"]] = f

    return list(seen.values())


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


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("RUNNING LIVESCOREBET UFC MONEYLINES SCRAPER")
    print(f"Opening {URL}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=is_github_actions())
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)

        accept_cookies(page)
        page.wait_for_timeout(1000)

        # Make sure the "Winner" tab is selected (it's the default, but be safe)
        try:
            page.get_by_text("Winner", exact=True).first.click(timeout=3000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception:
            pass

        for i in range(20):
            print(f"Loading page section {i + 1}/20...")
            page.mouse.wheel(0, 750)
            page.wait_for_timeout(650)

        text = page.locator("body").inner_text(timeout=30000)
        DEBUG_PATH.write_text(text, encoding="utf-8")

        fights = parse_livescorebet_ufc_text(text)

        output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "livescorebet",
            "bookmaker": "LiveScoreBet",
            "url": URL,
            "count": len(fights),
            "fights": fights,
        }

        OUT_PATH.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"\nSaved {len(fights)} LiveScoreBet UFC fights to:")
        print(OUT_PATH)

        if fights:
            print("\nSample:")
            for f in fights[:30]:
                sels = f["markets"]["fight_betting"]
                print(f"- {f['date_label']} | {f['fight_name']} | "
                      f"{sels[0]['selection']} {sels[0]['odds']} vs "
                      f"{sels[1]['selection']} {sels[1]['odds']}")
        else:
            print("\nNo LiveScoreBet UFC fights found.")
            print(f"Debug text saved to: {DEBUG_PATH}")

        browser.close()


if __name__ == "__main__":
    main()