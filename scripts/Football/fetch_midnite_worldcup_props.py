"""
fetch_midnite_worldcup_props.py - Midnite World Cup 2026 Props

Markets:
  All tab:     Match Result, Total Goals O/U, BTTS, Double Chance,
               Half Result 1H/2H, HT/FT, Total Shots on Target (combined),
               Total Shots (combined)
  Players tab: Player Carded, Player Shots on Target, Player Fouls Committed,
               Player Fouls Won, Player to Score, Player Shots
  Cards tab:   Total Match Cards
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT            = Path(__file__).resolve().parents[2]
OUTPUT_FILE     = ROOT / "football" / "data" / "midnite_worldcup_props.json"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
MONEYLINES_FILE = ROOT / "football" / "data" / "midnite_worldcup_moneylines.json"
PROFILE_DIR     = ROOT / "scripts" / "Football" / "midnite_profile"

COMPETITION_ID = "38826387"
BASE_URL   = f"https://www.midnite.com/sports/football/world-cup-2026-{COMPETITION_ID}/"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MAX_MATCHES = 15

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def frac(s):
    s = (s or "").strip().upper()
    if s in ("EVS", "EVENS"): return 2.0
    try: return round(float(Fraction(s)) + 1.0, 4)
    except: return None

def is_frac(s):
    return bool(re.match(r"^\d+\/\d+$", s.strip()))

def load_matches():
    if MONEYLINES_FILE.exists():
        return json.loads(MONEYLINES_FILE.read_text(encoding="utf-8")).get("matches", [])[:MAX_MATCHES]
    return []

def parse_section(lines, heading, n=80):
    try:
        idx = next(i for i, l in enumerate(lines) if l == heading)
        return lines[idx: idx + n]
    except StopIteration:
        return []

def get_lines(page):
    return [l.strip() for l in (page.evaluate("document.body.innerText") or "").split("\n") if l.strip()]

# ---------------------------------------------------------------------------
# Tab clicking
# ---------------------------------------------------------------------------
def click_tab(page, name):
    """Click a tab by data-cy=Tab, verify it becomes active, retry up to 3x."""
    for _ in range(3):
        page.evaluate(f"""
            const btn = Array.from(document.querySelectorAll('[data-cy="Tab"]'))
                .find(b => b.innerText.trim() === '{name}');
            if (btn) {{
                btn.dispatchEvent(new PointerEvent('pointerdown', {{bubbles:true,cancelable:true}}));
                btn.dispatchEvent(new PointerEvent('pointerup',   {{bubbles:true,cancelable:true}}));
                btn.dispatchEvent(new MouseEvent('click',         {{bubbles:true,cancelable:true}}));
            }}
        """)
        time.sleep(1.2)
        active = page.evaluate(f"""
            const btn = Array.from(document.querySelectorAll('[data-cy="Tab"]'))
                .find(b => b.innerText.trim() === '{name}');
            btn ? btn.className.includes('brand') : false;
        """)
        if active:
            break

def expand_accordion(page, name):
    """Expand accordion using real mouse click via bounding box."""
    try:
        box = page.evaluate(f"""
            (() => {{
                const el = Array.from(document.querySelectorAll('*'))
                    .find(e => e.childElementCount === 0 && e.innerText?.trim() === '{name}');
                if (!el) return null;
                const target = el.parentElement?.parentElement;
                if (!target) return null;
                target.scrollIntoView({{behavior:'instant', block:'center'}});
                const rect = target.getBoundingClientRect();
                return {{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
            }})()
        """)
        if box and box.get('x') and box.get('y'):
            page.mouse.click(box['x'], box['y'])
            time.sleep(0.6)
    except Exception:
        pass

def dismiss_popups(page):
    for sel in ["button:has-text('Got it')", "button:has-text('Accept all')",
                "button:has-text('Accept')", "button:has-text('Save')",
                "button:has-text('Reject all')", "[aria-label='Close']"]:
        try: page.click(sel, timeout=800); time.sleep(0.2)
        except: pass
    try:
        page.evaluate("""
            Array.from(document.querySelectorAll('button'))
                .filter(b => ['×','✕','✖'].includes(b.innerText?.trim()))
                .forEach(b => b.click());
        """)
    except: pass
    try: page.keyboard.press("Escape")
    except: pass
    time.sleep(0.3)

# ---------------------------------------------------------------------------
# Player market parser
# DOM structure: all player names listed first (with team/jersey junk between),
# then column header lines, then all odds in column-major order.
# ---------------------------------------------------------------------------
def parse_player_market(lines, heading, col_keys, skip_words=None):
    seg = parse_section(lines, heading, 500)  # needs 300-500 lines for full player lists
    if not seg: return None

    junk = {
        "all", "show all", "show less", "combined", "match",
        "1st half", "2nd half",
        "carded anytime", "sent off anytime", "carded first",
        "goalscorers", "multi", "method", "time", "first", "last",
        "to score", "anytime goalscorer", "anytime",
        "player shots on target", "player shots", "player fouls committed",
        "player fouls won", "player to score", "player carded",
        "player to score or assist", "corners", "cards", "player saves",
    }
    if skip_words:
        junk.update(w.lower() for w in skip_words)
    col_lower = {c.lower() for c in col_keys}

    names = []
    fracs = []
    in_odds = False

    for l in seg[1:]:
        ll = l.strip()
        lll = ll.lower()

        if is_frac(ll):
            in_odds = True
            fracs.append(ll)
            continue

        if in_odds:
            continue

        if re.match(r"^[A-Z]{2,4}(\s+\d+)?$", ll): continue
        if re.match(r"^\d+$", ll): continue
        if re.match(r"^\d+\+$", ll): continue
        if lll in junk or lll in col_lower: continue
        if len(ll) < 4: continue
        names.append(ll)

    if not names or not fracs: return None

    n_cols = len(col_keys)
    for nc in range(n_cols, 0, -1):
        if len(fracs) % nc == 0:
            n_cols = nc
            col_keys = col_keys[:nc]
            break

    n_players = len(fracs) // n_cols
    result = {}
    for pi, name in enumerate(names[:n_players]):
        result[name] = {}
        for ci, ck in enumerate(col_keys):
            idx = ci * n_players + pi
            result[name][ck] = frac(fracs[idx]) if idx < len(fracs) else None
    return result or None

# ---------------------------------------------------------------------------
# Scrape one match
# ---------------------------------------------------------------------------
def select_filter(page, market_name, option):
    """Click v-popper filter dropdown then select option by mouse."""
    try:
        box = page.evaluate(f"""
            (() => {{
                const el = Array.from(document.querySelectorAll('*'))
                    .find(e => e.childElementCount === 0 && e.innerText?.trim() === '{market_name}');
                if (!el) return null;
                const group = el.parentElement?.parentElement;
                const sib = group?.parentElement?.children[1];
                if (!sib) return null;
                const popper = Array.from(sib.querySelectorAll('*'))
                    .find(e => e.className?.includes('v-popper'));
                if (!popper) return null;
                const r = popper.getBoundingClientRect();
                return {{x: r.x + r.width/2, y: r.y + r.height/2}};
            }})()
        """)
        if not box: return False
        page.mouse.click(box['x'], box['y'])
        time.sleep(0.4)
        box2 = page.evaluate(f"""
            (() => {{
                const opts = Array.from(document.querySelectorAll('*'))
                    .filter(e => e.childElementCount === 0 && e.innerText?.trim() === '{option}');
                const vis = opts.find(e => {{
                    const r = e.getBoundingClientRect();
                    return r.y > 0 && r.y < window.innerHeight && r.width > 0;
                }});
                if (!vis) return null;
                const r = vis.getBoundingClientRect();
                return {{x: r.x + r.width/2, y: r.y + r.height/2}};
            }})()
        """)
        if not box2: return False
        page.mouse.click(box2['x'], box2['y'])
        time.sleep(0.5)
        return True
    except Exception:
        return False

def parse_thresholds(lines, heading, n=25):
    """Parse N+ threshold markets from lines."""
    seg = parse_section(lines, heading, n)
    result = {}
    thresh = [l for l in seg if re.match(r"^.+\d+\+$", l) or re.match(r"^\d+\+$", l)]
    fracs  = [l for l in seg if is_frac(l)]
    for i,t in enumerate(thresh):
        m = re.search(r"(\d+)\+", t)
        if m: result[f"over_{m.group(1)}"] = frac(fracs[i]) if i < len(fracs) else None
    return result or None

def scrape_match(page, match):
    url  = match.get("url") or f"{BASE_URL}{match['match_id']}-{match['event_id']}"
    home = match.get("home", "")
    away = match.get("away", "")

    page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    try:
        page.wait_for_selector('[data-cy="Tab"]', timeout=12_000)
    except Exception:
        # Try waiting for any button as fallback
        try:
            page.wait_for_selector('button', timeout=8_000)
            time.sleep(1.0)
        except Exception as e:
            print(f" SKIP ({e})")
            return None
    dismiss_popups(page)
    time.sleep(0.5)

    props = {}

    # ------------------------------------------------------------------ #
    # ALL tab
    # ------------------------------------------------------------------ #
    click_tab(page, "All")

    # Click Show all to expand Total Goals to all lines
    try:
        page.evaluate("""
            Array.from(document.querySelectorAll('button'))
                .filter(b => b.innerText?.trim() === 'Show all')
                .forEach(b => {
                    b.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true,cancelable:true}));
                    b.dispatchEvent(new PointerEvent('pointerup', {bubbles:true,cancelable:true}));
                    b.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true}));
                });
        """)
        time.sleep(0.8)
    except Exception:
        pass

    # Expand all needed accordions using real mouse clicks
    for accordion_name in ["Both Teams To Score", "Double Chance", "Half Result", "Half Time/Full Time",
                           "Total Shots on Target", "Total Shots"]:
        expand_accordion(page, accordion_name)

    lines = get_lines(page)

    # Match Result
    seg = parse_section(lines, "Match Result", 15)
    f   = [l for l in seg if is_frac(l)]
    if len(f) >= 3:
        props["match_result"] = {"home": frac(f[0]), "draw": frac(f[1]), "away": frac(f[2])}

    # Total Goals O/U
    # DOM layout after Show all:
    # line values (0.5, 1.5...) → "Over" label → "Under" label →
    # Over odds row (n values) → Under odds row (n values)
    seg = parse_section(lines, "Total Goals", 50)
    lvs = [l for l in seg if re.match(r"^\d+\.\d+$", l)]
    # Skip "Over"/"Under" label lines, collect only fractions
    f   = [l for l in seg if is_frac(l)]
    tg  = {}
    n   = len(lvs)
    if n > 0 and len(f) >= n * 2:
        for i, lv in enumerate(lvs):
            k = lv.replace(".", "_")
            tg[f"over_{k}"]  = frac(f[i])
            tg[f"under_{k}"] = frac(f[i + n])
    elif n > 0 and len(f) >= n:
        for i, lv in enumerate(lvs):
            k = lv.replace(".", "_")
            tg[f"over_{k}"] = frac(f[i])
    if tg: props["total_goals"] = tg

    # BTTS — read directly from DOM sibling to avoid toggle issues
    expand_accordion(page, "Both Teams To Score")
    btts_data = page.evaluate("""
        (() => {
            const el = Array.from(document.querySelectorAll('*'))
                .find(e => e.childElementCount===0 && e.innerText?.trim()==='Both Teams To Score');
            if (!el) return null;
            const sib = el.parentElement?.parentElement?.parentElement?.children[1];
            if (!sib) return null;
            const lines = sib.innerText.split('\\n').map(l=>l.trim()).filter(Boolean);
            const fracs = lines.filter(l => /^\\d+\\/\\d+$/.test(l));
            if (fracs.length < 2) return null;
            function toDecimal(f) {
                const [a,b] = f.split('/').map(Number);
                return Math.round((a/b+1)*10000)/10000;
            }
            // Row-major: first 4 fracs = Yes odds, next 4 = No odds
            return {yes: toDecimal(fracs[0]), no: toDecimal(fracs[4] || fracs[1])};
        })()
    """)
    if btts_data: props["btts"] = btts_data

    # Double Chance
    seg    = parse_section(lines, "Double Chance", 15)
    f      = [l for l in seg if is_frac(l)]
    labels = [l for l in seg if " or " in l]
    dc = {}
    for k, label in enumerate(labels[:3]):
        lu  = label.upper()
        key = "home_or_draw" if ("DRAW" in lu and home.upper() in lu) else \
              "away_or_draw" if ("DRAW" in lu and away.upper() in lu) else "home_or_away"
        dc[key] = frac(f[k]) if k < len(f) else None
    if dc: props["double_chance"] = dc

    # Half Result
    seg = parse_section(lines, "Half Result", 20)
    f   = [l for l in seg if is_frac(l)]
    if len(f) >= 3:
        props["half_result_1h"] = {"home": frac(f[0]), "draw": frac(f[1]), "away": frac(f[2])}
    if len(f) >= 6:
        props["half_result_2h"] = {"home": frac(f[3]), "draw": frac(f[4]), "away": frac(f[5])}

    # HT/FT
    seg    = parse_section(lines, "Half Time/Full Time", 40)
    labels = [l for l in seg if "/" in l and not is_frac(l)
              and not re.search(r"\d{2}:\d{2}", l)
              and not any(x in l for x in ["World Cup", "http", "Midnite"])]
    f = [l for l in seg if is_frac(l)]
    htft = {}
    for k, label in enumerate(labels[:9]):
        parts = [p.strip() for p in label.split("/")]
        if len(parts) == 2:
            def norm(p):
                if p.upper() == "DRAW": return "draw"
                if p.upper() == home.upper(): return "home"
                if p.upper() == away.upper(): return "away"
                return p.lower()
            htft[f"{norm(parts[0])}_{norm(parts[1])}"] = frac(f[k]) if k < len(f) else None
    if htft: props["htft"] = htft

    # Total Shots on Target — Combined, Home, Away
    expand_accordion(page, "Total Shots on Target")
    for filter_name, prop_key in [("Combined","total_shots_on_target"), (home,"home_shots_on_target"), (away,"away_shots_on_target")]:
        select_filter(page, "Total Shots on Target", filter_name)
        # Re-expand if filter click collapsed accordion
        d = page.evaluate(f"""
            (() => {{
                const el = Array.from(document.querySelectorAll('*'))
                    .find(e => e.childElementCount===0 && e.innerText?.trim()==='Total Shots on Target');
                if (!el) return null;
                const sib = el.parentElement?.parentElement?.parentElement?.children[1];
                if (!sib || sib.innerText.trim().length < 5) return null;
                const lines = sib.innerText.split('\\n').map(l=>l.trim()).filter(Boolean);
                const thresh = lines.filter(l => /\\d+\\+/.test(l));
                const fracs  = lines.filter(l => /^\\d+\\/\\d+$/.test(l));
                const result = {{}};
                thresh.forEach((t,i) => {{
                    const m = t.match(/(\\d+)\\+/);
                    if (m && fracs[i]) {{
                        const [a,b] = fracs[i].split('/').map(Number);
                        result['over_' + m[1]] = Math.round((a/b + 1) * 10000) / 10000;
                    }}
                }});
                return Object.keys(result).length ? result : null;
            }})()
        """)
        if not d:
            # Accordion closed — re-expand and try again
            expand_accordion(page, "Total Shots on Target")
            d = page.evaluate(f"""
                (() => {{
                    const el = Array.from(document.querySelectorAll('*'))
                        .find(e => e.childElementCount===0 && e.innerText?.trim()==='Total Shots on Target');
                    if (!el) return null;
                    const sib = el.parentElement?.parentElement?.parentElement?.children[1];
                    if (!sib) return null;
                    const lines = sib.innerText.split('\\n').map(l=>l.trim()).filter(Boolean);
                    const thresh = lines.filter(l => /\\d+\\+/.test(l));
                    const fracs  = lines.filter(l => /^\\d+\\/\\d+$/.test(l));
                    const result = {{}};
                    thresh.forEach((t,i) => {{
                        const m = t.match(/(\\d+)\\+/);
                        if (m && fracs[i]) {{
                            const [a,b] = fracs[i].split('/').map(Number);
                            result['over_' + m[1]] = Math.round((a/b + 1) * 10000) / 10000;
                        }}
                    }});
                    return Object.keys(result).length ? result : null;
                }})()
            """)
        if d: props[prop_key] = d

    # Total Shots — Combined, Home, Away
    expand_accordion(page, "Total Shots")
    for filter_name, prop_key in [("Combined","total_shots"), (home,"home_shots"), (away,"away_shots")]:
        select_filter(page, "Total Shots", filter_name)
        d = page.evaluate(f"""
            (() => {{
                const el = Array.from(document.querySelectorAll('*'))
                    .find(e => e.childElementCount===0 && e.innerText?.trim()==='Total Shots');
                if (!el) return null;
                const sib = el.parentElement?.parentElement?.parentElement?.children[1];
                if (!sib || sib.innerText.trim().length < 5) return null;
                const lines = sib.innerText.split('\\n').map(l=>l.trim()).filter(Boolean);
                const thresh = lines.filter(l => /\\d+\\+/.test(l));
                const fracs  = lines.filter(l => /^\\d+\\/\\d+$/.test(l));
                const result = {{}};
                thresh.forEach((t,i) => {{
                    const m = t.match(/(\\d+)\\+/);
                    if (m && fracs[i]) {{
                        const [a,b] = fracs[i].split('/').map(Number);
                        result['over_' + m[1]] = Math.round((a/b + 1) * 10000) / 10000;
                    }}
                }});
                return Object.keys(result).length ? result : null;
            }})()
        """)
        if not d:
            expand_accordion(page, "Total Shots")
            d = page.evaluate(f"""
                (() => {{
                    const el = Array.from(document.querySelectorAll('*'))
                        .find(e => e.childElementCount===0 && e.innerText?.trim()==='Total Shots');
                    if (!el) return null;
                    const sib = el.parentElement?.parentElement?.parentElement?.children[1];
                    if (!sib) return null;
                    const lines = sib.innerText.split('\\n').map(l=>l.trim()).filter(Boolean);
                    const thresh = lines.filter(l => /\\d+\\+/.test(l));
                    const fracs  = lines.filter(l => /^\\d+\\/\\d+$/.test(l));
                    const result = {{}};
                    thresh.forEach((t,i) => {{
                        const m = t.match(/(\\d+)\\+/);
                        if (m && fracs[i]) {{
                            const [a,b] = fracs[i].split('/').map(Number);
                            result['over_' + m[1]] = Math.round((a/b + 1) * 10000) / 10000;
                        }}
                    }});
                    return Object.keys(result).length ? result : null;
                }})()
            """)
        if d: props[prop_key] = d

    # ------------------------------------------------------------------ #
    # CARDS tab
    # ------------------------------------------------------------------ #
    click_tab(page, "Cards")
    time.sleep(0.8)
    lines_c = get_lines(page)
    cards_idx = [i for i,l in enumerate(lines_c) if l == "Cards"]
    if len(cards_idx) >= 2:
        seg = lines_c[cards_idx[1]:cards_idx[1]+20]
        thresh = [l for l in seg if re.match(r"^\d+\+$",l)]
        f = [l for l in seg if is_frac(l)]
        d = {f"over_{t.replace('+','')}":frac(f[i]) if i<len(f) else None for i,t in enumerate(thresh)}
        if d: props["total_cards"] = d

    # ------------------------------------------------------------------ #
    # CORNERS tab
    # ------------------------------------------------------------------ #
    click_tab(page, "Corners")
    time.sleep(0.8)
    lines_cn = get_lines(page)
    ci = [i for i,l in enumerate(lines_cn) if l == "Corners"]
    if ci:
        seg = lines_cn[ci[0]:ci[0]+20]
        thresh = [l for l in seg if re.match(r"^\d+\+$",l)]
        f = [l for l in seg if is_frac(l)]
        d = {f"over_{t.replace('+','')}":frac(f[i]) if i<len(f) else None for i,t in enumerate(thresh)}
        if d: props["total_corners"] = d
    twmc = next((i for i,l in enumerate(lines_cn) if l=="Team with Most Corners"),None)
    if twmc is not None:
        f = [l for l in lines_cn[twmc:twmc+10] if is_frac(l)]
        if len(f) >= 3:
            props["team_most_corners"] = {"home":frac(f[0]),"draw":frac(f[1]),"away":frac(f[2])}

    # ------------------------------------------------------------------ #
    # PLAYERS tab
    # ------------------------------------------------------------------ #
    click_tab(page, "Players")
    time.sleep(1.5)
    try:
        page.evaluate("""
            Array.from(document.querySelectorAll('button'))
                .filter(b => b.innerText?.trim() === 'Show all')
                .forEach(b => {
                    b.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true}));
                    b.dispatchEvent(new PointerEvent('pointerup',  {bubbles:true,cancelable:true}));
                    b.dispatchEvent(new MouseEvent('click',        {bubbles:true,cancelable:true}));
                });
        """)
        time.sleep(1.0)
    except Exception:
        pass
    expand_accordion(page, "Player Shots")
    try:
        page.evaluate("""
            Array.from(document.querySelectorAll('button'))
                .filter(b => b.innerText?.trim() === 'Show all')
                .forEach(b => {
                    b.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true}));
                    b.dispatchEvent(new PointerEvent('pointerup',  {bubbles:true,cancelable:true}));
                    b.dispatchEvent(new MouseEvent('click',        {bubbles:true,cancelable:true}));
                });
        """)
        time.sleep(0.8)
    except Exception:
        pass
    lines2 = get_lines(page)
    skip = [home, away]
    p = parse_player_market(lines2,"Player Carded",["carded_anytime","sent_off_anytime","carded_first"],skip)
    if p: props["player_carded"] = p
    p = parse_player_market(lines2,"Player Shots on Target",["1+","2+","3+","4+"],skip)
    if p: props["player_shots_on_target"] = p
    p = parse_player_market(lines2,"Player Fouls Committed",["1+","2+","3+","4+","5+"],skip)
    if p: props["player_fouls_committed"] = p
    p = parse_player_market(lines2,"Player Fouls Won",["1+","2+","3+","4+","5+"],skip)
    if p: props["player_fouls_won"] = p
    p = parse_player_market(lines2,"Player to Score",["to_score","first","last"],skip)
    if p: props["player_to_score"] = p
    p = parse_player_market(lines2,"Player Shots",["1+","2+","3+","4+","5+","6+"],skip)
    if p: props["player_shots"] = p

    if not props: return None
    return {
        "match_id":  match.get("match_id",""),
        "event_id":  match.get("event_id",""),
        "home":      home,
        "away":      away,
        "kickoff":   match.get("kickoff",""),
        "bookmaker": "Midnite",
        "url":       url,
        "markets":   props,
    }
def main():
    print("=" * 60)
    print("Midnite — World Cup 2026 Props")
    print("=" * 60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: run: pip install playwright && playwright install chromium")
        sys.exit(1)

    matches = load_matches()
    if not matches:
        print("ERROR: No matches found. Run fetch_midnite_worldcup_moneylines.py first.")
        sys.exit(1)

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  Scraping props for {len(matches)} matches …\n")
    results = []

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 900},
            user_agent=USER_AGENT,
            locale="en-GB",
        )
        page = context.new_page()

        for i, match in enumerate(matches, 1):
            label = f"{match.get('home','?')} vs {match.get('away','?')}"
            print(f"  [{i:02d}/{len(matches)}] {label}", end="", flush=True)
            try:
                result = scrape_match(page, match)
            except Exception as e:
                print(f" ✗ error: {e}")
                results.append(None)
                continue
            if result:
                print(f" ✓ {len(result['markets'])} markets: {', '.join(result['markets'].keys())}")
                results.append(result)
            else:
                print(" ✗ skipped")

        context.close()

    results = [r for r in results if r]
    if not results:
        print("\n✗ No props scraped.")
        sys.exit(1)

    OUTPUT_FILE.write_text(
        json.dumps({"bookmaker": "Midnite", "competition": "FIFA World Cup 2026",
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "matches": results}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"\n✓ Saved {len(results)} matches → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()