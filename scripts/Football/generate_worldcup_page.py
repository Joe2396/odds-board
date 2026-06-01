#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PADDY_PATH = ROOT / "football" / "data" / "paddypower_worldcup_moneylines.json"
BOYLE_PATH = ROOT / "football" / "data" / "boylesports_worldcup_moneylines.json"
BETVICTOR_PATH = ROOT / "football" / "data" / "betvictor_worldcup_moneylines.json"

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


def slugify(s):
    s = str(s or "").lower()
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fractional_to_decimal(value):
    value = str(value or "").strip().upper()

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


def display_team(s):
    s = str(s or "").strip()

    aliases = {
        "Bosnia & Herzegovina": "Bosnia",
        "Bosnia and Herzegovina": "Bosnia",
        "Czech Republic": "Czechia",
        "Turkey": "Türkiye",
        "Turkiye": "Türkiye",
        "Curaçao": "Curacao",
    }

    return aliases.get(s, s)


def key_team(s):
    s = display_team(s).lower()
    s = s.replace("&", "and")
    s = s.replace("herzegovina", "")
    s = s.replace("türkiye", "turkiye")
    s = s.replace("turkey", "turkiye")
    s = s.replace("curaçao", "curacao")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    aliases = {
        "bosnia and": "bosnia",
        "bosnia": "bosnia",
        "czech republic": "czechia",
        "czechia": "czechia",
        "ivory coast": "ivory coast",
        "curacao": "curacao",
        "turkiye": "turkiye",
        "dr congo": "dr congo",
    }

    return aliases.get(s, s)


def fixture_key(home, away):
    return f"{key_team(home)}__{key_team(away)}"


def loose_fixture_key(home, away):
    parts = sorted([key_team(home), key_team(away)])
    return "__".join(parts)


def load_book(bookmaker, path):
    data = load_json(path)
    rows = []

    for m in data.get("matches") or []:
        home = display_team(m.get("home_team"))
        away = display_team(m.get("away_team"))

        if not home or not away:
            continue

        rows.append({
            "bookmaker": bookmaker,
            "date_label": m.get("date_label") or "",
            "time": m.get("time") or "",
            "match": f"{home} v {away}",
            "home_team": home,
            "away_team": away,
            "odds": m.get("odds") or {},
            "source_url": m.get("source_url") or "",
            "strict_key": fixture_key(home, away),
            "loose_key": loose_fixture_key(home, away),
            "generated_at": data.get("generated_at") or "",
        })

    return rows, data.get("generated_at") or ""


