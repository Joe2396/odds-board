#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "888sport_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "888sport_worldcup_text_debug.txt"

URL = "https://www.888sport.com/football/world-cup/"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DATE_RE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+\w+$", re.I)

WORLD_CUP_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic", "Czechia",
    "Canada", "Bosnia & Herzegovina", "Bosnia and Herzegovina", "Bosnia",
    "USA", "Paraguay", "Qatar", "Switzerland", "Brazil", "Morocco",
    "Haiti", "Scotland", "Australia", "Turkey", "Turkiye", "Türkiye",
    "Germany", "Curacao", "Curaçao", "Netherlands", "Japan",
    "Ivory Coast", "Ecuador", "Sweden", "Tunisia", "Spain",
    "Cape Verde", "Cape Verde Islands", "Belgium", "Egypt",
    "Saudi Arabia", "Uruguay", "Iran", "New Zealand", "France",
    "Senegal", "Iraq", "Norway", "Argentina", "Algeria", "Austria",
    "Jordan", "Portugal", "DR Congo", "Congo DR", "England", "Croatia",
    "Ghana", "Panama", "Colombia", "Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
    "Cape Verde Islands": "Cape Verde",
    "Congo DR": "DR Congo",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    return TEAM_ALIASES.get(clean(s), clean(s))


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_time(s):
    return bool(TIME_RE.match(clean(s)))


def is_date(s):
    return bool(DATE_RE.match(clean(s)))


def is_team_line(s):
    return clean(s) in WORLD_CUP_TEAMS


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


def parse_888sport_text(text):
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

        # 888Sport format:
        # Mexico
        # South Africa
        # 20:00
        # 2/5
        # 3/1
        # 6/1
        if (
            i + 5 < len(lines)
            and is_team_line(lines[i])
            and is_team_line(lines[i + 1])
            and is_time(lines[i + 2])
            and is_odds(lines[i + 3])
            and is_odds(lines[i + 4])
            and is_odds(lines[i + 5])
        ):
            home = canonical_team(lines[i])
            away = canonical_team(lines[i + 1])
            time_label = lines[i + 2]

            matches.append({
                "competition": "FIFA World Cup",
                "bookmaker": "888Sport",
                "date_label": current_date,
                "time": time_label,
                "match": f"{home} v {away}",
                "home_team": home,
                "away_team": away,
                "market": "Match Odds",
                "odds": {
                    "home": lines[i + 3].upper(),
                    "draw": lines[i + 4].upper(),
                    "away": lines[i + 5].upper(),
                },
                "source_url": URL,
            })

            i += 6
            continue

        i += 1

    return dedupe(matches)


def scrape_snapshot(page, all_text, all_matches, label):
    text = page.locator("body").inner_text(timeout=30000)
    all_text.append(f"\n\n--- {label} ---\n\n{text}")

    found = parse_888sport_text(text)
    all_matches.extend(found)
    all_matches[:] = dedupe(all_matches)

    print(f"{label}: {len(all_matches)} matches")


def set_scroll_top(page, y):
    page.evaluate(
        """
        (y) => {
            document.scrollingElement.scrollTop = y;
            window.scrollTo(0, y);
        }
        """,
        y,
    )


def get_scroll_height(page):
    try:
        return int(page.evaluate("document.scrollingElement.scrollHeight"))
    except Exception:
        return 0


def get_client_height(page):
    try:
        return int(page.evaluate("document.scrollingElement.clientHeight"))
    except Exception:
        return 0


def force_scroll_all_containers(page, pixels):
    page.evaluate(
        """
        (pixels) => {
            window.scrollBy(0, pixels);
            document.scrollingElement.scrollTop += pixels;

            const nodes = Array.from(document.querySelectorAll('*'));
            for (const el of nodes) {
                try {
                    if (el.scrollHeight > el.clientHeight + 80) {
                        el.scrollTop += pixels;
                    }
                } catch (e) {}
            }
        }
        """,
        pixels,
    )


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    all_text = []
    all_matches = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        print(f"Opening {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)

        for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "Got it"]:
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if btn.count():
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

        try:
            set_scroll_top(page, 0)
            page.wait_for_timeout(1200)
        except Exception:
            pass

        scrape_snapshot(page, all_text, all_matches, "top")

        # Pass 1: small browser scrolls
        for i in range(120):
            scrape_snapshot(page, all_text, all_matches, f"small wheel {i + 1}/120")
            page.mouse.wheel(0, 400)
            page.wait_for_timeout(450)

        # Pass 2: keyboard PageDown
        try:
            page.mouse.click(800, 500)
            page.wait_for_timeout(500)
        except Exception:
            pass

        for i in range(60):
            scrape_snapshot(page, all_text, all_matches, f"pagedown {i + 1}/60")
            try:
                page.keyboard.press("PageDown")
            except Exception:
                pass
            page.wait_for_timeout(650)

        # Pass 3: direct scroll positions based on actual height
        for pass_no in range(1, 5):
            print(f"\nDirect scroll pass {pass_no}/4")

            scroll_height = get_scroll_height(page)
            client_height = get_client_height(page)
            max_y = max(scroll_height - client_height, 0)

            positions = list(range(0, max_y + 1, 160))
            if max_y not in positions:
                positions.append(max_y)

            for idx, y in enumerate(positions):
                set_scroll_top(page, y)
                force_scroll_all_containers(page, 160)
                page.wait_for_timeout(500)

                scrape_snapshot(
                    page,
                    all_text,
                    all_matches,
                    f"direct pass {pass_no} y={y} step {idx + 1}/{len(positions)}",
                )

        # Pass 4: End key can force lazy loading of the bottom content
        for i in range(8):
            scrape_snapshot(page, all_text, all_matches, f"end key {i + 1}/8")
            try:
                page.keyboard.press("End")
            except Exception:
                pass
            force_scroll_all_containers(page, 1200)
            page.wait_for_timeout(1200)

        DEBUG_PATH.write_text(
            "\n\n--- PAGE SNAPSHOT ---\n\n".join(all_text),
            encoding="utf-8",
        )

        matches = dedupe(all_matches)

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "888Sport",
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

        print(f"\nSaved {len(matches)} 888Sport World Cup moneyline matches to:")
        print(OUT_PATH)

        if matches:
            print("\nSample:")
            for m in matches[:140]:
                print(
                    f"- {m['date_label']} {m['time']} | {m['match']} | "
                    f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}"
                )
        else:
            print("\nNo 888Sport World Cup matches found.")
            print(f"Debug text saved to: {DEBUG_PATH}")

        print("\nDone. Press Enter to close browser...")
        input()

        browser.close()


if __name__ == "__main__":
    main()