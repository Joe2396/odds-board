from pathlib import Path
from datetime import datetime, timezone
import json
import re

ROOT = Path(__file__).resolve().parents[2]

DATA_PATH = ROOT / "darts" / "data" / "paddypower_darts_matches.json"
OUT_ROOT = ROOT / "darts" / "matches"

BASE = "/odds-board"


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


def slugify(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def match_slug(match):
    return slugify(
        f"{match.get('player_1', '')}-vs-{match.get('player_2', '')}"
    )


def load_matches():
    if not DATA_PATH.exists():
        return []

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    all_matches = []

    for competition, matches in data.get("competitions", {}).items():
        for match in matches:
            match["competition"] = competition
            all_matches.append(match)

    return all_matches


def render_page(match):
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    player_1 = esc(match.get("player_1"))
    player_2 = esc(match.get("player_2"))
    competition = esc(match.get("competition"))
    time = esc(match.get("time"))
    day = esc(match.get("day"))
    bookmaker = esc(match.get("bookmaker"))

    title = f"{player_1} vs {player_2}"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title} | Darts Match</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background: #070d18;
      color: white;
      font-family: Arial, Helvetica, sans-serif;
    }}

    a {{
      text-decoration: none;
      color: inherit;
    }}

    .page {{
      max-width: 1700px;
      margin: 0 auto;
      padding: 44px 54px 80px;
    }}

    .back-link {{
      display: inline-flex;
      margin-bottom: 24px;
      color: #93c5fd;
      font-weight: 800;
    }}

    .hero {{
      border-radius: 28px;
      padding: 48px;
      border: 1px solid #22314a;
      background:
        radial-gradient(circle at top right, rgba(59,130,246,0.18), transparent 34%),
        linear-gradient(135deg, #0d1526, #111c31);
    }}

    .tag {{
      display: inline-flex;
      color: #22c55e;
      background: rgba(34,197,94,0.13);
      border: 1px solid rgba(34,197,94,0.35);
      padding: 10px 18px;
      border-radius: 999px;
      font-weight: 800;
      margin-bottom: 24px;
    }}

    h1 {{
      font-size: clamp(44px, 6vw, 82px);
      line-height: 0.95;
      margin: 0 0 18px;
      letter-spacing: -0.06em;
    }}

    .sub {{
      color: #bcd0ef;
      font-size: 22px;
      line-height: 1.5;
      max-width: 900px;
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      gap: 18px;
      margin-top: 34px;
      max-width: 1000px;
    }}

    .stat {{
      border: 1px solid #263958;
      border-radius: 18px;
      padding: 22px;
      background: rgba(5,12,25,0.72);
    }}

    .stat strong {{
      display: block;
      font-size: 28px;
      margin-bottom: 8px;
    }}

    .stat span {{
      color: #bcd0ef;
    }}

    .section {{
      margin-top: 28px;
      border-radius: 26px;
      overflow: hidden;
      border: 1px solid #22314a;
      background: #0b1220;
    }}

    .section-header {{
      padding: 30px 36px;
      border-bottom: 1px solid #22314a;
      background: linear-gradient(135deg, rgba(31,41,55,0.95), rgba(15,23,42,0.95));
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
      margin: 0;
      font-size: 34px;
      letter-spacing: -0.04em;
    }}

    .content {{
      padding: 26px;
    }}

    .placeholder {{
      border: 1px dashed #334155;
      border-radius: 20px;
      padding: 34px;
      background: rgba(15,23,42,0.5);
    }}

    .placeholder h3 {{
      margin: 0 0 12px;
      font-size: 28px;
    }}

    .placeholder p {{
      margin: 0;
      color: #bcd0ef;
      line-height: 1.6;
      font-size: 18px;
    }}

    .footer {{
      margin-top: 32px;
      color: #7f93b4;
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
    }}
  </style>
</head>

<body>
  <main class="page">

    <a class="back-link" href="{BASE}/darts/">← Back to Darts Hub</a>

    <section class="hero">

      <div class="tag">🎯 Darts Match</div>

      <h1>{title}</h1>

      <div class="sub">
        Match page for {title}. Odds comparison, props, EV calculations,
        bookmaker prices and arbitrage opportunities will appear here.
      </div>

      <div class="stats">
        <div class="stat">
          <strong>{competition}</strong>
          <span>Competition</span>
        </div>

        <div class="stat">
          <strong>{day}</strong>
          <span>Day</span>
        </div>

        <div class="stat">
          <strong>{time}</strong>
          <span>Start time</span>
        </div>

        <div class="stat">
          <strong>{bookmaker}</strong>
          <span>Source</span>
        </div>
      </div>

    </section>

    <section class="section">
      <div class="section-header">
        <div class="eyebrow">Odds</div>
        <h2>Best bookmaker prices</h2>
      </div>

      <div class="content">
        <div class="placeholder">
          <h3>Odds integration coming next</h3>
          <p>
            This page is now fully wired into the darts system.
            Next we connect bookmaker odds, props, EV analysis
            and arbitrage scanning.
          </p>
        </div>
      </div>
    </section>

    <div class="footer">
      Last generated: {updated}
    </div>

  </main>
</body>
</html>
"""


def main():
    matches = load_matches()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    generated = 0

    for match in matches:
        slug = match_slug(match)

        out_dir = OUT_ROOT / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / "index.html"

        out_path.write_text(
            render_page(match),
            encoding="utf-8"
        )

        print(f"Generated {out_path}")

        generated += 1

    print(f"Generated {generated} darts match pages")


if __name__ == "__main__":
    main()