from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEBUG_DIR = ROOT / "ufc" / "data" / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

URL = "https://tote.co.uk/sports/en/sports/mma"

print("STARTING TOTE FIGHT CLICK PROBE")

captured = []

def handle_response(response):
    url = response.url.lower()

    if (
        "graphql" in url
        or "market" in url
        or "event" in url
        or "bet" in url
    ):
        try:
            text = response.text()

            item = {
                "url": response.url,
                "status": response.status,
                "body": text[:200000]
            }

            captured.append(item)

            print(f"CAPTURED: {response.url}")

        except Exception as e:
            print("FAILED:", e)

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=False
    )

    page = browser.new_page()

    page.on("response", handle_response)

    print("OPENING:", URL)

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=90000
    )

    page.wait_for_timeout(8000)

    try:
        page.click("text=Accept", timeout=3000)
        print("ACCEPTED COOKIES")
    except:
        pass

    page.wait_for_timeout(3000)

    print("CLICKING FIRST UFC FIGHT")

    page.goto("https://tote.co.uk/sports/en/sports/mma/event/2815180", wait_until="domcontentloaded", timeout=90000)

    page.wait_for_timeout(15000)

    browser.close()

OUT = DEBUG_DIR / "tote_click_probe.json"

OUT.write_text(
    json.dumps(captured, indent=2),
    encoding="utf-8"
)

print()
print("DONE")
print("SAVED:", OUT)
print("TOTAL CAPTURED:", len(captured))