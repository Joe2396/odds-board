from playwright.sync_api import sync_playwright
from pathlib import Path
from datetime import datetime, timezone
import json
import re
import time
import os

print("FETCHING BETVICTOR UFC FIGHT URLS")

ROOT = Path(__file__).resolve().parents[1]

EVENTS_PATH = ROOT / "ufc" / "data" / "events.json"
OUT_PATH = ROOT / "ufc" / "data" / "betvictor_fight_urls.json"
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"

BETVICTOR_MMA_PAGE = "https://www.betvictor.com/en-ie/sports/1327866"
BETVICTOR_BASE = "https://www.betvictor.com"


def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"


def clean_text(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()


def clean_name(x):
    x = str(x or "").lower()
    x = x.replace("é", "e").replace("á", "a").replace("í", "i").replace("ó", "o").replace("ú", "u")
    x = re.sub(r"[^a-z0-9 ]", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def is_tba(name):
    n = clean_name(name)
    return not n or "tba" in n or "opponent" in n


def event_is_upcoming(date_str):
    try:
        d = str(date_str or "")[:10]
        event_date = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return event_date >= today
    except Exception:
        return True


def accept_cookies(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
    ]:
        try:
            page.locator(selector).first.click(timeout=3000, force=True)
            print("Accepted cookies")
            time.sleep(1)
            return
        except Exception:
            pass


def save_debug(page, label):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=True)
        print(f"Debug screenshot: {label}")
    except Exception as e:
        print(f"Debug failed: {e}")


def get_fighter_name(fight, side):
    if side == 1:
        return (
            fight.get("fighter1")
            or fight.get("fighter_1")
            or fight.get("home")
            or fight.get("competitor1")
            or ((fight.get("red") or {}).get("name"))
            or ""
        )

    return (
        fight.get("fighter2")
        or fight.get("fighter_2")
        or fight.get("away")
        or fight.get("competitor2")
        or ((fight.get("blue") or {}).get("name"))
        or ""
    )


def load_upcoming_fights():
    if not EVENTS_PATH.exists():
        print(f"ERROR: events.json not found at {EVENTS_PATH}")
        return []

    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = data if isinstance(data, list) else data.get("events", [])
    fights_out = []

    for event in events:
        if not event_is_upcoming(event.get("date")):
            continue

        for fight in event.get("fights") or []:
            f1 = clean_text(get_fighter_name(fight, 1))
            f2 = clean_text(get_fighter_name(fight, 2))

            if not f1 or not f2:
                continue

            if is_tba(f1) or is_tba(f2):
                continue

            fights_out.append({
                "fight": f"{f1} vs {f2}",
                "fighter1": f1,
                "fighter2": f2,
                "event_name": event.get("name", ""),
                "date": event.get("date", ""),
                "fight_id": fight.get("id", ""),
            })

    print(f"Upcoming fights from events.json: {len(fights_out)}")
    for f in fights_out[:12]:
        print(" -", f["fight"])
    if len(fights_out) > 12:
        print(f"... plus {len(fights_out) - 12} more")

    return fights_out


def names_match(fight, body):
    body = clean_name(body)

    f1 = clean_name(fight["fighter1"])
    f2 = clean_name(fight["fighter2"])

    f1_last = f1.split()[-1] if f1 else ""
    f2_last = f2.split()[-1] if f2 else ""

    return f1_last in body and f2_last in body


def get_mma_meeting_links(page):
    print("Opening exact BetVictor MMA/UFC page only...")
    page.goto(BETVICTOR_MMA_PAGE, wait_until="domcontentloaded", timeout=60000)
    time.sleep(6)
    accept_cookies(page)
    time.sleep(2)

    save_debug(page, "betvictor_exact_mma_page")

    # Click the MMA/UFC Fights accordion only.
    for selector in [
        "text=MMA/UFC Fights",
        "button:has-text('MMA/UFC Fights')",
        "div:has-text('MMA/UFC Fights')",
    ]:
        try:
            page.locator(selector).first.click(timeout=4000, force=True)
            print("Clicked MMA/UFC Fights")
            time.sleep(3)
            break
        except Exception:
            pass

    body = page.locator("body").inner_text(timeout=15000)
    print("\n--- MMA PAGE PREVIEW ---")
    print(body[:1200])
    print("--- END PREVIEW ---\n")

    links = page.locator("a").evaluate_all("""
        els => els.map(a => ({
            text: (a.innerText || '').trim(),
            href: a.href || ''
        }))
    """)

    meeting_links = []

    for item in links:
        href = item.get("href", "")
        text = item.get("text", "")

        if not href:
            continue

        if href.startswith("/"):
            href = BETVICTOR_BASE + href

        # HARD FILTER: only MMA/UFC sport ID 1327866 meeting pages.
        if "/en-ie/sports/1327866/meetings/" not in href:
            continue

        if "/all" not in href:
            continue

        if href not in meeting_links:
            meeting_links.append(href)
            print(f"Found UFC meeting link: {text} -> {href}")

    return meeting_links


def main():
    upcoming_fights = load_upcoming_fights()

    matched = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_github_actions(),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
        )

        page = context.new_page()

        meeting_links = get_mma_meeting_links(page)

        print(f"\nUFC meeting links found: {len(meeting_links)}")
        for link in meeting_links:
            print(" -", link)

        for meeting_url in meeting_links:
            print(f"\nOpening UFC meeting page: {meeting_url}")

            try:
                page.goto(meeting_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(8)

                # Do NOT click random links. Only read and scroll.
                for _ in range(6):
                    page.mouse.wheel(0, 900)
                    time.sleep(0.7)

                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(1)

                save_debug(page, "betvictor_ufc_meeting")

                body = page.locator("body").inner_text(timeout=20000)

                print("\n--- MEETING PAGE PREVIEW ---")
                print(body[:1800])
                print("--- END PREVIEW ---\n")

            except Exception as e:
                print(f"Failed meeting page: {e}")
                continue

            for fight in upcoming_fights:
                already = any(x["fight"] == fight["fight"] for x in matched)
                if already:
                    continue

                if names_match(fight, body):
                    print("MATCHED:", fight["fight"])

                    matched.append({
                        "bookmaker": "BetVictor",
                        "fight": fight["fight"],
                        "fight_name": fight["fight"],
                        "fighter1": fight["fighter1"],
                        "fighter2": fight["fighter2"],
                        "event_name": fight["event_name"],
                        "date": fight["date"],
                        "fight_id": fight["fight_id"],
                        "url": meeting_url,
                    })
                else:
                    print("NO MATCH:", fight["fight"])

        browser.close()

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "betvictor",
        "bookmaker": "BetVictor",
        "count": len(matched),
        "fights": matched,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("\nDONE")
    print("Matched fights:", len(matched))
    print("Saved to:", OUT_PATH)


if __name__ == "__main__":
    main()