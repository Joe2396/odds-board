#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

def url_param(s):
    return quote(str(s or ""), safe="")

ROOT = Path(__file__).resolve().parents[1]

UFC_PAGE_PATH = ROOT / "ufc" / "ev-alerts" / "index.html"
FOOTBALL_EV_PATH = ROOT / "football" / "data" / "ev_alerts.json"

OUT_JSON = ROOT / "data" / "ev_alerts_all.json"
OUT_PAGE = ROOT / "ev-alerts" / "index.html"

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


def pct(value):
    try:
        return float(value)
    except Exception:
        return 0.0


def load_football_alerts():
    data = load_json(FOOTBALL_EV_PATH)
    rows = data.get("alerts") or []

    alerts = []

    for row in rows:
        alerts.append({
            "sport": "Football",
            "competition": row.get("competition") or "FIFA World Cup",
            "event": row.get("match") or "",
            "market": row.get("market") or "Match Odds",
            "selection": row.get("selection") or "",
            "bookmaker": row.get("bookmaker") or "",
            "odds": row.get("bookmaker_odds") or "",
            "decimal_odds": row.get("bookmaker_decimal_odds") or "",
            "fair_odds": row.get("fair_fractional_odds") or "",
            "fair_decimal_odds": row.get("fair_decimal_odds") or "",
            "edge_percent": pct(row.get("ev_percent")),
            "book_count": row.get("bookmaker_count") or "",
            "time": row.get("time") or "",
            "date_label": row.get("date_label") or "",
            "source_url": row.get("source_url") or "",
            "type": row.get("type") or "moneyline_1x2",
        })

    return alerts, data


def extract_ufc_cards_from_existing_page():
    """
    Short-term bridge:
    Your existing UFC EV generator writes HTML directly, not JSON.
    So for now we keep the combined page Football-first and link users
    to the UFC EV page. Later we can refactor UFC EV into JSON.
    """
    if not UFC_PAGE_PATH.exists():
        return []

    return [{
        "sport": "UFC",
        "competition": "UFC",
        "event": "UFC EV Alerts",
        "market": "Props",
        "selection": "Open UFC EV page",
        "bookmaker": "Multiple",
        "odds": "View",
        "decimal_odds": "",
        "fair_odds": "",
        "fair_decimal_odds": "",
        "edge_percent": 0,
        "book_count": "",
        "time": "",
        "date_label": "",
        "source_url": f"{BASE}/ufc/ev-alerts/",
        "is_link_card": True,
    }]


def sport_counts(alerts):
    counts = {"All": len(alerts)}

    for row in alerts:
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


def slugify(s):
    """Convert display name to URL slug e.g. 'Iran v New Zealand' -> 'iran-v-new-zealand'"""
    import re as _re
    s = str(s or "").lower().strip()
    s = s.replace(" v ", "-v-").replace(" vs ", "-v-")
    return _re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def player_props_url(alert):
    """Build local/GitHub Pages URL to this player's props page, or None."""
    match = alert.get("event") or ""
    selection = alert.get("selection") or ""
    market_type = alert.get("type") or ""
    if "props" not in market_type:
        return None
    # Extract player name — strip threshold suffix like "2+" or "1+"
    import re as _re
    player = _re.sub(r"\s+\d+\+\s*$", "", selection).strip()
    if not player or not match:
        return None
    match_slug = slugify(match)
    player_slug = slugify(player)
    return f"../football/world-cup/{match_slug}/player-props/players/{player_slug}/index.html"


def render_alert_card(alert, index):
    sport = alert.get("sport") or "Other"
    edge = pct(alert.get("edge_percent"))

    if alert.get("is_link_card"):
        return f"""
        <article class="alert-card link-card" data-sport="{esc(sport)}">
          <div class="card-top">
            <span class="sport-pill sport-ufc">UFC</span>
            <span class="rank">#{index}</span>
          </div>

          <h2>{esc(alert.get("event"))}</h2>
          <p class="muted">Your existing UFC EV alerts are still available on the UFC page.</p>

          <a class="open-link" href="{esc(alert.get("source_url"))}">Open UFC EV Alerts →</a>
        </article>
        """

    badge_class = "hot"
    if edge >= 10:
        badge_class = "fire"
    elif edge < 5:
        badge_class = "value"

    sport_class = f"sport-{sport.lower().replace(' ', '-')}"

    meta_bits = []
    if alert.get("competition"):
        meta_bits.append(alert.get("competition"))
    if alert.get("date_label") or alert.get("time"):
        meta_bits.append(f"{alert.get('date_label', '')} {alert.get('time', '')}".strip())
    if alert.get("book_count"):
        meta_bits.append(f"{alert.get('book_count')} books")

    meta = " · ".join([str(x) for x in meta_bits if x])

    return f"""
    <article class="alert-card" data-sport="{esc(sport)}">
      <div class="card-top">
        <span class="sport-pill {esc(sport_class)}">{esc(sport)}</span>
        <span class="rank">#{index}</span>
      </div>

      <h2>{esc(alert.get("event"))}</h2>
      <p class="meta">{esc(meta)}</p>

      <div class="edge-badge {badge_class}">
        ⚡ +{edge:.2f}% EV
      </div>

      <div class="card-grid">
        <div>
          <span>Selection</span>
          <strong>{esc(alert.get("selection"))}</strong>
          <em class="market-label">{esc(alert.get("market"))}</em>
        </div>
        <div>
          <span>Best Price</span>
          <strong>{esc(alert.get("odds"))}</strong>
          <em>{esc(alert.get("bookmaker"))}</em>
        </div>
        <div>
          <span>Fair Price</span>
          <strong>{esc(alert.get("fair_odds"))}</strong>
          <em>{esc(alert.get("fair_decimal_odds"))}</em>
        </div>
      </div>
      {f'<a class="player-link" href="{player_props_url(alert)}">View all bookmaker prices →</a>' if player_props_url(alert) else ""}
      <a class="btn-tracker"
         href="https://beatthebooks-2.myshopify.com/pages/betting-tracker?sport={url_param(sport)}&event={url_param(alert.get('event',''))}&market={url_param(alert.get('market',''))}&selection={url_param(alert.get('selection',''))}&bookmaker={url_param(alert.get('bookmaker',''))}&odds={url_param(alert.get('odds',''))}"
         target="_blank">
        Add to Bet Tracker →
      </a>
    </article>
    """


