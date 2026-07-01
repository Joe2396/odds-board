"""
fetch_midnite_worldcup_props_PROD15.py

Production Midnite World Cup main/player props scraper.

Scrapes the exact 7-fixture production snapshot from:
    football/data/midnite_worldcup_props_fixtures_prod15.json

This stage intentionally excludes aggregate Match/Home/Away Shots and SOT.
Those six markets are scraped by:
    fetch_midnite_worldcup_team_stats_PROD15.py

Temporary output:
    football/data/midnite_worldcup_props_main_prod15.json

The final production JSON is only replaced by:
    merge_midnite_worldcup_props_PROD15.py
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT            = Path(__file__).resolve().parents[2]
OUTPUT_FILE     = ROOT / "football" / "data" / "midnite_worldcup_props_main_prod15.json"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
FIXTURES_FILE   = ROOT / "football" / "data" / "midnite_worldcup_props_fixtures_prod15.json"
PROFILE_DIR     = ROOT / "scripts" / "Football" / "midnite_props_prod15_profile"

COMPETITION_ID = "38826387"
BASE_URL   = f"https://www.midnite.com/sports/football/world-cup-2026-{COMPETITION_ID}/"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MAX_MATCHES = 7
TEST_START_INDEX = 0
TEST_MODE = False
DEBUG_DIR = ROOT / "football" / "debug" / "midnite_worldcup_props_prod15"
FILTER_AUDIT = []


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
    if not FIXTURES_FILE.exists():
        raise FileNotFoundError(
            "Midnite fixture snapshot is missing. Run "
            "prepare_midnite_worldcup_props_fixtures.py first."
        )

    payload = json.loads(
        FIXTURES_FILE.read_text(
            encoding="utf-8"
        )
    )
    matches = payload.get(
        "matches",
        [],
    )

    expected = payload.get(
        "expected_match_count",
        payload.get(
            "selected_match_count",
            len(matches),
        ),
    )

    try:
        expected = int(expected)
    except (TypeError, ValueError):
        raise RuntimeError(
            "Fixture snapshot has an invalid expected_match_count"
        )

    if expected != len(matches):
        raise RuntimeError(
            f"Fixture snapshot count mismatch: metadata says {expected}, "
            f"but contains {len(matches)} matches"
        )

    if not 1 <= expected <= MAX_MATCHES:
        raise RuntimeError(
            f"Fixture snapshot must contain between 1 and {MAX_MATCHES} "
            f"matches; found {expected}"
        )

    return matches, payload

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
def _normalise_filter_label(value):
    value = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()

    if value.casefold() in {
        "match",
        "combined",
    }:
        return "Combined"

    return value


def _read_exact_market_body(
    page,
    market_name,
    option,
    home,
    away,
):
    """
    Read the body attached to one exact accordion heading.

    The body must contain its inline filter pills and prices, while containing
    no neighbouring aggregate-market heading.
    """
    try:
        return page.evaluate(
            r"""(payload) => {
                const heading = payload.marketName;
                const requested = payload.option;
                const home = payload.home;
                const away = payload.away;

                const norm = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const visible = element => {
                    if (!element) return false;
                    const rect =
                        element.getBoundingClientRect();
                    const style =
                        window.getComputedStyle(element);
                    return (
                        rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                    );
                };

                const isPrice = value =>
                    /^\d+\/\d+$|^EVS$|^EVENS$/i.test(
                        norm(value)
                    );

                const toDecimal = value => {
                    const cleaned =
                        norm(value).toUpperCase();

                    if (
                        cleaned === "EVS"
                        || cleaned === "EVENS"
                    ) {
                        return 2;
                    }

                    const [a, b] =
                        cleaned.split("/").map(Number);

                    if (!b) return null;

                    return Math.round(
                        (a / b + 1) * 10000
                    ) / 10000;
                };

                const requestedLabel =
                    ["match", "combined"].includes(
                        norm(requested).toLowerCase()
                    )
                        ? "Combined"
                        : norm(requested);

                const pillLabels = [
                    "Combined",
                    "Match",
                    norm(home),
                    norm(away),
                ].filter(Boolean);

                const competing = [
                    "Total Shots on Target",
                    "Total Shots",
                    "Total Shots Outside the Box",
                    "Total Fouls",
                    "Total Cards",
                    "Total Corners",
                ];

                const headingElement = Array.from(
                    document.querySelectorAll("body *")
                ).find(element =>
                    element.childElementCount === 0
                    && norm(element.innerText) === heading
                    && visible(element)
                );

                if (!headingElement) {
                    return {
                        found: false,
                        reason: "heading not found",
                    };
                }

                const candidates = [];

                let node = headingElement;

                for (
                    let depth = 0;
                    depth < 9 && node;
                    depth += 1,
                    node = node.parentElement
                ) {
                    const directChildren =
                        Array.from(node.children || []);

                    for (
                        const child of directChildren
                    ) {
                        if (
                            child.contains(headingElement)
                            || !visible(child)
                        ) {
                            continue;
                        }

                        const raw =
                            child.innerText || "";
                        const lines = raw
                            .split(/\n/)
                            .map(norm)
                            .filter(Boolean);
                        const prices =
                            lines.filter(isPrice);

                        if (!prices.length) {
                            continue;
                        }

                        const leaves = Array.from(
                            child.querySelectorAll("*")
                        ).filter(element =>
                            element.childElementCount === 0
                            && visible(element)
                            && norm(element.innerText)
                        );

                        const availablePills =
                            pillLabels.filter(
                                label =>
                                    leaves.some(
                                        element =>
                                            norm(
                                                element.innerText
                                            ) === label
                                    )
                            );

                        if (
                            availablePills.length < 2
                        ) {
                            continue;
                        }

                        const hasForeignHeading =
                            competing.some(
                                other =>
                                    other !== heading
                                    && leaves.some(
                                        element =>
                                            norm(
                                                element.innerText
                                            ) === other
                                    )
                            );

                        if (hasForeignHeading) {
                            continue;
                        }

                        const rect =
                            child.getBoundingClientRect();

                        candidates.push({
                            body: child,
                            leaves,
                            lines,
                            prices,
                            size:
                                raw.length
                                + rect.width
                                * rect.height
                                / 100000,
                        });
                    }

                    if (candidates.length) {
                        break;
                    }
                }

                candidates.sort(
                    (a, b) => a.size - b.size
                );

                const selected =
                    candidates[0] || null;

                if (!selected) {
                    return {
                        found: false,
                        reason:
                            "exact isolated body not found",
                    };
                }

                const pills = [];

                for (
                    const label of pillLabels
                ) {
                    const leaf =
                        selected.leaves.find(
                            element =>
                                norm(
                                    element.innerText
                                ) === label
                        );

                    if (!leaf) continue;

                    let target = leaf;

                    for (
                        let current = leaf;
                        current
                        && current !== selected.body;
                        current = current.parentElement
                    ) {
                        const tag =
                            current.tagName.toLowerCase();
                        const role = (
                            current.getAttribute(
                                "role"
                            ) || ""
                        ).toLowerCase();
                        const style =
                            window.getComputedStyle(
                                current
                            );

                        if (
                            tag === "button"
                            || role === "button"
                            || role === "tab"
                            || style.cursor === "pointer"
                        ) {
                            target = current;
                            break;
                        }
                    }

                    const rect =
                        target.getBoundingClientRect();

                    pills.push({
                        label,
                        x:
                            rect.left
                            + rect.width / 2,
                        y:
                            rect.top
                            + rect.height / 2,
                    });
                }

                const accepted =
                    requestedLabel === "Combined"
                        ? ["Combined", "Match"]
                        : [requestedLabel];

                const requestedPill =
                    pills.find(
                        item =>
                            accepted.includes(item.label)
                    ) || null;

                const thresholdLines =
                    selected.lines.filter(
                        line =>
                            /(?:^|\s)\d+\+$/
                                .test(line)
                    );

                const ladder = {};

                thresholdLines.forEach(
                    (line, index) => {
                        const match =
                            line.match(/(\d+)\+$/);
                        const price =
                            selected.prices[index];

                        if (
                            !match
                            || !price
                        ) {
                            return;
                        }

                        const decimal =
                            toDecimal(price);

                        if (
                            decimal
                            && decimal > 1
                        ) {
                            ladder[
                                "over_" + match[1]
                            ] = decimal;
                        }
                    }
                );

                let contentVerified = false;

                if (
                    requestedLabel === "Combined"
                ) {
                    const prefixes = [
                        norm(home).toLowerCase() + " ",
                        norm(away).toLowerCase() + " ",
                    ];

                    contentVerified =
                        thresholdLines.length > 0
                        && !thresholdLines.some(
                            line =>
                                prefixes.some(
                                    prefix =>
                                        line.toLowerCase()
                                            .startsWith(prefix)
                                )
                        );
                } else {
                    const prefix =
                        requestedLabel.toLowerCase()
                        + " ";

                    contentVerified =
                        thresholdLines.length > 0
                        && thresholdLines.every(
                            line =>
                                line.toLowerCase()
                                    .startsWith(prefix)
                        );
                }

                return {
                    found: true,
                    requestedPill,
                    pills,
                    thresholdLines,
                    ladder,
                    contentVerified,
                };
            }""",
            {
                "marketName": market_name,
                "option": option,
                "home": home,
                "away": away,
            },
        )
    except Exception as error:
        return {
            "found": False,
            "reason": str(error),
        }


def _click_exact_heading(
    page,
    market_name,
):
    try:
        point = page.evaluate(
            r"""(heading) => {
                const norm = value =>
                    (value || "")
                        .replace(/\s+/g, " ")
                        .trim();

                const leaf = Array.from(
                    document.querySelectorAll("body *")
                ).find(element =>
                    element.childElementCount === 0
                    && norm(element.innerText) === heading
                );

                if (!leaf) return null;

                let target =
                    leaf.parentElement?.parentElement
                    || leaf;

                target.scrollIntoView({
                    block: "center",
                });

                const rect =
                    target.getBoundingClientRect();

                return {
                    x:
                        rect.left
                        + rect.width / 2,
                    y:
                        rect.top
                        + rect.height / 2,
                };
            }""",
            market_name,
        )
    except Exception:
        point = None

    if not point:
        return False

    page.mouse.click(
        point["x"],
        point["y"],
    )
    return True


def ensure_inline_market_expanded(
    page,
    market_name,
    home,
    away,
):
    state = _read_exact_market_body(
        page,
        market_name,
        "Combined",
        home,
        away,
    )

    if state.get("found"):
        return True

    if not _click_exact_heading(
        page,
        market_name,
    ):
        return False

    for _ in range(16):
        time.sleep(0.25)

        state = _read_exact_market_body(
            page,
            market_name,
            "Combined",
            home,
            away,
        )

        if state.get("found"):
            return True

    return False


def select_filter(
    page,
    market_name,
    option,
    home,
    away,
):
    option = _normalise_filter_label(
        option
    )

    if not ensure_inline_market_expanded(
        page,
        market_name,
        home,
        away,
    ):
        print(
            f" {market_name} filter SKIPPED: "
            f"{option} — market unavailable "
            "or withdrawn"
        )
        return False

    state = _read_exact_market_body(
        page,
        market_name,
        option,
        home,
        away,
    )

    if (
        state.get("found")
        and state.get("contentVerified")
        and state.get("ladder")
    ):
        print(
            f" {market_name} filter: "
            f"{option} verified"
        )
        return True

    pill = state.get(
        "requestedPill"
    ) or {}

    if not pill:
        print(
            f" {market_name} filter SKIPPED: "
            f"{option} pill not found"
        )
        return False

    page.mouse.click(
        pill["x"],
        pill["y"],
    )

    for _ in range(24):
        time.sleep(0.25)

        state = _read_exact_market_body(
            page,
            market_name,
            option,
            home,
            away,
        )

        if (
            state.get("found")
            and state.get("contentVerified")
            and state.get("ladder")
        ):
            print(
                f" {market_name} filter: "
                f"{option} verified"
            )
            print(
                "  Thresholds: "
                + ", ".join(
                    state.get(
                        "thresholdLines",
                        [],
                    )[:8]
                )
            )
            return True

    print(
        f" {market_name} filter SKIPPED: "
        f"{option} — exact ladder "
        "did not verify"
    )
    return False


def read_verified_inline_ladder(
    page,
    market_name,
    option,
    home,
    away,
):
    state = _read_exact_market_body(
        page,
        market_name,
        option,
        home,
        away,
    )

    if (
        state.get("found")
        and state.get("contentVerified")
    ):
        return state.get("ladder") or None

    return None


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
    Return raw lines from the smallest exact Midnite market card.
    """
    try:
        result = page.evaluate(
            r"""(heading) => {
                const norm = value =>
                    (value || "").replace(/\s+/g, " ").trim();

                const isPrice = value =>
                    /^\d+\/\d+$|^EVS$|^EVENS$/i.test(
                        norm(value)
                    );

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
                        depth < 11 && node;
                        depth += 1,
                        node = node.parentElement
                    ) {
                        const rawText =
                            node.innerText || "";
                        const lines = rawText
                            .split(/\n/)
                            .map(value => value.trim())
                            .filter(Boolean);
                        const prices = lines.filter(
                            isPrice
                        );

                        if (
                            norm(rawText).includes(heading)
                            && prices.length >= 2
                        ) {
                            candidates.push({
                                lines,
                                characterCount:
                                    rawText.length,
                                priceCount:
                                    prices.length,
                            });
                            break;
                        }
                    }
                }

                candidates.sort((a, b) => {
                    if (
                        a.characterCount
                        !== b.characterCount
                    ) {
                        return (
                            a.characterCount
                            - b.characterCount
                        );
                    }
                    return b.priceCount - a.priceCount;
                });

                return candidates.length
                    ? candidates[0].lines
                    : [];
            }""",
            heading,
        )
    except Exception as error:
        print(
            f" Market card extraction "
            f"failed for {heading}: {error}"
        )
        return []

    return [
        line.strip()
        for line in (result or [])
        if line and line.strip()
    ]


