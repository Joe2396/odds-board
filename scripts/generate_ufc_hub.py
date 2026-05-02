#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DATA_PATH = os.path.join(ROOT, "ufc", "data", "events.json")
ODDS_PATH = os.path.join(ROOT, "ufc", "data", "odds.json")
OUT_PATH = os.path.join(ROOT, "ufc", "index.html")

BASE = "/odds-board"


def load_events():
    if not os.path.exists(DATA_PATH):
        return {"generated_at": None, "events": []}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_odds():
    if not os.path.exists(ODDS_PATH):
        return {"events": []}
    with open(ODDS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def esc(s):
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def norm_name(name):
    return " ".join(str(name or "").lower().strip().split())


def get_corner_name(corner):
    if isinstance(corner, dict):
        return corner.get("name") or ""
    if isinstance(corner, str):
        return corner
    return ""


def fmt_generated(ts):
    if not ts:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(ts).replace("T", " ").replace("+00:00", " UTC")


def implied_prob(decimal_odds):
    try:
        odds = float(decimal_odds)
        if odds <= 1:
            return "—"
        return f"{round((1 / odds) * 100, 1)}%"
    except Exception:
        return "—"


def parse_event_date(value):
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        raw_iso = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def is_upcoming_event(ev):
    dt = parse_event_date(ev.get("date"))
    if not dt:
        return False

    today = datetime.now(timezone.utc).date()
    status = str(ev.get("status") or "").strip().lower()

    if status == "upcoming":
        return dt.date() >= today

    return dt.date() >= today


def sort_key(ev):
    dt = parse_event_date(ev.get("date"))
    return dt or datetime.max.replace(tzinfo=timezone.utc)


def find_featured_fight(upcoming_events):
    for ev in upcoming_events:
        fights = ev.get("fights", []) or []
        if not fights:
            continue

        fight = fights[0]
        fight_id = str(fight.get("id") or "").strip()
        red = esc(get_corner_name(fight.get("red")))
        blue = esc(get_corner_name(fight.get("blue")))

        if not fight_id or not red or not blue:
            continue

        return {
            "event_name": esc(ev.get("name")),
            "event_date": esc(ev.get("date")),
            "event_location": esc(ev.get("location")),
            "event_slug": esc(ev.get("slug") or ev.get("id")),
            "fight_id": esc(fight_id),
            "red": red,
            "blue": blue,
            "title": f"{red} vs {blue}",
            "weight": esc(fight.get("weight_class")),
            "bout": esc(fight.get("bout")),
            "status": esc(fight.get("status")),
        }

    return None


def find_odds_event(red, blue, odds_events):
    target = {norm_name(red), norm_name(blue)}

    for ev in odds_events:
        home = norm_name(ev.get("home_team"))
        away = norm_name(ev.get("away_team"))

        if {home, away} == target:
            return ev

    return None


def best_price_for_fighter(fighter_name, odds_event):
    if not odds_event:
        return None

    target = norm_name(fighter_name)
    prices = []

    for book in odds_event.get("bookmakers", []) or []:
        bookmaker = book.get("title") or book.get("key")

        for market in book.get("markets", []) or []:
            if market.get("key") != "h2h":
                continue

            for outcome in market.get("outcomes", []) or []:
                if norm_name(outcome.get("name")) == target:
                    try:
                        prices.append(
                            {
                                "bookmaker": bookmaker,
                                "price": float(outcome.get("price")),
                                "last_update": book.get("last_update"),
                            }
                        )
                    except Exception:
                        pass

    if not prices:
        return None

    return sorted(prices, key=lambda x: x["price"], reverse=True)[0]


def render_betting_edge(red, blue, odds_events):
    odds_event = find_odds_event(red, blue, odds_events)

    red_best = best_price_for_fighter(red, odds_event)
    blue_best = best_price_for_fighter(blue, odds_event)

    def row(name, best):
        if not best:
            return f"""
            <div class="bet-row">
              <div>
                <strong>{esc(name)}</strong>
                <span class="muted">No odds found</span>
              </div>
              <div>
                <span class="odds-price">—</span>
                <span class="muted">Implied: —</span>
              </div>
            </div>
            """

        return f"""
        <div class="bet-row">
          <div>
            <strong>{esc(name)}</strong>
            <span class="muted">{esc(best.get("bookmaker"))}</span>
          </div>
          <div>
            <span class="odds-price">@ {esc(best.get("price"))}</span>
            <span class="muted">Implied: {implied_prob(best.get("price"))}</span>
          </div>
        </div>
        """

    return f"""
    <div class="betting-panel">
      <div class="betting-head">
        <div>
          <div class="eyebrow">💰 Betting Edge</div>
          <h3>Best Moneyline Prices</h3>
        </div>
        <span class="edge-pill">+EV model coming next</span>
      </div>

      {row(red, red_best)}
      {row(blue, blue_best)}

      <p class="muted betting-note">
        This currently shows best available UK moneyline odds and implied probability.
        True +EV needs a fair-probability model.
      </p>
    </div>
    """


def main():
    payload = load_events()
    events = payload.get("events", []) or []
    generated_at = payload.get("generated_at")

    odds_payload = load_odds()
    odds_events = odds_payload.get("events", []) or []

    upcoming_events = [ev for ev in events if is_upcoming_event(ev)]
    upcoming_events = sorted(upcoming_events, key=sort_key)

    featured = find_featured_fight(upcoming_events)

    featured_html = ""
    if featured:
        betting_html = render_betting_edge(
            featured["red"],
            featured["blue"],
            odds_events,
        )

        featured_html = f"""
    <section class="featured-fight">
      <div class="featured-copy">
        <div class="eyebrow">🔥 Featured Fight</div>
        <h2>{featured["title"]}</h2>
        <p class="muted">
          {featured["event_name"]} • {featured["event_date"]} • {featured["event_location"]}
        </p>

        <div class="featured-meta">
          <span>{featured["weight"]}</span>
          <span>{featured["bout"]}</span>
          <span>Status: {featured["status"]}</span>
        </div>

        <div class="actions">
          <a class="btn primary" href="{BASE}/ufc/fights/{featured["fight_id"]}/">View full breakdown →</a>
          <a class="btn" href="{BASE}/ufc/events/{featured["event_slug"]}/">View full event →</a>
        </div>
      </div>

      <div class="fighter-vs">
        <div class="fighter-side">
          <span>Red corner</span>
          <strong>{featured["red"]}</strong>
        </div>
        <div class="vs">VS</div>
        <div class="fighter-side">
          <span>Blue corner</span>
          <strong>{featured["blue"]}</strong>
        </div>
      </div>

      {betting_html}
    </section>
        """

    rows_html = ""
    if not upcoming_events:
        rows_html = "<div class='empty'>No upcoming events found.</div>"
    else:
        for ev in upcoming_events:
            name = esc(ev.get("name"))
            date = esc(ev.get("date"))
            location = esc(ev.get("location"))
            slug = esc(ev.get("slug") or ev.get("id"))

            if not slug:
                continue

            rows_html += f"""
            <a class="event-card" href="{BASE}/ufc/events/{slug}/">
              <div>
                <div class="event-kicker">Upcoming event</div>
                <h3>{name}</h3>
                <p>{date} • {location}</p>
              </div>
              <span>→</span>
            </a>
            """.rstrip()

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>UFC Hub</title>
  <style>
    :root {{
      --bg: #0F1621;
      --panel: #111827;
      --panel-2: #0b1220;
      --border: #263447;
      --text: #ffffff;
      --muted: #aab4c0;
      --blue: #60a5fa;
      --green: #22c55e;
      --gold: #facc15;
    }}

    * {{ box-sizing: border-box; }}

    html, body {{
      margin: 0;
      padding: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    body {{
      width: 100%;
      min-height: 100vh;
      overflow-x: hidden;
    }}

    a {{
      color: var(--blue);
      text-decoration: none;
    }}

    a:hover {{ text-decoration: underline; }}

    .page {{
      width: 100%;
      max-width: none;
      margin: 0;
      padding: 36px 48px 64px;
    }}

    .hero, .featured-fight {{
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 24px;
      background:
        radial-gradient(circle at top right, rgba(96,165,250,0.18), transparent 28%),
        linear-gradient(180deg, var(--panel), var(--panel-2));
      padding: 36px;
      box-shadow: 0 24px 60px rgba(0,0,0,0.28);
    }}

    .hero-top {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 24px;
      flex-wrap: wrap;
    }}

    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--green);
      border: 1px solid rgba(34,197,94,0.35);
      background: rgba(34,197,94,0.10);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 14px;
      font-weight: 700;
      margin-bottom: 16px;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(38px, 5vw, 72px);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }}

    .subtitle {{
      max-width: 780px;
      margin: 18px 0 0;
      color: var(--muted);
      font-size: 18px;
      line-height: 1.6;
    }}

    .actions {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 28px;
    }}

    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 12px;
      padding: 12px 16px;
      font-weight: 800;
      border: 1px solid var(--border);
      background: #162033;
      color: white;
    }}

    .btn.primary {{
      background: var(--blue);
      color: #07111f;
      border-color: var(--blue);
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      min-width: 360px;
    }}

    .stat {{
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 18px;
      background: rgba(15,22,33,0.75);
    }}

    .stat strong {{
      display: block;
      font-size: 28px;
      margin-bottom: 4px;
    }}

    .stat span {{
      color: var(--muted);
      font-size: 14px;
    }}

    .featured-fight {{
      margin-top: 28px;
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.8fr);
      gap: 24px;
      align-items: stretch;
      background:
        radial-gradient(circle at top left, rgba(250,204,21,0.16), transparent 26%),
        linear-gradient(180deg, #131d2d, #0b1220);
    }}

    .featured-fight h2 {{
      margin: 0;
      font-size: clamp(34px, 4vw, 58px);
      line-height: 1;
      letter-spacing: -0.04em;
    }}

    .featured-meta {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}

    .featured-meta span {{
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 8px 12px;
      color: var(--muted);
      background: rgba(255,255,255,0.025);
      font-size: 13px;
    }}

    .fighter-vs {{
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      gap: 12px;
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 18px;
      background: rgba(255,255,255,0.025);
    }}

    .fighter-side {{
      min-height: 150px;
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 18px;
      background: #0F1621;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}

    .fighter-side span {{
      color: var(--muted);
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 10px;
    }}

    .fighter-side strong {{
      font-size: 24px;
      line-height: 1.1;
    }}

    .vs {{
      color: var(--gold);
      font-weight: 900;
      font-size: 20px;
    }}

    .betting-panel {{
      grid-column: 1 / -1;
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 22px;
      background: rgba(15,22,33,0.75);
    }}

    .betting-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }}

    .betting-head h3 {{
      margin: 0;
      font-size: 28px;
    }}

    .edge-pill {{
      border: 1px solid rgba(250,204,21,0.45);
      background: rgba(250,204,21,0.10);
      color: var(--gold);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
      font-weight: 800;
    }}

    .bet-row {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      background: #0F1621;
      margin-top: 10px;
    }}

    .bet-row strong,
    .bet-row span {{
      display: block;
    }}

    .odds-price {{
      font-size: 24px;
      font-weight: 900;
      color: var(--green);
      text-align: right;
    }}

    .betting-note {{
      margin: 14px 0 0;
      font-size: 14px;
    }}

    .section-head {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin: 36px 0 16px;
      flex-wrap: wrap;
    }}

    h2 {{
      margin: 0;
      font-size: 32px;
      letter-spacing: -0.03em;
    }}

    .muted {{ color: var(--muted); }}

    .events-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(330px, 1fr));
      gap: 16px;
      width: 100%;
    }}

    .event-card {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      min-height: 180px;
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 22px;
      background: var(--panel);
      color: white;
      transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
    }}

    .event-card:hover {{
      transform: translateY(-2px);
      border-color: rgba(96,165,250,0.7);
      background: #152033;
      text-decoration: none;
    }}

    .event-kicker {{
      color: var(--green);
      font-size: 13px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 12px;
    }}

    .event-card h3 {{
      margin: 0 0 14px;
      font-size: 22px;
      line-height: 1.25;
      color: white;
    }}

    .event-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
    }}

    .event-card span {{
      color: var(--blue);
      font-size: 26px;
    }}

    .footer {{
      margin-top: 34px;
      padding-top: 22px;
      border-top: 1px solid var(--border);
      color: var(--muted);
      display: flex;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }}

    .empty {{
      border: 1px dashed var(--border);
      border-radius: 18px;
      padding: 24px;
      color: var(--muted);
      background: var(--panel);
    }}

    @media (max-width: 950px) {{
      .featured-fight {{
        grid-template-columns: 1fr;
      }}

      .fighter-vs {{
        grid-template-columns: 1fr;
      }}

      .vs {{
        text-align: center;
      }}
    }}

    @media (max-width: 800px) {{
      .page {{
        padding: 24px 18px 48px;
      }}

      .hero, .featured-fight {{
        padding: 24px;
      }}

      .stats {{
        min-width: 0;
        width: 100%;
        grid-template-columns: 1fr;
      }}

      .events-grid {{
        grid-template-columns: 1fr;
      }}

      .bet-row {{
        align-items: flex-start;
        flex-direction: column;
      }}

      .odds-price {{
        text-align: left;
      }}
    }}
  </style>
