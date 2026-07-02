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
MAX_MATCHES = 3


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


# JS that expands "Show all" inside a named section.
_MIDNITE_GRID_JS = r"""
(heading) => {
  const all = [...document.querySelectorAll('*')];
  const hdr = all.find(e => {
    const own = [...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('');
    return own === heading;
  });
  if (!hdr) return null;
  let sec = hdr;
  for (let i=0;i<10;i++){ sec = sec.parentElement; if(!sec) break; if((sec.innerText||'').match(/\d+\/\d+/)) break; }
  if (!sec) return null;
  for (let pass=0; pass<2; pass++){
    const sa = [...sec.querySelectorAll('*')].find(e=>{
      const own=[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('');
      return own==='Show all';
    });
    if (sa) {
      sa.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
      sa.dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));
      sa.dispatchEvent(new MouseEvent('click',{bubbles:true}));
    } else break;
  }
  return true;
}
"""

# JS that reads a section's grid: maps each odds button to its player row
# (nearest y) and threshold column (nearest x). Mirrors the visual grid and
# tolerates missing cells, unlike flattened text.
_MIDNITE_READ_JS = r"""
(heading) => {
  const all = [...document.querySelectorAll('*')];
  const hdr = all.find(e => {
    const own = [...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('');
    return own === heading;
  });
  if (!hdr) return null;
  let sec = hdr;
  for (let i=0;i<10;i++){ sec = sec.parentElement; if(!sec) break; if((sec.innerText||'').match(/\d+\/\d+/)) break; }
  if (!sec) return null;

  const mid = el => { const r = el.getBoundingClientRect(); return {x:r.left+r.width/2, y:r.top+r.height/2}; };

  const names = [...sec.querySelectorAll('span.line-clamp-2')]
    .map(el => ({ name: el.textContent.trim(), ...mid(el) }))
    .filter(n => n.name.length > 2);

  let heads = [...sec.querySelectorAll('*')].filter(e=>{
    const own=[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('');
    return /^\d+\+$/.test(own);
  }).map(e=>({label:e.textContent.trim(), x:mid(e).x}));
  const colMap={}; heads.forEach(h=>{ if(!(h.label in colMap)) colMap[h.label]=h.x; });
  let cols = Object.entries(colMap).sort((a,b)=>a[1]-b[1]);

  const odds = [...sec.querySelectorAll('button')].map(b=>{
    const t=(b.innerText||'').trim(); const m=mid(b); return {t, x:m.x, y:m.y};
  }).filter(o=>/^\d+\/\d+$|^EVS$/.test(o.t));

  if (cols.length === 0 && odds.length) {
    const xs=[...new Set(odds.map(o=>Math.round(o.x/5)*5))].sort((a,b)=>a-b);
    cols = xs.map((x,i)=>[String(i),x]);
  }

  const result = {};
  for (const o of odds) {
    let bn=null,bd=1e9; for(const n of names){const d=Math.abs(n.y-o.y); if(d<bd){bd=d;bn=n;}}
    let bc=null,cd=1e9; for(const [lab,cx] of cols){const d=Math.abs(cx-o.x); if(d<cd){cd=d;bc=lab;}}
    if(bn&&bc&&bd<25&&cd<45){ (result[bn.name]=result[bn.name]||{})[bc]=o.t; }
  }
  return { colLabels: cols.map(c=>c[0]), grid: result };
}
"""


