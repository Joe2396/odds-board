from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEBUG = ROOT / "ufc" / "data" / "debug"
DEBUG.mkdir(parents=True, exist_ok=True)

URL = "https://tote.co.uk/sports/en/sports/mma"

print("PROBING TOTE API WITH REQUEST PAYLOADS...")

saved = 0

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1500, "height": 1000})

    def handle_response(resp):
        global saved
        url = resp.url.lower()

        if "graphql" not in url and "sportsbook" not in url:
            return

        try:
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return

            req = resp.request
            post_data = req.post_data

            data = resp.json()

            saved += 1
            out = {
                "url": resp.url,
                "method": req.method,
                "post_data": post_data,
                "response": data,
            }

            path = DEBUG / f"tote_probe_full_{saved}.json"
            path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

            print("SAVED:", path)
            print("METHOD:", req.method)
            print("URL:", resp.url)
            if post_data:
                print("POST:", post_data[:300])
        except Exception:
            pass

    page.on("response", handle_response)

    page.goto(URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(25000)

    print("DONE. Saved", saved, "files.")
    browser.close()