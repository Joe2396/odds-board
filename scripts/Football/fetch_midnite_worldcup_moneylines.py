"""
fetch_midnite_worldcup_moneylines.py
Scrapes World Cup 2026 moneyline odds (1X2) from Midnite.

Strategy:
  Playwright headless Chromium — loads the competition page, scrolls to
  trigger lazy-loaded matches, then scrapes team names + fractional odds
  directly from the rendered DOM.
  AWS WAF is bypassed because a real browser executes the JS challenge.

Output → football/data/midnite_worldcup_moneylines.json
Schema matches all other bookmaker moneyline scrapers:
  { match_id, event_id, home, away, kickoff, home_odds, draw_odds, away_odds, bookmaker, url }
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT        = Path(__file__).resolve().parents[2]   # C:\Users\joete\odds-board
OUTPUT_FILE = ROOT / "football" / "data" / "midnite_worldcup_moneylines.json"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
COMPETITION_ID   = "38826387"
COMPETITION_PAGE = f"https://www.midnite.com/sports/football/world-cup-2026-{COMPETITION_ID}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fractional_to_decimal(frac_str: str) -> float | None:
    """Convert '4/11' -> 1.3636, 'EVS' -> 2.0. Returns None if unparseable."""
    s = (frac_str or "").strip().upper()
    if s in ("EVS", "EVENS"):
        return 2.0
    try:
        return round(float(Fraction(s)) + 1.0, 4)
    except (ValueError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def scrape() -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("ERROR: playwright not installed.")
        print("  Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    print(f"  Loading: {COMPETITION_PAGE}")
    matches = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1280, "height": 900},
            user_agent=USER_AGENT,
            locale="en-GB",
        )

        try:
            page.goto(COMPETITION_PAGE, wait_until="networkidle", timeout=30_000)
        except PWTimeout:
            print("  Page load timed out — continuing anyway")

        # Wait for first match row
        try:
            page.wait_for_selector("a[href*='-v-']", timeout=15_000)
        except PWTimeout:
            print("  ERROR: No match rows appeared — page may be blocked")
            browser.close()
            return []

        # Scroll down repeatedly to trigger lazy loading of all 48 matches
        print("  Scrolling to load all matches …")
        prev_count = 0
        for _ in range(12):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.7)
            count = page.eval_on_selector_all(
                f"a[href*='world-cup-2026-{COMPETITION_ID}/'][href*='-v-']",
                "els => els.length"
            )
            if count == prev_count and count > 0:
                break   # No new matches loaded — we have them all
            prev_count = count

        print(f"  Found {prev_count} match links")

        # Extract all match data from DOM
        match_links = page.query_selector_all(
            f"a[href*='world-cup-2026-{COMPETITION_ID}/'][href*='-v-']"
        )

        for row in match_links:
            href = row.get_attribute("href") or ""
            event_id_m = re.search(r"-(\d{7,})$", href)
            if not event_id_m:
                continue

            event_id  = event_id_m.group(1)
            slug_full = href.split("/")[-1]                    # "mexico-v-south-africa-42532589"
            slug      = re.sub(r"-\d+$", "", slug_full)        # "mexico-v-south-africa"

            # The parent container has: team names + 3 fractional odds + kick-off time
            container = row.evaluate_handle("el => el.parentElement.parentElement")
            raw_text  = container.evaluate("el => el.innerText") or ""
            lines     = [l.strip() for l in raw_text.split("\n") if l.strip()]

            # Fractional odds — exactly 3 in home / draw / away order
            odds_raw = [l for l in lines if re.match(r"^\d+\/\d+$", l)]
            home_odds = fractional_to_decimal(odds_raw[0]) if len(odds_raw) > 0 else None
            draw_odds = fractional_to_decimal(odds_raw[1]) if len(odds_raw) > 1 else None
            away_odds = fractional_to_decimal(odds_raw[2]) if len(odds_raw) > 2 else None

            # Team names — everything that isn't an odds fraction or time string
            non_odds = [
                l for l in lines
                if not re.match(r"^\d+\/\d+$", l)
                and not re.search(r"\d{2}:\d{2}", l)
            ]
            home = non_odds[0] if len(non_odds) > 0 else ""
            away = non_odds[1] if len(non_odds) > 1 else ""

            # Kick-off time (raw string e.g. "Thu 20:00")
            kickoff_raw = next(
                (l for l in lines if re.search(r"\d{2}:\d{2}", l)), ""
            )

            match_url = (
                f"https://www.midnite.com{href}" if href.startswith("/") else href
            )

            if home and away and any([home_odds, draw_odds, away_odds]):
                matches.append({
                    "match_id":  slug,
                    "event_id":  event_id,
                    "home":      home,
                    "away":      away,
                    "kickoff":   kickoff_raw,
                    "home_odds": home_odds,
                    "draw_odds": draw_odds,
                    "away_odds": away_odds,
                    "bookmaker": "Midnite",
                    "url":       match_url,
                })

        browser.close()

    # De-duplicate by event_id (scroll can yield duplicates)
    seen, unique = set(), []
    for m in matches:
        if m["event_id"] not in seen:
            seen.add(m["event_id"])
            unique.append(m)

    return unique


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Midnite — World Cup 2026 Moneylines")
    print("=" * 60)

    matches = scrape()

    if not matches:
        print("\n✗ No matches scraped. Nothing saved.")
        sys.exit(1)

    from datetime import date, timedelta

    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    today = date.today()
    today_idx = today.weekday()  # 0=Mon, 6=Sun

    def kickoff_sort_key(m):
        k = m.get("kickoff", "")
        time_m = re.search(r"(\d{2}):(\d{2})", k)
        time_val = int(time_m.group(1)) * 60 + int(time_m.group(2)) if time_m else 0

        # Dated kickoff e.g. "Fri 19th Jun 02:00" — parse the day number
        dated = re.search(r"(\d+)(st|nd|rd|th)\s+(\w+)", k)
        if dated:
            day_num = int(dated.group(1))
            month_str = dated.group(3)
            months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                      "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
            month_num = months.get(month_str, 6)
            year = today.year if month_num >= today.month else today.year + 1
            try:
                d = date(year, month_num, day_num)
                return (d.toordinal() * 1440 + time_val,)
            except Exception:
                return (99999999,)

        # Undated kickoff e.g. "Thu 20:00" — find next occurrence of that day
        day_m = re.match(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)", k)
        if day_m:
            day_name = day_m.group(1)
            target_idx = DAY_NAMES.index(day_name)
            # Always find the NEXT occurrence (1-7 days ahead, never today=0)
            days_ahead = (target_idx - today_idx) % 7
            if days_ahead == 0:
                days_ahead = 7  # same weekday = next week
            d = today + timedelta(days=days_ahead)
            return (d.toordinal() * 1440 + time_val,)

        return (99999998,)

    matches.sort(key=kickoff_sort_key)

    output = {
        "bookmaker":   "Midnite",
        "competition": "FIFA World Cup 2026",
        "scraped_at":  datetime.now(timezone.utc).isoformat(),
        "matches":     matches,
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n✓ Saved {len(matches)} matches → {OUTPUT_FILE}")
    for m in matches[:5]:
        print(
            f"  {m['home']:<22} vs {m['away']:<22} | "
            f"{m['home_odds']} / {m['draw_odds']} / {m['away_odds']}"
        )
    if len(matches) > 5:
        print(f"  … and {len(matches) - 5} more")


if __name__ == "__main__":
    main()