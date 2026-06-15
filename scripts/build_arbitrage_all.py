#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FOOTBALL_ARB_PATH = ROOT / "football" / "data" / "arbitrage.json"
UFC_ARB_PATH = ROOT / "ufc" / "data" / "arbitrage.json"
DARTS_ARB_PATH = ROOT / "darts" / "data" / "arbitrage.json"

OUT_JSON = ROOT / "data" / "arbitrage_all.json"
OUT_PAGE = ROOT / "arbitrage" / "index.html"

BASE = "/odds-board"


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
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR loading {path}: {e}")
        return {}


def as_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def normalize_profit(row):
    if row.get("profit_margin_percent") is not None:
        return as_float(row.get("profit_margin_percent"))
    if row.get("profit_percent") is not None:
        return as_float(row.get("profit_percent"))
    return 0.0


def normalize_football():
    data = load_json(FOOTBALL_ARB_PATH)
    rows = data.get("arbitrage") or data.get("arbitrage_opportunities") or []
    out = []

    for row in rows:
        selections = row.get("selections") or {}
        books = []

        # Handle both moneyline (home/draw/away) and props O/U (over/under) arbs
        sides = ["home", "draw", "away"] if row.get("type") != "props_ou" else ["over", "under"]
        side_labels = {"home": row.get("home_team") or "Home", "draw": "Draw",
                      "away": row.get("away_team") or "Away",
                      "over": f"Over {row.get('line','')}", "under": f"Under {row.get('line','')}"}
        for side in sides:
            info = selections.get(side) or {}
            if not info:
                continue
            books.append({
                "selection": side_labels.get(side, side.title()),
                "bookmaker": info.get("bookmaker") or "",
                "odds": info.get("odds") or "",
                "decimal_odds": info.get("decimal_odds") or "",
                "implied_probability": info.get("implied_probability") or "",
            })

        out.append({
            "sport": "Football",
            "competition": row.get("competition") or "FIFA World Cup",
            "event": row.get("match") or "",
            "market": row.get("market") or "Match Odds",
            "type": row.get("type") or "moneyline_1x2",
            "date_label": row.get("date_label") or "",
            "time": row.get("time") or "",
            "profit_margin_percent": normalize_profit(row),
            "arb_percent": row.get("arb_percent") or "",
            "arb_sum": row.get("arb_sum") or "",
            "bookmaker_count": row.get("bookmaker_count") or len(books),
            "bookmakers": books,
            "source_file": "football/data/arbitrage.json",
        })

    return out, data


def normalize_ufc():
    data = load_json(UFC_ARB_PATH)
    rows = data.get("arbitrage") or data.get("arbitrage_opportunities") or []
    out = []

    for row in rows:
        books = []

        if row.get("fighters"):
            for fighter, info in (row.get("fighters") or {}).items():
                books.append({
                    "selection": fighter,
                    "bookmaker": info.get("best_bookmaker") or info.get("bookmaker") or "",
                    "odds": info.get("best_price") or info.get("odds") or "",
                    "decimal_odds": info.get("best_decimal") or info.get("decimal_odds") or info.get("best_price") or "",
                    "implied_probability": info.get("implied_probability") or "",
                })

        elif row.get("selections"):
            for selection, info in (row.get("selections") or {}).items():
                books.append({
                    "selection": selection,
                    "bookmaker": info.get("bookmaker") or "",
                    "odds": info.get("odds") or "",
                    "decimal_odds": info.get("decimal_odds") or "",
                    "implied_probability": info.get("implied_probability") or "",
                })

        out.append({
            "sport": "UFC",
            "competition": row.get("competition") or "UFC",
            "event": row.get("fight") or row.get("event") or row.get("match") or "",
            "market": row.get("market") or "Moneyline",
            "type": row.get("type") or "moneyline",
            "date_label": row.get("date_label") or "",
            "time": row.get("time") or "",
            "profit_margin_percent": normalize_profit(row),
            "arb_percent": row.get("arb_percent") or "",
            "arb_sum": row.get("arb_sum") or "",
            "bookmaker_count": row.get("bookmaker_count") or len(books),
            "bookmakers": books,
            "source_file": "ufc/data/arbitrage.json",
        })

    return out, data


