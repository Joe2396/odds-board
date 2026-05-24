from pathlib import Path
from datetime import datetime, timezone
import json

ROOT = Path(__file__).resolve().parents[2]

OUT_DIR = ROOT / "darts"
DATA_DIR = OUT_DIR / "data"
OUT_PATH = OUT_DIR / "index.html"

OUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)


def esc(value):
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_section(title, subtitle, anchor):
    return f"""
    <section class="section-card" id="{anchor}">
      <div class="section-header">
        <div>
          <p class="eyebrow">Darts Markets</p>
          <h2>{esc(title)}</h2>
          <p>{esc(subtitle)}</p>
        </div>
        <span class="status-pill">Awaiting feeds</span>
      </div>

      <div class="empty-card">
        <h3>No odds loaded yet</h3>
        <p>
          This section is ready. Once we add PaddyPower, BoyleSports, BetVictor and other darts scrapers,
          match odds and props will appear here automatically.
        </p>
      </div>
    </section>
    """


def main():
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Darts Hub | Odds Board</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background: #070d18;
      color: #ffffff;
      font-family: Arial, Helvetica, sans-serif;
    }}

    .page {{
      max-width: 1840px;
      margin: 0 auto;
      padding: 46px 60px 90px;
    }}

    .hero {{
      border: 1px solid #22314a;
      border-radius: 28px;
      padding: 52px 48px;
      background:
        radial-gradient(circle at top right, rgba(34, 197, 94, 0.18), transparent 34%),
        linear-gradient(135deg, #0d1526, #111c31);
      box-shadow: 0 24px 80px rgba(0,0,0,0.35);
    }}

    .tag {{
      display: inline-flex;
      color: #22c55e;
      background: rgba(34,197,94,0.13);
      border: 1px solid rgba(34,197,94,0.35);
      padding: 10px 18px;
      border-radius: 999px;
      font-weight: 800;
      margin-bottom: 28px;
    }}

    h1 {{
      font-size: clamp(56px, 7vw, 96px);
      line-height: 0.95;
      margin: 0 0 24px;
      letter-spacing: -0.06em;
    }}

    .hero-text {{
      max-width: 1050px;
      color: #bcd0ef;
      font-size: 23px;
      line-height: 1.55;
      margin: 0;
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 18px;
      margin-top: 38px;
      max-width: 980px;
    }}

    .stat {{
      border: 1px solid #263958;
      background: rgba(5, 12, 25, 0.72);
      border-radius: 18px;
      padding: 24px;
    }}

    .stat strong {{
      display: block;
      font-size: 34px;
      margin-bottom: 8px;
    }}

    .stat span {{
      color: #bcd0ef;
    }}

    .nav-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin: 34px 0;
    }}

    .nav-tabs a {{
      color: #d9e7ff;
      text-decoration: none;
      border: 1px solid #263958;
      background: #0d1526;
      padding: 13px 18px;
      border-radius: 999px;
      font-weight: 800;
    }}

    .section-card {{
      margin-top: 28px;
      border: 1px solid #22314a;
      background: #0b1220;
      border-radius: 26px;
      overflow: hidden;
    }}

    .section-header {{
      padding: 34px 40px;
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-start;
      background: linear-gradient(135deg, rgba(31,41,55,0.95), rgba(15,23,42,0.95));
      border-bottom: 1px solid #22314a;
    }}

    .eyebrow {{
      color: #22c55e;
      font-size: 14px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      font-weight: 900;
      margin: 0 0 8px;
    }}

    h2 {{
      font-size: 36px;
      margin: 0 0 10px;
      letter-spacing: -0.04em;
    }}

    .section-header p {{
      color: #bcd0ef;
      font-size: 18px;
      margin: 0;
    }}

    .status-pill {{
      white-space: nowrap;
      color: #fde047;
      border: 1px solid rgba(253,224,71,0.45);
      background: rgba(253,224,71,0.09);
      padding: 10px 16px;
      border-radius: 999px;
      font-weight: 900;
    }}

    .empty-card {{
      margin: 28px;
      border: 1px dashed #334155;
      border-radius: 20px;
      padding: 30px;
      background: rgba(15,23,42,0.55);
    }}

    .empty-card h3 {{
      margin: 0 0 8px;
      font-size: 24px;
    }}

    .empty-card p {{
      margin: 0;
      color: #bcd0ef;
      font-size: 17px;
      line-height: 1.5;
    }}

    .footer {{
      color: #7f93b4;
      margin-top: 34px;
      font-size: 14px;
    }}

    @media (max-width: 900px) {{
      .page {{
        padding: 24px 18px 50px;
      }}

      .hero {{
        padding: 30px;
      }}

      .stats {{
        grid-template-columns: 1fr 1fr;
      }}

      .section-header {{
        flex-direction: column;
        padding: 26px;
      }}
    }}
  </style>
</head>

<body>
  <main class="page">
    <section class="hero">
      <div class="tag">🎯 Darts Lab</div>
      <h1>Darts Hub</h1>
      <p class="hero-text">
        Track darts tournaments, compare bookmaker odds, monitor match markets, props,
        outrights, EV opportunities and arbitrage across MODUS, European Tour, World Cup
        and major PDC events.
      </p>

      <div class="stats">
        <div class="stat">
          <strong>0</strong>
          <span>Matches loaded</span>
        </div>
        <div class="stat">
          <strong>0</strong>
          <span>Prop markets tracked</span>
        </div>
        <div class="stat">
          <strong>0</strong>
          <span>Bookmakers live</span>
        </div>
        <div class="stat">
          <strong>5</strong>
          <span>Tournament sections</span>
        </div>
      </div>
    </section>

    <nav class="nav-tabs">
      <a href="#modus">MODUS Super Series</a>
      <a href="#european-tour">European Tour</a>
      <a href="#world-cup">World Cup</a>
      <a href="#world-championship">World Championship</a>
      <a href="#outrights">Outrights</a>
    </nav>

    {render_section(
      "MODUS Super Series",
      "Daily MODUS match odds, legs markets, 180s, checkout props and bookmaker prices.",
      "modus"
    )}

    {render_section(
      "European Tour / PDC International Darts Open",
      "European Tour and PDC match markets grouped separately from MODUS.",
      "european-tour"
    )}

    {render_section(
      "World Cup of Darts",
      "Country/team markets, match betting and tournament props will live here.",
      "world-cup"
    )}

    {render_section(
      "World Championship",
      "World Championship matches, long-term markets and tournament-specific props.",
      "world-championship"
    )}

    {render_section(
      "Tournament Outrights",
      "Winner markets, futures prices and outright odds across bookmakers.",
      "outrights"
    )}

    <div class="footer">
      Last generated: {esc(updated)}
    </div>
  </main>
</body>
</html>
"""

    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Generated {OUT_PATH}")


if __name__ == "__main__":
    main()