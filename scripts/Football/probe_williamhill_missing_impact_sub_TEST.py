#!/usr/bin/env python3
"""
Read-only William Hill probe for fixtures where the PROD15 candidate could not
find the top-level Impact Sub tab.

This script does not write or replace any production JSON.
It checks three failed fixtures, prints visible top-level labels, saves the full
body text, a screenshot, and a compact JSON diagnostic for each fixture.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
DEBUG_DIR = ROOT / "football" / "debug" / "williamhill_missing_impact_sub_probe"

HEADLESS = False

FIXTURES = [
    {
        "match": "Netherlands v Morocco",
        "url": "https://sports.williamhill.com/betting/en-gb/football/OB_EV40261449/netherlands-vs-morocco",
        "source": "cache",
    },
    {
        "match": "Mexico v Ecuador",
        "url": "https://sports.williamhill.com/betting/en-gb/football/OB_EV40281380/mexico-vs-ecuador",
        "source": "row_discovery",
    },
    {
        "match": "Australia v Egypt",
        "url": "https://sports.williamhill.com/betting/en-gb/football/OB_EV40273925/australia-vs-egypt",
        "source": "cache",
    },
]


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value):
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


def accept_cookies(page):
    labels = [
        "Accept All", "Accept all", "I Accept", "Accept",
        "Agree", "Allow all", "Got it", "OK",
    ]
    for label in labels:
        try:
            loc = page.get_by_role("button", name=re.compile(label, re.I))
            if loc.count():
                loc.first.click(timeout=2000)
                page.wait_for_timeout(600)
                return True
        except Exception:
            pass
    return False


def inspect_page(page):
    return page.evaluate(
        r"""
        () => {
            const norm = s => (s || '').replace(/\s+/g, ' ').trim();

            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 4 && r.height > 4 &&
                       r.bottom > 0 &&
                       st.display !== 'none' &&
                       st.visibility !== 'hidden' &&
                       st.opacity !== '0';
            };

            const selector = [
                'button',
                '[role=tab]',
                '[role=button]',
                'a',
                'div',
                'span'
            ].join(',');

            const all = Array.from(document.querySelectorAll(selector))
                .filter(visible)
                .map(el => {
                    const r = el.getBoundingClientRect();
                    return {
                        text: norm(el.innerText || el.textContent || ''),
                        top: Math.round(r.top),
                        left: Math.round(r.left),
                        width: Math.round(r.width),
                        height: Math.round(r.height),
                        tag: el.tagName,
                        role: el.getAttribute('role') || '',
                        testid: el.getAttribute('data-testid') || ''
                    };
                })
                .filter(x => x.text && x.text.length <= 80);

            const exactImpact = all.filter(
                x => x.text.toLowerCase() === 'impact sub'
            );

            const impactContains = all.filter(
                x => x.text.toLowerCase().includes('impact sub')
            );

            // William Hill top market tabs are normally in the upper portion
            // of the event page. Keep a broad range so layout changes are visible.
            const topLabels = all
                .filter(x => x.top >= 80 && x.top <= 750)
                .filter(x => x.width >= 30 && x.height >= 12)
                .sort((a, b) => a.top - b.top || a.left - b.left);

            const unique = [];
            const seen = new Set();
            for (const item of topLabels) {
                const key = `${item.text}|${item.top}|${item.left}`;
                if (seen.has(key)) continue;
                seen.add(key);
                unique.push(item);
            }

            return {
                url: location.href,
                title: document.title,
                exact_impact_sub_nodes: exactImpact,
                impact_sub_containing_nodes: impactContains,
                top_labels: unique.slice(0, 250),
                body_contains_impact_sub:
                    norm(document.body.innerText || '').toLowerCase()
                        .includes('impact sub'),
                body_contains_players:
                    norm(document.body.innerText || '').toLowerCase()
                        .includes('players'),
                body_contains_goals:
                    norm(document.body.innerText || '').toLowerCase()
                        .includes('goals')
            };
        }
        """
    )


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("William Hill missing Impact Sub probe")
    print("READ ONLY — production files will not be changed")
    print("=" * 72)

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1100})

        for index, fixture in enumerate(FIXTURES, start=1):
            name = fixture["match"]
            url = fixture["url"]
            slug = slugify(name)

            print()
            print("=" * 72)
            print(f"[{index}/{len(FIXTURES)}] {name}")
            print(url)

            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(7000)
            accept_cookies(page)
            page.wait_for_timeout(1500)

            try:
                page.evaluate(
                    "window.scrollTo(0,0); document.scrollingElement.scrollTop = 0"
                )
            except Exception:
                pass
            page.wait_for_timeout(800)

            body_text = page.locator("body").inner_text(timeout=30000)
            diagnostic = inspect_page(page)

            text_path = DEBUG_DIR / f"{slug}.txt"
            json_path = DEBUG_DIR / f"{slug}.json"
            screenshot_path = DEBUG_DIR / f"{slug}.png"

            text_path.write_text(body_text, encoding="utf-8")
            json_path.write_text(
                json.dumps(diagnostic, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            page.screenshot(path=str(screenshot_path), full_page=True)

            exact_count = len(diagnostic["exact_impact_sub_nodes"])
            contains_count = len(diagnostic["impact_sub_containing_nodes"])

            print(f"  final URL: {diagnostic['url']}")
            print(f"  exact visible 'Impact Sub' nodes: {exact_count}")
            print(f"  visible nodes containing 'Impact Sub': {contains_count}")
            print(
                "  body text contains Impact Sub: "
                f"{diagnostic['body_contains_impact_sub']}"
            )
            print(
                "  body text contains Players / Goals: "
                f"{diagnostic['body_contains_players']} / "
                f"{diagnostic['body_contains_goals']}"
            )

            interesting = []
            for item in diagnostic["top_labels"]:
                low = item["text"].lower()
                if any(
                    token in low
                    for token in [
                        "popular", "all", "impact", "player",
                        "goals", "corners", "cards", "bet builder",
                    ]
                ):
                    interesting.append(item["text"])

            deduped = list(dict.fromkeys(interesting))
            print(
                "  relevant visible top labels: "
                + (", ".join(deduped[:30]) if deduped else "<none>")
            )

            results.append({
                "match": name,
                "requested_url": url,
                "source": fixture["source"],
                **diagnostic,
                "text_file": str(text_path),
                "json_file": str(json_path),
                "screenshot_file": str(screenshot_path),
            })

        browser.close()

    summary_path = DEBUG_DIR / "summary.json"
    summary_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("Probe complete")
    print(f"Saved diagnostics to: {DEBUG_DIR}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