def normalize_darts():
    data = load_json(DARTS_ARB_PATH)
    rows = data.get("arbitrage") or data.get("arbitrage_opportunities") or []
    out = []

    for row in rows:
        books = []

        if row.get("selections"):
            for selection, info in (row.get("selections") or {}).items():
                books.append({
                    "selection": selection,
                    "bookmaker": info.get("bookmaker") or "",
                    "odds": info.get("odds") or "",
                    "decimal_odds": info.get("decimal_odds") or "",
                    "implied_probability": info.get("implied_probability") or "",
                })

        out.append({
            "sport": "Darts",
            "competition": row.get("competition") or "Darts",
            "event": row.get("match") or row.get("event") or "",
            "market": row.get("market") or "Match Odds",
            "type": row.get("type") or "moneyline",
            "date_label": row.get("date_label") or "",
            "time": row.get("time") or "",
            "profit_margin_percent": normalize_profit(row),
            "arb_percent": row.get("arb_percent") or "",
            "arb_sum": row.get("arb_sum") or "",
            "bookmaker_count": row.get("bookmaker_count") or len(books),
            "bookmakers": books,
            "source_file": "darts/data/arbitrage.json",
        })

    return out, data


def sport_counts(rows):
    counts = {"All": len(rows)}
    for row in rows:
        sport = row.get("sport") or "Other"
        counts[sport] = counts.get(sport, 0) + 1
    return counts


def render_filter_buttons(counts):
    order = ["All", "Football", "UFC", "Darts"]
    html = ""

    for sport in order:
        count = counts.get(sport, 0)
        active = " active" if sport == "All" else ""

        html += f"""
        <button class="filter-btn{active}" data-filter="{esc(sport)}">
          {esc(sport)} <span>{count}</span>
        </button>
        """

    return html


def render_books(books):
    if not books:
        return """<div class="empty-books">No bookmaker breakdown available</div>"""

    html = ""

    for book in books:
        html += f"""
        <div class="book-row">
          <span>{esc(book.get("selection"))}</span>
          <strong>{esc(book.get("odds"))}</strong>
          <em>{esc(book.get("bookmaker"))}</em>
        </div>
        """

    return html


def render_card(row, index):
    sport = row.get("sport") or "Other"
    profit = normalize_profit(row)
    sport_class = f"sport-{sport.lower().replace(' ', '-')}"
    badge_class = "gold"

    if profit >= 2:
        badge_class = "fire"
    elif profit >= 1:
        badge_class = "hot"

    meta_bits = []
    if row.get("competition"):
        meta_bits.append(row.get("competition"))
    if row.get("date_label") or row.get("time"):
        meta_bits.append(f"{row.get('date_label', '')} {row.get('time', '')}".strip())
    if row.get("bookmaker_count"):
        meta_bits.append(f"{row.get('bookmaker_count')} books")

    meta = " · ".join([str(x) for x in meta_bits if x])

    return f"""
    <article class="arb-card" data-sport="{esc(sport)}">
      <div class="card-top">
        <span class="sport-pill {esc(sport_class)}">{esc(sport)}</span>
        <span class="rank">#{index}</span>
      </div>

      <h2>{esc(row.get("event"))}</h2>
      <p class="meta">{esc(meta)}</p>

      <div class="profit-badge {badge_class}">
        💰 +{profit:.2f}% guaranteed
      </div>

      <div class="details-grid">
        <div>
          <span>Market</span>
          <strong>{esc(row.get("market"))}</strong>
        </div>
        <div>
          <span>Arb %</span>
          <strong>{esc(row.get("arb_percent"))}</strong>
        </div>
        <div>
          <span>Arb Sum</span>
          <strong>{esc(row.get("arb_sum"))}</strong>
        </div>
      </div>

      <div class="books">
        <div class="books-title">Best prices</div>
        {render_books(row.get("bookmakers") or [])}
      </div>
    </article>
    """