def scrape_player_market_grid(page, heading, col_keys):
    """
    Geometry-based extraction of one player-prop section.
    Returns {player_name: {col_key: decimal_odds}} matching the visual grid.
    col_keys maps the on-screen column order (left->right) to internal keys.
    """
    import time as _t
    try:
        ok = page.evaluate(_MIDNITE_GRID_JS, heading)
    except Exception:
        ok = None
    if not ok:
        return None
    _t.sleep(0.6)
    try:
        data = page.evaluate(_MIDNITE_READ_JS, heading)
    except Exception:
        return None
    if not data or not data.get("grid"):
        return None

    col_labels = data.get("colLabels", [])
    grid = data["grid"]
    result = {}
    for player, cells in grid.items():
        out = {}
        for screen_label, frac_str in cells.items():
            if screen_label in col_labels:
                pos = col_labels.index(screen_label)
            else:
                try: pos = int(screen_label)
                except Exception: continue
            if pos < len(col_keys):
                dec = frac(frac_str)
                if dec is not None:
                    out[col_keys[pos]] = dec
        if out:
            result[player] = out
    return result or None

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
# DOM structure: player name, then their odds on the following lines (interleaved).
# ---------------------------------------------------------------------------
def parse_player_market(lines, heading, col_keys, skip_words=None):
    """
    DOM layout: all player names listed first (with team/jersey junk between),
    then threshold headers (1+, 2+, 3+), then ALL odds in column-major order
    (all 1+ odds first, then all 2+ odds, etc.)
    """
    seg = parse_section(lines, heading, 500)
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

    for l in seg[1:]:
        ll = l.strip()
        lll = ll.lower()

        if is_frac(ll):
            fracs.append(ll)
            continue

        # Skip junk lines
        if re.match(r"^[A-Z]{2,4}(\s+\d+)?$", ll): continue  # team codes
        if re.match(r"^\d+$", ll): continue  # jersey numbers
        if re.match(r"^\d+\+$", ll): continue  # threshold headers
        if lll in junk or lll in col_lower: continue
        if len(ll) < 4: continue

        # Only collect names if we haven't found odds yet
        # (names appear before odds in the DOM)
        if not fracs:
            names.append(ll)

    if not names or not fracs: return None

    # Odds are column-major with a stride of len(names): all of column 1's
    # odds (one per player) come first, then column 2, etc. The names list is
    # the reliable count; len(fracs) can contain trailing padding/junk.
    n_players = len(names)
    # How many full columns of odds do we actually have?
    n_cols = min(len(col_keys), len(fracs) // n_players) if n_players else 0
    if n_cols < 1:
        return None
    col_keys = col_keys[:n_cols]

    result = {}
    for pi, name in enumerate(names):
        result[name] = {}
        for ci, ck in enumerate(col_keys):
            idx = ci * n_players + pi  # column-major, stride = number of players
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

def get_midnite_market_card_lines(page, heading):
    """
    Return the smallest DOM container for one Midnite market card.

    Reading the whole page caused odds from neighbouring markets to be attached
    to Half Result. This helper scopes extraction to the exact card.
    """
    try:
        return page.evaluate(
            """(heading) => {
                const norm = value =>
                    (value || "").replace(/\\s+/g, " ").trim();

                const fraction = /(?:^|\\s)\\d+\\/\\d+(?=\\s|$)/g;

                const headings = Array.from(
                    document.querySelectorAll("body *")
                ).filter(element =>
                    element.childElementCount === 0
                    && norm(element.innerText) === heading
                );

                const candidates = [];

                for (const headingElement of headings) {
                    let node = headingElement;

                    for (
                        let depth = 0;
                        depth < 10 && node;
                        depth += 1, node = node.parentElement
                    ) {
                        const text = norm(node.innerText);
                        const prices = text.match(fraction) || [];

                        if (
                            text.includes(heading)
                            && prices.length >= 3
                        ) {
                            candidates.push({
                                text,
                                length: text.length,
                            });
                            break;
                        }
                    }
                }

                candidates.sort((a, b) => a.length - b.length);

                if (!candidates.length) {
                    return [];
                }

                return candidates[0].text
                    .split(/\\n/)
                    .map(value => value.trim())
                    .filter(Boolean);
            }""",
            heading,
        ) or []
    except Exception as error:
        print(f" Half Result card extraction failed: {error}")
        return []


def _midnite_three_way_sum(decimal_prices):
    if len(decimal_prices) != 3:
        return None
    if any(not value or value <= 1 for value in decimal_prices):
        return None
    return sum(1.0 / value for value in decimal_prices)


def parse_midnite_half_result_card(page, home, away):
    """
    Parse Midnite's first-half 1X2 prices from the exact Half Result card.

    Midnite's six-price grid is column-major:
        home 1H, home 2H,
        draw 1H, draw 2H,
        away 1H, away 2H

    The previous parser incorrectly used the first three prices, which mixed
    home 1H, home 2H and draw 1H.
    """
    expand_accordion(page, "Half Result")
    time.sleep(0.8)

    card_lines = get_midnite_market_card_lines(
        page,
        "Half Result",
    )
    fractions = [
        line for line in card_lines
        if is_frac(line)
    ]

    if len(fractions) < 3:
        print(" Half Result rejected: fewer than three prices")
        return None

    candidates = []

    # Preferred actual Midnite six-price grid: first-half prices are 0,2,4.
    if len(fractions) >= 6:
        candidates.append(
            (
                "column-major first half",
                [fractions[0], fractions[2], fractions[4]],
            )
        )

    # Fallback for a genuine row-major layout.
    candidates.append(
        (
            "row-major first half",
            fractions[:3],
        )
    )

    for layout, raw_prices in candidates:
        decimal_prices = [frac(price) for price in raw_prices]
        implied_sum = _midnite_three_way_sum(decimal_prices)

        if implied_sum is None:
            continue

        if 0.98 <= implied_sum <= 1.35:
            print(
                f" Half Result 1H: {raw_prices} "
                f"({layout}, sum {implied_sum:.3f})"
            )
            return {
                "home": decimal_prices[0],
                "draw": decimal_prices[1],
                "away": decimal_prices[2],
            }

    print(
        f" Half Result rejected: implausible prices {fractions[:6]}"
    )
    return None



# ---------------------------------------------------------------------------
# MIDNITE_MATCH_TEAM_CORNERS_V1
# Verified live on three active World Cup fixtures.
# ---------------------------------------------------------------------------
def _midnite_corner_norm(value):
    return re.sub(r"\\s+", " ", str(value or "")).strip()


def _midnite_corner_team_key(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        _midnite_corner_norm(value).lower(),
    ).strip()


def _midnite_corner_card_state(page):
    try:
        return page.evaluate(
            r"""() => {
                const norm = value => (value || "").replace(/\s+/g, " ").trim();
                const visible = element => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && rect.bottom > 0 && rect.top < window.innerHeight
                        && style.display !== "none" && style.visibility !== "hidden";
                };
                const isOdds = value => /^(?:\d+\/\d+|EVS|EVENS|EVEN)$/i.test(norm(value));
                const isThreshold = value => /^(?:.+?\s+)?\d+\+$/.test(norm(value));

                const headings = Array.from(document.querySelectorAll("body *"))
                    .filter(element => element.childElementCount === 0
                        && norm(element.innerText) === "Corners" && visible(element));
                const candidates = [];

                for (const heading of headings) {
                    let node = heading;
                    for (let depth = 0; node && node !== document.body && depth < 12;
                         node = node.parentElement, depth += 1) {
                        const leaves = Array.from(node.querySelectorAll("*"))
                            .filter(element => element.childElementCount === 0
                                && visible(element) && norm(element.innerText));
                        const odds = leaves.filter(element => isOdds(element.innerText));
                        const thresholds = leaves.filter(element => isThreshold(element.innerText));
                        const poppers = Array.from(node.querySelectorAll("*"))
                            .filter(element => visible(element)
                                && String(element.className || "").includes("v-popper")
                                && norm(element.innerText));
                        if (odds.length >= 2 && thresholds.length >= 2 && poppers.length >= 2) {
                            const rect = node.getBoundingClientRect();
                            candidates.push({node, odds, thresholds, poppers, area: rect.width * rect.height});
                            break;
                        }
                    }
                }

                candidates.sort((a, b) => a.area - b.area);
                const selected = candidates[0];
                if (!selected) return {found:false, controls:[], scope_control:null, rows:[]};

                const center = element => {
                    const rect = element.getBoundingClientRect();
                    return {x:rect.left + rect.width/2, y:rect.top + rect.height/2};
                };

                const controls = [];
                for (const element of selected.poppers) {
                    const point = center(element);
                    const text = norm(element.innerText);
                    if (!text || text.length > 80) continue;
                    if (controls.some(control => control.text === text
                        && Math.abs(control.x-point.x) < 8
                        && Math.abs(control.y-point.y) < 8)) continue;
                    controls.push({text, ...point});
                }
                controls.sort((a,b) => Math.abs(a.y-b.y) > 25 ? a.y-b.y : a.x-b.x);
                let scopeControl = null;
                if (controls.length) {
                    const topY = controls[0].y;
                    const topRow = controls.filter(control => Math.abs(control.y-topY) <= 25)
                        .sort((a,b) => a.x-b.x);
                    scopeControl = topRow[0] || null;
                }

                const odds = selected.odds.map(element => ({odds:norm(element.innerText), ...center(element)}));
                const thresholds = selected.thresholds.map(element => ({label:norm(element.innerText), ...center(element)}));
                const rows = [];
                for (const threshold of thresholds) {
                    const nearest = odds.reduce((best, price) => {
                        const distance = Math.abs(price.y-threshold.y);
                        return !best || distance < best.distance ? {...price, distance} : best;
                    }, null);
                    if (nearest && nearest.distance <= 38) {
                        rows.push({label:threshold.label, odds:nearest.odds});
                    }
                }
                return {found:true, controls, scope_control:scopeControl, rows};
            }"""
        )
    except Exception:
        return {"found": False, "controls": [], "scope_control": None, "rows": []}


def _midnite_corner_scope_key(value):
    value = _midnite_corner_team_key(value)
    return "combined" if value in {"combined", "match"} else value


def _midnite_corner_scope_confirmed(state, target):
    control = state.get("scope_control") or {}
    return bool(
        _midnite_corner_scope_key(control.get("text"))
        == _midnite_corner_scope_key(target)
    )


def _midnite_click_open_corner_option(page, target, control):
    aliases = (
        ["Combined", "Match"]
        if _midnite_corner_scope_key(target) == "combined"
        else [_midnite_corner_norm(target)]
    )
    for alias in aliases:
        try:
            point = page.evaluate(
                r"""payload => {
                    const norm = value => (value || "").replace(/\s+/g, " ").trim();
                    const visible = element => {
                        if (!element) return false;
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0 && rect.bottom > 0
                            && rect.top < window.innerHeight && style.display !== "none"
                            && style.visibility !== "hidden";
                    };
                    const matches = Array.from(document.querySelectorAll("body *"))
                        .filter(element => element.childElementCount === 0
                            && norm(element.innerText) === payload.text && visible(element))
                        .map(element => {
                            const rect = element.getBoundingClientRect();
                            return {x:rect.left+rect.width/2, y:rect.top+rect.height/2,
                                    area:rect.width*rect.height};
                        })
                        .filter(point => point.y > payload.controlY - 10
                            && Math.abs(point.x-payload.controlX) < 260)
                        .sort((a,b) => {
                            const ay = Math.abs(a.y-payload.controlY);
                            const by = Math.abs(b.y-payload.controlY);
                            return ay !== by ? ay-by : a.area-b.area;
                        });
                    return matches[0] || null;
                }""",
                {"text": alias, "controlX": control["x"], "controlY": control["y"]},
            )
        except Exception:
            point = None
        if point:
            page.mouse.click(point["x"], point["y"])
            time.sleep(0.35)
            return True
    return False


def _midnite_click_corner_scope(page, target):
    for _attempt in range(3):
        state = _midnite_corner_card_state(page)
        if state.get("found") and _midnite_corner_scope_confirmed(state, target):
            return True
        control = state.get("scope_control") or {}
        if not control:
            expand_accordion(page, "Corners")
            time.sleep(0.4)
            continue
        page.mouse.click(control["x"], control["y"])
        time.sleep(0.35)
        if not _midnite_click_open_corner_option(page, target, control):
            try: page.keyboard.press("Escape")
            except Exception: pass
            continue
        for _ in range(12):
            time.sleep(0.25)
            verified = _midnite_corner_card_state(page)
            if verified.get("found") and _midnite_corner_scope_confirmed(verified, target):
                return True
        try: page.keyboard.press("Escape")
        except Exception: pass
    return False


def _midnite_parse_corner_scope(state, target):
    result = {}
    wanted = _midnite_corner_team_key(target)
    for row in state.get("rows", []):
        label = _midnite_corner_norm(row.get("label"))
        odds = _midnite_corner_norm(row.get("odds")).upper()
        parsed = re.fullmatch(r"(?:(.+?)\s+)?(\d+)\+", label)
        if not parsed or not (is_frac(odds) or odds in {"EVS", "EVENS"}):
            continue
        team_text = _midnite_corner_norm(parsed.group(1))
        team_key = _midnite_corner_team_key(team_text)
        if wanted == "combined":
            if team_text: continue
        elif team_key != wanted:
            continue
        decimal = frac(odds)
        if decimal is not None:
            result[f"over_{parsed.group(2)}"] = decimal
    return result or None


def scrape_midnite_corner_scopes(page, home, away):
    try:
        click_tab(page, "Corners")
    except Exception:
        pass
    time.sleep(0.8)
    expand_accordion(page, "Corners")
    time.sleep(0.5)
    if not _midnite_corner_card_state(page).get("found"):
        return {}

    scopes = [
        ("Combined", "total_corners"),
        (home, "home_corners"),
        (away, "away_corners"),
    ]
    output = {}
    signatures = set()

    for scope, source_key in scopes:
        if not _midnite_click_corner_scope(page, scope):
            print(f" Midnite corners: scope not confirmed: {scope}")
            continue
        expand_accordion(page, "Corners")
        time.sleep(0.35)
        ladder = _midnite_parse_corner_scope(
            _midnite_corner_card_state(page),
            scope,
        )
        if not ladder:
            print(f" Midnite corners: no rows for {scope}")
            continue
        signature = tuple(sorted(ladder.items()))
        if scope != "Combined" and signature in signatures:
            print(f" Midnite corners: duplicate scope rejected: {scope}")
            continue
        signatures.add(signature)
        output[source_key] = ladder
        print(f" Midnite corners: {scope}({len(ladder)} Overs)")

    return output

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

    # Half Result — scoped card parser
    half_result_1h = parse_midnite_half_result_card(
        page,
        home,
        away,
    )
    if half_result_1h:
        props["half_result_1h"] = half_result_1h

    # 2H is deliberately not saved until its grid has a separate verified
    # parser. This prevents first-half and second-half prices being mixed.

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
    # CORNERS tab — Combined, Home and Away milestone Overs
    # ------------------------------------------------------------------ #
    corner_markets = scrape_midnite_corner_scopes(page, home, away)
    for source_key, ladder in corner_markets.items():
        props[source_key] = ladder

    # Keep Team with Most Corners as a separate three-way market.
    lines_cn = get_lines(page)
    twmc = next(
        (i for i, line in enumerate(lines_cn) if line == "Team with Most Corners"),
        None,
    )
    if twmc is not None:
        f = [line for line in lines_cn[twmc:twmc+10] if is_frac(line)]
        if len(f) >= 3:
            props["team_most_corners"] = {
                "home": frac(f[0]),
                "draw": frac(f[1]),
                "away": frac(f[2]),
            }

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
    skip = [home, away]
    p = scrape_player_market_grid(page, "Player Carded", ["carded_anytime","sent_off_anytime","carded_first","carded_last"])
    if p: props["player_carded"] = p
    p = scrape_player_market_grid(page, "Player Shots on Target", ["1+","2+","3+","4+"])
    if p: props["player_shots_on_target"] = p
    p = scrape_player_market_grid(page, "Player Fouls Committed", ["1+","2+","3+","4+","5+"])
    if p: props["player_fouls_committed"] = p
    p = scrape_player_market_grid(page, "Player Fouls Won", ["1+","2+","3+","4+","5+"])
    if p: props["player_fouls_won"] = p
    p = scrape_player_market_grid(page, "Player to Score", ["to_score","first","last"])
    if p: props["player_to_score"] = p
    p = scrape_player_market_grid(page, "Player Shots", ["1+","2+","3+","4+","5+","6+"])
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