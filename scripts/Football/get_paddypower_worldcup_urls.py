import re
from playwright.sync_api import sync_playwright

URL = "https://www.paddypower.com/fifa-world-cup"

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1600, "height": 1000})

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    for label in ["Accept All", "Accept all", "I Accept", "Accept", "Agree", "Allow all"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                break
        except Exception:
            pass

    try:
        page.get_by_text("Matches", exact=True).first.click(timeout=4000)
        page.wait_for_timeout(2500)
    except Exception:
        pass

    for _ in range(25):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(400)

    links = page.evaluate("""
        () => Array.from(document.querySelectorAll('a'))
            .map(a => ({href: a.href, text: a.innerText}))
            .filter(x =>
                x.href &&
                x.href.includes('/football/fifa-world-cup/') &&
                x.href.includes('-v-') &&
                !x.href.includes('/bet')
            )
    """)

    seen = set()
    real = []

    for x in links:
        href = x["href"].split("?")[0]
        text = clean(x["text"])
        if href in seen:
            continue
        seen.add(href)
        real.append((text, href))

    print(f"FOUND {len(real)} REAL MATCH URLS\\n")

    for text, href in real:
        print(f"{text} => {href}")

    browser.close()