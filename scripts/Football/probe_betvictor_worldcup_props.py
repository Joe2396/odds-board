#!/usr/bin/env python3
"""
probe_betvictor_worldcup_props.py

First BetVictor props probe for Odds Board.

What it does:
- Reads football/data/betvictor_worldcup_moneylines.json
- Opens the saved BetVictor match URLs
- Clicks obvious "show more / markets / all" buttons
- Dumps full page text + detected links/buttons to football/debug/betvictor_props_probe
- Does NOT write the final props JSON yet

Run:
  python scripts\Football\probe_betvictor_worldcup_props.py
"""

import json
import re
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
MONEYLINES_PATH = ROOT / "football" / "data" / "betvictor_worldcup_moneylines.json"
DEBUG_DIR = ROOT / "football" / "debug" / "betvictor_props_probe"

MAX_MATCHES = 3
HEADLESS = False

WANTED_WORDS = [
    "Both Teams To Score",
    "Total Goals",
    "Double Chance",
    "Half Time",
    "Anytime Goalscorer",
    "First Goalscorer",
    "Player Shots",
    "Shots On Target",
    "Player Cards",
    "To Be Carded",
    "To Assist",
    "Assists",
    "Corners",
    "Cards",
    "Fouls",
]


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")


def load_match_urls():
    if not MONEYLINES_PATH.exists():
        raise FileNotFoundError(f"Missing {MONEYLINES_PATH}")

    data = json.loads(MONEYLINES_PATH.read_text(encoding="utf-8"))
    matches = data.get("matches") or data.get("results") or []

    out = []
    for m in matches:
        home = m.get("home_team") or m.get("home") or ""
        away = m.get("away_team") or m.get("away") or ""
        match = m.get("match") or f"{home} v {away}".strip()
        url = m.get("source_url") or m.get("url") or ""
        if not url:
            continue
        out.append({
            "match": clean(match),
            "home": clean(home),
            "away": clean(away),
            "url": url,
        })

    return out


def safe_click_text(page, patterns, max_clicks=20):
    clicked = 0

    for _ in range(max_clicks):
        did_click = False

        for pat in patterns:
            try:
                loc = page.get_by_text(re.compile(pat, re.I)).first
                if loc and loc.is_visible(timeout=700):
                    loc.click(timeout=1500)
                    page.wait_for_timeout(650)
                    clicked += 1
                    did_click = True
                    break
            except Exception:
                pass

        if did_click:
            continue

        try:
            buttons = page.locator("button, a, [role=button]").all()
        except Exception:
            buttons = []

        for b in buttons[:80]:
            try:
                txt = clean(b.inner_text(timeout=300))
                if not txt:
                    continue
                if re.search(r"(show more|view more|more markets|all markets|see more|expand)", txt, re.I):
                    b.click(timeout=1200)
                    page.wait_for_timeout(650)
                    clicked += 1
                    did_click = True
                    break
            except Exception:
                continue

        if not did_click:
            break

    return clicked


def dump_page(page, match_name):
    slug = slugify(match_name) or "match"
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    text = page.locator("body").inner_text(timeout=10000)
    (DEBUG_DIR / f"{slug}.txt").write_text(text, encoding="utf-8")

    buttons = []
    try:
        for el in page.locator("button, a, [role=button]").all()[:250]:
            try:
                txt = clean(el.inner_text(timeout=300))
                href = ""
                try:
                    href = el.get_attribute("href") or ""
                except Exception:
                    pass
                if txt or href:
                    buttons.append({"text": txt, "href": href})
            except Exception:
                pass
    except Exception:
        pass

    lines = [clean(x) for x in text.splitlines() if clean(x)]
    wanted_hits = []
    for i, line in enumerate(lines):
        if any(w.lower() in line.lower() for w in WANTED_WORDS):
            wanted_hits.append({
                "line_no": i,
                "line": line,
                "before": lines[max(0, i-3):i],
                "after": lines[i+1:i+8],
            })

    data = {
        "match": match_name,
        "url": page.url,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "buttons": buttons,
        "wanted_hits": wanted_hits,
        "line_count": len(lines),
    }
    (DEBUG_DIR / f"{slug}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Debug text: {DEBUG_DIR / (slug + '.txt')}")
    print(f"Debug json: {DEBUG_DIR / (slug + '.json')}")
    print(f"Wanted market hits: {len(wanted_hits)}")


def main():
    matches = load_match_urls()
    print(f"Loaded {len(matches)} BetVictor match URLs from {MONEYLINES_PATH}")

    matches = matches[:MAX_MATCHES]
    print(f"Probing first {len(matches)} matches")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(
            viewport={"width": 1500, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        page.set_default_timeout(8000)

        for idx, m in enumerate(matches, 1):
            print("\n" + "=" * 50)
            print(f"{idx}/{len(matches)} {m['match']}")
            print(m["url"])

            try:
                page.goto(m["url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(4500)

                for pat in [r"accept all", r"accept", r"agree", r"continue", r"close", r"ok"]:
                    try:
                        loc = page.get_by_text(re.compile(pat, re.I)).first
                        if loc and loc.is_visible(timeout=800):
                            loc.click(timeout=1500)
                            page.wait_for_timeout(1000)
                    except Exception:
                        pass

                for _ in range(8):
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(450)

                clicked = safe_click_text(
                    page,
                    [r"show more", r"view more", r"more markets", r"all markets", r"see more"],
                    max_clicks=25,
                )
                print(f"Clicked expand buttons: {clicked}")

                page.keyboard.press("Home")
                page.wait_for_timeout(500)
                for _ in range(10):
                    page.mouse.wheel(0, 1000)
                    page.wait_for_timeout(300)

                dump_page(page, m["match"])

            except Exception as e:
                print(f"FAILED {m['match']}: {type(e).__name__}: {e}")

        ctx.close()
        browser.close()

    print("\nDone.")
    print(f"Open debug folder: {DEBUG_DIR}")


if __name__ == "__main__":
    main()
