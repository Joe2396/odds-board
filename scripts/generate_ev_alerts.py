#!/usr/bin/env python3
import json
import re
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROP_FILES = [
    ("PaddyPower", ROOT / "ufc" / "data" / "props.json"),
    ("BoyleSports", ROOT / "ufc" / "data" / "boylesports_props.json"),
    ("BetVictor", ROOT / "ufc" / "data" / "betvictor_props.json"),
    ("Coral", ROOT / "ufc" / "data" / "coral_props.json"),
    ("BetMGM", ROOT / "ufc" / "data" / "betmgm_props.json"),
]

OUT_PATH = ROOT / "ufc" / "ev-alerts" / "index.html"
BASE = "/odds-board"
OUTLIER_THRESHOLD = 10


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


def fight_key(name):
    text = str(name or "").lower()
    text = text.replace(" vs ", " v ").replace(" versus ", " v ")
    text = re.sub(r"[^a-z0-9\s]", "", text)
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
    if value == "EVS":
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


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def canonical_market(label):
    text = str(label or "").lower()
    if "method" in text or "victory" in text or "winning" in text:
        return "Method of Victory"
    if "round" in text:
        return "Rounds"
    if "distance" in text:
        return "Go The Distance"
    if "fight betting" in text or "bout" in text:
        return "Fight Betting"
    return label or "Props"


def clean_selection(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def selection_key(s):
    text = clean_selection(s).lower()
    text = text.replace("ko/tko", "ko").replace("tko/ko", "ko")
    text = text.replace("knockout", "ko").replace("submission", "sub")
    text = text.replace("decision", "dec")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def collect_all_rows():
    rows = []

    for default_bookmaker, path in PROP_FILES:
        data = load_json(path)
        if not data:
            continue

        fights = data.get("fights", []) or []

        for fight in fights:
            bookmaker = fight.get("bookmaker") or default_bookmaker
            fight_name = (
                fight.get("fight")
                or fight.get("fight_name")
                or fight.get("name")
                or ""
            )
            if not fight_name:
                continue

            fkey = fight_key(fight_name)
            markets = fight.get("markets") or {}

            def add_rows(market_label, items):
                if not items:
                    return
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    sel = item.get("selection")
                    odds = item.get("odds")
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
                        "odds": odds,
                        "decimal": dec,
                    })

            if isinstance(markets, dict):
                add_rows("Fight Betting", markets.get("fight_betting"))
                add_rows("Method of Victory", markets.get("method_of_victory"))
                add_rows("Rounds", markets.get("rounds"))
                add_rows("Go The Distance", markets.get("go_the_distance"))

            add_rows("Method of Victory", fight.get("method_props"))
            add_rows("Rounds", fight.get("round_props"))
            add_rows("Go The Distance", fight.get("distance_props"))

        # Flat props array (BetMGM style)
        props = data.get("props", []) or []
        for prop in props:
            bookmaker = prop.get("bookmaker") or default_bookmaker
            fight_name = prop.get("fight") or ""
            if not fight_name:
                continue
            fkey = fight_key(fight_name)
            market = prop.get("market") or ""
            sel = prop.get("selection") or ""
            odds = prop.get("odds") or ""
            if not sel or not odds:
                continue
            dec = fractional_to_decimal(odds)
            if dec <= 1.0:
                continue
            rows.append({
                "fight": fight_name,
                "fight_key": fkey,
                "bookmaker": bookmaker,
                "market": canonical_market(market),
                "selection": clean_selection(sel),
                "selection_key": selection_key(sel),
                "odds": odds,
                "decimal": dec,
            })

    return rows


def find_value_spots(rows):
    grouped = {}
    for row in rows:
        key = (row["fight_key"], row["market"], row["selection_key"])
        grouped.setdefault(key, []).append(row)

    spots = []

    for key, items in grouped.items():
        if len(items) < 2:
            continue

        decimals = [r["decimal"] for r in items if r["decimal"] > 0]
        if len(decimals) < 2:
            continue

        best = max(items, key=lambda r: r["decimal"])
        avg = sum(decimals) / len(decimals)
        value_pct = ((best["decimal"] / avg) - 1) * 100

        if value_pct < OUTLIER_THRESHOLD:
            continue

        spots.append({
            **best,
            "avg_decimal": avg,
            "value_pct": value_pct,
            "book_count": len(set(r["bookmaker"] for r in items)),
            "all_prices": sorted(
                [{"bookmaker": r["bookmaker"], "decimal": r["decimal"], "odds": r["odds"]} for r in items],
                key=lambda x: x["decimal"],
                reverse=True,
            ),
        })

    spots.sort(key=lambda s: s["value_pct"], reverse=True)
    return spots


