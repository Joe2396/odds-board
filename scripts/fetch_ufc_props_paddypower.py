from playwright.sync_api import sync_playwright
import time
import json
import re
import os
from pathlib import Path
from datetime import datetime, timezone

print("RUNNING SAFE MULTI-FIGHT PADDYPOWER SCRIPT")

ROOT = Path(__file__).resolve().parents[1]
URLS_PATH = ROOT / "ufc" / "data" / "paddypower_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "props.json"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def is_odds(x):
    x = str(x).strip().upper()

    if not x:
        return False

    if x == "EVS":
        return True

    if re.match(r"^\d+/\d+$", x):
        return True

    if re.match(r"^\d+(\.\d+)?$", x):
        try:
            return float(x) > 1
        except Exception:
            return False

    return False


def empty_output():
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "paddypower",
        "bookmaker": "PaddyPower",
        "markets_scraped": [
            "fight_betting",
            "method_of_victory",
            "total_rounds",
            "go_the_distance"
        ],
        "fights": []
    }


def load_existing_output():
    if OUT_PATH.exists():
        try:
            return json.load(open(OUT_PATH, encoding="utf-8"))
        except Exception:
            pass

    return empty_output()


def save_output(output):
    output["updated_at"] = datetime.now(timezone.utc).isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved progress to {OUT_PATH}")


def close_cookie_popup(page):
    try:
        page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
        print("Accepted cookies")
        time.sleep(1)
    except Exception:
        print("No cookie popup found")


