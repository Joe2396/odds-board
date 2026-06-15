#!/usr/bin/env python3
"""
fetch_betvictor_worldcup_moneylines_SCROLL_CONTAINERS.py

BetVictor World Cup moneyline scraper — no clicking, no props.

This version scrolls the page AND any internal scrollable BetVictor containers.
The previous moneyline-only script stayed stuck on the same 38 visible matches,
which usually means the fixture list is inside its own scroll container.

Output:
  football/data/betvictor_worldcup_moneylines.json
Debug:
  football/debug/betvictor_worldcup_text_debug.txt
  football/debug/betvictor_worldcup_snapshots.txt
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
SCROLL_PASSES = 120

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
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "OK"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=2500)
                page.wait_for_timeout(900)
                return
        except Exception:
            pass


def parse_snapshot(text, fallback_date=""):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    matches = []
    current_date = fallback_date

    i = 0
    while i < len(lines):
        line = lines[i]

        if is_date(line):
            current_date = line
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

    return matches, current_date


def get_scrollables(page):
    try:
        return page.evaluate(
            """() => {
                const els = Array.from(document.querySelectorAll('body *'));
                const out = [];
                for (let i = 0; i < els.length; i++) {
                    const el = els[i];
                    const st = getComputedStyle(el);
                    const canScroll = (el.scrollHeight > el.clientHeight + 80) &&
                                      ['auto','scroll','overlay'].includes(st.overflowY);
                    if (canScroll) {
                        const r = el.getBoundingClientRect();
                        out.push({
                            idx: i,
                            tag: el.tagName,
                            cls: String(el.className || '').slice(0, 120),
                            h: el.clientHeight,
                            sh: el.scrollHeight,
                            y: r.y,
                            text: (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120)
                        });
                    }
                }
                out.sort((a,b) => (b.sh-b.h) - (a.sh-a.h));
                return out.slice(0, 12);
            }"""
        )
    except Exception:
        return []


def scroll_all_containers(page):
    """Scroll window and every scrollable container. No clicking."""
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


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    found = {}
    snapshots_debug = []
    last_date = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        print(f"Opening {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)
        accept_cookies(page)

        page.keyboard.press("Home")
        page.wait_for_timeout(1000)

        scrollables = get_scrollables(page)
        print(f"Detected {len(scrollables)} scrollable containers")
        for s in scrollables[:8]:
            print(f"  container idx={s['idx']} tag={s['tag']} h={s['h']} sh={s['sh']} cls={s['cls']} text={s['text']}")

        stable = 0
        last_total = 0

        for n in range(SCROLL_PASSES):
            text = page.locator("body").inner_text(timeout=25000)
            snapshot_matches, last_date = parse_snapshot(text, last_date)

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

            moved = scroll_all_containers(page)
            page.wait_for_timeout(600)

            print(f"Scroll {n+1:03d}/{SCROLL_PASSES}: visible {len(snapshot_matches)} | added {added} | total {len(found)} | moved_containers {moved}")

            snapshots_debug.append(
                f"\n\n===== SNAPSHOT {n+1:03d} | visible {len(snapshot_matches)} | total {len(found)} | moved {moved} =====\n{text}"
            )

            if len(found) == last_total:
                stable += 1
            else:
                stable = 0
            last_total = len(found)

            if len(found) >= 60 and n >= 25:
                break

            if n >= 35 and stable >= 18 and moved == 0:
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
