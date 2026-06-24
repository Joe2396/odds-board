from pathlib import Path
from datetime import datetime, timezone
import json
import re
import time
from playwright.sync_api import sync_playwright
import os

def is_github_actions():
    return os.getenv("GITHUB_ACTIONS") == "true"

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "williamhill_props.json"

LIST_URLS = [
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/today/match-betting",
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/saturday/match-betting",
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/sunday/match-betting",
    "https://sports.williamhill.com/betting/en-gb/ufc/matches/competition/future/match-betting",
]

BASE = "https://sports.williamhill.com/betting/en-gb/ufc"
print("RUNNING WILLIAM HILL UFC PROP SCRAPER")

def clean(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()

def is_frac(t):
    return bool(re.fullmatch(r"\d+/\d+", str(t or "").strip()))

def get_ob_ev_ids(page, comp_url):
    """Get OB_EV IDs from a competition page DOM."""
    try:
        page.goto(comp_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(7)
    except Exception as e:
        print(f"    Failed: {e}")
        return []

    ids = page.evaluate("""
        () => {
            const ids = [];
            document.querySelectorAll('[id^="OB_EV"]').forEach(el => {
                ids.push(el.id.replace('OB_EV', ''));
            });
            // Also check HTML for any missed
            const matches = document.body.innerHTML.matchAll(/OB_EV(\\d+)/g);
            for (const m of matches) {
                if (!ids.includes(m[1])) ids.push(m[1]);
            }
            return [...new Set(ids)];
        }
    """)
    print(f"    OB_EV IDs: {ids}")
    return ids

def scrape_fight_page(page, ob_ev_id):
    """Navigate to fight page via OB_EV ID and scrape all props."""
    url = f"{BASE}/OB_EV{ob_ev_id}"
    print(f"  [{ob_ev_id}] {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)
    except Exception as e:
        print(f"    Failed: {e}")
        return None

    return page.evaluate("""
        () => {
            function clean(t) { return (t||'').replace(/\\s+/g,' ').trim(); }
            function isFrac(t) { return /^\\d+\\/\\d+$/.test((t||'').trim()); }

            const title = clean(document.querySelector('h1')?.innerText || '');

            const MARKET_MAP = {
                'bout betting': 'fight_betting',
                'match betting': 'fight_betting',
                'fight betting': 'fight_betting',
                'total rounds': 'total_rounds',
                'round betting': 'total_rounds',
                'go the distance': 'go_the_distance',
                'method of victory': 'method_of_victory',
                'winning method': 'method_of_victory',
            };

            const markets = {};

            // Find all market sections
            const sections = Array.from(document.querySelectorAll(
                'article[id^="OB_EV"], section, [class*="market"], [class*="accordion"], [class*="group"]'
            ));

            for (const sec of sections) {
                // Find the market header
                const hdrEl = sec.querySelector('h2,h3,h4,[class*="header"],[class*="title"],[class*="name"]');
                if (!hdrEl) continue;
                const hdr = clean(hdrEl.innerText).toLowerCase();

                let mk = null;
                for (const [key, val] of Object.entries(MARKET_MAP)) {
                    if (hdr.includes(key)) { mk = val; break; }
                }
                if (!mk) continue;

                // Find all selection+odds pairs in this section
                const rows = [];
                const els = Array.from(sec.querySelectorAll('*'));
                const seen = new Set();

                for (let i = 0; i < els.length; i++) {
                    const t = clean(els[i].innerText || '');
                    if (!isFrac(t) || els[i].children.length > 1) continue;

                    // Find selection name - look back for short text
                    for (let j = i-1; j >= Math.max(0, i-8); j--) {
                        const s = clean(els[j].innerText || '');
                        if (s && s.length > 1 && s.length < 60 && !isFrac(s) && els[j].children.length <= 3) {
                            const key = s + t;
                            if (!seen.has(key)) {
                                seen.add(key);
                                rows.push({ selection: s, odds: t });
                            }
                            break;
                        }
                    }
                }

                if (rows.length) {
                    markets[mk] = (markets[mk] || []).concat(rows);
                }
            }

            return { title, markets };
        }
    """)

def main():
    all_fights = {}
    all_ob_ev_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=is_github_actions())
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        # Step 1: get moneylines from list pages + competition hub URLs
        comp_urls = set()
        for list_url in LIST_URLS:
            print(f"\nList page: {list_url}")
            try:
                page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(7)
            except Exception:
                continue

            # Moneylines
            lines = [clean(x) for x in page.locator("body").inner_text().splitlines() if clean(x)]
            for i in range(len(lines) - 3):
                f1, f2, o1, o2 = lines[i], lines[i+1], lines[i+2], lines[i+3]
                if len(f1.split()) >= 2 and len(f2.split()) >= 2 and is_frac(o1) and is_frac(o2):
                    name = f"{f1} vs {f2}"
                    if name not in all_fights:
                        all_fights[name] = {
                            "bookmaker": "WilliamHill",
                            "fight_name": name,
                            "url": list_url,
                            "markets": {"fight_betting": [
                                {"selection": f1, "odds": o1},
                                {"selection": f2, "odds": o2},
                            ]},
                        }

            # Competition hub links
            links = page.evaluate("""
                () => [...new Set(
                    Array.from(document.querySelectorAll('a[href*="/ufc/competitions/"]'))
                    .map(a => a.href)
                    .filter(h => h.includes('/matches'))
                )]
            """)
            for l in links:
                comp_urls.add(l)

        print(f"\nCompetition hubs: {len(comp_urls)}")

        # Step 2: get OB_EV IDs from each competition hub
        for comp_url in comp_urls:
            print(f"\nCompetition: {comp_url}")
            ids = get_ob_ev_ids(page, comp_url)
            all_ob_ev_ids.update(ids)

        print(f"\nTotal fight pages to scrape: {len(all_ob_ev_ids)}")

        # Step 3: scrape each fight page
        for i, ob_ev_id in enumerate(all_ob_ev_ids, 1):
            print(f"\n[{i}/{len(all_ob_ev_ids)}]", end=" ")
            result = scrape_fight_page(page, ob_ev_id)
            if not result:
                continue

            title = result.get("title", "")
            markets = result.get("markets", {})

            if not title:
                print(f"No title found")
                continue

            print(f"{title} | {list(markets.keys())}")

            # Match to existing fight
            title_norm = title.lower().replace(" v ", " vs ")
            matched = None
            for fname in all_fights:
                parts = [p.strip() for p in fname.lower().split(" vs ")]
                if all(p in title_norm for p in parts):
                    matched = fname
                    break

            entry = all_fights.get(matched) or {
                "bookmaker": "WilliamHill",
                "fight_name": title,
                "url": f"{BASE}/OB_EV{ob_ev_id}",
                "markets": {},
            }
            for mk, rows in markets.items():
                if mk not in entry["markets"] or not entry["markets"][mk]:
                    entry["markets"][mk] = rows

            if matched:
                all_fights[matched] = entry
            else:
                all_fights[title] = entry

        browser.close()

    fights = list(all_fights.values())
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "williamhill",
        "bookmaker": "WilliamHill",
        "count": len(fights),
        "fights": fights,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ Saved {len(fights)} fights")
    for f in fights:
        print(f"  - {f['fight_name']} | {list(f['markets'].keys())}")

if __name__ == "__main__":
    main()