def _midnite_three_way_sum(decimal_prices):
    if len(decimal_prices) != 3:
        return None
    if any(not value or value <= 1 for value in decimal_prices):
        return None
    return sum(1.0 / value for value in decimal_prices)


def parse_midnite_half_result_card(page, home, away):
    """
    Parse Midnite's visible 1st Half 1X2 prices from the exact Half Result card.

    Safety rules:
      - explicitly click the 1st Half tab inside the Half Result card;
      - require that tab to report an active/brand state;
      - read only visible fraction-price leaf elements;
      - require exactly three left-to-right prices;
      - require visible Home / Draw / Away labels in that order;
      - reject an implausible three-way source book.

    This avoids mixing hidden 2nd Half prices into the 1st Half market.
    """
    expand_accordion(page, "Half Result")
    time.sleep(0.8)

    try:
        click_point = page.evaluate(
            r"""(payload) => {
                const norm = value =>
                    (value || "").replace(/\s+/g, " ").trim();

                const visible = element => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);

                    return (
                        element.getClientRects().length > 0
                        && rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                        && style.opacity !== "0"
                    );
                };

                const isPrice = value =>
                    /^\d+\/\d+$|^EVS$|^EVENS$/i.test(norm(value));

                const exactLeaves = root =>
                    Array.from(root.querySelectorAll("*")).filter(
                        element =>
                            element.childElementCount === 0
                            && visible(element)
                            && norm(element.innerText)
                    );

                const headingLeaves = Array.from(
                    document.querySelectorAll("body *")
                ).filter(
                    element =>
                        element.childElementCount === 0
                        && visible(element)
                        && norm(element.innerText) === "Half Result"
                );

                const candidates = [];

                for (const heading of headingLeaves) {
                    let node = heading;

                    for (
                        let depth = 0;
                        depth < 11 && node;
                        depth += 1, node = node.parentElement
                    ) {
                        const leaves = exactLeaves(node);
                        const hasFirst = leaves.some(
                            element => norm(element.innerText) === "1st Half"
                        );
                        const hasSecond = leaves.some(
                            element => norm(element.innerText) === "2nd Half"
                        );
                        const prices = leaves.filter(
                            element => isPrice(element.innerText)
                        );

                        if (hasFirst && hasSecond && prices.length >= 3) {
                            const rect = node.getBoundingClientRect();

                            candidates.push({
                                node,
                                leaves,
                                area: rect.width * rect.height,
                                chars: (node.innerText || "").length,
                            });
                            break;
                        }
                    }
                }

                candidates.sort(
                    (a, b) =>
                        a.area - b.area
                        || a.chars - b.chars
                );

                const card = candidates[0];

                if (!card) return null;

                const firstHalf = card.leaves.find(
                    element => norm(element.innerText) === "1st Half"
                );

                if (!firstHalf) return null;

                let target = firstHalf;

                for (
                    let node = firstHalf;
                    node && node !== card.node;
                    node = node.parentElement
                ) {
                    const tag = node.tagName.toLowerCase();
                    const role = (
                        node.getAttribute("role") || ""
                    ).toLowerCase();
                    const style = window.getComputedStyle(node);

                    if (
                        tag === "button"
                        || role === "button"
                        || role === "tab"
                        || style.cursor === "pointer"
                    ) {
                        target = node;
                        break;
                    }
                }

                target.scrollIntoView({
                    block: "center",
                    inline: "center",
                });

                const rect = target.getBoundingClientRect();

                return {
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                };
            }""",
            {
                "home": home,
                "away": away,
            },
        )
    except Exception as error:
        print(f" Half Result rejected: tab lookup failed: {error}")
        return None

    if not click_point:
        print(" Half Result rejected: exact 1st Half tab not found")
        return None

    page.mouse.click(
        click_point["x"],
        click_point["y"],
    )
    time.sleep(1.0)

    try:
        state = page.evaluate(
            r"""(payload) => {
                const norm = value =>
                    (value || "").replace(/\s+/g, " ").trim();

                const folded = value =>
                    norm(value).toLocaleLowerCase();

                const visible = element => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);

                    return (
                        element.getClientRects().length > 0
                        && rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                        && style.opacity !== "0"
                    );
                };

                const isPrice = value =>
                    /^\d+\/\d+$|^EVS$|^EVENS$/i.test(norm(value));

                const exactLeaves = root =>
                    Array.from(root.querySelectorAll("*")).filter(
                        element =>
                            element.childElementCount === 0
                            && visible(element)
                            && norm(element.innerText)
                    );

                const headingLeaves = Array.from(
                    document.querySelectorAll("body *")
                ).filter(
                    element =>
                        element.childElementCount === 0
                        && visible(element)
                        && norm(element.innerText) === "Half Result"
                );

                const candidates = [];

                for (const heading of headingLeaves) {
                    let node = heading;

                    for (
                        let depth = 0;
                        depth < 11 && node;
                        depth += 1, node = node.parentElement
                    ) {
                        const leaves = exactLeaves(node);
                        const hasFirst = leaves.some(
                            element => norm(element.innerText) === "1st Half"
                        );
                        const hasSecond = leaves.some(
                            element => norm(element.innerText) === "2nd Half"
                        );
                        const prices = leaves.filter(
                            element => isPrice(element.innerText)
                        );

                        if (hasFirst && hasSecond && prices.length >= 3) {
                            const rect = node.getBoundingClientRect();

                            candidates.push({
                                node,
                                leaves,
                                area: rect.width * rect.height,
                                chars: (node.innerText || "").length,
                            });
                            break;
                        }
                    }
                }

                candidates.sort(
                    (a, b) =>
                        a.area - b.area
                        || a.chars - b.chars
                );

                const card = candidates[0];

                if (!card) {
                    return {
                        ok: false,
                        reason: "exact Half Result card not found",
                    };
                }

                const firstHalf = card.leaves.find(
                    element => norm(element.innerText) === "1st Half"
                );

                let firstHalfActive = false;

                for (
                    let node = firstHalf;
                    node && node !== card.node.parentElement;
                    node = node.parentElement
                ) {
                    const className = String(node.className || "")
                        .toLowerCase();
                    const ariaSelected = (
                        node.getAttribute
                        && node.getAttribute("aria-selected")
                    ) || "";
                    const dataState = (
                        node.getAttribute
                        && node.getAttribute("data-state")
                    ) || "";

                    if (
                        ariaSelected === "true"
                        || dataState.toLowerCase() === "active"
                        || className.includes("brand")
                        || className.includes("active")
                        || className.includes("selected")
                    ) {
                        firstHalfActive = true;
                        break;
                    }

                    if (node === card.node) break;
                }

                const rawPrices = card.leaves
                    .filter(element => isPrice(element.innerText))
                    .map(element => {
                        const rect = element.getBoundingClientRect();

                        return {
                            value: norm(element.innerText).toUpperCase(),
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2,
                        };
                    });

                const uniquePrices = [];

                for (const item of rawPrices) {
                    const duplicate = uniquePrices.some(
                        existing =>
                            existing.value === item.value
                            && Math.abs(existing.x - item.x) < 3
                            && Math.abs(existing.y - item.y) < 3
                    );

                    if (!duplicate) uniquePrices.push(item);
                }

                uniquePrices.sort((a, b) => a.x - b.x || a.y - b.y);

                const requestedLabels = [
                    folded(payload.home),
                    "draw",
                    folded(payload.away),
                ];

                const visibleLabels = requestedLabels.map(label => {
                    const matches = card.leaves.filter(
                        element => folded(element.innerText) === label
                    );

                    if (!matches.length) return null;

                    matches.sort((a, b) => {
                        const ar = a.getBoundingClientRect();
                        const br = b.getBoundingClientRect();
                        return ar.top - br.top || ar.left - br.left;
                    });

                    const rect = matches[0].getBoundingClientRect();

                    return {
                        label,
                        x: rect.left + rect.width / 2,
                    };
                });

                if (visibleLabels.some(item => !item)) {
                    return {
                        ok: false,
                        reason: "Home / Draw / Away labels not all visible",
                        firstHalfActive,
                        prices: uniquePrices.map(item => item.value),
                    };
                }

                const labelOrder = [...visibleLabels]
                    .sort((a, b) => a.x - b.x)
                    .map(item => item.label);

                if (
                    labelOrder.join("|")
                    !== requestedLabels.join("|")
                ) {
                    return {
                        ok: false,
                        reason: "visible outcome labels are out of order",
                        firstHalfActive,
                        labelOrder,
                        prices: uniquePrices.map(item => item.value),
                    };
                }

                if (!firstHalfActive) {
                    return {
                        ok: false,
                        reason: "1st Half tab did not become active",
                        prices: uniquePrices.map(item => item.value),
                    };
                }

                if (uniquePrices.length !== 3) {
                    return {
                        ok: false,
                        reason:
                            "expected exactly three visible 1st Half prices",
                        firstHalfActive,
                        prices: uniquePrices.map(item => item.value),
                    };
                }

                return {
                    ok: true,
                    firstHalfActive,
                    prices: uniquePrices.map(item => item.value),
                };
            }""",
            {
                "home": home,
                "away": away,
            },
        )
    except Exception as error:
        print(f" Half Result rejected: visible-price read failed: {error}")
        return None

    if not state or not state.get("ok"):
        reason = (
            state.get("reason")
            if isinstance(state, dict)
            else "unknown card-state failure"
        )
        prices = (
            state.get("prices")
            if isinstance(state, dict)
            else None
        )
        print(
            f" Half Result rejected: {reason}"
            + (f" — {prices}" if prices else "")
        )
        return None

    raw_prices = state.get("prices") or []
    decimal_prices = [frac(price) for price in raw_prices]
    implied_sum = _midnite_three_way_sum(decimal_prices)

    if implied_sum is None or not 0.98 <= implied_sum <= 1.35:
        print(
            f" Half Result rejected: implausible visible "
            f"1st Half prices {raw_prices}"
        )
        return None

    print(
        f" Half Result 1H: {raw_prices} "
        f"(visible active tab, sum {implied_sum:.3f})"
    )

    return {
        "home": decimal_prices[0],
        "draw": decimal_prices[1],
        "away": decimal_prices[2],
    }


