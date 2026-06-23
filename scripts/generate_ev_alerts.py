#!/usr/bin/env python3
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROP_FILES = [
    ("PaddyPower", [
        ROOT / "ufc" / "data" / "props_filtered.json",
        ROOT / "ufc" / "data" / "props.json",
    ]),
    ("BoyleSports", [
        ROOT / "ufc" / "data" / "boylesports_props_filtered.json",
        ROOT / "ufc" / "data" / "boylesports_props.json",
    ]),
    ("BoyleSports", [
        ROOT / "ufc" / "data" / "boylesports_moneylines.json",
    ]),
    ("BetVictor", [
        ROOT / "ufc" / "data" / "betvictor_props_filtered.json",
        ROOT / "ufc" / "data" / "betvictor_props.json",
    ]),
    ("Coral", [
        ROOT / "ufc" / "data" / "coral_props_filtered.json",
        ROOT / "ufc" / "data" / "coral_props.json",
    ]),
    ("BetMGM", [
        ROOT / "ufc" / "data" / "betmgm_props_filtered.json",
        ROOT / "ufc" / "data" / "betmgm_props.json",
    ]),
    ("Bwin", [
        ROOT / "ufc" / "data" / "bwin_props.json",
    ]),
]

EVENTS_PATH = ROOT / "ufc" / "data" / "events.json"
OUT_PATH = ROOT / "ufc" / "ev-alerts" / "index.html"
BASE = "/odds-board"

OUTLIER_THRESHOLD = 5
APPLY_UPCOMING_FILTER = False


def esc(s):
    if s is None or s == "":
        return "—"
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def load_json(path):
    try:
        if not Path(path).exists():
            return {}
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR loading {path}: {e}")
        return {}


def choose_prop_file(paths):
    for path in paths:
        data = load_json(path)
        if not data:
            continue

        fights = data.get("fights") or []
        props = data.get("props") or []

        if fights or props:
            return path, data

    return paths[0], {}


def normalize_name(s):
    text = str(s or "").lower()
    text = text.replace("’", "'")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fight_key(name):
    text = str(name or "").lower()
    text = text.replace(" versus ", " v ")
    text = text.replace(" vs. ", " v ")
    text = text.replace(" vs ", " v ")
    text = text.replace(" v. ", " v ")

    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if " v " in text:
        left, right = text.split(" v ", 1)
        parts = sorted([left.strip(), right.strip()])
        return " v ".join(parts)

    return text


def fractional_to_decimal(value):
    value = str(value or "").strip().upper()
    if not value:
        return 0

    if value in {"EVS", "EVENS", "EVEN"}:
        return 2.0

    if "/" in value:
        try:
            a, b = value.split("/", 1)
            return (float(a) / float(b)) + 1
        except Exception:
            return 0

    try:
        val = float(value)
        if val > 1:
            return val
    except Exception:
        pass

    return 0


def get_upcoming_fight_keys():
    data = load_json(EVENTS_PATH)
    events = data.get("events") or []
    now = datetime.now(timezone.utc)
    upcoming_keys = set()

    for event in events:
        date_str = str(event.get("date") or "").strip()
        if not date_str:
            continue

        try:
            event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
        except Exception:
            try:
                event_dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                continue

        if now > event_dt + timedelta(hours=8):
            continue

        for fight in event.get("fights") or []:
            red = fight.get("red")
            blue = fight.get("blue")

            if isinstance(red, dict):
                red = red.get("name", "")
            if isinstance(blue, dict):
                blue = blue.get("name", "")

            if red and blue:
                upcoming_keys.add(fight_key(f"{red} v {blue}"))

    print(f"Upcoming fight keys from events.json: {len(upcoming_keys)}")
    return upcoming_keys


def canonical_market(label):
    text = str(label or "").lower()

    if "method" in text or "victory" in text or "winning" in text or "result" in text:
        return "Method of Victory"

    if "round" in text:
        return "Rounds"

    if "distance" in text or "go the distance" in text:
        return "Go The Distance"

    if "fight betting" in text or "bout" in text or "match odds" in text or "moneyline" in text:
        return "Fight Betting"

    return str(label or "Props").strip() or "Props"


