from pathlib import Path
from datetime import datetime, timezone
import json
import re

ROOT = Path(__file__).resolve().parents[2]

MATCHES_PATH = ROOT / "darts" / "data" / "paddypower_darts_matches.json"
PLAYERS_PATH = ROOT / "darts" / "data" / "players_flashscore.json"
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


def norm_name(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def match_slug(match):
    return slugify(f"{match.get('player_1', '')}-vs-{match.get('player_2', '')}")


def load_matches():
    if not MATCHES_PATH.exists():
        return []

    data = json.loads(MATCHES_PATH.read_text(encoding="utf-8"))
    all_matches = []

    for competition, matches in data.get("competitions", {}).items():
        for match in matches:
            match["competition"] = competition
            all_matches.append(match)

    return all_matches


def load_players():
    if not PLAYERS_PATH.exists():
        return {}

    data = json.loads(PLAYERS_PATH.read_text(encoding="utf-8"))
    players = {}

    for player in data.get("players", []):
        name = player.get("name", "")
        if name:
            players[norm_name(name)] = player

    return players


def find_player(players, name):
    wanted = norm_name(name)

    if wanted in players:
        return players[wanted]

    # Fuzzy fallback for names like Danny Lauby vs Lauby Danny Jr
    wanted_parts = [p for p in re.split(r"\s+", str(name).lower()) if len(p) >= 3]

    for key, player in players.items():
        player_name = str(player.get("name", "")).lower()
        if all(part in player_name for part in wanted_parts[:2]):
            return player

    # Even looser fallback: surname match
    if wanted_parts:
        surname = wanted_parts[-1]
        for key, player in players.items():
            if surname in str(player.get("name", "")).lower():
                return player

    return None


def render_form(player):
    form = player.get("recent_form", []) if player else []

    if not form:
        return '<div class="muted">No recent form loaded yet.</div>'

    pills = []

    for item in form[:10]:
        cls = "win" if item == "W" else "loss" if item == "L" else "neutral"
        pills.append(f'<span class="form-pill {cls}">{esc(item)}</span>')

    return '<div class="form-row">' + "".join(pills) + "</div>"


def render_results(player):
    if not player:
        return """
        <div class="empty-mini">
          No Flashscore results matched for this player yet.
        </div>
        """

    results = player.get("last_10_results", [])[:10]

    if not results:
        return """
        <div class="empty-mini">
          No last 10 results loaded yet.
        </div>
        """

    rows = []

    for r in results:
        result = esc(r.get("result", ""))
        date = esc(r.get("date", ""))
        opponent = esc(r.get("opponent", ""))
        score = esc(r.get("score", ""))
        raw = esc(r.get("raw", ""))

        badge_cls = "win" if result == "W" else "loss" if result == "L" else "neutral"
        badge = f'<span class="result-badge {badge_cls}">{result or "—"}</span>'

        if not opponent:
            opponent = raw[:120] + ("..." if len(raw) > 120 else "")

        rows.append(f"""
        <div class="result-row">
          <div class="result-main">
            <strong>{badge} {opponent}</strong>
            <span>{date}</span>
          </div>
          <div class="score">{score or "—"}</div>
        </div>
        """)

    return "\n".join(rows)


def render_player_panel(label, name, player):
    profile_url = player.get("profile_url", "") if player else ""
    country = player.get("country", "") if player else ""
    age = player.get("age", "") if player else ""

    meta_bits = []
    if country:
        meta_bits.append(country)
    if age:
        meta_bits.append(f"Age {age}")

    meta = " • ".join(meta_bits) if meta_bits else "Flashscore data loading"

    profile_link = ""
    if profile_url:
        profile_link = f'<a class="profile-link" href="{esc(profile_url)}" target="_blank">Flashscore profile →</a>'

    return f"""
    <section class="player-panel">
      <div class="player-header">
        <div>
          <p class="eyebrow">{esc(label)}</p>
          <h2>{esc(name)}</h2>
          <div class="player-meta">{esc(meta)}</div>
        </div>
        {profile_link}
      </div>

      <div class="form-block">
        <h3>Recent form</h3>
        {render_form(player)}
      </div>

      <div class="results-block">
        <h3>Last 10 results</h3>
        {render_results(player)}
      </div>
    </section>
    """


def render_page(match, players):
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    player_1 = match.get("player_1", "")
    player_2 = match.get("player_2", "")

    p1_data = find_player(players, player_1)
    p2_data = find_player(players, player_2)

    competition = esc(match.get("competition"))
    time = esc(match.get("time"))
    day = esc(match.get("day"))
    bookmaker = esc(match.get("bookmaker"))

    title = f"{esc(player_1)} vs {esc(player_2)}"

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
      max-width: 920px;
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

    .player-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
      margin-top: 28px;
    }}

    .player-panel {{
      border-radius: 26px;
      overflow: hidden;
      border: 1px solid #22314a;
      background: #0b1220;
    }}

    .player-header {{
      padding: 30px 34px;
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-start;
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
      font-size: 38px;
      letter-spacing: -0.04em;
    }}

    h3 {{
      margin: 0 0 14px;
      font-size: 21px;
    }}

    .player-meta {{
      color: #bcd0ef;
      margin-top: 10px;
      font-size: 16px;
    }}

    .profile-link {{
      color: #93c5fd;
      font-weight: 900;
      white-space: nowrap;
    }}

    .form-block,
    .results-block {{
      padding: 26px 30px;
      border-bottom: 1px solid #18263d;
    }}

    .results-block {{
      border-bottom: none;
    }}

    .form-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .form-pill,
    .result-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 34px;
      height: 34px;
      padding: 0 10px;
      border-radius: 999px;
      font-weight: 900;
      font-size: 14px;
    }}

    .win {{
      color: #22c55e;
      background: rgba(34,197,94,0.14);
      border: 1px solid rgba(34,197,94,0.35);
    }}

    .loss {{
      color: #f87171;
      background: rgba(248,113,113,0.14);
      border: 1px solid rgba(248,113,113,0.35);
    }}

    .neutral {{
      color: #dbeafe;
      background: rgba(147,197,253,0.12);
      border: 1px solid rgba(147,197,253,0.3);
    }}

    .result-row {{
      display: grid;
      grid-template-columns: 1fr 80px;
      gap: 16px;
      align-items: center;
      padding: 15px 0;
      border-bottom: 1px solid #18263d;
    }}

    .result-row:last-child {{
      border-bottom: none;
    }}

    .result-main strong {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 15px;
    }}

    .result-main span {{
      display: block;
      margin-top: 6px;
      color: #8ea4c4;
      font-size: 14px;
    }}

    .score {{
      text-align: right;
      font-size: 20px;
      font-weight: 900;
      color: #ffffff;
    }}

    .muted,
    .empty-mini {{
      color: #9fb3d1;
      font-size: 15px;
      line-height: 1.5;
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

    @media (max-width: 1000px) {{
      .player-grid {{
        grid-template-columns: 1fr;
      }}
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

      .player-header {{
        flex-direction: column;
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
        Match page for {title}. Recent player form is powered by Flashscore.
        Odds comparison, props, EV calculations and arbitrage tools will appear here next.
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
          <span>Fixture source</span>
        </div>
      </div>
    </section>

    <div class="player-grid">
      {render_player_panel("Player 1", player_1, p1_data)}
      {render_player_panel("Player 2", player_2, p2_data)}
    </div>

    <section class="section">
      <div class="section-header">
        <div class="eyebrow">Odds</div>
        <h2>Best bookmaker prices</h2>
      </div>

      <div class="content">
        <div class="placeholder">
          <h3>Odds integration coming next</h3>
          <p>
            The match page now has fixture context and recent player results.
            Next we connect PaddyPower odds, props, EV analysis and arbitrage scanning.
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
    players = load_players()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    generated = 0

    for match in matches:
        slug = match_slug(match)
        out_dir = OUT_ROOT / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / "index.html"
        out_path.write_text(render_page(match, players), encoding="utf-8")

        print(f"Generated {out_path}")
        generated += 1

    print(f"Generated {generated} darts match pages")


if __name__ == "__main__":
    main()