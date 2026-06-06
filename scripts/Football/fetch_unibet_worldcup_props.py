#!/usr/bin/env python3
import json
import math
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "data" / "unibet_worldcup_props.json"
DEBUG_DIR = ROOT / "football" / "debug" / "unibet_worldcup_props"

LIST_URL = "https://www.unibet.ie/betting/odds/football/fifa-world-cup/group-matches"

MAX_MATCHES = 15

DECIMAL_RE = re.compile(r"^\d+(?:\.\d+)?$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")

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


def normalize(s):
    s = clean(s).lower()
    s = s.replace("&", "and")
    s = s.replace("?", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def slugify(s):
    return normalize(s).replace("_", "-")


def is_decimal_odds(s):
    s = clean(s)
    if not DECIMAL_RE.match(s):
        return False
    try:
        v = float(s)
        return 1.01 <= v <= 501
    except Exception:
        return False


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


def selection_obj(selection, odds, extra=None):
    obj = {
        "selection": clean(selection),
        "normalized_selection": normalize(selection),
        "odds": decimal_to_fractional(odds),
        "decimal_odds": float(odds),
    }
    if extra:
        obj.update(extra)
    return obj


def market_obj(name, selections):
    return {
        "market": name,
        "normalized_market": normalize(name),
        "selection_count": len(selections),
        "selections": selections,
    }


def accept_cookies(page):
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
                return
        except Exception:
            pass


def collect_match_links(page):
    print(f"Opening Unibet World Cup page: {LIST_URL}")

    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(9000)
    accept_cookies(page)

    for i in range(12):
        print(f"Scrolling list page {i + 1}/12...")
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(700)

    links = page.evaluate("""
        () => Array.from(document.querySelectorAll('a'))
          .map(a => ({ href: a.href, text: a.innerText }))
          .filter(x =>
            x.href &&
            x.href.includes('/betting/odds/football/fifa-world-cup/group-matches/') &&
            x.href.includes('-vs-')
          )
    """)

    out = []
    seen = set()

    for item in links:
        href = clean(item.get("href"))
        text = clean(item.get("text"))

        if not href or href in seen:
            continue

        seen.add(href)
        out.append({
            "url": href,
            "text": text,
        })

    print(f"Found {len(out)} possible Unibet match links")
    return out[:MAX_MATCHES]


def title_from_slug(url):
    part = url.rstrip("/").split("/")[-2] if re.match(r"^[a-f0-9]{16,}$", url.rstrip("/").split("/")[-1]) else url.rstrip("/").split("/")[-1]
    part = part.split("?")[0]
    part = re.sub(r"/.*", "", part)

    if "-vs-" not in part:
        return ""

    home, away = part.split("-vs-", 1)

    def nice(x):
        return " ".join(w.capitalize() for w in x.split("-"))

    return f"{nice(home)} v {nice(away)}"


def get_match_name_from_page(text, url, fallback_text=""):
    lines = [clean(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    for line in lines:
        if " - " in line and len(line) < 90:
            a, b = [clean(x) for x in line.split(" - ", 1)]
            if a and b:
                return f"{canonical_team(a)} v {canonical_team(b)}"

    if fallback_text and "\n" in fallback_text:
        parts = [clean(x) for x in fallback_text.splitlines() if clean(x)]
        teams = [p for p in parts if p in WORLD_CUP_TEAMS]
        if len(teams) >= 2:
            return f"{canonical_team(teams[0])} v {canonical_team(teams[1])}"

    return title_from_slug(url)


def split_teams(match_name):
    if re.search(r"\s+v\s+", match_name, re.I):
        home, away = re.split(r"\s+v\s+", match_name, maxsplit=1, flags=re.I)
        return canonical_team(home), canonical_team(away)
    return "", ""


def lines_from_text(text):
    lines = [clean(x) for x in text.splitlines()]
    return [x for x in lines if x]


def parse_main_markets(text, home, away):
    lines = lines_from_text(text)
    markets = []

    # Full Time Result
    try:
        idx = next(i for i, x in enumerate(lines) if x == "Full Time Result")
        block = lines[idx:idx + 20]
        odds = [x for x in block if is_decimal_odds(x)]
        if len(odds) >= 3:
            markets.append(market_obj("Match Betting", [
                selection_obj(home, odds[0], {"side": "home"}),
                selection_obj("Draw", odds[1], {"side": "draw"}),
                selection_obj(away, odds[2], {"side": "away"}),
            ]))
    except Exception:
        pass

    # Total Goals: row format line / over / under
    total_goal_selections = []
    try:
        idx = next(i for i, x in enumerate(lines) if x == "Total Goals")
        end = min(len(lines), idx + 80)
        for i in range(idx, end - 2):
            line = lines[i]
            if re.match(r"^\d+(?:\.5)$", line) and is_decimal_odds(lines[i + 1]) and is_decimal_odds(lines[i + 2]):
                total_goal_selections.append(selection_obj(f"Over {line}", lines[i + 1], {
                    "side": "over",
                    "line": line,
                }))
                total_goal_selections.append(selection_obj(f"Under {line}", lines[i + 2], {
                    "side": "under",
                    "line": line,
                }))
        if total_goal_selections:
            markets.append(market_obj("Total Goals Over / Under", total_goal_selections))
    except Exception:
        pass

    # Both Teams To Score
    try:
        idx = next(i for i, x in enumerate(lines) if x == "Both Teams to Score")
        block = lines[idx:idx + 20]
        yes_idx = next((i for i, x in enumerate(block) if x.lower() == "yes"), None)
        no_idx = next((i for i, x in enumerate(block) if x.lower() == "no"), None)
        selections = []
        if yes_idx is not None and yes_idx + 1 < len(block) and is_decimal_odds(block[yes_idx + 1]):
            selections.append(selection_obj("Both Teams To Score - Yes", block[yes_idx + 1], {"side": "yes"}))
        if no_idx is not None and no_idx + 1 < len(block) and is_decimal_odds(block[no_idx + 1]):
            selections.append(selection_obj("Both Teams To Score - No", block[no_idx + 1], {"side": "no"}))
        if selections:
            markets.append(market_obj("Both Teams To Score", selections))
    except Exception:
        pass

    # Double Chance: generic capture after header
    try:
        idx = next(i for i, x in enumerate(lines) if x == "Double Chance")
        block = lines[idx:idx + 30]
        odds = [x for x in block if is_decimal_odds(x)]
        labels = [f"{home} or Draw", f"{home} or {away}", f"Draw or {away}"]
        if len(odds) >= 3:
            markets.append(market_obj("Double Chance", [
                selection_obj(labels[0], odds[0]),
                selection_obj(labels[1], odds[1]),
                selection_obj(labels[2], odds[2]),
            ]))
    except Exception:
        pass

    return markets


def parse_player_markets(text):
    lines = lines_from_text(text)
    markets = []

    try:
        idx = next(i for i, x in enumerate(lines) if x == "Goalscorer")
        end = min(len(lines), idx + 120)
        block = lines[idx:end]

        selections_anytime = []
        selections_first = []

        # Expected pattern:
        # Player name
        # Anytime decimal
        # 1st decimal
        # Last decimal
        for i in range(len(block) - 3):
            player = block[i]
            if not player or is_decimal_odds(player):
                continue

            if is_decimal_odds(block[i + 1]) and is_decimal_odds(block[i + 2]):
                if len(player) > 45:
                    continue
                if player.lower() in {"goalscorer", "anytime", "1st", "last", "view more"}:
                    continue

                selections_anytime.append(selection_obj(f"{player} Anytime Goalscorer", block[i + 1], {
                    "player": player,
                    "prop_type": "anytime_goalscorer",
                }))
                selections_first.append(selection_obj(f"{player} First Goalscorer", block[i + 2], {
                    "player": player,
                    "prop_type": "first_goalscorer",
                }))

        if selections_anytime:
            markets.append(market_obj("Anytime Goalscorer", selections_anytime))
        if selections_first:
            markets.append(market_obj("First Goalscorer", selections_first))
    except Exception:
        pass

    return markets


def click_tab(page, name):
    try:
        loc = page.get_by_text(name, exact=True)
        if loc.count():
            print(f"Clicking tab: {name}")
            loc.first.click(timeout=4000)
            page.wait_for_timeout(1800)
            return True
    except Exception:
        pass
    return False


def scrape_match(page, url, fallback_text=""):
    print(f"\nOpening Unibet match page: {url}")

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6500)
    accept_cookies(page)

    text_parts = []

    match_text = page.locator("body").inner_text(timeout=30000)
    match_name = get_match_name_from_page(match_text, url, fallback_text=fallback_text)
    home, away = split_teams(match_name)

    click_tab(page, "Main Markets")
    page.wait_for_timeout(1500)
    main_text = page.locator("body").inner_text(timeout=30000)
    text_parts.append(main_text)
    markets = parse_main_markets(main_text, home, away) if home and away else []

    click_tab(page, "Players")
    page.wait_for_timeout(1500)

    # Click View more once if visible so we get more scorers.
    try:
        loc = page.get_by_text("View more", exact=True)
        if loc.count():
            loc.first.click(timeout=3000)
            page.wait_for_timeout(1200)
    except Exception:
        pass

    players_text = page.locator("body").inner_text(timeout=30000)
    text_parts.append(players_text)
    markets.extend(parse_player_markets(players_text))

    debug_name = slugify(match_name or url[-40:]) or "unknown-match"
    debug_file = DEBUG_DIR / f"{debug_name}.txt"
    debug_file.write_text("\n\n--- SNAPSHOT ---\n\n".join(text_parts), encoding="utf-8")

    return {
        "match": match_name,
        "home_team": home,
        "away_team": away,
        "source_url": url,
        "market_count": len(markets),
        "markets": markets,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    matches = []
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        links = collect_match_links(page)

        print()
        print("==============================")
        print(f"Limiting Unibet props scrape to first {len(links)} matches")
        print("==============================")

        for index, item in enumerate(links, start=1):
            url = item["url"]
            fallback_text = item.get("text") or ""

            print()
            print("==============================")
            print(f"Unibet props {index}/{len(links)}")
            print("==============================")

            try:
                match = scrape_match(page, url, fallback_text=fallback_text)
                matches.append(match)
                print(f"Saved match: {match['match']} | markets: {match['market_count']}")
            except Exception as e:
                print(f"ERROR scraping {url}: {e}")
                errors.append({
                    "url": url,
                    "error": str(e),
                })
                continue

        browser.close()

    good_matches = [m for m in matches if m.get("market_count", 0) > 0]

    output = {
        "sport": "football",
        "competition": "FIFA World Cup",
        "bookmaker": "Unibet",
        "market_type": "props",
        "source_url": LIST_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_count": len(matches),
        "matches_with_markets": len(good_matches),
        "error_count": len(errors),
        "errors": errors,
        "matches": matches,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("==============================")
    print("Unibet World Cup props complete")
    print("==============================")
    print(f"Match links scraped: {len(matches)}")
    print(f"Matches with markets: {len(good_matches)}")
    print(f"Errors: {len(errors)}")
    print(f"Wrote: {OUT_PATH}")


if __name__ == "__main__":
    main()
