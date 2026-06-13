from pathlib import Path
from playwright.sync_api import sync_playwright
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "football" / "debug" / "livescorebet_total_shots_test.txt"

URL = "https://www.livescorebet.com/ie/sports/football/world-cup-2026/canada-bosnia-herzegovina/SBTE_2_1027164909/?marketGroupId=-1"

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def accept_cookies(page):
    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all", "Got it"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass

def click_text(page, text):
    try:
        loc = page.get_by_text(text, exact=True)
        print(text, "count =", loc.count())
        if not loc.count():
            return False
        loc.last.scroll_into_view_if_needed(timeout=3000)
        page.wait_for_timeout(500)
        loc.last.click(timeout=3000)
        page.wait_for_timeout(1000)
        return True
    except Exception as e:
        print("click failed:", text, e)
        return False

def extract_near_total_shots(page):
    return page.evaluate("""
        () => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            const els = Array.from(document.querySelectorAll('body *'))
                .filter(e => norm(e.innerText) === 'Total Shots');
            if (!els.length) return 'NO TOTAL SHOTS HEADING FOUND';

            let best = '';
            for (const h of els) {
                let node = h;
                for (let d = 0; d < 10 && node; d++, node = node.parentElement) {
                    const txt = norm(node.innerText);
                    if (
                        txt.includes('Total Shots') &&
                        txt.includes('Both Teams Combined') &&
                        txt.includes('Over') &&
                        txt.includes('Under')
                    ) {
                        if (txt.length > best.length) best = txt;
                    }
                }
            }
            return best || 'NO USEFUL TOTAL SHOTS CONTAINER FOUND';
        }
    """)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1700, "height": 1000})

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookies(page)

    for _ in range(14):
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(250)

    print("Opening Total Shots...")
    click_text(page, "Total Shots")

    chunks = []

    for scope in ["Both Teams Combined", "Canada", "Bosnia & Herzegovina"]:
        print("\nScope:", scope)
        clicked = click_text(page, scope)
        page.wait_for_timeout(1500)

        txt = extract_near_total_shots(page)
        print(txt[:1000])
        chunks.append(f"\n\n===== {scope} | clicked={clicked} =====\n{txt}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(chunks), encoding="utf-8")

    print("\nSaved:", OUT)
    browser.close()