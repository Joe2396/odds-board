#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]

DATA_PATH = ROOT / "football" / "data" / "paddypower_worldcup_moneylines.json"
OUT_DIR = ROOT / "football" / "world-cup"
OUT_PATH = OUT_DIR / "index.html"
HUB_PATH = ROOT / "football" / "index.html"

BASE = "/odds-board"


def esc(s):
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def load_data():
    if not DATA_PATH.exists():
        return {"matches": [], "generated_at": None}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def render_worldcup_page(data):
    matches = data.get("matches") or []
    generated_at = data.get("generated_at") or ""

    grouped = {}
    for m in matches:
        grouped.setdefault(m.get("date_label") or "Upcoming", []).append(m)

    groups_html = ""

    for date_label, items in grouped.items():
        cards = ""

        for m in items:
            home = m.get("home_team", "")
            away = m.get("away_team", "")
            odds = m.get("odds", {})

            cards += f"""
            <article class="match-card">
              <div class="match-top">
                <div>
                  <h3>{esc(home)} <span>v</span> {esc(away)}</h3>
                  <p>{esc(m.get("time"))} · PaddyPower</p>
                </div>
                <div class="market-badge">Match Odds</div>
              </div>

              <div class="odds-grid">
                <div class="odd-box">
                  <span>{esc(home)}</span>
                  <strong>{esc(odds.get("home"))}</strong>
                </div>
                <div class="odd-box">
                  <span>Draw</span>
                  <strong>{esc(odds.get("draw"))}</strong>
                </div>
                <div class="odd-box">
                  <span>{esc(away)}</span>
                  <strong>{esc(odds.get("away"))}</strong>
                </div>
              </div>
            </article>
            """

        groups_html += f"""
        <section class="date-section">
          <div class="date-header">
            <h2>{esc(date_label)}</h2>
            <span>{len(items)} match{"es" if len(items) != 1 else ""}</span>
          </div>
          <div class="matches-grid">
            {cards}
          </div>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FIFA World Cup Odds — BeatTheBooks</title>
  <style>
    :root {{
      --bg: #0f1621;
      --panel: #111827;
      --border: #223047;
      --text: #ffffff;
      --muted: #91a0b5;
      --green: #22c55e;
      --blue: #60a5fa;
      --gold: #facc15;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background:
        radial-gradient(circle at top left, rgba(34,197,94,0.16), transparent 32%),
        radial-gradient(circle at top right, rgba(96,165,250,0.13), transparent 30%),
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
      box-shadow: 0 20px 80px rgba(0,0,0,0.28);
      margin-bottom: 28px;
    }}

    .eyebrow {{
      display: inline-flex;
      border: 1px solid rgba(34,197,94,0.45);
      background: rgba(34,197,94,0.1);
      color: #86efac;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 16px;
    }}

    h1 {{
      font-size: clamp(42px, 6vw, 82px);
      line-height: 0.95;
      letter-spacing: -0.055em;
      margin-bottom: 14px;
    }}

    .subtitle {{
      color: var(--muted);
      font-size: 17px;
      max-width: 760px;
      line-height: 1.6;
      margin-bottom: 18px;
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      margin-top: 22px;
    }}

    .stat {{
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
      background: rgba(255,255,255,0.03);
    }}

    .stat strong {{
      display: block;
      font-size: 30px;
      color: var(--green);
      margin-bottom: 4px;
    }}

    .stat span {{
      color: var(--muted);
      font-size: 13px;
    }}

    .date-section {{
      margin-top: 34px;
    }}

    .date-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
      margin-bottom: 14px;
    }}

    .date-header h2 {{
      font-size: 24px;
      letter-spacing: -0.02em;
    }}

    .date-header span {{
      border: 1px solid rgba(96,165,250,0.35);
      color: #bfdbfe;
      background: rgba(96,165,250,0.08);
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 800;
    }}

    .matches-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
      gap: 14px;
    }}

    .match-card {{
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 18px;
      background: rgba(17,24,39,0.72);
    }}

    .match-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 16px;
    }}

    .match-top h3 {{
      font-size: 18px;
      letter-spacing: -0.02em;
      margin-bottom: 5px;
    }}

    .match-top h3 span {{
      color: var(--muted);
      font-weight: 500;
    }}

    .match-top p {{
      color: var(--muted);
      font-size: 13px;
    }}

    .market-badge {{
      white-space: nowrap;
      border: 1px solid rgba(250,204,21,0.4);
      color: #fde68a;
      background: rgba(250,204,21,0.08);
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 11px;
      font-weight: 900;
      text-transform: uppercase;
    }}

    .odds-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }}

    .odd-box {{
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 10px;
      background: rgba(15,22,33,0.82);
      text-align: center;
    }}

    .odd-box span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
      min-height: 30px;
    }}

    .odd-box strong {{
      display: block;
      color: var(--green);
      font-size: 22px;
      font-weight: 950;
    }}

    .footer-note {{
      margin-top: 34px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}

    @media (max-width: 700px) {{
      .page {{ padding: 20px 14px 50px; }}
      .hero {{ padding: 24px; border-radius: 22px; }}
      .matches-grid {{ grid-template-columns: 1fr; }}
      .odds-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <nav class="top-nav">
      <a href="{BASE}/football/">Football</a>
      <span>›</span>
      <span>FIFA World Cup</span>
    </nav>

    <section class="hero">
      <div class="eyebrow">⚽ Football Odds</div>
      <h1>FIFA World Cup Odds</h1>
      <p class="subtitle">
        PaddyPower match odds for available FIFA World Cup fixtures.
        This first version tracks moneylines only: Home, Draw and Away.
      </p>

      <div class="stats">
        <div class="stat">
          <strong>{len(matches)}</strong>
          <span>Fixtures tracked</span>
        </div>
        <div class="stat">
          <strong>1</strong>
          <span>Bookmaker</span>
        </div>
        <div class="stat">
          <strong>H/D/A</strong>
          <span>Moneyline markets</span>
        </div>
      </div>

      <p class="footer-note">Updated: {esc(generated_at)}</p>
    </section>

    {groups_html}

    <p class="footer-note">
      Odds are scraped from PaddyPower and may change. Always check the bookmaker before placing any bet.
    </p>
  </main>
</body>
</html>
"""