def render_page(rows):
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y, %H:%M:%S")
    counts = sport_counts(rows)
    rows = sorted(rows, key=lambda x: normalize_profit(x), reverse=True)

    if rows:
        cards = ""
        for i, row in enumerate(rows, start=1):
            cards += render_card(row, i)
    else:
        cards = """
        <section class="empty-state">
          <p>No arbitrage opportunities right now.</p>
        </section>
        """

    best_profit = max([normalize_profit(r) for r in rows], default=0)
    football_count = counts.get("Football", 0)
    ufc_count = counts.get("UFC", 0)
    darts_count = counts.get("Darts", 0)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Multi-Sport Arbitrage Board — BeatTheBooks</title>
  <style>
    :root {{
      --bg: #0b1220;
      --panel: #111827;
      --panel2: #0f172a;
      --border: #23314b;
      --text: #ffffff;
      --muted: #9fb0c7;
      --green: #22c55e;
      --green2: #86efac;
      --blue: #60a5fa;
      --orange: #f97316;
      --gold: #facc15;
      --red: #ef4444;
      --line: rgba(148,163,184,0.18);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    html, body {{
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    body {{
      background:
        radial-gradient(circle at top left, rgba(34,197,94,0.12), transparent 30%),
        radial-gradient(circle at top right, rgba(96,165,250,0.10), transparent 36%),
        #0b1220;
    }}

    a {{ color: inherit; text-decoration: none; }}

    .page {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 46px 32px 80px;
    }}

    .top-row {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 22px;
      flex-wrap: wrap;
      margin-bottom: 42px;
    }}

    .title-block h1 {{
      font-size: clamp(38px, 5vw, 70px);
      line-height: 0.96;
      letter-spacing: -0.055em;
      margin-bottom: 14px;
      font-weight: 950;
    }}

    .title-block p {{
      color: #c7d2fe;
      font-size: 17px;
      line-height: 1.55;
      max-width: 720px;
    }}

    .controls {{
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 12px;
    }}

    .pill {{
      border: 1px solid var(--border);
      background: rgba(17,24,39,0.75);
      border-radius: 999px;
      padding: 12px 16px;
      display: inline-flex;
      align-items: center;
      gap: 9px;
      color: #dbeafe;
      white-space: nowrap;
      box-shadow: 0 10px 30px rgba(0,0,0,0.18);
    }}

    .live-dot {{
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--green);
      box-shadow: 0 0 18px rgba(34,197,94,0.9);
    }}

    .bankroll-pill {{
      border: 1px solid var(--border);
      background: rgba(17,24,39,0.75);
      border-radius: 999px;
      padding: 10px 12px 10px 16px;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: #dbeafe;
    }}

    .bankroll-pill input {{
      width: 150px;
      border: 1px solid var(--border);
      background: #0b1220;
      color: white;
      border-radius: 14px;
      padding: 12px 14px;
      font-size: 16px;
      outline: none;
    }}

    .section-heading {{
      font-size: clamp(34px, 4vw, 58px);
      letter-spacing: -0.055em;
      line-height: 1;
      margin-bottom: 22px;
      font-weight: 950;
    }}

    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}

    .summary-card {{
      border: 1px solid var(--border);
      border-radius: 18px;
      background: rgba(17,24,39,0.72);
      padding: 18px;
    }}

    .summary-card strong {{
      display: block;
      color: var(--green);
      font-size: 34px;
      line-height: 1;
      margin-bottom: 8px;
    }}

    .summary-card span {{
      color: var(--muted);
      font-size: 13px;
    }}

    .filters {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 18px 0 26px;
    }}

    .filter-btn {{
      border: 1px solid var(--border);
      background: rgba(17,24,39,0.76);
      color: white;
      border-radius: 999px;
      padding: 11px 16px;
      font-weight: 900;
      cursor: pointer;
      transition: 0.15s ease;
    }}

    .filter-btn:hover {{
      border-color: rgba(34,197,94,0.55);
    }}

    .filter-btn.active {{
      border-color: rgba(34,197,94,0.6);
      background: rgba(34,197,94,0.14);
      color: #86efac;
    }}

    .filter-btn span {{
      color: var(--muted);
      margin-left: 7px;
    }}

    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(370px, 1fr));
      gap: 14px;
    }}

    .arb-card {{
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      background: rgba(17,24,39,0.76);
      box-shadow: 0 18px 50px rgba(0,0,0,0.18);
    }}

    .card-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }}

    .sport-pill {{
      display: inline-flex;
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 11px;
      font-weight: 950;
      text-transform: uppercase;
      letter-spacing: .08em;
      border: 1px solid var(--border);
    }}

    .sport-football {{
      color: #86efac;
      background: rgba(34,197,94,0.1);
      border-color: rgba(34,197,94,0.35);
    }}

    .sport-ufc {{
      color: #fdba74;
      background: rgba(249,115,22,0.1);
      border-color: rgba(249,115,22,0.35);
    }}

    .sport-darts {{
      color: #bfdbfe;
      background: rgba(96,165,250,0.1);
      border-color: rgba(96,165,250,0.35);
    }}

    .rank {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 900;
    }}

    .arb-card h2 {{
      font-size: 20px;
      letter-spacing: -0.025em;
      margin-bottom: 6px;
    }}

    .meta {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      margin-bottom: 13px;
    }}

    .profit-badge {{
      display: inline-flex;
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
      font-weight: 950;
      margin-bottom: 14px;
    }}

    .profit-badge.fire {{
      color: #fecaca;
      background: rgba(239,68,68,0.12);
      border: 1px solid rgba(239,68,68,0.45);
    }}

    .profit-badge.hot {{
      color: #fdba74;
      background: rgba(249,115,22,0.12);
      border: 1px solid rgba(249,115,22,0.45);
    }}

    .profit-badge.gold {{
      color: #fde68a;
      background: rgba(250,204,21,0.1);
      border: 1px solid rgba(250,204,21,0.4);
    }}

    .details-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px;
      margin-bottom: 12px;
    }}

    .details-grid div {{
      border: 1px solid var(--border);
      border-radius: 14px;
      background: rgba(15,22,33,0.82);
      padding: 11px;
    }}

    .details-grid span {{
      display: block;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 6px;
    }}

    .details-grid strong {{
      display: block;
      color: var(--text);
      font-size: 15px;
      word-break: break-word;
    }}

    .books {{
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}

    .books-title {{
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 8px;
    }}

    .book-row {{
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      gap: 8px;
      align-items: center;
      border-radius: 10px;
      padding: 8px 10px;
      background: rgba(255,255,255,0.025);
      margin-bottom: 5px;
      font-size: 13px;
    }}

    .book-row strong {{
      color: var(--green);
      font-size: 16px;
    }}

    .book-row em {{
      color: var(--muted);
      font-style: normal;
      text-align: right;
    }}

    .empty-books {{
      color: var(--muted);
      font-size: 13px;
    }}

    .empty-state {{
      border: 1px dashed var(--border);
      border-radius: 18px;
      padding: 28px;
      color: #cbd5e1;
      background: rgba(17,24,39,0.42);
    }}

    .empty-state p {{
      color: #cbd5e1;
      font-size: 16px;
    }}

    .hidden {{
      display: none !important;
    }}

    @media (max-width: 760px) {{
      .page {{ padding: 28px 16px 58px; }}
      .top-row {{ margin-bottom: 34px; }}
      .controls {{ width: 100%; }}
      .pill, .bankroll-pill {{ width: 100%; justify-content: space-between; }}
      .bankroll-pill input {{ width: 120px; }}
      .cards-grid {{ grid-template-columns: 1fr; }}
      .details-grid {{ grid-template-columns: 1fr; }}
      .book-row {{ grid-template-columns: 1fr; }}
      .book-row em {{ text-align: left; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="top-row">
      <div class="title-block">
        <h1>Multi-Sport Arbitrage Board</h1>
        <p>Live data from BeatTheBooks arbitrage engine.</p>
      </div>

      <div class="controls">
        <div class="pill"><span class="live-dot"></span> Live</div>
        <div class="pill">Updated: {esc(generated)}</div>
        <label class="bankroll-pill">
          Bankroll £
          <input id="bankrollInput" type="number" min="1" step="1" value="100" />
        </label>
      </div>
    </section>

    <h2 class="section-heading">Arbitrage Opportunities</h2>

    <div class="summary">
      <div class="summary-card">
        <strong>{len(rows)}</strong>
        <span>Total arbs</span>
      </div>
      <div class="summary-card">
        <strong>{football_count}</strong>
        <span>Football arbs</span>
      </div>
      <div class="summary-card">
        <strong>{ufc_count}</strong>
        <span>UFC arbs</span>
      </div>
      <div class="summary-card">
        <strong>{darts_count}</strong>
        <span>Darts arbs</span>
      </div>
      <div class="summary-card">
        <strong>{best_profit:.2f}%</strong>
        <span>Best profit</span>
      </div>
    </div>

    <div class="filters">
      {render_filter_buttons(counts)}
    </div>

    <section class="cards-grid">
      {cards}
    </section>
  </main>

  <script>
    const buttons = document.querySelectorAll(".filter-btn");
    const cards = document.querySelectorAll(".arb-card");

    buttons.forEach(btn => {{
      btn.addEventListener("click", () => {{
        const filter = btn.dataset.filter;

        buttons.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");

        cards.forEach(card => {{
          const sport = card.dataset.sport;
          if (filter === "All" || sport === filter) {{
            card.style.display = "";
          }} else {{
            card.style.display = "none";
          }}
        }});
      }});
    }});
  </script>
</body>
</html>
"""


def main():
    football_rows, football_data = normalize_football()
    ufc_rows, ufc_data = normalize_ufc()
    darts_rows, darts_data = normalize_darts()

    all_rows = football_rows + ufc_rows + darts_rows
    all_rows.sort(key=lambda x: normalize_profit(x), reverse=True)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_PAGE.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_arbitrage": len(all_rows),
        "sports": sport_counts(all_rows),
        "arbitrage": all_rows,
        "sources": {
            "football": str(FOOTBALL_ARB_PATH),
            "ufc": str(UFC_ARB_PATH),
            "darts": str(DARTS_ARB_PATH),
        },
        "source_counts": {
            "football": len(football_rows),
            "ufc": len(ufc_rows),
            "darts": len(darts_rows),
        },
    }

    OUT_JSON.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_PAGE.write_text(render_page(all_rows), encoding="utf-8")

    print(f"Football arbs loaded: {len(football_rows)}")
    print(f"UFC arbs loaded: {len(ufc_rows)}")
    print(f"Darts arbs loaded: {len(darts_rows)}")
    print(f"Total arbs: {len(all_rows)}")
    print(f"Wrote JSON: {OUT_JSON}")
    print(f"Wrote page: {OUT_PAGE}")


if __name__ == "__main__":
    main()