def click_market(page, market_name):
    selectors = [
        f"span.accordion__title:text-is('{market_name}')",
        f"text='{market_name}'",
        f"span:text('{market_name}')",
        f"div:text('{market_name}')",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.scroll_into_view_if_needed(timeout=5000)
            time.sleep(0.75)
            locator.click(force=True, timeout=8000)

            print(f"Opened market: {market_name}")
            time.sleep(1.5)
            return True
        except Exception:
            continue

    print(f"Could not open market: {market_name}")
    return False


def get_market_snippet(page, market_name, stop_words=None):
    if stop_words is None:
        stop_words = []

    text = page.locator("body").inner_text()
    start = text.find(market_name)

    if start == -1:
        return ""

    end = start + 3000

    for word in stop_words:
        idx = text.find(word, start + len(market_name))
        if idx != -1:
            end = min(end, idx)

    return text[start:end].strip()


def clean_lines(snippet):
    junk = {
        "Popular",
        "Fight Result",
        "Match Betting",
        "Cash Out",
        "All Markets",
        "Method of Victory",
        "Total Rounds",
        "Go The Distance?",
        "Will the fight go the distance?",
        "Round & Minute",
        "UFC Matches",
        "Bet Builder",
        "Show More",
    }

    return [
        line.strip()
        for line in snippet.splitlines()
        if line.strip() and line.strip() not in junk
    ]


def get_fighters_from_fight_name(fight_name):
    fight_name = str(fight_name or "").strip()

    if " vs " in fight_name.lower():
        fighters = re.split(r"\s+vs\s+", fight_name, flags=re.I)
    elif " v " in fight_name.lower():
        fighters = re.split(r"\s+v\s+", fight_name, flags=re.I)
    else:
        fighters = []

    return [f.strip() for f in fighters if f.strip()]


def normalize_text(text):
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_method_of_victory(snippet):
    lines = clean_lines(snippet)
    results = []

    for i in range(len(lines) - 1):
        selection = lines[i]
        odds = lines[i + 1]

        if is_odds(odds) and (
            " by " in selection
            or "Draw" in selection
            or "KO/TKO" in selection
            or "Submission" in selection
            or "Dec" in selection
            or "Points" in selection
        ):
            results.append({
                "selection": selection,
                "odds": odds
            })

    return results


def parse_simple_pairs(snippet):
    lines = clean_lines(snippet)
    results = []

    for i in range(len(lines) - 1):
        selection = lines[i]
        odds = lines[i + 1]

        if not is_odds(selection) and is_odds(odds):
            results.append({
                "selection": selection,
                "odds": odds
            })

    return results


def extract_decimal_sentence_odds(snippet, fight_name):
    fighters = get_fighters_from_fight_name(fight_name)
    results = []

    if len(fighters) < 2:
        return []

    for fighter in fighters:
        patterns = [
            re.compile(
                re.escape(fighter) + r".{0,180}?odds of\s+(\d+(?:\.\d+)?)",
                re.I | re.S,
            ),
            re.compile(
                r"If you bet\s+£?\d+(?:\.\d+)?\s+on\s+"
                + re.escape(fighter)
                + r".{0,260}?current odds of\s+(\d+(?:\.\d+)?)",
                re.I | re.S,
            ),
        ]

        for pattern in patterns:
            match = pattern.search(snippet)
            if match:
                results.append({
                    "selection": fighter,
                    "odds": match.group(1)
                })
                break

    return results[:2]


def parse_fight_result(snippet, fight_name):
    lines = clean_lines(snippet)
    fighters = get_fighters_from_fight_name(fight_name)

    if len(fighters) < 2:
        return parse_simple_pairs(snippet)[:2]

    sentence_odds = extract_decimal_sentence_odds(snippet, fight_name)
    if len(sentence_odds) == 2:
        return sentence_odds

    fighter_1 = fighters[0]
    fighter_2 = fighters[1]

    fighter_1_norm = normalize_text(fighter_1)
    fighter_2_norm = normalize_text(fighter_2)

    odds_lines = [line for line in lines if is_odds(line)]

    if len(odds_lines) >= 2:
        combined = normalize_text(" ".join(lines))

        if fighter_1_norm in combined and fighter_2_norm in combined:
            return [
                {"selection": fighter_1, "odds": odds_lines[0]},
                {"selection": fighter_2, "odds": odds_lines[1]},
            ]

    results = []

    for fighter in fighters:
        found = None
        fighter_norm = normalize_text(fighter)

        for i, line in enumerate(lines):
            line_norm = normalize_text(line)

            if line_norm == fighter_norm or fighter_norm in line_norm or line_norm in fighter_norm:
                for j in range(i + 1, min(i + 8, len(lines))):
                    if is_odds(lines[j]):
                        found = {
                            "selection": fighter,
                            "odds": lines[j]
                        }
                        break

            if found:
                break

        if found:
            results.append(found)

    if len(results) == 2:
        return results

    fallback = []

    for i in range(len(lines) - 1):
        selection = lines[i]
        odds = lines[i + 1]

        if not is_odds(odds):
            continue

        selection_norm = normalize_text(selection)

        matched = any(
            normalize_text(fighter) in selection_norm
            or selection_norm in normalize_text(fighter)
            for fighter in fighters
        )

        if matched:
            fallback.append({
                "selection": selection,
                "odds": odds
            })

    seen = set()
    unique = []

    for item in results + fallback:
        key = item["selection"].lower()

        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique[:2]


def extract_visible_moneyline_buttons(page, fight_name):
    fighters = get_fighters_from_fight_name(fight_name)

    if len(fighters) < 2:
        return []

    try:
        items = page.evaluate(
            """
            () => {
              const out = [];

              function visible(el) {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return (
                  rect.width > 0 &&
                  rect.height > 0 &&
                  style.visibility !== "hidden" &&
                  style.display !== "none"
                );
              }

              document.querySelectorAll("body *").forEach((el) => {
                if (!visible(el)) return;

                const text = (el.innerText || el.textContent || "").trim();
                if (!text) return;
                if (text.length > 120) return;

                const rect = el.getBoundingClientRect();

                out.push({
                  text,
                  x: rect.x,
                  y: rect.y,
                  w: rect.width,
                  h: rect.height
                });
              });

              return out;
            }
            """
        )
    except Exception:
        return []

    fighter_boxes = []
    odds_boxes = []

    for item in items:
        text = str(item.get("text") or "").strip()
        norm = normalize_text(text)

        if is_odds(text):
            odds_boxes.append(item)
            continue

        for fighter in fighters:
            fighter_norm = normalize_text(fighter)

            if norm == fighter_norm or fighter_norm in norm or norm in fighter_norm:
                fighter_boxes.append({
                    **item,
                    "fighter": fighter,
                })

    results = []

    for fighter in fighters:
        candidates = [
            b for b in fighter_boxes
            if normalize_text(b.get("fighter")) == normalize_text(fighter)
        ]

        if not candidates:
            continue

        fighter_box = sorted(candidates, key=lambda b: b.get("y", 999999))[0]
        fx = fighter_box.get("x", 0) + fighter_box.get("w", 0) / 2
        fy = fighter_box.get("y", 0)

        possible_odds = []

        for odds in odds_boxes:
            ox = odds.get("x", 0) + odds.get("w", 0) / 2
            oy = odds.get("y", 0)

            if oy < fy:
                continue

            if oy - fy > 180:
                continue

            score = abs(ox - fx) + ((oy - fy) * 0.25)

            possible_odds.append((score, odds))

        if possible_odds:
            possible_odds.sort(key=lambda x: x[0])
            best_odds = possible_odds[0][1].get("text")

            results.append({
                "selection": fighter,
                "odds": best_odds,
            })

    seen = set()
    unique = []

    for row in results:
        key = row["selection"].lower()

        if key not in seen and is_odds(row.get("odds")):
            seen.add(key)
            unique.append(row)

    return unique[:2]


def scrape_fight(page, fight):
    fight_name = fight["fight"]
    fight_url = fight["url"]

    print("\n==============================")
    print(f"Scraping: {fight_name}")
    print("==============================")

    page.goto(fight_url, timeout=60000)
    time.sleep(7)

    close_cookie_popup(page)

    moneyline_markets = [
        "Fight Result",
        "Match Betting",
    ]

    opened_moneyline_market = None

    for market_name in moneyline_markets:
        opened = click_market(page, market_name)

        if opened:
            opened_moneyline_market = market_name
            break

    time.sleep(1)

    fight_result_raw = ""

    if opened_moneyline_market:
        fight_result_raw = get_market_snippet(
            page,
            opened_moneyline_market,
            stop_words=[
                "Method of Victory",
                "Total Rounds",
                "Go The Distance?",
                "Will the fight go the distance?",
                "Round Betting",
                "Round & Minute",
                "Method & Round Combo",
                "Double Chance",
                "How fight will End",
            ],
        )

    fight_betting = parse_fight_result(
        fight_result_raw,
        fight_name
    )

    if len(fight_betting) < 2:
        dom_moneyline = extract_visible_moneyline_buttons(page, fight_name)

        if len(dom_moneyline) == 2:
            fight_betting = dom_moneyline

    for market in [
        "Method of Victory",
        "Total Rounds",
        "Go The Distance?",
        "Will the fight go the distance?",
    ]:
        click_market(page, market)

    time.sleep(2)

    method_raw = get_market_snippet(
        page,
        "Method of Victory",
        stop_words=[
            "Round Betting",
            "Total Rounds",
            "Go The Distance?",
            "Will the fight go the distance?",
        ],
    )

    total_rounds_raw = get_market_snippet(
        page,
        "Total Rounds",
        stop_words=[
            "Double Chance",
            "Go The Distance?",
            "Will the fight go the distance?",
            "How fight will End",
        ],
    )

    go_distance_raw = (
        get_market_snippet(
            page,
            "Go The Distance?",
            stop_words=[
                "How fight will End",
                "What Round",
                "Show More",
            ],
        )
        or
        get_market_snippet(
            page,
            "Will the fight go the distance?",
            stop_words=[
                "How fight will End",
                "What Round",
                "Show More",
            ],
        )
    )

    method = parse_method_of_victory(method_raw)
    total_rounds = parse_simple_pairs(total_rounds_raw)
    go_distance = parse_simple_pairs(go_distance_raw)

    has_props = bool(
        fight_betting
        or method
        or total_rounds
        or go_distance
    )

    print(f"Fight Betting: {len(fight_betting)}")
    print(f"Method of Victory: {len(method)}")
    print(f"Total Rounds: {len(total_rounds)}")
    print(f"Go The Distance: {len(go_distance)}")
    print(f"Has props: {has_props}")

    return {
        "fight": fight_name,
        "url": fight_url,
        "has_props": has_props,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markets": {
            "fight_betting": fight_betting,
            "method_of_victory": method,
            "total_rounds": total_rounds,
            "go_the_distance": go_distance,
        },
        "raw_markets": {
            "moneyline_market_name": opened_moneyline_market,
            "fight_betting": fight_result_raw,
            "method_of_victory": method_raw,
            "total_rounds": total_rounds_raw,
            "go_the_distance": go_distance_raw,
        }
    }