def render_football_hub(data):
    matches = data.get("matches") or []
    generated_at = data.get("generated_at") or ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Football — BeatTheBooks</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f1621;
      color: white;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      min-height: 100vh;
    }}
    a {{ color: inherit; text-decoration: none; }}
    .page {{ max-width: 1200px; margin: 0 auto; padding: 42px 24px; }}
    .hero {{
      border: 1px solid #223047;
      border-radius: 28px;
      padding: 34px;
      background: rgba(17,24,39,0.85);
      margin-bottom: 24px;
    }}
    .eyebrow {{
      display: inline-block;
      color: #86efac;
      border: 1px solid rgba(34,197,94,0.45);
      background: rgba(34,197,94,0.1);
      padding: 7px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
      margin-bottom: 16px;
    }}
    h1 {{ font-size: clamp(42px, 6vw, 78px); letter-spacing: -0.055em; margin-bottom: 12px; }}
    p {{ color: #91a0b5; line-height: 1.6; }}
    .card {{
      display: block;
      border: 1px solid #223047;
      border-radius: 22px;
      padding: 24px;
      background: rgba(255,255,255,0.035);
      transition: transform .15s ease, border-color .15s ease;
    }}
    .card:hover {{ transform: translateY(-2px); border-color: rgba(96,165,250,0.55); }}
    .card h2 {{ font-size: 28px; margin-bottom: 8px; }}
    .meta {{ margin-top: 18px; display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{
      border: 1px solid #223047;
      border-radius: 999px;
      padding: 7px 10px;
      color: #bfdbfe;
      font-size: 13px;
      font-weight: 800;
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="eyebrow">⚽ Football</div>
      <h1>Football Hub</h1>
      <p>Football odds, fixtures and betting tools. Starting with FIFA World Cup moneylines.</p>
    </section>

    <a class="card" href="{BASE}/football/world-cup/">
      <h2>FIFA World Cup</h2>
      <p>PaddyPower match odds for available World Cup fixtures.</p>
      <div class="meta">
        <span class="pill">{len(matches)} fixtures</span>
        <span class="pill">Match Odds</span>
        <span class="pill">Updated {esc(generated_at)}</span>
      </div>
    </a>
  </main>
</body>
</html>
"""


def main():
    data = load_data()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HUB_PATH.parent.mkdir(parents=True, exist_ok=True)

    OUT_PATH.write_text(render_worldcup_page(data), encoding="utf-8")
    HUB_PATH.write_text(render_football_hub(data), encoding="utf-8")

    print(f"Wrote World Cup page: {OUT_PATH}")
    print(f"Wrote Football hub: {HUB_PATH}")
    print(f"Fixtures: {len(data.get('matches') or [])}")


if __name__ == "__main__":
    main()