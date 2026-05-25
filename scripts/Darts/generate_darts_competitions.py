from pathlib import Path
from datetime import datetime, timezone
import json
import re

ROOT = Path(__file__).resolve().parents[2]

DATA_PATH = ROOT / "darts" / "data" / "paddypower_darts_matches.json"
OUT_ROOT = ROOT / "darts" / "competitions"

BASE = "/odds-board"

COMPETITION_SLUGS = {
    "MODUS Super Series": "modus-super-series",
    "European Tour / PDC International Darts Open": "european-tour",
    "World Cup of Darts": "world-cup",
    "World Championship": "world-championship",
}


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
    return slugify(f"{match.get('player_1', '')}-vs-{match.get('player_2', '')}")


def load_matches():
    if not DATA_PATH.exists():
        return {}
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return data.get("competitions", {})


def render_match_card(match):
    player_1 = esc(match.get("player_1"))
    player_2 = esc(match.get("player_2"))
    time = esc(match.get("time"))
    day = esc(match.get("day"))
    bookmaker = esc(match.get("bookmaker", "PaddyPower"))
    slug = match_slug(match)

    return f"""
    <a class="match-card" href="{BASE}/darts/matches/{slug}/">
      <div>
        <div class="match-title">{player_1} vs {player_2}</div>
        <div class="match-meta">{day} • {time} • {bookmaker}</div>
      </div>
      <div class="match-actions">
        <span class="coming-soon">View match →</span>
      </div>
    </a>
    """


def render_page(competition_name, matches):
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    match_count = len(matches)

    body = "\n".join(render_match_card(m) for m in matches) if matches else """
    <div class="empty-card">
      <h3>No matches loaded yet</h3>
      <p>This page is ready. Once fixtures are detected, they will appear here automatically.</p>
    </div>
    """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{esc(competition_name)} | Darts Hub</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #070d18;
      color: #fff;
      font-family: Arial, Helvetica, sans-serif;
    }}
    a {{ color: inherit; text-decoration: none; }}
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
      border: 1px solid #22314a;
      border-radius: 28px;
      padding: 46px;
      background:
        radial-gradient(circle at top right, rgba(34,197,94,0.18), transparent 34%),
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
      font-size: clamp(44px, 6vw, 78px);
      line-height: 0.95;
      margin: 0 0 20px;
      letter-spacing: -0.06em;
    }}
    .hero p {{
      max-width: 940px;
      color: #bcd0ef;
      font-size: 21px;
      line-height: 1.5;
      margin: 0;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(160px, 1fr));
      gap: 18px;
      margin-top: 34px;
      max-width: 760px;
    }}
    .stat {{
      border: 1px solid #263958;
      background: rgba(5,12,25,0.72);
      border-radius: 18px;
      padding: 22px;
    }}
    .stat strong {{
      display: block;
      font-size: 32px;
      margin-bottom: 8px;
    }}
    .stat span {{ color: #bcd0ef; }}
    .section-card {{
      margin-top: 30px;
      border: 1px solid #22314a;
      background: #0b1220;
      border-radius: 26px;
      overflow: hidden;
    }}
    .section-header {{
      padding: 30px 36px;
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
      font-size: 34px;
      margin: 0;
      letter-spacing: -0.04em;
    }}
    .matches {{ padding: 24px; }}
    .match-card {{
      display: grid;
      grid-template-columns: 1fr 220px;
      gap: 20px;
      align-items: center;
      border: 1px solid #22314a;
      border-radius: 18px;
      padding: 22px;
      margin-bottom: 14px;
      background: #080f1d;
      transition: 0.18s ease;
    }}
    .match-card:hover {{
      border-color: #3b82f6;
      transform: translateY(-1px);
    }}
    .match-title {{
      font-size: 23px;
      font-weight: 900;
    }}
    .match-meta {{
      color: #9fb3d1;
      margin-top: 8px;
      font-size: 15px;
    }}
    .match-actions {{ text-align: right; }}
    .coming-soon {{
      display: inline-flex;
      color: #fde047;
      border: 1px solid rgba(253,224,71,0.45);
      background: rgba(253,224,71,0.09);
      padding: 10px 14px;
      border-radius: 999px;
      font-weight: 900;
      white-space: nowrap;
    }}
    .empty-card {{
      margin: 28px;
      border: 1px dashed #334155;
      border-radius: 20px;
      padding: 30px;
      background: rgba(15,23,42,0.55);
    }}
    .footer {{
      color: #7f93b4;
      margin-top: 34px;
      font-size: 14px;
    }}
    @media (max-width: 900px) {{
      .page {{ padding: 24px 18px 50px; }}
      .hero {{ padding: 30px; }}
      .stats {{ grid-template-columns: 1fr; }}
      .match-card {{ grid-template-columns: 1fr; }}
      .match-actions {{ text-align: left; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <a class="back-link" href="{BASE}/darts/">← Back to Darts Hub</a>
    <section class="hero">
      <div class="tag">🎯 Darts Competition</div>
      <h1>{esc(competition_name)}</h1>
      <p>Fixture board for {esc(competition_name)}. Click a match to view its dedicated odds, props, EV and arbitrage page.</p>
      <div class="stats">
        <div class="stat"><strong>{match_count}</strong><span>Matches loaded</span></div>
        <div class="stat"><strong>1</strong><span>Bookmaker source</span></div>
        <div class="stat"><strong>0</strong><span>Odds markets live</span></div>
      </div>
    </section>
    <section class="section-card">
      <div class="section-header">
        <p class="eyebrow">Fixtures</p>
        <h2>Upcoming matches</h2>
      </div>
      <div class="matches">{body}</div>
    </section>
    <div class="footer">Last generated: {esc(updated)}</div>
  </main>
</body>
</html>
"""


def main():
    competitions = load_matches()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    total_pages = 0

    for competition_name, matches in competitions.items():
        slug = COMPETITION_SLUGS.get(competition_name) or slugify(competition_name)
        out_dir = OUT_ROOT / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "index.html"
        out_path.write_text(render_page(competition_name, matches), encoding="utf-8")
        print(f"Generated {out_path} ({len(matches)} matches)")
        total_pages += 1

    print(f"Generated {total_pages} darts competition pages")


if __name__ == "__main__":
    main()