def render_spot_card(spot, index):
    fight = esc(spot["fight"])
    market = esc(spot["market"])
    selection = esc(spot["selection"])
    bookmaker = esc(spot["bookmaker"])
    odds = esc(spot["odds"])
    value_pct = spot["value_pct"]
    avg = spot["avg_decimal"]
    book_count = spot["book_count"]

    prices_html = ""
    for p in spot["all_prices"][:6]:
        is_best = p["decimal"] == spot["decimal"] and p["bookmaker"] == spot["bookmaker"]
        best_class = " best-price-row" if is_best else ""
        prices_html += f"""
        <div class="price-row{best_class}">
          <span>{esc(p["bookmaker"])}</span>
          <strong>{esc(p["odds"])}</strong>
        </div>
        """

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
            <div class="spot-fight">{fight}</div>
            <div class="spot-market">{market}</div>
          </div>
        </div>
        <div class="spot-badge {badge_class}">
          {badge_icon} +{value_pct:.0f}% vs avg
        </div>
      </div>

      <div class="spot-body">
        <div class="spot-selection">
          <span class="spot-label">Selection</span>
          <strong>{selection}</strong>
        </div>
        <div class="spot-best">
          <span class="spot-label">Best Price</span>
          <strong class="spot-odds">⭐ {odds}</strong>
          <span class="spot-book">{bookmaker}</span>
        </div>
        <div class="spot-avg">
          <span class="spot-label">Market Avg</span>
          <strong>{avg:.2f}</strong>
          <span class="spot-book">{book_count} books</span>
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

    unique_fights = len(set(s["fight"] for s in spots)) if spots else 0

    if not spots:
        body = """
        <div class="empty-state">
          <div class="empty-icon">🔍</div>
          <h2>No value spots found right now</h2>
          <p>Value spots appear when one bookmaker is pricing significantly better than the rest.
          Check back closer to fight night when more books price up.</p>
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
      max-width: 1400px;
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

    .nav-link {{
      color: var(--muted);
      font-size: 14px;
    }}

    .nav-link.active {{
      color: white;
      font-weight: 700;
    }}

    .page-header {{
      margin-bottom: 32px;
    }}

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
      max-width: 700px;
      margin-bottom: 8px;
    }}

    .header-meta {{
      color: var(--muted);
      font-size: 13px;
    }}

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

    .summary-stat span {{
      color: var(--muted);
      font-size: 13px;
    }}

    .fight-group {{
      margin-bottom: 36px;
    }}

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

    .spot-left {{
      display: flex;
      align-items: flex-start;
      gap: 12px;
    }}

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

    .spot-fight {{
      font-weight: 700;
      font-size: 14px;
      margin-bottom: 4px;
    }}

    .spot-market {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
    }}

    .spot-badge {{
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 900;
      white-space: nowrap;
    }}

    .badge-fire {{
      border: 1px solid rgba(239,68,68,0.6);
      background: rgba(239,68,68,0.12);
      color: #fca5a5;
    }}

    .badge-hot {{
      border: 1px solid rgba(249,115,22,0.6);
      background: rgba(249,115,22,0.12);
      color: #fdba74;
    }}

    .badge-value {{
      border: 1px solid rgba(250,204,21,0.5);
      background: rgba(250,204,21,0.1);
      color: #fde68a;
    }}

    .spot-body {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 10px;
    }}

    .spot-selection,
    .spot-best,
    .spot-avg {{
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

    .spot-selection strong,
    .spot-avg strong {{
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

    .empty-icon {{
      font-size: 48px;
      margin-bottom: 16px;
    }}

    .empty-state h2 {{
      font-size: 28px;
      margin-bottom: 12px;
    }}

    .empty-state p {{
      color: var(--muted);
      max-width: 500px;
      margin: 0 auto;
      line-height: 1.6;
    }}

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
        Prop selections where one bookmaker is pricing significantly better than the rest.
        Only spots where the best price is at least {OUTLIER_THRESHOLD}% above the market average are shown.
      </p>
      <p class="header-meta">Updated: {generated} &nbsp;•&nbsp; {len(spots)} spots across {unique_fights} fights</p>
    </header>

    {body}

  </main>
</body>
</html>
"""


def main():
    print("Collecting props from all bookmakers...")
    rows = collect_all_rows()
    print(f"Total prop rows: {len(rows)}")

    print("Finding value spots...")
    spots = find_value_spots(rows)
    print(f"Value spots found: {len(spots)}")

    if spots:
        print("\nTop 5 spots:")
        for spot in spots[:5]:
            print(f"  {spot['fight']} | {spot['market']} | {spot['selection']} @ {spot['odds']} ({spot['bookmaker']}) +{spot['value_pct']:.0f}%")

    html = generate_page(spots)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"\nWrote EV Alerts page: {OUT_PATH}")


if __name__ == "__main__":
    main()