def parse_midnite_double_chance_card(
    page,
    home,
    away,
):
    expand_accordion(
        page,
        "Double Chance",
    )
    time.sleep(0.5)

    lines = get_midnite_market_card_lines(
        page,
        "Double Chance",
    )

    labels = [
        line
        for line in lines
        if " or " in line.casefold()
    ]
    prices = [
        frac(line)
        for line in lines
        if is_frac(line)
    ]
    prices = [
        price
        for price in prices
        if price and price > 1
    ]

    if len(labels) < 3 or len(prices) < 3:
        return None

    result = {}

    for label, price in zip(
        labels[:7],
        prices[:7],
    ):
        low = label.casefold()
        home_low = home.casefold()
        away_low = away.casefold()

        if (
            "draw" in low
            and home_low in low
        ):
            key = "home_or_draw"
        elif (
            "draw" in low
            and away_low in low
        ):
            key = "away_or_draw"
        elif (
            home_low in low
            and away_low in low
        ):
            key = "home_or_away"
        else:
            continue

        result[key] = price

    if set(result) != {
        "home_or_draw",
        "home_or_away",
        "away_or_draw",
    }:
        return None

    return result


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
    for accordion_name in [
        "Both Teams To Score",
        "Double Chance",
        "Half Result",
    ]:
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

    # Double Chance — exact card parser.
    dc = parse_midnite_double_chance_card(
        page,
        home,
        away,
    )
    if dc:
        props["double_chance"] = dc

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


    # Aggregate Match/Home/Away Shots and SOT are deliberately
    # handled by fetch_midnite_worldcup_team_stats_PROD15.py.

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
    skip = [home, away]
    p = scrape_player_market_grid(page, "Player Carded", ["carded_anytime"])
    if p: props["player_carded"] = p
    p = scrape_player_market_grid(page, "Player Shots on Target", ["1+","2+","3+","4+"])
    if p: props["player_shots_on_target"] = p
    p = scrape_player_market_grid(page, "Player Fouls Committed", ["1+","2+","3+","4+","5+"])
    if p: props["player_fouls_committed"] = p
    p = scrape_player_market_grid(page, "Player Fouls Won", ["1+","2+","3+","4+","5+"])
    if p: props["player_fouls_won"] = p
    p = scrape_player_market_grid(page, "Player to Score", ["to_score"])
    if p: props["player_to_score"] = p
    p = scrape_player_market_grid(page, "Player Shots", ["1+","2+","3+","4+","5+","6+"])
    if p: props["player_shots"] = p

    if not props:
        return None

    match_filter_audit = list(FILTER_AUDIT)
    FILTER_AUDIT.clear()

    return {
        "match_id": match.get("match_id", ""),
        "event_id": match.get("event_id", ""),
        "home": home,
        "away": away,
        "kickoff": match.get("kickoff", ""),
        "bookmaker": "Midnite",
        "url": url,
        "market_count": len(props),
        "markets": props,
    }

