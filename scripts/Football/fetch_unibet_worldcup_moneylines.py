#!/usr/bin/env python3
import json
import math
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "unibet_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "unibet_worldcup_text_debug.txt"

URL = "https://www.unibet.ie/betting/odds/football/international/worldcup/matches"

DECIMAL_RE = re.compile(r"^\d+(?:\.\d+)?$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DATE_RE = re.compile(r"^\d{1,2}\s+\w+\s+\d{4}$", re.I)

WORLD_CUP_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic", "Czechia",
    "Canada", "Bosnia & Herzegovina", "Bosnia and Herzegovina", "Bosnia",
    "USA", "Paraguay", "Qatar", "Switzerland", "Brazil", "Morocco",
    "Haiti", "Scotland", "Australia", "Turkey", "Turkiye", "Türkiye",
    "Germany", "Curacao", "Curaçao", "Netherlands", "Japan",
    "Ivory Coast", "Ecuador", "Sweden", "Tunisia", "Spain",
    "Cape Verde", "Belgium", "Egypt", "Saudi Arabia", "Uruguay", "Iran",
    "New Zealand", "France", "Senegal", "Iraq", "Norway", "Argentina",
    "Algeria", "Austria", "Jordan", "Portugal", "DR Congo", "England",
    "Croatia", "Ghana", "Panama", "Colombia", "Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    s = clean(s)
    return TEAM_ALIASES.get(s, s)


def is_decimal_odds(s):
    s = clean(s)
    if not DECIMAL_RE.match(s):
        return False
    try:
        v = float(s)
        return 1.01 <= v <= 101
    except Exception:
        return False


def is_time(s):
    return bool(TIME_RE.match(clean(s)))


def is_date(s):
    return bool(DATE_RE.match(clean(s)))


def is_team_line(s):
    return clean(s) in WORLD_CUP_TEAMS


def decimal_to_fractional(decimal_value):
    try:
        dec = float(decimal_value)
    except Exception:
        return str(decimal_value)

    frac = dec - 1.0

    common_denoms = [1, 2, 3, 4, 5, 6, 8, 10, 11, 20, 25, 50, 100]
    best_num = 0
    best_den = 1
    best_err = 999

    for den in common_denoms:
        num = round(frac * den)
        if num <= 0:
            continue
        err = abs((num / den) - frac)
        if err < best_err:
            best_err = err
            best_num = num
            best_den = den

    g = math.gcd(best_num, best_den)
    best_num //= g
    best_den //= g

    if best_num == best_den:
        return "EVS"

    return f"{best_num}/{best_den}"


def parse_unibet_text(text):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    matches = []
    current_date = ""

    i = 0

    while i < len(lines):
        line = lines[i]

        if is_date(line):
            current_date = line
            i += 1
            continue

        # Format:
        # 20:00
        # Mexico
        # South Africa
        # 1.42
        # 4.20
        # 7.00
        if (
            i + 5 < len(lines)
            and is_time(lines[i])
            and is_team_line(lines[i + 1])
            and is_team_line(lines[i + 2])
            and is_decimal_odds(lines[i + 3])
            and is_decimal_odds(lines[i + 4])
            and is_decimal_odds(lines[i + 5])
        ):
            time_label = lines[i]
            home = canonical_team(lines[i + 1])
            away = canonical_team(lines[i + 2])

            home_dec = lines[i + 3]
            draw_dec = lines[i + 4]
            away_dec = lines[i + 5]

            matches.append({
                "competition": "FIFA World Cup",
                "bookmaker": "Unibet",
                "date_label": current_date,
                "time": time_label,
                "match": f"{home} v {away}",
                "home_team": home,
                "away_team": away,
                "market": "Match Odds",
                "odds": {
                    "home": decimal_to_fractional(home_dec),
                    "draw": decimal_to_fractional(draw_dec),
                    "away": decimal_to_fractional(away_dec),
                },
                "decimal_odds": {
                    "home": float(home_dec),
                    "draw": float(draw_dec),
                    "away": float(away_dec),
                },
                "source_url": URL,
            })

            i += 6
            continue

        i += 1

    return dedupe(matches)


def dedupe(matches):
    seen = set()
    unique = []

    for m in matches:
        key = (m["date_label"], m["time"], m["match"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)

    return unique


def collect_matches_from_page(page):
    text = page.locator("body").inner_text(timeout=30000)
    return parse_unibet_text(text), text


def click_all_date_rows(page):
    """
    Unibet only expands some dates by default.
    This clicks visible date headers like '13 Jun 2026', '14 Jun 2026', etc.
    """
    clicked_count = 0

    date_pattern = re.compile(r"^\d{1,2}\s+\w+\s+2026$")

    for round_no in range(3):
        print(f"Expanding date rows pass {round_no + 1}/3...")

        try:
            locs = page.locator("text=/^\\d{1,2}\\s+\\w+\\s+2026$/")
            count = locs.count()
        except Exception:
            count = 0

        for i in range(count):
            try:
                item = locs.nth(i)
                label = clean(item.inner_text(timeout=1500))

                if not date_pattern.match(label):
                    continue

                box = item.bounding_box()
                if not box:
                    continue

                # Click around the middle/right of the date row to expand.
                page.mouse.click(box["x"] + 40, box["y"] + box["height"] / 2)
                page.wait_for_timeout(700)
                clicked_count += 1
            except Exception:
                pass

        page.mouse.wheel(0, 900)
        page.wait_for_timeout(900)

    return clicked_count


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    all_matches = []
    all_text_parts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        print(f"Opening {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)

        for label in [
            "Accept All",
            "Accept all",
            "I Accept",
            "Accept",
            "Agree",
            "Allow all",
            "Got it",
        ]:
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if btn.count():
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

        for label in ["Matches", "Full Time Result"]:
            try:
                item = page.get_by_text(label, exact=True)
                if item.count():
                    item.first.click(timeout=3000)
                    page.wait_for_timeout(1500)
            except Exception:
                pass

        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception:
            pass

        # First scrape visible dates.
        matches, text = collect_matches_from_page(page)
        all_matches.extend(matches)
        all_text_parts.append(text)
        print(f"Initial visible matches: {len(matches)}")

        # Click collapsed date rows.
        clicked = click_all_date_rows(page)
        print(f"Date rows clicked: {clicked}")

        # Now scroll and scrape every visible area.
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception:
            pass

        for i in range(30):
            print(f"Loading page section {i + 1}/30...")
            matches, text = collect_matches_from_page(page)
            all_matches.extend(matches)
            all_matches = dedupe(all_matches)
            all_text_parts.append(text)

            page.mouse.wheel(0, 850)
            page.wait_for_timeout(700)

        matches = dedupe(all_matches)

        DEBUG_PATH.write_text(
            "\n\n--- PAGE SNAPSHOT ---\n\n".join(all_text_parts),
            encoding="utf-8",
        )

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "Unibet",
            "market": "Match Odds",
            "source_url": URL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "match_count": len(matches),
            "matches": matches,
        }

        OUT_PATH.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"\nSaved {len(matches)} Unibet World Cup moneyline matches to:")
        print(OUT_PATH)

        if matches:
            print("\nSample:")
            for m in matches[:100]:
                print(
                    f"- {m['date_label']} {m['time']} | {m['match']} | "
                    f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']} "
                    f"(dec {m['decimal_odds']['home']} / {m['decimal_odds']['draw']} / {m['decimal_odds']['away']})"
                )
        else:
            print("\nNo Unibet World Cup matches found.")
            print(f"Debug text saved to: {DEBUG_PATH}")


        browser.close()


if __name__ == "__main__":
    main()
