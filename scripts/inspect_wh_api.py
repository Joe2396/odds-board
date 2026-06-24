from playwright.sync_api import sync_playwright
import time, json

URL = "https://sports.williamhill.com/betting/en-gb/ufc/competitions/ufc-fight-night-fiziev-vs-torres/matches"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    # Capture network requests
    api_responses = []
    def handle_response(response):
        if any(x in response.url for x in ['api', 'event', 'market', 'competition', 'match']):
            if 'williamhill' in response.url or 'whapi' in response.url:
                api_responses.append(response.url)

    page.on("response", handle_response)
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(8)

    print("API calls made:")
    for u in api_responses:
        print(" ", u)

    # Also check if fight links appear after JS loads
    links = page.evaluate("""
        () => [...new Set(
            Array.from(document.querySelectorAll('a[href]'))
            .map(a => a.href)
            .filter(h => h.includes('/ufc/') && !h.includes('/competitions/') && !h.includes('/matches/competition/'))
        )]
    """)
    print("\nNon-competition UFC links after JS load:")
    for l in links:
        print(" ", l)

    # Dump full page HTML snippet around any OB_EV references
    html_snippet = page.evaluate("""
        () => {
            const html = document.body.innerHTML;
            const idx = html.indexOf('OB_EV');
            if (idx === -1) return 'No OB_EV found in DOM';
            return html.slice(Math.max(0, idx-100), idx+200);
        }
    """)
    print("\nOB_EV in DOM:")
    print(html_snippet)

    input("\nPress Enter to close...")
    browser.close()