#!/usr/bin/env python3
"""
fetch_betvictor_worldcup_moneylines_DATE_ACCORDIONS.py

BetVictor World Cup moneyline scraper — MONEYLINES ONLY.

This fixes the 37/38 match cap by opening collapsed date accordions
like Thu 25 June 2026, Fri 26 June 2026, Sat 27 June 2026, etc.

No broad clicking.
No props.
No help-centre/event-url discovery.
Only clicks text that exactly matches a date header.

Output:
  football/data/betvictor_worldcup_moneylines.json
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "betvictor_worldcup_moneylines.json"
DEBUG_PATH = ROOT / "football" / "debug" / "betvictor_worldcup_text_debug.txt"
SNAP_DEBUG_PATH = ROOT / "football" / "debug" / "betvictor_worldcup_snapshots.txt"

URL = "https://www.betvictor.com/en-ie/sports/240/sections/custom-list/7199/group/world-cup-matches/item/matches"

HEADLESS = False
SCROLL_PASSES = 45

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DATE_RE = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+\w+\s+\d{4}$",
    re.I,
)

WORLD_CUP_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic", "Czechia",
    "Canada", "Bosnia and Herzegovina", "Bosnia & Herzegovina", "Bosnia",
    "USA", "United States", "Paraguay", "Qatar", "Switzerland", "Brazil", "Morocco",
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
    "Bosnia and Herzegovina": "Bosnia",
    "Bosnia & Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
    "United States": "USA",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    s = clean(s)
    return TEAM_ALIASES.get(s, s)


def norm_team(s):
    s = canonical_team(s).lower().replace("&", "and")
    s = s.replace("türkiye", "turkiye")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def fixture_key(home, away):
    return "__".join(sorted([norm_team(home), norm_team(away)]))


def is_date(s):
    return bool(DATE_RE.match(clean(s)))


def is_time(s):
    return bool(TIME_RE.match(clean(s)))


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_team_line(s):
    return clean(s) in WORLD_CUP_TEAMS


def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "OK", "I have read the above"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=2500)
                page.wait_for_timeout(700)
                return
        except Exception:
            pass


def parse_snapshot(text, fallback_date=""):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    matches = []
    dates_seen = []
    current_date = fallback_date

    i = 0
    while i < len(lines):
        line = lines[i]

        if is_date(line):
            current_date = line
            if line not in dates_seen:
                dates_seen.append(line)
            i += 1
            continue

        if (
            i + 5 < len(lines)
            and is_team_line(lines[i])
            and is_team_line(lines[i + 1])
            and is_time(lines[i + 2])
        ):
            home = canonical_team(lines[i])
            away = canonical_team(lines[i + 1])
            time_label = lines[i + 2]

            odds = []
            for j in range(i + 3, min(i + 24, len(lines))):
                if is_odds(lines[j]):
                    odds.append(lines[j].upper())
                    if len(odds) == 3:
                        break

            if len(odds) == 3:
                matches.append({
                    "competition": "FIFA World Cup",
                    "bookmaker": "BetVictor",
                    "date_label": current_date,
                    "time": time_label,
                    "match": f"{home} v {away}",
                    "home_team": home,
                    "away_team": away,
                    "market": "Match Odds",
                    "odds": {
                        "home": odds[0],
                        "draw": odds[1],
                        "away": odds[2],
                    },
                    "source_url": URL,
                    "url": URL,
                })
                i += 8
                continue

        i += 1

    return matches, current_date, dates_seen


def add_matches(found, snapshot_matches):
    added = 0
    for m in snapshot_matches:
        loose = fixture_key(m["home_team"], m["away_team"])
        existing = [
            k for k, v in found.items()
            if fixture_key(v["home_team"], v["away_team"]) == loose and v.get("time") == m.get("time")
        ]
        if existing:
            old_key = existing[0]
            if m.get("date_label") and not found[old_key].get("date_label"):
                found[old_key]["date_label"] = m["date_label"]
            continue

        key = (m.get("date_label") or "", m.get("time") or "", loose)
        found[key] = m
        added += 1
    return added


def scroll_all_containers(page):
    return page.evaluate(
        """() => {
            window.scrollBy(0, 900);
            const els = Array.from(document.querySelectorAll('body *'));
            let moved = 0;
            for (const el of els) {
                const st = getComputedStyle(el);
                if (el.scrollHeight > el.clientHeight + 80 &&
                    ['auto','scroll','overlay'].includes(st.overflowY)) {
                    const before = el.scrollTop;
                    el.scrollTop = Math.min(el.scrollTop + 850, el.scrollHeight);
                    if (el.scrollTop !== before) moved++;
                }
            }
            return moved;
        }"""
    )


def click_date_header(page, date_label):
    """Safely click only an exact date header, never generic page containers."""
    try:
        loc = page.get_by_text(date_label, exact=True).first
        if loc and loc.count():
            loc.scroll_into_view_if_needed(timeout=2500)
            page.wait_for_timeout(250)
            loc.click(timeout=2500)
            page.wait_for_timeout(1300)
            return True
    except Exception:
        pass

    # JS fallback: exact text only, click nearest clickable/date row ancestor.
    try:
        return bool(page.evaluate(
            """(dateLabel) => {
                const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
                const nodes = Array.from(document.querySelectorAll('body *'))
                    .filter(el => clean(el.innerText || el.textContent || '') === dateLabel);

                for (const node of nodes) {
                    let el = node;
                    for (let i = 0; i < 6 && el; i++, el = el.parentElement) {
                        const role = (el.getAttribute('role') || '').toLowerCase();
                        const tag = (el.tagName || '').toLowerCase();
                        const txt = clean(el.innerText || el.textContent || '');
                        if (txt.length > 180) continue;

                        if (tag === 'button' || role === 'button' || el.onclick || i >= 1) {
                            el.scrollIntoView({block: 'center'});
                            el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                            el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                            el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                            el.click();
                            return true;
                        }
                    }
                }
                return false;
            }""",
            date_label,
        ))
    except Exception:
        return False


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    found = {}
    snapshots_debug = []
    last_date = ""
    discovered_dates = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        print(f"Opening {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)
        accept_cookies(page)

        page.keyboard.press("Home")
        page.wait_for_timeout(1000)

        # Pass 1: accumulate all currently expanded/visible dates.
        stable = 0
        last_total = 0

        for n in range(SCROLL_PASSES):
            text = page.locator("body").inner_text(timeout=25000)
            snapshot_matches, last_date, dates = parse_snapshot(text, last_date)

            for d in dates:
                if d not in discovered_dates:
                    discovered_dates.append(d)

            added = add_matches(found, snapshot_matches)
            moved = scroll_all_containers(page)
            page.wait_for_timeout(500)

            print(f"Scroll {n+1:02d}/{SCROLL_PASSES}: visible {len(snapshot_matches)} | added {added} | total {len(found)} | dates {len(discovered_dates)} | moved {moved}")

            snapshots_debug.append(
                f"\n\n===== SCROLL SNAPSHOT {n+1:02d} | visible {len(snapshot_matches)} | total {len(found)} =====\n{text}"
            )

            if len(found) == last_total:
                stable += 1
            else:
                stable = 0
            last_total = len(found)

            # Enough scrolling to reveal collapsed date headers at bottom.
            if n >= 28 and stable >= 10:
                break

        print(f"\nDate headers discovered: {discovered_dates}")

        # Pass 2: click every date accordion once and parse immediately after.
        # Existing expanded dates may collapse, but we already captured them.
        for idx, date_label in enumerate(discovered_dates, 1):
            print(f"Opening date {idx}/{len(discovered_dates)}: {date_label}", end=" ... ", flush=True)

            clicked = click_date_header(page, date_label)
            if not clicked:
                print("not clicked")
                continue

            page.wait_for_timeout(1000)

            # Parse after click.
            text = page.locator("body").inner_text(timeout=25000)
            snapshot_matches, last_date, dates = parse_snapshot(text, date_label)
            added = add_matches(found, snapshot_matches)
            print(f"visible {len(snapshot_matches)} | added {added} | total {len(found)}")

            snapshots_debug.append(
                f"\n\n===== DATE CLICK {date_label} | visible {len(snapshot_matches)} | total {len(found)} =====\n{text}"
            )

            # Small scroll within newly opened date section.
            for _ in range(4):
                scroll_all_containers(page)
                page.wait_for_timeout(300)
                text2 = page.locator("body").inner_text(timeout=25000)
                snapshot_matches2, last_date, _ = parse_snapshot(text2, date_label)
                add_matches(found, snapshot_matches2)

            if len(found) >= 60:
                break

        final_text = page.locator("body").inner_text(timeout=25000)
        DEBUG_PATH.write_text(final_text, encoding="utf-8")
        SNAP_DEBUG_PATH.write_text("\n".join(snapshots_debug), encoding="utf-8")

        browser.close()

    matches = sorted(
        found.values(),
        key=lambda m: (m.get("date_label", ""), m.get("time", ""), m.get("match", ""))
    )

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BetVictor",
        "market": "Match Odds",
        "source_url": URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(matches),
        "matches": matches,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved {len(matches)} BetVictor World Cup moneyline matches to:")
    print(OUT_PATH)
    print(f"Debug text: {DEBUG_PATH}")
    print(f"Snapshot debug: {SNAP_DEBUG_PATH}")

    if matches:
        print("\nSample:")
        for m in matches[:100]:
            print(
                f"- {m['date_label']} {m['time']} | {m['match']} | "
                f"H {m['odds']['home']} D {m['odds']['draw']} A {m['odds']['away']}"
            )


if __name__ == "__main__":
    main()
