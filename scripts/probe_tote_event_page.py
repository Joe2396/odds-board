from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEBUG = ROOT / "ufc" / "data" / "debug"
DEBUG.mkdir(parents=True, exist_ok=True)

EVENT_ID = "2815180"
URL = f"https://tote.co.uk/sports/en/sports/mma/event/{EVENT_ID}"

print("PROBING TOTE EVENT PAGE:", URL)

saved = 0

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1500, "height": 1000})

    def handle_response(resp):
        global saved
        url = resp.url.lower()

        if "graphql" not in url:
            return

        try:
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return

            req = resp.request
            body = resp.json()

            saved += 1
            out = {
                "url": resp.url,
                "method": req.method,
                "post_data": req.post_data,
                "response": body,
            }

            path = DEBUG / f"tote_event_page_graphql_{saved}.json"
            path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

            print("SAVED:", path)
            print("URL:", resp.url)
            if req.post_data:
                print("POST:", req.post_data[:500])

        except Exception as e:
            print("SKIP:", e)

    page.on("response", handle_response)

    page.goto(URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(25000)

    browser.close()

print("DONE. SAVED:", saved)