def render_page(alerts, football_data):
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    counts = sport_counts(alerts)

    sorted_alerts = sorted(
        alerts,
        key=lambda x: pct(x.get("edge_percent")),
        reverse=True,
    )

    cards = ""

    if sorted_alerts:
        for i, alert in enumerate(sorted_alerts, start=1):
            cards += render_alert_card(alert, i)
    else:
        cards = """
        <div class="empty-state">
          <h2>No EV alerts right now</h2>
          <p>Run the football and UFC EV scripts, then rebuild this page.</p>
        </div>
        """

    best_edge = max([pct(a.get("edge_percent")) for a in alerts], default=0)
    football_count = counts.get("Football", 0)
    ufc_count = counts.get("UFC", 0)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EV Alerts — BeatTheBooks</title>
  <style>
    :root {{
      --bg: #0f1621;
      --panel: #111827;
      --border: #223047;
      --text: #ffffff;
      --muted: #91a0b5;
      --green: #22c55e;
      --blue: #60a5fa;
      --orange: #f97316;
      --gold: #facc15;
      --red: #ef4444;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background:
        radial-gradient(circle at top left, rgba(249,115,22,0.14), transparent 30%),
        radial-gradient(circle at top right, rgba(96,165,250,0.12), transparent 34%),
        var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      min-height: 100vh;
    }}

    a {{ color: inherit; text-decoration: none; }}

    .page {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 34px 28px 70px;
    }}

    .top-nav {{
      display: flex;
      gap: 12px;
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 28px;
      flex-wrap: wrap;
    }}

    .top-nav a {{ color: var(--blue); }}

    .hero {{
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 34px;
      background: rgba(17,24,39,0.82);
      margin-bottom: 22px;
      box-shadow: 0 20px 80px rgba(0,0,0,0.28);
    }}

    .eyebrow {{
      display: inline-flex;
      border: 1px solid rgba(249,115,22,0.45);
      background: rgba(249,115,22,0.1);
      color: #fdba74;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 16px;
    }}

    h1 {{
      font-size: clamp(42px, 6vw, 82px);
      line-height: .95;
      letter-spacing: -0.055em;
      margin-bottom: 14px;
    }}

    .subtitle {{
      color: var(--muted);
      font-size: 17px;
      max-width: 780px;
      line-height: 1.6;
      margin-bottom: 16px;
    }}

    .updated {{
      color: var(--muted);
      font-size: 13px;
    }}

    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(165px, 1fr));
      gap: 12px;
      margin: 22px 0;
    }}

    .summary-card {{
      border: 1px solid var(--border);
      border-radius: 16px;
      background: rgba(255,255,255,0.035);
      padding: 16px;
    }}

    .summary-card strong {{
      display: block;
      color: var(--green);
      font-size: 30px;
      margin-bottom: 4px;
    }}

    .summary-card span {{
      color: var(--muted);
      font-size: 13px;
    }}

    .filters {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 20px 0 26px;
    }}

    .filter-btn {{
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.035);
      color: var(--text);
      border-radius: 999px;
      padding: 10px 14px;
      font-weight: 900;
      cursor: pointer;
    }}

    .filter-btn.active {{
      border-color: rgba(34,197,94,0.55);
      background: rgba(34,197,94,0.14);
      color: #86efac;
    }}

    .filter-btn span {{
      color: var(--muted);
      margin-left: 6px;
    }}

    .alerts-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
      gap: 14px;
    }}

    .alert-card {{
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 18px;
      background: rgba(17,24,39,0.76);
    }}

    .card-top {{
      display: flex;
      justify-content: space-between;
      margin-bottom: 12px;
      align-items: center;
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

    .alert-card h2 {{
      font-size: 18px;
      letter-spacing: -0.02em;
      margin-bottom: 6px;
    }}

    .meta, .muted {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      margin-bottom: 12px;
    }}

    .edge-badge {{
      display: inline-flex;
      border-radius: 999px;
      padding: 7px 11px;
      font-size: 13px;
      font-weight: 950;
      margin-bottom: 14px;
    }}

    .edge-badge.fire {{
      color: #fecaca;
      background: rgba(239,68,68,0.12);
      border: 1px solid rgba(239,68,68,0.45);
    }}

    .edge-badge.hot {{
      color: #fdba74;
      background: rgba(249,115,22,0.12);
      border: 1px solid rgba(249,115,22,0.45);
    }}

    .edge-badge.value {{
      color: #fde68a;
      background: rgba(250,204,21,0.1);
      border: 1px solid rgba(250,204,21,0.4);
    }}

    .card-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px;
      margin-bottom: 12px;
    }}

    .card-grid div {{
      border: 1px solid var(--border);
      border-radius: 13px;
      background: rgba(15,22,33,0.82);
      padding: 11px;
    }}

    .card-grid span {{
      display: block;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 6px;
    }}

    .card-grid strong {{
      display: block;
      color: var(--text);
      font-size: 15px;
      word-break: break-word;
    }}

    .card-grid em {{
      display: block;
      color: var(--muted);
      font-style: normal;
      font-size: 11px;
      margin-top: 4px;
    }}

    .market-label {{
      display: block;
      font-size: 0.75rem;
      color: var(--text-muted, #888);
      margin-top: 2px;
    }}
    .player-link {{
      display: inline-block;
      margin-top: 12px;
      font-size: 0.8rem;
      color: var(--accent, #00e676);
      text-decoration: none;
      border: 1px solid var(--accent, #00e676);
      border-radius: 4px;
      padding: 4px 10px;
    }}
    .player-link:hover {{
      background: var(--accent, #00e676);
      color: #000;
    }}
    .btn-tracker {{
      display: block;
      margin-top: 10px;
      text-align: center;
      padding: 6px 12px;
      background: transparent;
      border: 1px solid #4ade80;
      color: #4ade80;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 600;
      text-decoration: none;
    }}
    .btn-tracker:hover {{
      background: rgba(74, 222, 128, 0.1);
    }}
    .market {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }}

    .open-link {{
      display: inline-flex;
      margin-top: 8px;
      color: #86efac;
      font-weight: 900;
    }}

    .empty-state {{
      grid-column: 1 / -1;
      border: 1px dashed var(--border);
      border-radius: 24px;
      padding: 70px 24px;
      text-align: center;
      color: var(--muted);
    }}

    @media (max-width: 760px) {{
      .page {{ padding: 22px 14px 54px; }}
      .hero {{ padding: 24px; border-radius: 22px; }}
      .alerts-grid {{ grid-template-columns: 1fr; }}
      .card-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <nav class="top-nav">
      <a href="{BASE}/">Home</a>
      <span>›</span>
      <span>EV Alerts</span>
    </nav>

    <section class="hero">
      <div class="eyebrow">⚡ EV Alerts</div>
      <h1>EV Alerts</h1>
      <p class="subtitle">
        Combined value alerts across sports. Football uses a no-vig fair price
        from tracked bookmakers. UFC alerts currently link through to the UFC EV page.
      </p>
      <p class="updated">Updated: {esc(generated)}</p>

      <div class="summary">
        <div class="summary-card">
          <strong>{len(alerts)}</strong>
          <span>Total alerts</span>
        </div>
        <div class="summary-card">
          <strong>{football_count}</strong>
          <span>Football alerts</span>
        </div>
        <div class="summary-card">
          <strong>{ufc_count}</strong>
          <span>UFC sections</span>
        </div>
        <div class="summary-card">
          <strong>{best_edge:.1f}%</strong>
          <span>Best edge</span>
        </div>
      </div>
    </section>

    <div class="filters">
      {render_filter_buttons(counts)}
    </div>

    <section class="alerts-grid" id="alertsGrid">
      {cards}
    </section>
  </main>

  <script>
    const buttons = document.querySelectorAll(".filter-btn");
    const cards = document.querySelectorAll(".alert-card");

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
    football_alerts, football_data = load_football_alerts()
    ufc_alerts = extract_ufc_cards_from_existing_page()

    all_alerts = football_alerts + ufc_alerts

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_PAGE.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "alert_count": len(all_alerts),
        "sports": sport_counts(all_alerts),
        "alerts": all_alerts,
        "football_source": str(FOOTBALL_EV_PATH),
        "ufc_source": str(UFC_PAGE_PATH),
    }

    OUT_JSON.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_PAGE.write_text(render_page(all_alerts, football_data), encoding="utf-8")

    print(f"Football alerts loaded: {len(football_alerts)}")
    print(f"UFC link cards loaded: {len(ufc_alerts)}")
    print(f"Total combined alerts: {len(all_alerts)}")
    print(f"Wrote JSON: {OUT_JSON}")
    print(f"Wrote page: {OUT_PAGE}")


if __name__ == "__main__":
    main()