#!/usr/bin/env python3
import time
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ufc" / "data" / "bet365_mma_nav_debug.txt"

KEYWORDS = [
    "ufc",
    "mma",
    "topuria",
    "gaethje",
    "pereira",
    "gane",
]

ODDS_RE = re.compile(r"\b\d+/\d+\b|\bEVS\b", re.I)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def save(label, page):
    try:
        body = clean(page.locator("body").inner_text(timeout=10000))
    except Exception:
        body = ""

    hits = [k for k in KEYWORDS if k.lower() in body.lower()]
    odds = ODDS_RE.findall(body)

    text = f"""
==================================================
LABEL: {label}
URL: {page.url}
BODY LENGTH: {len(body)}
KEYWORD HITS: {hits}
ODDS COUNT: {len(odds)}
==================================================

{body[:15000]}
"""

    print(text[:4000])

    with open(OUT, "a", encoding="utf-8") as f:
        f.write(text)


def click_if_exists(page, text):
    selectors = [
        f"text={text}",
        f"a:has-text('{text}')",
        f"div:has-text('{text}')",
        f"span:has-text('{text}')",
    ]

    for sel in selectors:
        try:
            page.locator(sel).first.click(timeout=4000, force=True)
            print(f"CLICKED: {text}")
            time.sleep(5)
            return True
        except Exception:
            pass

    return False


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        slow_mo=500,
    )

    context = browser.new_context(
        viewport={"width": 1500, "height": 1000},
        locale="en-GB",
        timezone_id="Europe/London",
    )

    page = context.new_page()

    page.goto("https://www.bet365.com/", timeout=60000)

    time.sleep(8)

    try:
        page.locator("text=Accept").first.click(timeout=4000)
        print("Accepted cookies")
    except Exception:
        pass

    time.sleep(3)

    save("homepage", page)

    NAV_STEPS = [
        "All Sports",
        "MMA",
        "UFC",
        "Mixed Martial Arts",
    ]

    for step in NAV_STEPS:
        click_if_exists(page, step)
        time.sleep(4)
        save(step, page)

    for _ in range(8):
        page.mouse.wheel(0, 1500)
        time.sleep(1)

    save("after scroll", page)

    print("\nDONE")
    input("Press ENTER to close...")