def clean_selection(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def selection_key(s):
    text = clean_selection(s).lower()

    replacements = {
        "ko/tko": "ko",
        "tko/ko": "ko",
        "ko or tko": "ko",
        "knockout": "ko",
        "submission": "sub",
        "decision": "dec",
        "points": "dec",
        "unanimous": "dec",
        "split": "dec",
        "majority": "dec",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-z0-9\s\.]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_rows_from_fight(default_bookmaker, fight, upcoming_keys):
    rows = []

    bookmaker = fight.get("bookmaker") or default_bookmaker
    fight_name = (
        fight.get("fight")
        or fight.get("fight_name")
        or fight.get("name")
        or fight.get("match")
        or ""
    )

    if not fight_name:
        return rows

    fkey = fight_key(fight_name)

    if APPLY_UPCOMING_FILTER and upcoming_keys and fkey not in upcoming_keys:
        return rows

    def add_rows(market_label, items):
        if not items:
            return

        if isinstance(items, dict):
            possible = []
            for val in items.values():
                if isinstance(val, list):
                    possible.extend(val)
            items = possible

        if not isinstance(items, list):
            return

        for item in items:
            if not isinstance(item, dict):
                continue

            sel = (
                item.get("selection")
                or item.get("name")
                or item.get("runner")
                or item.get("outcome")
                or ""
            )
            odds = (
                item.get("odds")
                or item.get("price")
                or item.get("fractional")
                or item.get("decimal")
                or ""
            )

            if not sel or not odds:
                continue

            dec = fractional_to_decimal(odds)
            if dec <= 1.0:
                continue

            rows.append({
                "fight": fight_name,
                "fight_key": fkey,
                "bookmaker": bookmaker,
                "market": canonical_market(market_label),
                "selection": clean_selection(sel),
                "selection_key": selection_key(sel),
                "odds": str(odds),
                "decimal": dec,
            })

    markets = fight.get("markets") or {}

    if isinstance(markets, dict):
        for market_label, items in markets.items():
            add_rows(market_label, items)

        add_rows("Fight Betting", markets.get("fight_betting"))
        add_rows("Method of Victory", markets.get("method_of_victory"))
        add_rows("Rounds", markets.get("rounds"))
        add_rows("Rounds", markets.get("total_rounds"))
        add_rows("Go The Distance", markets.get("go_the_distance"))

    add_rows("Method of Victory", fight.get("method_props"))
    add_rows("Rounds", fight.get("round_props"))
    add_rows("Rounds", fight.get("total_rounds"))
    add_rows("Go The Distance", fight.get("distance_props"))
    add_rows("Fight Betting", fight.get("fight_betting"))

    return rows


def collect_all_rows(upcoming_keys):
    all_rows = []
    seen = set()

    print("\nReading UFC prop files:")

    for default_bookmaker, paths in PROP_FILES:
        path, data = choose_prop_file(paths)

        fights = data.get("fights") or []
        props = data.get("props") or []

        before = len(all_rows)
        fight_names = set()

        print(f"\n{default_bookmaker}")
        print(f"  file: {path}")
        print(f"  fights in file: {len(fights)}")
        print(f"  flat props in file: {len(props)}")

        for fight in fights:
            rows = extract_rows_from_fight(default_bookmaker, fight, upcoming_keys)

            for row in rows:
                key = (
                    row["bookmaker"],
                    row["fight_key"],
                    row["market"],
                    row["selection_key"],
                    row["odds"],
                )
                if key in seen:
                    continue
                seen.add(key)
                all_rows.append(row)
                fight_names.add(row["fight"])

        for prop in props:
            if not isinstance(prop, dict):
                continue

            bookmaker = prop.get("bookmaker") or default_bookmaker
            fight_name = prop.get("fight") or prop.get("fight_name") or prop.get("match") or ""
            market = prop.get("market") or prop.get("market_name") or "Props"
            sel = prop.get("selection") or prop.get("name") or prop.get("runner") or ""
            odds = prop.get("odds") or prop.get("price") or prop.get("fractional") or prop.get("decimal") or ""

            if not fight_name or not sel or not odds:
                continue

            fkey = fight_key(fight_name)

            if APPLY_UPCOMING_FILTER and upcoming_keys and fkey not in upcoming_keys:
                continue

            dec = fractional_to_decimal(odds)
            if dec <= 1.0:
                continue

            row = {
                "fight": fight_name,
                "fight_key": fkey,
                "bookmaker": bookmaker,
                "market": canonical_market(market),
                "selection": clean_selection(sel),
                "selection_key": selection_key(sel),
                "odds": str(odds),
                "decimal": dec,
            }

            key = (
                row["bookmaker"],
                row["fight_key"],
                row["market"],
                row["selection_key"],
                row["odds"],
            )
            if key in seen:
                continue

            seen.add(key)
            all_rows.append(row)
            fight_names.add(fight_name)

        added = len(all_rows) - before
        print(f"  rows collected: {added}")
        print(f"  fights with rows: {len(fight_names)}")

        if fight_names:
            sample = sorted(fight_names)[:5]
            print("  sample fights:")
            for name in sample:
                print(f"    - {name}")

    print(f"\nTotal collected UFC prop rows: {len(all_rows)}")
    print(f"Unique fights collected: {len(set(r['fight_key'] for r in all_rows))}")
    print(f"Unique markets collected: {len(set(r['market'] for r in all_rows))}")

    return all_rows


def find_value_spots(rows):
    grouped = {}

    for row in rows:
        key = (
            row["fight_key"],
            row["market"],
            row["selection_key"],
        )
        grouped.setdefault(key, []).append(row)

    comparable_groups = 0
    spots = []

    for _, items in grouped.items():
        bookmakers = set(r["bookmaker"] for r in items)

        if len(bookmakers) < 2:
            continue

        decimals = [r["decimal"] for r in items if r["decimal"] > 1]
        if len(decimals) < 2:
            continue

        comparable_groups += 1

        best = max(items, key=lambda r: r["decimal"])
        avg = sum(decimals) / len(decimals)
        value_pct = ((best["decimal"] / avg) - 1) * 100

        if value_pct < OUTLIER_THRESHOLD:
            continue

        spots.append({
            **best,
            "avg_decimal": avg,
            "value_pct": value_pct,
            "book_count": len(bookmakers),
            "all_prices": sorted(
                [
                    {
                        "bookmaker": r["bookmaker"],
                        "decimal": r["decimal"],
                        "odds": r["odds"],
                    }
                    for r in items
                ],
                key=lambda x: x["decimal"],
                reverse=True,
            ),
        })

    print(f"Comparable groups across 2+ books: {comparable_groups}")
    print(f"Value spots over {OUTLIER_THRESHOLD}%: {len(spots)}")

    spots.sort(key=lambda s: s["value_pct"], reverse=True)
    return spots


def render_spot_card(spot, index):
    prices_html = ""

    for p in spot["all_prices"][:8]:
        is_best = p["decimal"] == spot["decimal"] and p["bookmaker"] == spot["bookmaker"]
        best_class = " best-price-row" if is_best else ""
        prices_html += f"""
        <div class="price-row{best_class}">
          <span>{esc(p["bookmaker"])}</span>
          <strong>{esc(p["odds"])}</strong>
        </div>
        """

    value_pct = spot["value_pct"]

    if value_pct >= 25:
        badge_class = "badge-fire"
        badge_icon = "🔥🔥"
    elif value_pct >= 15:
        badge_class = "badge-hot"
        badge_icon = "🔥"
    else:
        badge_class = "badge-value"
        badge_icon = "⚡"

    return f"""
    <article class="spot-card">
      <div class="spot-header">
        <div class="spot-left">
          <div class="spot-rank">#{index}</div>
          <div>
            <div class="spot-fight">{esc(spot["fight"])}</div>
            <div class="spot-market">{esc(spot["market"])}</div>
          </div>
        </div>
        <div class="spot-badge {badge_class}">
          {badge_icon} +{value_pct:.0f}% vs avg
        </div>
      </div>

      <div class="spot-body">
        <div class="spot-selection">
          <span class="spot-label">Selection</span>
          <strong>{esc(spot["selection"])}</strong>
        </div>
        <div class="spot-best">
          <span class="spot-label">Best Price</span>
          <strong class="spot-odds">⭐ {esc(spot["odds"])}</strong>
          <span class="spot-book">{esc(spot["bookmaker"])}</span>
        </div>
        <div class="spot-avg">
          <span class="spot-label">Market Avg</span>
          <strong>{spot["avg_decimal"]:.2f}</strong>
          <span class="spot-book">{spot["book_count"]} books</span>
        </div>
      </div>

      <div class="spot-prices">
        <div class="prices-label">All prices</div>
        <div class="prices-grid">
          {prices_html}
        </div>
      </div>
    </article>
    """


def generate_page(spots):
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    unique_fights = len(set(s["fight_key"] for s in spots)) if spots else 0

    if not spots:
        body = """
        <div class="empty-state">
          <div class="empty-icon">🔍</div>
          <h2>No value spots right now</h2>
          <p>
            EV alerts appear when the same UFC prop is priced across multiple bookmakers
            and one bookmaker is meaningfully above the market average.
          </p>
        </div>
        """
    else:
        by_fight = {}

        for spot in spots:
            by_fight.setdefault(spot["fight"], []).append(spot)

        body = f"""
        <div class="summary-bar">
          <div class="summary-stat">
            <strong>{len(spots)}</strong>
            <span>Value spots</span>
          </div>
          <div class="summary-stat">
            <strong>{unique_fights}</strong>
            <span>Fights with value</span>
          </div>
          <div class="summary-stat">
            <strong>{spots[0]["value_pct"]:.0f}%</strong>
            <span>Best edge found</span>
          </div>
          <div class="summary-stat">
            <strong>{OUTLIER_THRESHOLD}%+</strong>
            <span>Min edge threshold</span>
          </div>
        </div>
        """

        global_index = 1

        for fight_name, fight_spots in by_fight.items():
            cards_html = ""

            for spot in fight_spots:
                cards_html += render_spot_card(spot, global_index)
                global_index += 1

            body += f"""
            <div class="fight-group">
              <div class="fight-group-header">
                <h2>{esc(fight_name)}</h2>
                <span class="fight-spot-count">{len(fight_spots)} spot{"s" if len(fight_spots) != 1 else ""}</span>
              </div>
              <div class="spots-grid">
                {cards_html}
              </div>
            </div>
            """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EV Alerts — UFC Value Spots</title>
  <style>
    :root {{
      --bg: #0F1621;
      --panel: #111827;
      --border: #1e2d42;
      --text: #ffffff;
      --muted: #8899aa;
      --blue: #60a5fa;
      --green: #22c55e;
      --orange: #f97316;
      --gold: #facc15;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    html, body {{
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
      min-height: 100vh;
    }}

    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    .page {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 36px 32px 64px;
    }}

    .top-nav {{
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 28px;
      flex-wrap: wrap;
    }}

    .nav-link {{ color: var(--muted); font-size: 14px; }}
    .nav-link.active {{ color: white; font-weight: 700; }}

    .page-header {{ margin-bottom: 32px; }}

    .header-eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid rgba(249,115,22,0.4);
      background: rgba(249,115,22,0.1);
      color: #fdba74;
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 13px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 14px;
    }}

    .page-title {{
      font-size: clamp(36px, 5vw, 68px);
      font-weight: 900;
      letter-spacing: -0.04em;
      line-height: 1;
      margin-bottom: 12px;
    }}

    .page-subtitle {{
      color: var(--muted);
      font-size: 16px;
      line-height: 1.6;
      max-width: 760px;
      margin-bottom: 8px;
    }}

    .header-meta {{ color: var(--muted); font-size: 13px; }}

    .summary-bar {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 32px;
    }}

    .summary-stat {{
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
      background: rgba(255,255,255,0.025);
    }}

    .summary-stat strong {{
      display: block;
      font-size: 28px;
      font-weight: 900;
      color: var(--green);
      margin-bottom: 4px;
    }}

    .summary-stat span {{ color: var(--muted); font-size: 13px; }}

    .fight-group {{ margin-bottom: 36px; }}

    .fight-group-header {{
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 14px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border);
    }}

    .fight-group-header h2 {{
      font-size: 22px;
      font-weight: 800;
      letter-spacing: -0.02em;
    }}

    .fight-spot-count {{
      border: 1px solid rgba(249,115,22,0.4);
      background: rgba(249,115,22,0.1);
      color: #fdba74;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 800;
    }}

    .spots-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 14px;
    }}

    .spot-card {{
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 18px;
      background: rgba(255,255,255,0.02);
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}

    .spot-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }}

    .spot-left {{ display: flex; align-items: flex-start; gap: 12px; }}

    .spot-rank {{
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 4px 8px;
      font-size: 12px;
      font-weight: 900;
      color: var(--muted);
      white-space: nowrap;
      margin-top: 2px;
    }}

    .spot-fight {{ font-weight: 700; font-size: 14px; margin-bottom: 4px; }}
    .spot-market {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.07em; }}

    .spot-badge {{
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 900;
      white-space: nowrap;
    }}

    .badge-fire {{ border: 1px solid rgba(239,68,68,0.6); background: rgba(239,68,68,0.12); color: #fca5a5; }}
    .badge-hot {{ border: 1px solid rgba(249,115,22,0.6); background: rgba(249,115,22,0.12); color: #fdba74; }}
    .badge-value {{ border: 1px solid rgba(250,204,21,0.5); background: rgba(250,204,21,0.1); color: #fde68a; }}

    .spot-body {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }}

    .spot-selection, .spot-best, .spot-avg {{
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      background: rgba(15,22,33,0.8);
    }}

    .spot-label {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      margin-bottom: 6px;
    }}

    .spot-selection strong, .spot-avg strong {{
      display: block;
      font-size: 15px;
      font-weight: 700;
    }}

    .spot-odds {{
      display: block;
      font-size: 22px;
      font-weight: 900;
      color: var(--green);
      margin-bottom: 4px;
    }}

    .spot-book {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
    }}

    .spot-prices {{
      border-top: 1px solid var(--border);
      padding-top: 12px;
    }}

    .prices-label {{
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      margin-bottom: 8px;
    }}

    .prices-grid {{
      display: flex;
      flex-direction: column;
      gap: 5px;
    }}

    .price-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 6px 10px;
      border-radius: 8px;
      background: rgba(255,255,255,0.02);
      font-size: 13px;
    }}

    .price-row strong {{
      font-weight: 700;
      color: var(--muted);
    }}

    .price-row.best-price-row {{
      background: rgba(34,197,94,0.08);
      border: 1px solid rgba(34,197,94,0.3);
    }}

    .price-row.best-price-row strong {{
      color: var(--green);
    }}

    .empty-state {{
      text-align: center;
      padding: 80px 32px;
      border: 1px dashed var(--border);
      border-radius: 24px;
    }}

    .empty-icon {{ font-size: 48px; margin-bottom: 16px; }}
    .empty-state h2 {{ font-size: 28px; margin-bottom: 12px; }}
    .empty-state p {{ color: var(--muted); max-width: 560px; margin: 0 auto; line-height: 1.6; }}

    @media (max-width: 768px) {{
      .page {{ padding: 20px 16px 48px; }}
      .spot-body {{ grid-template-columns: 1fr; }}
      .spots-grid {{ grid-template-columns: 1fr; }}
      .summary-bar {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <nav class="top-nav">
      <a class="nav-link" href="{BASE}/ufc/">UFC Hub</a>
      <span class="nav-link">›</span>
      <span class="nav-link active">⚡ EV Alerts</span>
    </nav>

    <header class="page-header">
      <div class="header-eyebrow">⚡ EV Alerts</div>
      <h1 class="page-title">EV Alerts</h1>
      <p class="page-subtitle">
        UFC prop selections where one bookmaker is pricing significantly better than the rest.
        This scans your scraped UFC prop files from PaddyPower, BoyleSports, BetVictor, Coral and BetMGM.
      </p>
      <p class="header-meta">Updated: {generated} &nbsp;•&nbsp; {len(spots)} spots across {unique_fights} fights</p>
    </header>

    {body}

  </main>
</body>
</html>
"""


def main():
    print("Loading upcoming fight keys...")
    upcoming_keys = get_upcoming_fight_keys()

    if APPLY_UPCOMING_FILTER:
        print("Upcoming fight filter: ON")
    else:
        print("Upcoming fight filter: OFF - scanning all scraped UFC prop fights")

    print("Collecting UFC props from scraped bookmaker files...")
    rows = collect_all_rows(upcoming_keys)

    print("\nFinding EV/value spots...")
    spots = find_value_spots(rows)

    if spots:
        print("\nTop 10 spots:")
        for spot in spots[:10]:
            print(
                f"  {spot['fight']} | {spot['market']} | {spot['selection']} "
                f"@ {spot['odds']} ({spot['bookmaker']}) +{spot['value_pct']:.1f}%"
            )
    else:
        print("\nNo EV spots found.")
        print("This means either:")
        print("  1. The same props are not appearing across 2+ books yet")
        print("  2. Selection names differ too much between bookmakers")
        print("  3. No best price is above the current threshold")

    html = generate_page(spots)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")

    print(f"\nWrote EV Alerts page: {OUT_PATH}")


if __name__ == "__main__":
    main()