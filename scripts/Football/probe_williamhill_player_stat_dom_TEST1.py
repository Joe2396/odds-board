#!/usr/bin/env python3
"""
probe_williamhill_player_stat_dom_TEST1.py

Read-only William Hill DOM probe for ONE fixture.

Purpose:
  - inspect the real accordion/container structure for player-stat markets;
  - show whether Impact Sub and Enhanced Win prices coexist in the DOM;
  - identify a reliable parent container for each exact market heading;
  - stop guessing from flattened body.inner_text().

This script does NOT write or replace production JSON.
It depends on the already-installed safe test candidate:
  scripts/Football/fetch_williamhill_worldcup_props_FAST_TEST3_V8_SCOPED_IMPACT_SUB.py

Output:
  football/debug/williamhill_dom_probe_TEST1/summary.json
  football/debug/williamhill_dom_probe_TEST1/body.txt
  football/debug/williamhill_dom_probe_TEST1/<market>.html
  football/debug/williamhill_dom_probe_TEST1/<market>.txt
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / "scripts" / "Football" / "fetch_williamhill_worldcup_props_FAST_TEST3_V8_SCOPED_IMPACT_SUB.py"
OUT_DIR = ROOT / "football" / "debug" / "williamhill_dom_probe_TEST1"

HEADLESS = False

TARGET_HEADINGS = [
    "Player Shots On Target",
    "Player Shots on Target",
    "Total Player Shots",
    "Total Player Tackles",
    "Player Fouls",
    "Player Fouls Won",
]


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean(value).lower()).strip("-")


def load_base_module():
    if not BASE_PATH.exists():
        raise SystemExit(
            f"Missing required V8 test script:\n{BASE_PATH}\n\n"
            "Copy the V8 script into scripts\\Football first."
        )

    spec = importlib.util.spec_from_file_location("wh_v8_probe_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load module spec: {BASE_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def choose_fixture(base):
    targets = base.load_moneyline_targets()
    cached = base.load_cached_event_urls()

    for target in targets:
        key = base.normalize(target["name"])
        url = cached.get(key, "")
        if url and "/OB_EV" in url:
            return {
                "name": target["name"],
                "home": target["home"],
                "away": target["away"],
                "url": url,
            }

    raise SystemExit(
        "No cached William Hill /OB_EV event URL was found.\n"
        "Run the William Hill moneyline scraper and one successful TEST3 scraper first."
    )


PROBE_JS = r"""
({heading, allHeadings}) => {
    const clean = s => (s || '').replace(/\s+/g, ' ').trim();
    const norm = s => clean(s).toLowerCase();
    const target = norm(heading);
    const headingSet = new Set(allHeadings.map(norm));
    const oddsRe = /^(?:\d+\/\d+|EVS|EVENS|EVEN|Evens)$/i;
    const rowRe = /\b(?:At Least|Over)\s+\d+(?:\.\d+)?\b.*\b(?:Shot|Shots|Shot On Target|Shots On Target|Tackle|Tackles|Foul|Fouls|Foul Won|Fouls Won)\b/i;

    const rectOf = el => {
        const r = el.getBoundingClientRect();
        return {
            x: Math.round(r.x), y: Math.round(r.y),
            width: Math.round(r.width), height: Math.round(r.height),
            top: Math.round(r.top), bottom: Math.round(r.bottom),
            left: Math.round(r.left), right: Math.round(r.right),
        };
    };

    const isVisible = el => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 &&
               st.display !== 'none' && st.visibility !== 'hidden' &&
               st.opacity !== '0';
    };

    const attrMap = el => {
        const out = {};
        for (const a of Array.from(el.attributes || [])) {
            if (
                a.name === 'class' || a.name === 'id' || a.name === 'role' ||
                a.name.startsWith('data-') || a.name.startsWith('aria-')
            ) out[a.name] = a.value;
        }
        return out;
    };

    const exactTextNodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,div,span,p,button,[role=button],[role=tab]'))
        .filter(el => norm(el.innerText || el.textContent || '') === target);

    const headingNodeSummaries = [];
    const ancestorCandidates = [];

    for (let nodeIndex = 0; nodeIndex < exactTextNodes.length; nodeIndex++) {
        const node = exactTextNodes[nodeIndex];
        headingNodeSummaries.push({
            node_index: nodeIndex,
            tag: node.tagName,
            attrs: attrMap(node),
            visible: isVisible(node),
            rect: rectOf(node),
            text: clean(node.innerText || node.textContent || ''),
        });

        let cur = node;
        for (let depth = 0; depth <= 12 && cur && cur !== document.documentElement; depth++, cur = cur.parentElement) {
            const text = clean(cur.innerText || cur.textContent || '');
            if (!text) continue;

            const allDesc = Array.from(cur.querySelectorAll('*'));
            const oddsTokens = allDesc
                .map(el => clean(el.innerText || el.textContent || ''))
                .filter(t => t && !t.includes('\n') && oddsRe.test(t));
            const rowLabels = allDesc
                .map(el => clean(el.innerText || el.textContent || ''))
                .filter(t => t && t.length < 180 && !t.includes('\n') && rowRe.test(t));
            const marketHeadings = allDesc
                .map(el => norm(el.innerText || el.textContent || ''))
                .filter(t => headingSet.has(t));

            const children = Array.from(cur.children || []).slice(0, 30).map((child, i) => ({
                index: i,
                tag: child.tagName,
                attrs: attrMap(child),
                visible: isVisible(child),
                rect: rectOf(child),
                text: clean(child.innerText || child.textContent || '').slice(0, 220),
            }));

            ancestorCandidates.push({
                node_index: nodeIndex,
                depth,
                tag: cur.tagName,
                attrs: attrMap(cur),
                visible: isVisible(cur),
                rect: rectOf(cur),
                text_length: text.length,
                text_preview: text.slice(0, 900),
                odds_count: oddsTokens.length,
                odds_sample: oddsTokens.slice(0, 25),
                row_label_count: rowLabels.length,
                row_label_sample: rowLabels.slice(0, 20),
                market_heading_count: marketHeadings.length,
                market_headings: Array.from(new Set(marketHeadings)).slice(0, 20),
                impact_sub_count: (text.match(/Impact Sub/gi) || []).length,
                enhanced_win_count: (text.match(/Enhanced Win/gi) || []).length,
                children,
            });
        }
    }

    // Prefer the smallest ancestor that contains rows/odds but only this market heading.
    const ranked = ancestorCandidates
        .filter(x => x.row_label_count > 0 || x.odds_count > 0)
        .sort((a, b) => {
            const aSingle = a.market_heading_count === 1 ? 0 : 1;
            const bSingle = b.market_heading_count === 1 ? 0 : 1;
            if (aSingle !== bSingle) return aSingle - bSingle;
            const aUseful = a.row_label_count > 0 && a.odds_count > 0 ? 0 : 1;
            const bUseful = b.row_label_count > 0 && b.odds_count > 0 ? 0 : 1;
            if (aUseful !== bUseful) return aUseful - bUseful;
            return a.text_length - b.text_length;
        });

    let chosen = null;
    if (ranked.length) {
        const pick = ranked[0];
        const node = exactTextNodes[pick.node_index];
        let cur = node;
        for (let d = 0; d < pick.depth && cur; d++) cur = cur.parentElement;
        if (cur) {
            const text = clean(cur.innerText || cur.textContent || '');
            const rowElements = Array.from(cur.querySelectorAll('*'))
                .filter(el => {
                    const t = clean(el.innerText || el.textContent || '');
                    return t && t.length < 180 && !t.includes('\n') && rowRe.test(t);
                })
                .slice(0, 120)
                .map(el => {
                    let p = el;
                    const ancestors = [];
                    for (let d = 0; d < 5 && p; d++, p = p.parentElement) {
                        const pt = clean(p.innerText || p.textContent || '');
                        const odds = Array.from(p.querySelectorAll('*'))
                            .map(x => clean(x.innerText || x.textContent || ''))
                            .filter(x => x && !x.includes('\n') && oddsRe.test(x));
                        ancestors.push({
                            depth: d,
                            tag: p.tagName,
                            attrs: attrMap(p),
                            visible: isVisible(p),
                            rect: rectOf(p),
                            text: pt.slice(0, 500),
                            odds: odds.slice(0, 12),
                        });
                    }
                    return {
                        label: clean(el.innerText || el.textContent || ''),
                        tag: el.tagName,
                        attrs: attrMap(el),
                        visible: isVisible(el),
                        rect: rectOf(el),
                        ancestors,
                    };
                });

            chosen = {
                candidate: pick,
                text,
                outer_html: cur.outerHTML,
                row_elements: rowElements,
            };
        }
    }

    return {
        heading,
        url: location.href,
        heading_nodes: headingNodeSummaries,
        ancestors: ancestorCandidates,
        chosen,
    };
}
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_base_module()
    fixture = choose_fixture(base)

    print("=" * 68)
    print("William Hill player-stat DOM probe — TEST1")
    print("READ ONLY: no production JSON will be changed")
    print("=" * 68)
    print(f"Fixture: {fixture['name']}")
    print(f"URL: {fixture['url']}")

    summary = {
        "fixture": fixture,
        "markets": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})

        page.goto(fixture["url"], wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(4500)
        base.accept_cookies(page)

        if not base.page_has_fixture(page, fixture["home"], fixture["away"]):
            browser.close()
            raise SystemExit("Cached URL did not contain the expected fixture teams.")

        player_tab = base.try_tab_aliases(page, ["Player", "Players", "Player Stats"])
        if not player_tab:
            browser.close()
            raise SystemExit("Could not open the William Hill Player/Players tab.")

        print(f"Opened tab: {player_tab}")
        clicked, present, ladder_status = base.expand_relevant_player_markets_fast(page)
        base.scroll_page(page, 8)
        page.wait_for_timeout(1200)

        print(f"Relevant headings found: {len(present)}")
        print(f"Generic clicks: {clicked}")
        print(f"Ladder status: {dict(ladder_status)}")

        body_text = page.locator("body").inner_text(timeout=20000)
        (OUT_DIR / "body.txt").write_text(body_text, encoding="utf-8")

        for heading in TARGET_HEADINGS:
            result = page.evaluate(PROBE_JS, {"heading": heading, "allHeadings": TARGET_HEADINGS})
            summary["markets"][heading] = result

            chosen = result.get("chosen") if isinstance(result, dict) else None
            if chosen:
                market_slug = slugify(heading)
                (OUT_DIR / f"{market_slug}.html").write_text(
                    chosen.get("outer_html", ""), encoding="utf-8"
                )
                (OUT_DIR / f"{market_slug}.txt").write_text(
                    chosen.get("text", ""), encoding="utf-8"
                )

                candidate = chosen.get("candidate", {})
                print(
                    f"  {heading:<28} "
                    f"rows={candidate.get('row_label_count', 0):>3} "
                    f"odds={candidate.get('odds_count', 0):>3} "
                    f"headings={candidate.get('market_heading_count', 0):>2} "
                    f"ImpactSub={candidate.get('impact_sub_count', 0):>2} "
                    f"EnhancedWin={candidate.get('enhanced_win_count', 0):>2} "
                    f"depth={candidate.get('depth', '-') }"
                )
            else:
                node_count = len(result.get("heading_nodes", [])) if isinstance(result, dict) else 0
                print(f"  {heading:<28} NO CONTAINER (heading nodes={node_count})")

        (OUT_DIR / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        browser.close()

    print("\nSaved DOM probe to:")
    print(OUT_DIR)
    print("\nPlease paste the six one-line market summaries printed above.")
    print("If any show identical row/odds counts, upload summary.json as well.")


if __name__ == "__main__":
    main()