def add_book_rows(fixtures, strict_index, loose_index, rows, bookmaker):
    for row in rows:
        target_key = None

        if row["strict_key"] in strict_index:
            target_key = strict_index[row["strict_key"]]
        elif row["loose_key"] in loose_index:
            target_key = loose_index[row["loose_key"]]

        if target_key:
            fixtures[target_key]["bookmakers"][bookmaker] = {
                "bookmaker": bookmaker,
                "odds": row["odds"],
                "source_url": row["source_url"],
            }
        else:
            key = row["strict_key"]

            fixtures[key] = {
                "key": key,
                "loose_key": row["loose_key"],
                "slug": slugify(f"{row['home_team']}-v-{row['away_team']}"),
                "date_label": row["date_label"],
                "time": row["time"],
                "match": row["match"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "bookmakers": {
                    bookmaker: {
                        "bookmaker": bookmaker,
                        "odds": row["odds"],
                        "source_url": row["source_url"],
                    }
                },
            }

            strict_index[key] = key
            loose_index[row["loose_key"]] = key


def load_all_matches():
    paddy_rows, paddy_generated = load_book("PaddyPower", PADDY_PATH)
    boyle_rows, boyle_generated = load_book("BoyleSports", BOYLE_PATH)
    betvictor_rows, betvictor_generated = load_book("BetVictor", BETVICTOR_PATH)

    fixtures = {}

    # PaddyPower is the master fixture list.
    for row in paddy_rows:
        key = row["strict_key"]

        fixtures[key] = {
            "key": key,
            "loose_key": row["loose_key"],
            "slug": slugify(f"{row['home_team']}-v-{row['away_team']}"),
            "date_label": row["date_label"],
            "time": row["time"],
            "match": row["match"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "bookmakers": {
                "PaddyPower": {
                    "bookmaker": "PaddyPower",
                    "odds": row["odds"],
                    "source_url": row["source_url"],
                }
            },
        }

    strict_index = {f["key"]: key for key, f in fixtures.items()}
    loose_index = {f["loose_key"]: key for key, f in fixtures.items()}

    add_book_rows(fixtures, strict_index, loose_index, boyle_rows, "BoyleSports")
    add_book_rows(fixtures, strict_index, loose_index, betvictor_rows, "BetVictor")

    fixtures_list = list(fixtures.values())

    fixtures_list.sort(
        key=lambda x: (
            date_sort_key(x.get("date_label")),
            x.get("time", ""),
            x.get("match", ""),
        )
    )

    generated = betvictor_generated or boyle_generated or paddy_generated

    bookmaker_names = set()
    for f in fixtures_list:
        for b in f.get("bookmakers", {}):
            bookmaker_names.add(b)

    return fixtures_list, len(bookmaker_names), generated


def date_sort_key(date_label):
    label = str(date_label or "")

    day_order = {
        "Monday": 1,
        "Tuesday": 2,
        "Wednesday": 3,
        "Thursday": 4,
        "Friday": 5,
        "Saturday": 6,
        "Sunday": 7,
        "Mon": 1,
        "Tue": 2,
        "Wed": 3,
        "Thu": 4,
        "Fri": 5,
        "Sat": 6,
        "Sun": 7,
    }

    parts = label.split()

    number = 999
    day = 999

    if parts:
        day = day_order.get(parts[0], 999)

    for p in parts:
        if p.isdigit():
            number = int(p)
            break

    return (number, day, label)


def best_price(fixture, side):
    offers = []

    for bookmaker, info in fixture.get("bookmakers", {}).items():
        raw = (info.get("odds") or {}).get(side)
        dec = fractional_to_decimal(raw)

        if raw and dec > 1:
            offers.append({
                "bookmaker": bookmaker,
                "odds": raw,
                "decimal": dec,
            })

    if not offers:
        return None

    return sorted(offers, key=lambda x: x["decimal"], reverse=True)[0]


def all_prices_for_side(fixture, side):
    rows = []

    for bookmaker, info in sorted(fixture.get("bookmakers", {}).items()):
        raw = (info.get("odds") or {}).get(side)
        dec = fractional_to_decimal(raw)

        if raw and dec > 1:
            rows.append({
                "bookmaker": bookmaker,
                "odds": raw,
                "decimal": dec,
            })

    best = best_price(fixture, side)
    best_key = (best["bookmaker"], best["odds"]) if best else None

    for row in rows:
        row["is_best"] = best_key == (row["bookmaker"], row["odds"])

    return rows


def render_best_box(label, best):
    if not best:
        return f"""
        <div class="odd-box">
          <span>{esc(label)}</span>
          <strong>—</strong>
          <em>No price</em>
        </div>
        """

    return f"""
    <div class="odd-box">
      <span>{esc(label)}</span>
      <strong>{esc(best["odds"])}</strong>
      <em>{esc(best["bookmaker"])}</em>
    </div>
    """


def render_worldcup_page(fixtures, bookmaker_count, generated_at):
    grouped = {}

    for fixture in fixtures:
        grouped.setdefault(fixture.get("date_label") or "Upcoming", []).append(fixture)

    groups_html = ""

    for date_label, items in grouped.items():
        cards = ""

        for fixture in items:
            home = fixture["home_team"]
            away = fixture["away_team"]
            slug = fixture["slug"]

            best_home = best_price(fixture, "home")
            best_draw = best_price(fixture, "draw")
            best_away = best_price(fixture, "away")

            books_count = len(fixture.get("bookmakers", {}))

            cards += f"""
            <article class="match-card">
              <div class="match-top">
                <div>
                  <h3>{esc(home)} <span>v</span> {esc(away)}</h3>
                  <p>{esc(fixture.get("time"))} · {books_count} bookmaker{"s" if books_count != 1 else ""}</p>
                </div>
                <a class="market-badge" href="{BASE}/football/world-cup/{slug}/">View books →</a>
              </div>

              <div class="odds-grid">
                {render_best_box(home, best_home)}
                {render_best_box("Draw", best_draw)}
                {render_best_box(away, best_away)}
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

    .date-section {{ margin-top: 34px; }}

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
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
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
      padding: 6px 10px;
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

    .odd-box em {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-style: normal;
      margin-top: 5px;
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
        Best available match odds across tracked bookmakers.
        Click any fixture to compare prices by bookmaker.
      </p>

      <div class="stats">
        <div class="stat">
          <strong>{len(fixtures)}</strong>
          <span>Fixtures tracked</span>
        </div>
        <div class="stat">
          <strong>{bookmaker_count}</strong>
          <span>Bookmakers</span>
        </div>
        <div class="stat">
          <strong>Best H/D/A</strong>
          <span>Moneyline markets</span>
        </div>
      </div>

      <p class="footer-note">Updated: {esc(generated_at)}</p>
    </section>

    {groups_html}

    <p class="footer-note">
      Odds are scraped from tracked bookmakers and may change. Always check the bookmaker before placing any bet.
    </p>
  </main>
</body>
</html>
"""


def render_match_page(fixture):
    home = fixture["home_team"]
    away = fixture["away_team"]

    home_rows = all_prices_for_side(fixture, "home")
    draw_rows = all_prices_for_side(fixture, "draw")
    away_rows = all_prices_for_side(fixture, "away")

    def render_table(side_label, rows):
        body = ""

        for r in rows:
            cls = "best-row" if r["is_best"] else ""
            tag = "BEST" if r["is_best"] else ""
            body += f"""
            <tr class="{cls}">
              <td>{esc(r["bookmaker"])}</td>
              <td><strong>{esc(r["odds"])}</strong></td>
              <td>{tag}</td>
            </tr>
            """

        if not body:
            body = """
            <tr>
              <td colspan="3">No prices available</td>
            </tr>
            """

        return f"""
        <section class="price-panel">
          <h2>{esc(side_label)}</h2>
          <table>
            <thead>
              <tr>
                <th>Bookmaker</th>
                <th>Odds</th>
                <th></th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(home)} v {esc(away)} Odds — BeatTheBooks</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f1621;
      color: white;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      min-height: 100vh;
    }}
    a {{ color: #60a5fa; text-decoration: none; }}
    .page {{ max-width: 1200px; margin: 0 auto; padding: 34px 24px 70px; }}
    .nav {{ color: #91a0b5; margin-bottom: 28px; display: flex; gap: 12px; flex-wrap: wrap; }}
    .hero {{
      border: 1px solid #223047;
      border-radius: 28px;
      padding: 32px;
      background: rgba(17,24,39,0.86);
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
      margin-bottom: 14px;
    }}
    h1 {{
      font-size: clamp(38px, 6vw, 72px);
      letter-spacing: -0.055em;
      line-height: .95;
      margin-bottom: 12px;
    }}
    .meta {{ color: #91a0b5; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    .price-panel {{
      border: 1px solid #223047;
      border-radius: 20px;
      padding: 18px;
      background: rgba(17,24,39,0.72);
    }}
    .price-panel h2 {{ margin-bottom: 14px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid #223047;
      color: #c7d2fe;
      font-size: 14px;
    }}
    th {{ color: #91a0b5; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
    td strong {{ color: #22c55e; font-size: 20px; }}
    .best-row {{
      background: rgba(34,197,94,0.08);
    }}
    .best-row td:last-child {{
      color: #86efac;
      font-weight: 900;
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <main class="page">
    <nav class="nav">
      <a href="{BASE}/football/">Football</a>
      <span>›</span>
      <a href="{BASE}/football/world-cup/">FIFA World Cup</a>
      <span>›</span>
      <span>{esc(home)} v {esc(away)}</span>
    </nav>

    <section class="hero">
      <div class="eyebrow">⚽ Match Odds</div>
      <h1>{esc(home)} v {esc(away)}</h1>
      <p class="meta">{esc(fixture.get("date_label"))} · {esc(fixture.get("time"))} · {len(fixture.get("bookmakers", {}))} bookmaker{"s" if len(fixture.get("bookmakers", {})) != 1 else ""}</p>
    </section>

    <div class="grid">
      {render_table(home, home_rows)}
      {render_table("Draw", draw_rows)}
      {render_table(away, away_rows)}
    </div>
  </main>
</body>
</html>
"""


def render_football_hub(fixtures, bookmaker_count, generated_at):
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
      <p>Best available match odds across tracked bookmakers.</p>
      <div class="meta">
        <span class="pill">{len(fixtures)} fixtures</span>
        <span class="pill">{bookmaker_count} bookmakers</span>
        <span class="pill">Best H/D/A odds</span>
        <span class="pill">Updated {esc(generated_at)}</span>
      </div>
    </a>
  </main>
</body>
</html>
"""


def main():
    fixtures, bookmaker_count, generated_at = load_all_matches()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HUB_PATH.parent.mkdir(parents=True, exist_ok=True)

    OUT_PATH.write_text(render_worldcup_page(fixtures, bookmaker_count, generated_at), encoding="utf-8")
    HUB_PATH.write_text(render_football_hub(fixtures, bookmaker_count, generated_at), encoding="utf-8")

    for fixture in fixtures:
        match_dir = OUT_DIR / fixture["slug"]
        match_dir.mkdir(parents=True, exist_ok=True)
        (match_dir / "index.html").write_text(render_match_page(fixture), encoding="utf-8")

    print(f"Wrote World Cup page: {OUT_PATH}")
    print(f"Wrote Football hub: {HUB_PATH}")
    print(f"Wrote match pages: {len(fixtures)}")
    print(f"Fixtures: {len(fixtures)}")
    print(f"Bookmakers: {bookmaker_count}")


if __name__ == "__main__":
    main()