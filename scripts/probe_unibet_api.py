from playwright.sync_api import sync_playwright
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "ufc" / "data" / "debug"
OUT_DIR.mkdir(parents=True, exist_ok=True)

URL = "https://www.unibet.ie/betting/odds/mma/ufc"

saved = set()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    def handle_response(response):
        url = response.url.lower()

        if "quickbrowse" in url or "lobby" in url:
            try:
                data = response.json()
            except:
                return

            safe_name = (
                "quickbrowse"
                if "quickbrowse" in url
                else "lobby"
            )

            out_file = OUT_DIR / f"unibet_{safe_name}.json"

            if str(out_file) in saved:
                return

            out_file.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8"
            )

            saved.add(str(out_file))

            print(f"Saved: {out_file}")

    page.on("response", handle_response)

    try:
        page.goto(URL, timeout=30000)
        page.wait_for_timeout(8000)
    except Exception as e:
        print(f"Ignoring page timeout: {e}")

    print("")
    print("Finished.")
    print(f"Saved {len(saved)} files.")

    browser.close()