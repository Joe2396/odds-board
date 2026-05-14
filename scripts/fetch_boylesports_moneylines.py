from playwright.sync_api import sync_playwright
import json
import time
import os
import re
from pathlib import Path
from datetime import datetime, timezone

print("FETCHING BOYLESPORTS MONEYLINES - POSITION BASED")

ROOT = Path(__file__).resolve().parents[1]

URLS_PATH = ROOT / "ufc" / "data" / "boylesports_fight_urls.json"
OUT_PATH = ROOT / "ufc" / "data" / "boylesports_moneylines.json"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_name(name):
    name = str(name or "").strip()
    name = re.sub(r"\s+", " ", name)
    return name.strip(" -")


def get_fighters(fight_name):
    if " vs " in fight_name.lower():
        parts = re.split(r"\s+vs\s+", fight_name, flags=re.I)
    elif " v " in fight_name.lower():
        parts = re.split(r"\s+v\s+", fight_name, flags=re.I)
    else:
        parts = []

    return [clean_name(p) for p in parts if clean_name(p)]


def close_cookie_popup(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
    ]:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass

    print("No cookie popup found")


def click_to_win_fight(page):
    for label in ["To Win Fight", "Fight Betting", "Money Line", "Moneyline"]:
        try:
            locator = page.get_by_text(label, exact=True).first
            locator.scroll_into_view_if_needed(timeout=4000)
            time.sleep(0.4)
            locator.click(force=True, timeout=4000)
            print(f"Clicked market/tab: {label}")
            time.sleep(1)
            return True
        except Exception:
            pass

    print("Could not click To Win Fight; trying visible page anyway")
    return False


def extract_moneyline_from_positions(page, fighters):
    return page.evaluate(
        """
        ({fighters}) => {
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);

                return (
                    r.width > 0 &&
                    r.height > 0 &&
                    s.display !== "none" &&
                    s.visibility !== "hidden"
                );
            }

            function isOdds(t) {
                t = (t || "").trim().toUpperCase();
                return t === "EVS" || /^\\d+\\/\\d+$/.test(t);
            }

            function norm(t) {
                return (t || "")
                    .toLowerCase()
                    .replace(/[^a-z0-9\\s]/g, " ")
                    .replace(/\\s+/g, " ")
                    .trim();
            }

            const nodes = Array.from(document.querySelectorAll("body *"));
            const items = [];

            for (const el of nodes) {
                if (!isVisible(el)) continue;

                const text = (el.innerText || el.textContent || "").trim();
                if (!text) continue;
                if (text.length > 90) continue;

                const r = el.getBoundingClientRect();

                items.push({
                    text,
                    norm: norm(text),
                    x: r.x,
                    y: r.y,
                    w: r.width,
                    h: r.height,
                    cx: r.x + r.width / 2,
                    cy: r.y + r.height / 2
                });
            }

            const oddsBoxes = items.filter(i => isOdds(i.text));
            const prices = [];
            const debugRows = [];

            for (const fighter of fighters) {
                const fn = norm(fighter);

                const nameBoxes = items.filter(i =>
                    i.norm === fn || i.norm.includes(fn)
                );

                debugRows.push({
                    fighter,
                    nameBoxCount: nameBoxes.length
                });

                if (!nameBoxes.length) continue;

                // Prefer visible fighter label on the left side of the odds row.
                nameBoxes.sort((a, b) => {
                    if (Math.abs(a.y - b.y) > 10) return a.y - b.y;
                    return a.x - b.x;
                });

                const nameBox = nameBoxes[0];

                const candidates = oddsBoxes
                    .filter(o => {
                        const sameRow = Math.abs(o.cy - nameBox.cy) < 45;
                        const toRight = o.cx > nameBox.cx;
                        const notTooFar = (o.cx - nameBox.cx) < 1200;
                        return sameRow && toRight && notTooFar;
                    })
                    .map(o => ({
                        score: Math.abs(o.cy - nameBox.cy) * 5 + Math.abs(o.cx - nameBox.cx),
                        text: o.text,
                        x: o.x,
                        y: o.y
                    }))
                    .sort((a, b) => a.score - b.score);

                debugRows[debugRows.length - 1].candidateCount = candidates.length;
                debugRows[debugRows.length - 1].candidates = candidates.slice(0, 5);

                if (candidates.length) {
                    prices.push({
                        selection: fighter,
                        odds: candidates[0].text.trim().toUpperCase()
                    });
                }
            }

            return {
                prices,
                debug: {
                    itemCount: items.length,
                    oddsCount: oddsBoxes.length,
                    fighters,
                    debugRows
                }
            };
        }
        """,
        {"fighters": fighters},
    )


def scrape_moneyline(page, fight):
    fight_name = fight["fight"]
    fight_url = fight["url"]

    print("\n============================")
    print(f"Scraping: {fight_name}")
    print("============================")

    page.goto(fight_url, timeout=70000, wait_until="domcontentloaded")
    time.sleep(8)

    close_cookie_popup(page)

    fighters = get_fighters(fight_name)

    if len(fighters) != 2:
        print("Could not split fighters safely")
        prices = []
        debug = {"error": "BAD_FIGHTER_SPLIT", "fighters": fighters}
    else:
        click_to_win_fight(page)
        result = extract_moneyline_from_positions(page, fighters)
        prices = result.get("prices") or []
        debug = result.get("debug") or {}

    if len(prices) != 2:
        print("WARNING: could not safely extract 2 moneylines")
        print(f"Debug: {debug}")
        prices = []

    print(f"Moneylines extracted: {len(prices)}")

    for p in prices:
        print(f"- {p['selection']}: {p['odds']}")

    return {
        "fight": fight_name,
        "url": fight_url,
        "bookmaker": "BoyleSports",
        "scraped_at": now_iso(),
        "markets": {
            "fight_betting": prices
        },
        "debug": debug,
    }


def save_output(fights):
    output = {
        "updated_at": now_iso(),
        "source": "boylesports",
        "bookmaker": "BoyleSports",
        "count": len(fights),
        "fights": fights,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved moneylines to {OUT_PATH}")


def main():
    if not URLS_PATH.exists():
        print(f"Missing file: {URLS_PATH}")
        return

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    fights = data.get("fights", [])

    if not fights:
        print("No fights found")
        return

    results = []

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
            viewport={"width": 1365, "height": 768},
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )

        page = context.new_page()

        for index, fight in enumerate(fights, start=1):
            print(f"\nProgress: {index}/{len(fights)}")

            try:
                result = scrape_moneyline(page, fight)
                results.append(result)
                save_output(results)

            except Exception as e:
                print(f"ERROR scraping {fight.get('fight')}: {e}")
                save_output(results)

        if not is_github_actions():
            input("\nDone. Press Enter to close browser...")

        browser.close()

    print("\nFinished BoyleSports moneylines")


if __name__ == "__main__":
    main()