</head>
<body>

  <main class="page">
    <section class="hero">
      <div class="hero-top">
        <div>
          <div class="eyebrow">🥊 UFC Lab</div>
          <h1>UFC Hub</h1>
          <p class="subtitle">
            Full-width UFC research dashboard for upcoming events, fight cards, fighter profiles and betting prep.
          </p>

          <div class="actions">
            <a class="btn primary" href="{BASE}/ufc/fighters/">Browse fighters →</a>
            <a class="btn" href="{BASE}/ufc/events/">View all events →</a>
          </div>
        </div>

        <div class="stats">
          <div class="stat">
            <strong>{len(upcoming_events)}</strong>
            <span>Upcoming events</span>
          </div>
          <div class="stat">
            <strong>10</strong>
            <span>Recent fights tracked</span>
          </div>
          <div class="stat">
            <strong>ML</strong>
            <span>Moneyline odds ready</span>
          </div>
        </div>
      </div>
    </section>

    {featured_html}

    <div class="section-head">
      <div>
        <h2>Upcoming Events</h2>
        <p class="muted">Select an event to view fight cards and matchup pages.</p>
      </div>
      <a class="btn" href="{BASE}/ufc/fighters/">Fighter database →</a>
    </div>

    <section class="events-grid">
      {rows_html}
    </section>

    <div class="footer">
      <span>Generated: {esc(fmt_generated(generated_at))}</span>
      <a href="{BASE}/">← Back to home</a>
    </div>
  </main>

</body>
</html>
"""

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Wrote UFC hub: {OUT_PATH}")
    print(f"Upcoming events shown: {len(upcoming_events)}")


if __name__ == "__main__":
    main()
