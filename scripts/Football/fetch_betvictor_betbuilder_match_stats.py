#!/usr/bin/env python3
"""
fetch_betvictor_betbuilder_match_stats_TEST3_SHOTS_ONLY.py

Separate BetVictor Bet Builder Match Stats scraper.

TEST MODE:
  MAX_MATCHES = 3

Purpose:
  Get only the useful Bet Builder Match Stats markets, then merge them into
  betvictor_worldcup_props.json once confirmed.

Keeps:
  - Match Shots On Target
  - Match Shots
  - Team Shots On Target
  - Team Shots

Ignores:
  - Tackles
  - Offsides

Input:
  football/data/betvictor_worldcup_props.json
    Uses exact event URLs already found by the main BetVictor props scraper.

Output:
  football/data/betvictor_worldcup_betbuilder_stats.json

Debug:
  football/debug/betvictor_betbuilder_stats/<match>/ALL.txt
  football/debug/betvictor_betbuilder_stats/<match>/HITS.txt
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_worldcup_betbuilder_stats.json"
DEBUG_ROOT = ROOT / "football" / "debug" / "betvictor_betbuilder_stats"

MAX_MATCHES = 15
HEADLESS = False
BETBUILDER_GROUP = "12536"

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN|Evens)$", re.I)
PLUS_RE = re.compile(r"^\d+\+$")

TEAM_ALIASES = {
    "United States": "USA",
    "USA": "USA",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Türkiye": "Türkiye",
    "Czech Republic": "Czechia",
    "Bosnia and Herzegovina": "Bosnia",
    "Bosnia & Herzegovina": "Bosnia",
    "Curaçao": "Curacao",
}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def canonical_team(s):
    s = clean(s)
    return TEAM_ALIASES.get(s, s)


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")


def is_odds(s):
    return bool(ODDS_RE.match(clean(s)))


def is_plus(s):
    return bool(PLUS_RE.match(clean(s)))


def base_event_url(url):
    return str(url or "").split("?", 1)[0]


def group_url(event_url):
    return f"{base_event_url(event_url)}?market_group={BETBUILDER_GROUP}"


def lines_from_text(text):
    return [clean(x) for x in text.splitlines() if clean(x)]


def selection(name, odds, **extra):
    out = {
        "selection": clean(name),
        "normalized_selection": normalize(name),
        "odds": clean(odds).upper(),
    }
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def market(name, selections):
    seen, out = set(), []
    for s in selections:
        key = (
            s.get("selection"),
            s.get("odds"),
            s.get("side"),
            s.get("line"),
            s.get("team"),
            s.get("stat"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(s)

    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(out),
        "selections": out,
    }


def load_fixtures():
    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    fixtures = []

    for m in data.get("matches", []):
        url = m.get("source_url", "")
        if "/events/" not in url:
            continue

        home = canonical_team(m.get("home_team", ""))
        away = canonical_team(m.get("away_team", ""))
        match = clean(m.get("match") or f"{home} v {away}")

        if not home or not away:
            if " v " in match:
                home, away = [canonical_team(x) for x in match.split(" v ", 1)]

        if not home or not away:
            continue

        fixtures.append({
            "match": match,
            "home": home,
            "away": away,
            "source_url": base_event_url(url),
        })

    seen, out = set(), []
    for f in fixtures:
        key = (normalize(f["match"]), f["source_url"])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)

    return out[:MAX_MATCHES]


def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "OK", "I have read the above", "Dismiss"]:
        try:
            loc = page.get_by_role("button", name=re.compile(label, re.I))
            if loc.count():
                loc.first.click(timeout=1200)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass


def scroll_all(page, passes=1):
    for _ in range(passes):
        try:
            page.evaluate(
                """() => {
                    window.scrollBy(0, 600);
                    const els = Array.from(document.querySelectorAll('body *'));
                    for (const el of els) {
                        const st = getComputedStyle(el);
                        if (el.scrollHeight > el.clientHeight + 80 &&
                            ['auto','scroll','overlay'].includes(st.overflowY)) {
                            el.scrollTop = Math.min(el.scrollTop + 600, el.scrollHeight);
                        }
                    }
                }"""
            )
        except Exception:
            page.mouse.wheel(0, 600)
        page.wait_for_timeout(250)


def click_show_more(page):
    for label in ["Show More", "Show more", "View More", "View more", "Show All", "Show all"]:
        try:
            loc = page.get_by_text(label, exact=True)
            for i in range(min(loc.count(), 8)):
                try:
                    loc.nth(i).click(timeout=800)
                    page.wait_for_timeout(300)
                except Exception:
                    pass
        except Exception:
            pass


def body_text(page):
    try:
        return page.locator("body").inner_text(timeout=20000)
    except Exception:
        return ""


def click_match_stats_tab(page):
    def active():
        txt = body_text(page)
        return "To Have the Most" in txt or "Match Shots on Target" in txt or "Match Shots" in txt

    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    page.wait_for_timeout(700)

    try:
        loc = page.get_by_text("Match Stats", exact=True)
        count = min(loc.count(), 12)
        print(f"      Match Stats labels found: {count}")
        for i in range(count):
            try:
                item = loc.nth(i)
                item.scroll_into_view_if_needed(timeout=2000)
                page.wait_for_timeout(250)
                box = item.bounding_box()
                if not box:
                    continue
                if box["width"] <= 5 or box["height"] <= 5 or box["width"] > 260:
                    continue
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.wait_for_timeout(1500)
                if active():
                    return True
            except Exception:
                pass
    except Exception:
        pass

    return active()


def click_row_chevron(page, label):
    """Open a BetVictor accordion row by exact label, clicking far-right chevron area."""
    try:
        loc = page.get_by_text(label, exact=True)
        count = min(loc.count(), 8)

        for i in range(count):
            try:
                item = loc.nth(i)
                item.scroll_into_view_if_needed(timeout=2500)
                page.wait_for_timeout(250)
                box = item.bounding_box()
                if not box:
                    continue
                if box["width"] <= 5 or box["height"] <= 5 or box["width"] > 360:
                    continue

                x = min(max(box["x"] + 700, box["x"] + 80), 1215)
                y = box["y"] + box["height"] / 2
                page.mouse.click(x, y)
                page.wait_for_timeout(900)
                return True
            except Exception:
                pass
    except Exception:
        pass

    return False


def capture_match_stats_page(page, fixture, debug_dir):
    chunks = []

    def capture(label):
        click_show_more(page)
        txt = body_text(page)
        chunks.append(f"=== {label} ===\n{txt}")

    ok = click_match_stats_tab(page)
    print(f"      Match Stats clicked: {ok}")
    capture(f"MATCH_STATS_TAB clicked={ok}")

    home = fixture["home"]
    away = fixture["away"]

    # Only desired rows. No tackles, no offsides.
    rows = [
        "Match Shots on Target",
        "Match Shots",
        f"{home} Shots on Target",
        f"{home} Shots",
        f"{away} Shots on Target",
        f"{away} Shots",
    ]

    for row in rows:
        clicked = click_row_chevron(page, row)
        capture(f"ROW {row} clicked={clicked}")

    all_text = "\n\n".join(chunks)
    (debug_dir / "ALL.txt").write_text(all_text, encoding="utf-8")
    write_hits(all_text, debug_dir)
    return all_text


def write_hits(text, debug_dir):
    words = [
        "Match Shots", "Shots on Target", "Shots", "Over", "Under",
    ]
    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if any(w.lower() in line.lower() for w in words):
            hits.append(f"{i:04d}: {line}")
            for j in range(i + 1, min(i + 16, len(lines))):
                if lines[j].strip():
                    hits.append(f"      {j:04d}: {lines[j]}")
            hits.append("")
    (debug_dir / "HITS.txt").write_text("\n".join(hits), encoding="utf-8")


def split_title_block(lines, title, all_titles):
    """Return lines after an exact title until next exact title/footer.

    BetVictor layout for these markets is:
      Match Shots
      19-25
      27-33
      19+
      21+
      23+
      25+
      1/10
      19/100
      17/50
      11/20

    We ignore range labels and pair plus thresholds with the following odds.
    """
    title_norm = normalize(title)
    idxs = [i for i, x in enumerate(lines) if normalize(x) == title_norm]
    if not idxs:
        return []

    # Pick the instance with most odds before the next title.
    best, best_score = [], -1
    for idx in idxs:
        block = []
        for j in range(idx + 1, min(idx + 80, len(lines))):
            tok = clean(lines[j])
            if not tok:
                continue
            if normalize(tok) != title_norm and normalize(tok) in all_titles:
                break
            if tok in {"Add to Betslip", "Save to Betslip and build a Multiple"}:
                break
            block.append(tok)

        score = sum(1 for x in block if is_odds(x))
        if score > best_score:
            best = block
            best_score = score

    return best


def parse_threshold_market(lines, title, market_name, stat, team=None):
    all_titles = {
        normalize("To Have the Most"),
        normalize("Match Shots on Target"),
        normalize("Match Shots"),
        normalize("France Shots on Target"),
        normalize("France Shots"),
        normalize("Senegal Shots on Target"),
        normalize("Senegal Shots"),
        # dynamic team titles are added below before split
    }

    # Add dynamic team titles by scanning lines ending with these words.
    for x in lines:
        lx = clean(x).lower()
        if lx.endswith("shots on target") or lx.endswith("shots"):
            all_titles.add(normalize(x))

    block = split_title_block(lines, title, all_titles)
    if not block:
        return market(market_name, [])

    thresholds = [x for x in block if is_plus(x)]
    odds = [x for x in block if is_odds(x)]

    # BetVictor usually has ranges first, then plus thresholds, then odds.
    # Example: 6-9, 10-13, 6+, 7+, 8+, 9+, 2/21, 1/5, 10/27, 5/8
    n = min(len(thresholds), len(odds))
    out = []
    for th, odd in zip(thresholds[:n], odds[:n]):
        out.append(selection(
            f"{market_name} {th}",
            odd,
            team=team,
            stat=stat,
            threshold=th,
        ))

    return market(market_name, out)


def parse_markets(text, fixture):
    lines = lines_from_text(text)
    home, away = fixture["home"], fixture["away"]

    candidates = [
        parse_threshold_market(lines, "Match Shots on Target", "Match Shots On Target", "shots_on_target"),
        parse_threshold_market(lines, "Match Shots", "Match Shots", "shots"),
        parse_threshold_market(lines, f"{home} Shots on Target", f"{home} Shots On Target", "shots_on_target", team=home),
        parse_threshold_market(lines, f"{home} Shots", f"{home} Shots", "shots", team=home),
        parse_threshold_market(lines, f"{away} Shots on Target", f"{away} Shots On Target", "shots_on_target", team=away),
        parse_threshold_market(lines, f"{away} Shots", f"{away} Shots", "shots", team=away),
    ]

    return [m for m in candidates if m["selection_count"] > 0]


def scrape_fixture(browser, fixture):
    debug_dir = DEBUG_ROOT / slugify(fixture["match"])
    debug_dir.mkdir(parents=True, exist_ok=True)

    page = browser.new_page(viewport={"width": 1700, "height": 1000})
    url = group_url(fixture["source_url"])

    try:
        print(f"\n{fixture['match']}")
        print(f"  {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5500)
        accept_cookies(page)

        body = body_text(page)
        if "There are currently no markets available" in body:
            print("  Bet Builder unavailable for this fixture")
            (debug_dir / "ALL.txt").write_text(body, encoding="utf-8")
            return {
                "match": fixture["match"],
                "home_team": fixture["home"],
                "away_team": fixture["away"],
                "source_url": fixture["source_url"],
                "market_count": 0,
                "markets": [],
                "note": "bet_builder_unavailable",
            }

        text = capture_match_stats_page(page, fixture, debug_dir)
        markets = parse_markets(text, fixture)

        print(f"  markets: {len(markets)}")
        for m in markets:
            print(f"    {m['market']:<35} {m['selection_count']} selections")

        return {
            "match": fixture["match"],
            "home_team": fixture["home"],
            "away_team": fixture["away"],
            "source_url": fixture["source_url"],
            "market_count": len(markets),
            "markets": markets,
        }

    finally:
        try:
            page.close()
        except Exception:
            pass


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_ROOT.mkdir(parents=True, exist_ok=True)

    fixtures = load_fixtures()
    print(f"Loaded {len(fixtures)} BetVictor event URLs from main props JSON")
    print("TEST MODE: MAX_MATCHES = 3")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        for i, fixture in enumerate(fixtures, 1):
            print("\n" + "=" * 70)
            print(f"[{i}/{len(fixtures)}]")
            try:
                results.append(scrape_fixture(browser, fixture))
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}")
                results.append({
                    "match": fixture["match"],
                    "home_team": fixture["home"],
                    "away_team": fixture["away"],
                    "source_url": fixture["source_url"],
                    "market_count": 0,
                    "markets": [],
                    "error": str(e),
                })

        browser.close()

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "BetVictor",
        "market_type": "bet_builder_match_stats",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(results),
        "matches_with_markets": len([r for r in results if r.get("market_count", 0) > 0]),
        "matches": results,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nSaved:")
    print(OUT_PATH)
    print(f"Matches with markets: {output['matches_with_markets']}/{output['match_count']}")


if __name__ == "__main__":
    main()
