#!/usr/bin/env python3

from playwright.sync_api import sync_playwright

FIGHT_URL = "https://www.paddypower.com/mixed-martial-arts/ufc-matches/khamzat-chimaev-v-sean-strickland-35369952"

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(FIGHT_URL, timeout=60000)

        print("Page title:", page.title())
        print("Loaded PaddyPower fight page")

        input("Press Enter to close browser...")
        browser.close()

if __name__ == "__main__":
    main()