def upsert_fight(output, fight_data):
    existing = output.get("fights", [])
    url = fight_data.get("url")

    updated = False

    for i, item in enumerate(existing):
        if item.get("url") == url:
            existing[i] = fight_data
            updated = True
            break

    if not updated:
        existing.append(fight_data)

    output["fights"] = existing


def main():
    if not URLS_PATH.exists():
        print(f"Missing fight URL file: {URLS_PATH}")
        output = empty_output()
        save_output(output)
        print("No fight URL file found. Exiting cleanly.")
        return

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        url_data = json.load(f)

    fights = url_data.get("fights", [])

    if not fights:
        print("No fights found in paddypower_fight_urls.json")
        output = empty_output()
        save_output(output)
        print("Saved empty props.json. Exiting cleanly.")
        return

    output = load_existing_output()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_github_actions(),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )

        page = context.new_page()

        for index, fight in enumerate(fights, start=1):
            print(f"\nProgress: {index}/{len(fights)}")

            try:
                fight_data = scrape_fight(page, fight)
                upsert_fight(output, fight_data)
                save_output(output)
            except Exception as e:
                print(f"ERROR scraping {fight.get('fight')}: {e}")
                save_output(output)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print(f"\nFinished. Saved props to {OUT_PATH}")


if __name__ == "__main__":
    main()