def main():
    print("=" * 72)
    print("MIDNITE WORLD CUP MAIN/PLAYER PROPS PROD15")
    print("=" * 72)
    print("Temporary stage output only — production JSON is not modified here")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "ERROR: run: pip install playwright "
            "&& playwright install chromium"
        )
        sys.exit(1)

    matches, fixture_snapshot = load_matches()
    expected_matches = len(matches)

    print(
        f"Availability-aware snapshot: {expected_matches} active fixtures "
        f"(maximum {MAX_MATCHES})"
    )

    PROFILE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    results = []
    errors = []
    started = time.perf_counter()

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={
                "width": 1280,
                "height": 900,
            },
            user_agent=USER_AGENT,
            locale="en-GB",
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        for index, match in enumerate(
            matches,
            start=1,
        ):
            label = (
                f"{match.get('home', '?')} vs "
                f"{match.get('away', '?')}"
            )

            print(
                f"[{index:02d}/{len(matches)}] "
                f"{label}",
                end="",
                flush=True,
            )

            try:
                result = scrape_match(
                    page,
                    match,
                )
            except Exception as error:
                print(f" ERROR: {error}")
                errors.append({
                    "match": label,
                    "url": match.get("url"),
                    "error": str(error),
                })

                try:
                    page.screenshot(
                        path=str(
                            DEBUG_DIR
                            / (
                                re.sub(
                                    r"[^a-z0-9]+",
                                    "-",
                                    label.lower(),
                                ).strip("-")
                                + "_error.png"
                            )
                        ),
                        full_page=True,
                    )
                except Exception:
                    pass

                continue

            if not result:
                print(" SKIPPED")
                errors.append({
                    "match": label,
                    "url": match.get("url"),
                    "error": "scrape_match returned no result",
                })
                continue

            print(
                f" OK — {len(result['markets'])} markets: "
                + ", ".join(result["markets"].keys())
            )
            results.append(result)

            debug_name = re.sub(
                r"[^a-z0-9]+",
                "-",
                label.lower(),
            ).strip("-")

            (
                DEBUG_DIR
                / f"{debug_name}.json"
            ).write_text(
                json.dumps(
                    {
                        "match": label,
                        "market_names":
                            list(
                                result.get(
                                    "markets",
                                    {},
                                ).keys()
                            ),
                        "market_count":
                            result.get(
                                "market_count",
                                0,
                            ),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        context.close()

    elapsed = time.perf_counter() - started

    output = {
        "bookmaker": "Midnite",
        "competition": "FIFA World Cup 2026",
        "stage": "main_and_player_props",
        "scraped_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "production_stage": True,
        "production_modified": False,
        "max_matches": MAX_MATCHES,
        "requested_max_matches": MAX_MATCHES,
        "expected_match_count": expected_matches,
        "fixture_snapshot_created_at": fixture_snapshot.get("created_at"),
        "match_count": len(results),
        "error_count": len(errors),
        "errors": errors,
        "elapsed_seconds":
            round(elapsed, 3),
        "matches": results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("")
    print("=" * 72)
    print("MIDNITE MAIN/PLAYER PROPS PROD15 COMPLETE")
    print("=" * 72)
    print(f"Matches scraped: {len(results)}/{expected_matches}")
    print(f"Errors: {len(errors)}")
    print(f"Elapsed: {elapsed:.2f}s")
    print(f"Wrote temporary stage: {OUTPUT_FILE}")
    print("Production JSON modified: NO")
    print("=" * 72)

    if (
        len(results) != expected_matches
        or errors
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
