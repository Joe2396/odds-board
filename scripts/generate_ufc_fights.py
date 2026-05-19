#!/usr/bin/env python3

import json
import re
import unicodedata
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]

EVENTS_JSON = ROOT / "ufc" / "data" / "events.json"
FIGHTERS_JSON = ROOT / "ufc" / "data" / "fighters.json"
ODDS_JSON = ROOT / "ufc" / "data" / "odds.json"

PROP_FILES = [
    ("PaddyPower", ROOT / "ufc" / "data" / "props.json"),
    ("BoyleSports", ROOT / "ufc" / "data" / "boylesports_props.json"),
    ("BetVictor", ROOT / "ufc" / "data" / "betvictor_props.json"),
    ("Coral", ROOT / "ufc" / "data" / "coral_props.json"),
    ("BetMGM", ROOT / "ufc" / "data" / "betmgm_props.json"),
]

FIGHTS_DIR = ROOT / "ufc" / "fights"
BASE_PATH = "/odds-board/ufc"

OUTLIER_THRESHOLD_PERCENT = 10
MIN_VALID_PRICE = 1.06
DEBUG_PROP_MATCHING = True


def html_escape(s):
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


def attr_escape(s):
    return html_escape(s).replace("\n", " ").replace("\r", " ")


def url_quote(s):
    return quote(str(s or ""), safe="")


def url_param(s):
    return quote(str(s or ""), safe="")


def build_tracker_href(sport, event_name, market, selection, bookmaker, odds):
    return (
        f"{BASE_PATH}/tracker/"
        f"?sport={url_param(sport)}"
        f"&event={url_param(event_name)}"
        f"&market={url_param(market)}"
        f"&selection={url_param(selection)}"
        f"&bookmaker={url_param(bookmaker)}"
        f"&odds={url_param(odds)}"
    )


def slugify(name):
    name = str(name or "").strip().lower()
    name = name.replace(" vs ", " v ")
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def normalize_person_name(name):
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = text.replace("'", "")
    text = text.replace("’", "")
    text = text.replace(".", "")
    text = text.replace("-", " ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r'"[^"]*"', " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fight_key(name):
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()

    text = text.replace(" versus ", " v ")
    text = text.replace(" vs. ", " v ")
    text = text.replace(" vs ", " v ")
    text = text.replace(" v. ", " v ")
    text = text.replace("–", " ")
    text = text.replace("—", " ")

    text = re.sub(r"\bversus\b", " v ", text)
    text = re.sub(r"\bvs\b", " v ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if " v " in text:
        left, right = text.split(" v ", 1)
        left = normalize_person_name(left)
        right = normalize_person_name(right)
        fighters = sorted([left, right])
        return " v ".join(fighters)

    return normalize_person_name(text)


def loose_fight_tokens(name):
    key = fight_key(name)
    return set(re.findall(r"[a-z0-9]+", key))


def keys_probably_match(event_name, prop_name):
    event_tokens = loose_fight_tokens(event_name)
    prop_tokens = loose_fight_tokens(prop_name)

    if not event_tokens or not prop_tokens:
        return False

    shared = event_tokens.intersection(prop_tokens)
    return len(shared) >= 3


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


def clean_selection(selection):
    text = str(selection or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("Over (+", "Over ")
    text = text.replace("Under (+", "Under ")
    text = text.replace(")", "")
    text = text.replace("+", "")
    return text.strip()


def selection_key(selection):
    text = clean_selection(selection).lower()
    text = text.replace("ko/tko", "ko")
    text = text.replace("tko/ko", "ko")
    text = text.replace("knockout", "ko")
    text = text.replace("submission", "sub")
    text = text.replace("decision", "dec")
    text = re.sub(r"[^a-z0-9\s\.]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def canonical_market_label(label):
    text = str(label or "").lower()

    if "fight betting" in text or text == "fight_betting":
        return "Fight Betting"
    if "method" in text:
        return "Method of Victory"
    if "round" in text:
        return "Rounds"
    if "distance" in text:
        return "Go The Distance?"

    return label or "Props"


def market_key(label):
    return canonical_market_label(label).lower().strip()


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_events():
    return load_json(EVENTS_JSON, {"events": []}).get("events", [])


def load_odds():
    return load_json(ODDS_JSON, {"events": []}).get("events", [])


def load_all_props():
    props_by_key = {}

    def add_item(name, item):
        if not name:
            return

        key = fight_key(name)
        if not key:
            return

        item = dict(item)
        item["match_key"] = key
        props_by_key.setdefault(key, []).append(item)

    for default_bookmaker, path in PROP_FILES:
        data = load_json(path, {"fights": [], "props": []})

        for fight in data.get("fights", []) or []:
            bookmaker = fight.get("bookmaker") or default_bookmaker
            name = fight.get("fight") or fight.get("fight_name") or fight.get("name") or ""

            if not name:
                continue

            item = dict(fight)
            item["bookmaker"] = bookmaker
            item["fight_name"] = name

            markets = item.get("markets")
            if not isinstance(markets, dict):
                markets = {}

            normalized_markets = {}

            if markets.get("fight_betting"):
                normalized_markets["fight_betting"] = markets.get("fight_betting") or []

            if markets.get("method_of_victory"):
                normalized_markets["method_of_victory"] = markets.get("method_of_victory") or []

            if markets.get("total_rounds"):
                normalized_markets["total_rounds"] = markets.get("total_rounds") or []

            if markets.get("rounds"):
                normalized_markets["rounds"] = markets.get("rounds") or []

            if markets.get("go_the_distance"):
                normalized_markets["go_the_distance"] = markets.get("go_the_distance") or []

            if normalized_markets:
                item["markets"] = normalized_markets

            add_item(name, item)

        flat_props = data.get("props", []) or []
        grouped = {}

        for prop in flat_props:
            name = prop.get("fight") or prop.get("fight_name") or prop.get("name") or ""

            if not name:
                continue

            bookmaker = prop.get("bookmaker") or default_bookmaker
            key = (bookmaker, fight_key(name))

            grouped.setdefault(
                key,
                {
                    "bookmaker": bookmaker,
                    "fight_name": name,
                    "url": prop.get("url") or "#",
                    "markets": {
                        "fight_betting": [],
                        "method_of_victory": [],
                        "total_rounds": [],
                        "go_the_distance": [],
                    },
                    "method_props": [],
                    "round_props": [],
                    "distance_props": [],
                },
            )

            market = str(prop.get("market") or "").lower()
            selection = prop.get("selection")
            odds = prop.get("odds")

            if not selection or not odds:
                continue

            row = {"selection": selection, "odds": odds}

            if "fight betting" in market or "moneyline" in market or "winner" in market:
                grouped[key]["markets"]["fight_betting"].append(row)
            elif "distance" in market:
                grouped[key]["markets"]["go_the_distance"].append(row)
                grouped[key]["distance_props"].append(row)
            elif "round" in market:
                grouped[key]["markets"]["total_rounds"].append(row)
                grouped[key]["round_props"].append(row)
            elif "method" in market:
                grouped[key]["markets"]["method_of_victory"].append(row)
                grouped[key]["method_props"].append(row)

        for item in grouped.values():
            add_item(item.get("fight_name"), item)

    return props_by_key


def load_fighter_details():
    raw = load_json(FIGHTERS_JSON, {"fighters": []})
    fighters_raw = raw.get("fighters", [])
    fighters_by_slug = {}

    if isinstance(fighters_raw, dict):
        iterable = fighters_raw.values()
    elif isinstance(fighters_raw, list):
        iterable = fighters_raw
    else:
        iterable = []

    for fighter in iterable:
        if isinstance(fighter, dict) and fighter.get("name"):
            fighters_by_slug[slugify(fighter["name"])] = fighter

    return fighters_by_slug


def get_fight_id(fight):
    value = fight.get("id")
    return str(value).strip() if value is not None else ""


def get_corner_name(corner):
    if isinstance(corner, dict):
        return corner.get("name") or ""
    if isinstance(corner, str):
        return corner
    return ""


def normalize_corner(corner):
    name = get_corner_name(corner)
    return {"name": name or "Fighter", "slug": slugify(name)}


def enrich_fighter(fighter, fighters_by_slug):
    slug = fighter.get("slug", "")
    details = fighters_by_slug.get(slug, {})

    if not isinstance(details, dict):
        details = {}

    merged = {**details, **fighter}
    merged["stats"] = details.get("stats") or fighter.get("stats") or {}
    merged["methods"] = details.get("methods") or fighter.get("methods") or {}
    merged["recent_fights"] = details.get("recent_fights") or fighter.get("recent_fights") or []

    for key in ["record", "stance", "height", "reach", "weight", "dob", "ufcstats_url"]:
        if not merged.get(key) or merged.get(key) == "—":
            merged[key] = details.get(key) or fighter.get(key)

    merged["slug"] = slug
    merged["name"] = fighter.get("name") or details.get("name")
    return merged


def stat_value(stats, key):
    if not isinstance(stats, dict):
        return "—"
    return html_escape(stats.get(key))


def get_recent_form(recent_fights):
    if not isinstance(recent_fights, list) or not recent_fights:
        return "—"

    form = []
    for fight in recent_fights[:10]:
        result = str(fight.get("result") or "").upper()
        if result == "WIN":
            form.append("W")
        elif result == "LOSS":
            form.append("L")
        elif result:
            form.append(result[0])
        else:
            form.append("—")

    return " ".join(form) if form else "—"


def get_finish_rate(methods):
    if not isinstance(methods, dict):
        return "—"

    ko_w = int(methods.get("ko_tko_w", 0) or 0)
    sub_w = int(methods.get("sub_w", 0) or 0)
    dec_w = int(methods.get("dec_w", 0) or 0)
    other_w = int(methods.get("other_w", 0) or 0)

    total_wins = ko_w + sub_w + dec_w + other_w
    finishes = ko_w + sub_w

    if total_wins <= 0:
        return "—"

    return f"{round((finishes / total_wins) * 100)}%"


def find_odds_event(red_name, blue_name, odds_events):
    red_slug = slugify(red_name)
    blue_slug = slugify(blue_name)
    target = {red_slug, blue_slug}

    for event in odds_events:
        home_slug = slugify(event.get("home_team"))
        away_slug = slugify(event.get("away_team"))

        if {home_slug, away_slug} == target:
            return event

    return None


def get_all_moneyline_odds(odds_event):
    if not odds_event:
        return {}

    by_fighter = {}

    for bookmaker in odds_event.get("bookmakers", []):
        book_title = bookmaker.get("title") or bookmaker.get("key")

        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue

            for outcome in market.get("outcomes", []):
                name = outcome.get("name")
                price = outcome.get("price")

                if not name or not price:
                    continue

                try:
                    price_f = float(price)
                except (ValueError, TypeError):
                    continue

                if price_f <= MIN_VALID_PRICE:
                    continue

                by_fighter.setdefault(name, []).append({
                    "bookmaker": book_title,
                    "price": price_f,
                })

    for name in by_fighter:
        by_fighter[name].sort(key=lambda r: r["price"], reverse=True)

    return by_fighter


def check_arbitrage(fighter_a_name, fighter_b_name, odds_by_fighter):
    a_odds = odds_by_fighter.get(fighter_a_name, [])
    b_odds = odds_by_fighter.get(fighter_b_name, [])

    if not a_odds or not b_odds:
        return False, None, None, 0

    best_a = a_odds[0]
    best_b = b_odds[0]

    implied_sum = (1 / best_a["price"]) + (1 / best_b["price"])

    if implied_sum < 1.0:
        arb_percent = (1 - implied_sum) * 100
        return True, best_a, best_b, arb_percent

    return False, best_a, best_b, 0


def render_moneyline_comparison(red_name, blue_name, odds_event):
    if not odds_event:
        return """
      <section class="moneyline-section">
        <div class="section-label-row">
          <div class="corner-label">Fight Winner</div>
        </div>
        <h2>Moneyline Odds</h2>
        <p class="muted">No UK odds found for this fight yet. Check back closer to fight night.</p>
      </section>
        """

    odds_by_fighter = get_all_moneyline_odds(odds_event)

    red_odds = odds_by_fighter.get(red_name, [])
    blue_odds = odds_by_fighter.get(blue_name, [])

    if not red_odds and not blue_odds:
        return """
      <section class="moneyline-section">
        <div class="section-label-row">
          <div class="corner-label">Fight Winner</div>
        </div>
        <h2>Moneyline Odds</h2>
        <p class="muted">Odds data found but no valid prices after filtering.</p>
      </section>
        """

    all_books = {}

    for row in red_odds:
        all_books[row["bookmaker"]] = {"red": row["price"], "blue": None}

    for row in blue_odds:
        book = row["bookmaker"]

        if book in all_books:
            all_books[book]["blue"] = row["price"]
        else:
            all_books[book] = {"red": None, "blue": row["price"]}

    best_red = max((r["price"] for r in red_odds), default=0)
    best_blue = max((r["price"] for r in blue_odds), default=0)

    is_arb, arb_a, arb_b, arb_pct = check_arbitrage(red_name, blue_name, odds_by_fighter)

    sorted_books = sorted(
        all_books.items(),
        key=lambda kv: (kv[1]["red"] or 0),
        reverse=True
    )

    rows_html = f"""
        <div class="ml-row ml-header">
          <div class="ml-book">Bookmaker</div>
          <div class="ml-price">{html_escape(red_name)}</div>
          <div class="ml-price">{html_escape(blue_name)}</div>
        </div>
    """

    for book_name, prices in sorted_books:
        red_p = prices["red"]
        blue_p = prices["blue"]

        red_class = " ml-best" if red_p and red_p == best_red else ""
        blue_class = " ml-best" if blue_p and blue_p == best_blue else ""

        red_str = f"{red_p:.2f}" if red_p else "—"
        blue_str = f"{blue_p:.2f}" if blue_p else "—"

        red_star = " ⭐" if red_p and red_p == best_red else ""
        blue_star = " ⭐" if blue_p and blue_p == best_blue else ""

        rows_html += f"""
        <div class="ml-row">
          <div class="ml-book">{html_escape(book_name)}</div>
          <div class="ml-price{red_class}">{red_str}{red_star}</div>
          <div class="ml-price{blue_class}">{blue_str}{blue_star}</div>
        </div>
        """

    if best_red > 0 and best_blue > 0:
        implied_red = round((1 / best_red) * 100, 1)
        implied_blue = round((1 / best_blue) * 100, 1)
        total_implied = round(implied_red + implied_blue, 1)
        overround = round(total_implied - 100, 1)

        implied_row = f"""
        <div class="ml-row ml-implied">
          <div class="ml-book">Implied Prob (best prices)</div>
          <div class="ml-price">{implied_red}%</div>
          <div class="ml-price">{implied_blue}%</div>
        </div>
        <div class="ml-row ml-overround">
          <div class="ml-book">Total implied / Book overround</div>
          <div class="ml-price" style="grid-column: span 2;">{total_implied}% &nbsp;|&nbsp; +{overround}%</div>
        </div>
        """
    else:
        implied_row = ""

    if is_arb:
        arb_html = f"""
        <div class="arb-banner">
          🎯 <strong>Arbitrage detected!</strong>
          Back {html_escape(red_name)} @ {arb_a["price"]:.2f} ({html_escape(arb_a["bookmaker"])})
          + {html_escape(blue_name)} @ {arb_b["price"]:.2f} ({html_escape(arb_b["bookmaker"])})
          = <strong>+{arb_pct:.2f}% guaranteed profit</strong>
        </div>
        """
    else:
        overround_val = round(((1 / best_red) + (1 / best_blue) - 1) * 100, 2) if best_red and best_blue else 0
        arb_html = f"""
        <div class="no-arb-note">
          No arbitrage at current best prices. Book margin: {overround_val:.2f}%
        </div>
        """

    summary_html = ""

    if best_red > 0 or best_blue > 0:
        red_book = red_odds[0]["bookmaker"] if red_odds else "—"
        blue_book = blue_odds[0]["bookmaker"] if blue_odds else "—"

        summary_html = f"""
        <div class="ml-best-strip">
          <div class="ml-best-card">
            <span>Best price — {html_escape(red_name)}</span>
            <strong>{best_red:.2f}</strong>
            <small>{html_escape(red_book)}</small>
          </div>
          <div class="ml-best-card">
            <span>Best price — {html_escape(blue_name)}</span>
            <strong>{best_blue:.2f}</strong>
            <small>{html_escape(blue_book)}</small>
          </div>
        </div>
        """

    return f"""
      <section class="moneyline-section">
        <div class="section-label-row">
          <div class="corner-label">Fight Winner</div>
        </div>
        <h2>Moneyline Odds</h2>
        <p class="muted">All UK bookmaker prices for the fight winner market. ⭐ marks the best available price per fighter.</p>

        {arb_html}
        {summary_html}

        <div class="ml-table">
          {rows_html}
          {implied_row}
        </div>
      </section>
    """


def render_best_odds_tab(red_name, blue_name, odds_event, props):
    moneyline_html = render_moneyline_comparison(red_name, blue_name, odds_event)
    props_html = render_best_prop_odds(props, red_name, blue_name)

    return f"""
      {moneyline_html}
      <div style="margin-top: 28px;">
        {props_html}
      </div>
    """


def render_odds(fighter_name, odds_event):
    odds_by_fighter = get_all_moneyline_odds(odds_event)
    odds_rows = odds_by_fighter.get(fighter_name, [])

    if not odds_rows:
        return """
      <div class="section-block">
        <h3>UK Moneyline Odds</h3>
        <p class="muted">No UK odds found yet.</p>
      </div>
        """

    best = odds_rows[0]
    rows_html = []

    for row in odds_rows:
        marker = " ⭐ Best" if row["price"] == best["price"] and row["bookmaker"] == best["bookmaker"] else ""
        rows_html.append(
            f"""
        <tr>
          <td>{html_escape(row.get("bookmaker"))}{marker}</td>
          <td>{row["price"]:.2f}</td>
        </tr>
            """.rstrip()
        )

    return f"""
      <div class="section-block">
        <h3>UK Moneyline Odds</h3>
        <table>
          <tr><td><strong>Best Price</strong></td><td><strong>{best["price"]:.2f}</strong></td></tr>
          {"".join(rows_html)}
        </table>
      </div>
    """


def render_methods(methods):
    if not isinstance(methods, dict):
        methods = {}

    return f"""
      <div class="section-block">
        <h3>Method Breakdown</h3>
        <table>
          <tr><td>KO/TKO</td><td>{methods.get("ko_tko_w", 0)} W • {methods.get("ko_tko_l", 0)} L</td></tr>
          <tr><td>Submission</td><td>{methods.get("sub_w", 0)} W • {methods.get("sub_l", 0)} L</td></tr>
          <tr><td>Decision</td><td>{methods.get("dec_w", 0)} W • {methods.get("dec_l", 0)} L</td></tr>
          <tr><td>Other</td><td>{methods.get("other_w", 0)} W • {methods.get("other_l", 0)} L</td></tr>
        </table>
      </div>
    """


def render_recent_fights(recent_fights):
    if not isinstance(recent_fights, list) or not recent_fights:
        return """
      <div class="section-block">
        <h3>Recent Fights</h3>
        <p class="muted">Recent fight history not available yet.</p>
      </div>
        """

    rows = []

    for fight in recent_fights[:10]:
        rows.append(
            f"""
        <div class="recent-fight">
          <strong>{html_escape(fight.get("result"))}</strong> vs {html_escape(fight.get("opponent"))}
          <div class="muted">{html_escape(fight.get("method"))} • R{html_escape(fight.get("round"))} • {html_escape(fight.get("time"))} • {html_escape(fight.get("event"))}</div>
        </div>
            """.rstrip()
        )

    return f"""
      <div class="section-block">
        <h3>Recent Fights</h3>
        <div class="recent-list">
          {"".join(rows)}
        </div>
      </div>
    """


def market_rows_from_structured(items):
    rows = []

    for item in items or []:
        if isinstance(item, dict):
            selection = item.get("selection")
            odds = item.get("odds")
            if selection and odds:
                rows.append((selection, odds))
        elif isinstance(item, str):
            rows.append((item, ""))

    return rows


def collect_prop_rows(prop_items):
    rows = []

    for item in prop_items or []:
        bookmaker = item.get("bookmaker") or "Bookmaker"
        markets = item.get("markets") or {}

        def add_rows(label, items):
            for selection, odds in market_rows_from_structured(items):
                clean = clean_selection(selection)
                decimal = fractional_to_decimal(odds)

                if not clean or not odds or decimal <= 0:
                    continue

                rows.append(
                    {
                        "bookmaker": bookmaker,
                        "market": canonical_market_label(label),
                        "market_key": market_key(label),
                        "selection": clean,
                        "selection_key": selection_key(clean),
                        "odds": odds,
                        "decimal": decimal,
                    }
                )

        if isinstance(markets, dict):
            # Fight Betting renders in Bookmaker Props, but stays out of Best Prop Odds
            # because OddsAPI remains the main clean moneyline source.
            add_rows("Method of Victory", markets.get("method_of_victory"))
            add_rows("Rounds", markets.get("rounds") or markets.get("total_rounds"))
            add_rows("Go The Distance?", markets.get("go_the_distance"))

        add_rows("Method of Victory", item.get("method_props"))
        add_rows("Rounds", item.get("round_props"))
        add_rows("Go The Distance?", item.get("distance_props"))

    return rows


def get_best_prop_rows_with_value(prop_items):
    rows = collect_prop_rows(prop_items)
    grouped = {}

    for row in rows:
        key = (row["market_key"], row["selection_key"])
        grouped.setdefault(key, []).append(row)

    best_rows = []

    for key, items in grouped.items():
        if not items:
            continue

        best = max(items, key=lambda r: r["decimal"])
        decimals = [r["decimal"] for r in items if r["decimal"] > 0]
        avg_decimal = sum(decimals) / len(decimals) if decimals else 0

        value_percent = 0
        is_outlier = False

        if avg_decimal > 0 and len(decimals) >= 2:
            value_percent = ((best["decimal"] / avg_decimal) - 1) * 100
            is_outlier = value_percent >= OUTLIER_THRESHOLD_PERCENT

        best = dict(best)
        best["book_count"] = len(set(r["bookmaker"] for r in items))
        best["market_average"] = avg_decimal
        best["value_percent"] = value_percent
        best["is_outlier"] = is_outlier
        best["comparison_count"] = len(decimals)

        best_rows.append(best)

    return best_rows


def render_value_badge(row):
    if not row.get("is_outlier"):
        if row.get("comparison_count", 0) >= 2:
            return f"""
              <div class="value-note">
                Market avg: {row.get("market_average", 0):.2f}
              </div>
            """
        return ""

    return f"""
      <div class="outlier-badge">
        🔥 Outlier +{row.get("value_percent", 0):.0f}% vs market avg
      </div>
      <div class="value-note">
        Avg price: {row.get("market_average", 0):.2f} • {row.get("comparison_count", 0)} prices compared
      </div>
    """


def render_best_prop_odds(prop_items, red_name="", blue_name=""):
    ordered = get_best_prop_rows_with_value(prop_items)

    if not ordered:
        return """
      <section class="best-props">
        <div class="best-props-head">
          <div>
            <div class="corner-label">Prop odds</div>
            <h2>Best Available Prop Odds</h2>
            <p class="muted">No comparable prop odds found yet.</p>
          </div>
        </div>
      </section>
        """

    fight_title = f"{red_name} vs {blue_name}".strip(" vs ")

    ordered = sorted(
        ordered,
        key=lambda r: (
            not r.get("is_outlier"),
            r["market"],
            r["selection"].lower(),
        ),
    )

    by_market = {}

    for row in ordered:
        by_market.setdefault(row["market"], []).append(row)

    market_html = ""

    for market, items in by_market.items():
        market_html += f"""
        <div class="best-market">
          <h3>{html_escape(market)}</h3>
          <div class="best-rows">
        """

        for row in items[:40]:
            outlier_class = " outlier-row" if row.get("is_outlier") else ""
            tracker_href = build_tracker_href(
                "UFC",
                fight_title,
                row["market"],
                row["selection"],
                row["bookmaker"],
                row["odds"],
            )

            market_html += f"""
            <div class="best-row{outlier_class}">
              <div>
                <strong>{html_escape(row["selection"])}</strong>
                <span>{html_escape(row["bookmaker"])} • {row.get("book_count", 1)} book(s)</span>
                {render_value_badge(row)}
              </div>

              <div class="best-right">
                <div class="best-price">⭐ {html_escape(row["odds"])}</div>

                <button
                  type="button"
                  class="ev-load-btn"
                  data-selection="{attr_escape(row["selection"])}"
                  data-bookmaker="{attr_escape(row["bookmaker"])}"
                  data-odds="{row["decimal"]:.2f}"
                >
                  Use in EV Tool →
                </button>

                <a
                  class="tracker-link-btn"
                  href="{html_escape(tracker_href)}"
                >
                  Add to Bet Tracker →
                </a>
              </div>
            </div>
            """

        market_html += """
          </div>
        </div>
        """

    return f"""
      <section class="best-props">
        <div class="best-props-head">
          <div>
            <div class="corner-label">Prop odds</div>
            <h2>Best Available Prop Odds</h2>
            <p class="muted">Highest available price per prop selection across matched bookmakers. 🔥 Outlier means the best price is at least {OUTLIER_THRESHOLD_PERCENT}% above the market average.</p>
          </div>
        </div>
        <div class="best-props-grid">
          {market_html}
        </div>
      </section>
    """


def render_market_summary_cards(props, odds_event, red_name, blue_name):
    rows = get_best_prop_rows_with_value(props)

    odds_by_fighter = get_all_moneyline_odds(odds_event)
    red_ml = odds_by_fighter.get(red_name, [])
    blue_ml = odds_by_fighter.get(blue_name, [])

    best_method = None
    best_outlier = None

    for row in rows:
        market = row["market"]

        if row.get("is_outlier"):
            if best_outlier is None or row.get("value_percent", 0) > best_outlier.get("value_percent", 0):
                best_outlier = row

        if market == "Method of Victory":
            if best_method is None or row["decimal"] > best_method["decimal"]:
                best_method = row

    def ml_card(name, ml_rows):
        if not ml_rows:
            return f"""
            <div class="summary-card">
              <span>{html_escape(name)}</span>
              <strong>—</strong>
              <small>No odds yet</small>
            </div>
            """

        best = ml_rows[0]

        return f"""
        <div class="summary-card">
          <span>Best price — {html_escape(name)}</span>
          <strong>{best["price"]:.2f}</strong>
          <small>{html_escape(best["bookmaker"])}</small>
        </div>
        """

    def card(title, row, value_mode=False):
        if not row:
            return f"""
            <div class="summary-card">
              <span>{html_escape(title)}</span>
              <strong>—</strong>
              <small>No market found</small>
            </div>
            """

        extra = ""

        if value_mode:
            extra = f"🔥 +{row.get('value_percent', 0):.0f}% vs avg"

        return f"""
        <div class="summary-card">
          <span>{html_escape(title)}</span>
          <strong>{html_escape(row["selection"])} @ {html_escape(row["odds"])}</strong>
          <small>{html_escape(row["bookmaker"])} {extra}</small>
        </div>
        """

    has_data = red_ml or blue_ml or best_method or best_outlier

    if not has_data:
        return ""

    return f"""
      <section class="summary-strip">
        {ml_card(red_name, red_ml)}
        {ml_card(blue_name, blue_ml)}
        {card("Best Method Price", best_method)}
        {card("Best Value Spot", best_outlier, True)}
      </section>
    """


def render_ev_calculator():
    return """
      <section class="ev-panel">
        <div>
          <div class="corner-label">Value tool</div>
          <h2>EV Calculator</h2>
          <p class="muted">
            Click "Use in EV Tool" from Best Odds to auto-load a selection, then enter your estimated fair probability.
          </p>
        </div>

        <div class="ev-picked">
          <div>
            <span>Selected Bet</span>
            <strong id="ev-selection">No selection loaded</strong>
          </div>
          <div>
            <span>Bookmaker</span>
            <strong id="ev-bookmaker">—</strong>
          </div>
        </div>

        <div class="ev-grid">
          <label>
            Fair Probability %
            <input id="ev-prob" type="number" min="1" max="99" step="0.1" value="50">
          </label>

          <label>
            Decimal Odds
            <input id="ev-odds" type="number" min="1.01" step="0.01" value="2.00">
          </label>

          <label>
            Bankroll £
            <input id="ev-bankroll" type="number" min="1" step="1" value="100">
          </label>

          <div class="ev-result">
            <span>Result</span>
            <strong id="ev-verdict">Break-even</strong>
          </div>

          <div class="ev-result">
            <span>Implied Probability</span>
            <strong id="ev-implied">50.00%</strong>
          </div>

          <div class="ev-result">
            <span>Edge</span>
            <strong id="ev-edge">0.00%</strong>
          </div>

          <div class="ev-result">
            <span>Expected Value</span>
            <strong id="ev-output">0.00%</strong>
          </div>

          <div class="ev-result">
            <span>Kelly Stake Guide</span>
            <strong id="ev-kelly">£0.00</strong>
          </div>
        </div>

        <p class="muted betting-note">
          EV = fair probability × decimal odds − 1. Kelly is a guide only, not betting advice.
        </p>
      </section>
    """


def render_market_block(label, items):
    rows = market_rows_from_structured(items)

    if not rows:
        return ""

    html = f"<div class='prop-market'><h4>{html_escape(label)}</h4>"

    for selection, odds in rows[:30]:
        html += f"""
        <div class="prop-row">
          <span>{html_escape(selection)}</span>
          <strong>{html_escape(odds)}</strong>
        </div>
        """

    html += "</div>"
    return html


def render_fight_props(prop_items):
    if not prop_items:
        return """
      <section class="fight-props">
        <h2>Bookmaker Props</h2>
        <p class="muted">No bookmaker props matched for this fight yet.</p>
      </section>
        """

    cards = ""

    for item in prop_items:
        bookmaker = item.get("bookmaker") or "Bookmaker"
        url = item.get("url") or "#"
        markets = item.get("markets") or {}
        market_html = ""

        if isinstance(markets, dict):
            market_html += render_market_block("Fight Betting", markets.get("fight_betting"))
            market_html += render_market_block("Method of Victory", markets.get("method_of_victory"))
            market_html += render_market_block("Rounds", markets.get("rounds") or markets.get("total_rounds"))
            market_html += render_market_block("Go The Distance?", markets.get("go_the_distance"))

        market_html += render_market_block("Method of Victory", item.get("method_props"))
        market_html += render_market_block("Rounds", item.get("round_props"))
        market_html += render_market_block("Go The Distance?", item.get("distance_props"))

        if not market_html:
            continue

        cards += f"""
        <article class="prop-card">
          <div class="prop-card-head">
            <div>
              <div class="corner-label">{html_escape(bookmaker)} props</div>
              <h3>{html_escape(item.get("fight_name"))}</h3>
            </div>
            <a class="small-link" href="{html_escape(url)}" target="_blank" rel="noopener">Open book →</a>
          </div>
          {market_html}
        </article>
        """

    if not cards:
        cards = "<p class='muted'>No displayable prop markets matched for this fight yet.</p>"

    return f"""
      <section class="fight-props">
        <h2>Bookmaker Props</h2>
        <div class="props-grid">
          {cards}
        </div>
      </section>
    """


def fighter_panel(fighter, odds_event, corner_label):
    name_raw = fighter.get("name")
    name = html_escape(name_raw)
    slug = fighter.get("slug", "")

    record = html_escape(fighter.get("record"))
    stance = html_escape(fighter.get("stance"))
    height = html_escape(fighter.get("height"))
    reach = html_escape(fighter.get("reach"))
    weight = html_escape(fighter.get("weight"))
    dob = html_escape(fighter.get("dob"))
    ufcstats_url = fighter.get("ufcstats_url")

    stats = fighter.get("stats") or {}
    methods = fighter.get("methods") or {}
    recent_fights = fighter.get("recent_fights") or []

    form = html_escape(get_recent_form(recent_fights))
    finish_rate = html_escape(get_finish_rate(methods))

    fighter_href = f"{BASE_PATH}/fighters/{slug}/" if slug else "#"

    ufcstats_link = ""
    if ufcstats_url:
        ufcstats_link = f'<a class="small-link" href="{html_escape(ufcstats_url)}">UFCStats profile →</a>'

    return f"""
    <section class="fighter-card">
      <div class="fighter-header">
        <div>
          <div class="corner-label">{corner_label}</div>
          <h2><a href="{fighter_href}">{name}</a></h2>
          {ufcstats_link}
        </div>
      </div>

      <div class="pillrow">
        <span class="pill">Record: {record}</span>
        <span class="pill">Weight: {weight}</span>
        <span class="pill">Stance: {stance}</span>
        <span class="pill">Height: {height}</span>
        <span class="pill">Reach: {reach}</span>
        <span class="pill">DOB: {dob}</span>
      </div>

      <div class="quick-summary">
        <div>
          <span class="muted">Recent Form</span>
          <strong>{form}</strong>
        </div>
        <div>
          <span class="muted">Finish Rate</span>
          <strong>{finish_rate}</strong>
        </div>
      </div>

      {render_odds(name_raw, odds_event)}

      <div class="stats-grid">
        <div class="section-block">
          <h3>Striking</h3>
          <table>
            <tr><td>SLpM</td><td>{stat_value(stats, "slpm")}</td></tr>
            <tr><td>Str. Acc.</td><td>{stat_value(stats, "str_acc")}</td></tr>
            <tr><td>SApM</td><td>{stat_value(stats, "sapm")}</td></tr>
            <tr><td>Str. Def.</td><td>{stat_value(stats, "str_def")}</td></tr>
          </table>
        </div>

        <div class="section-block">
          <h3>Grappling</h3>
          <table>
            <tr><td>TD Avg.</td><td>{stat_value(stats, "td_avg")}</td></tr>
            <tr><td>TD Acc.</td><td>{stat_value(stats, "td_acc")}</td></tr>
            <tr><td>TD Def.</td><td>{stat_value(stats, "td_def")}</td></tr>
            <tr><td>Sub. Avg.</td><td>{stat_value(stats, "sub_avg")}</td></tr>
          </table>
        </div>
      </div>

      {render_methods(methods)}
      {render_recent_fights(recent_fights)}
    </section>
    """


def get_matched_props(red_name, blue_name, props_by_key):
    title_a = f"{red_name} v {blue_name}"
    title_b = f"{blue_name} v {red_name}"

    key_a = fight_key(title_a)
    key_b = fight_key(title_b)

    props = props_by_key.get(key_a) or props_by_key.get(key_b) or []

    if props:
        return props, key_a, key_b, "exact"

    loose_matches = []

    for key, items in props_by_key.items():
        for item in items:
            prop_name = item.get("fight_name") or item.get("fight") or item.get("name") or key
            if keys_probably_match(title_a, prop_name):
                loose_matches.extend(items)
                break

    if loose_matches:
        return loose_matches, key_a, key_b, "loose"

    return [], key_a, key_b, "none"


def build_fight_page(event, fight, fight_id, fighters_by_slug, odds_events, props_by_key):
    event_slug = event.get("slug", "")
    event_name = html_escape(event.get("name", "Event"))

    red = enrich_fighter(normalize_corner(fight.get("red", {})), fighters_by_slug)
    blue = enrich_fighter(normalize_corner(fight.get("blue", {})), fighters_by_slug)

    red_name = red.get("name") or "Fighter A"
    blue_name = blue.get("name") or "Fighter B"

    odds_event = find_odds_event(red_name, blue_name, odds_events)

    title = f"{red_name} vs {blue_name}"

    props, lookup_a, lookup_b, match_type = get_matched_props(red_name, blue_name, props_by_key)

    if DEBUG_PROP_MATCHING:
        print("")
        print("DEBUG PROP MATCH")
        print(f"EVENT: {title}")
        print(f"KEY A: {lookup_a}")
        print(f"KEY B: {lookup_b}")
        print(f"MATCH TYPE: {match_type}")
        print(f"MATCHED PROP BOOKS: {len(props)}")
        if not props:
            print("NO MATCH. SAMPLE AVAILABLE PROP KEYS:")
            for k in list(props_by_key.keys())[:25]:
                print(f" - {k}")

    value_rows = get_best_prop_rows_with_value(props)
    outlier_count = len([r for r in value_rows if r.get("is_outlier")])

    odds_by_fighter = get_all_moneyline_odds(odds_event)
    ml_book_count = len(set(
        r["bookmaker"]
        for rows in odds_by_fighter.values()
        for r in rows
    ))

    weight = html_escape(fight.get("weight_class"))
    bout = html_escape(fight.get("bout"))
    status = html_escape(fight.get("status"))

    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    css_href = "../../assets/ufc.css"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html_escape(title)}</title>
  <link rel="stylesheet" href="{css_href}">
  <style>
    html,
    body {{
      width: 100%;
      max-width: none;
      margin: 0;
      padding: 0;
      overflow-x: hidden;
      background: #0F1621;
    }}

    body {{
      min-height: 100vh;
    }}

    .fight-page {{
      width: 100%;
      max-width: none;
      margin: 0;
      padding: 32px 40px 64px;
    }}

    .fight-shell {{
      width: 100%;
      max-width: none;
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 28px;
      background: rgba(255,255,255,0.02);
    }}

    .fight-hero {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 24px;
      flex-wrap: wrap;
      margin-bottom: 22px;
    }}

    .fight-hero h1 {{
      margin: 12px 0 10px;
      font-size: clamp(34px, 4vw, 64px);
      line-height: 1.02;
      letter-spacing: -0.04em;
      max-width: 1100px;
    }}

    .meta-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .meta-pill,
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      color: var(--muted);
      background: rgba(255,255,255,0.025);
      font-size: 13px;
    }}

    .matchup-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 22px;
      align-items: start;
      width: 100%;
    }}

    .fighter-card,
    .fight-meta,
    .fight-props,
    .best-props,
    .moneyline-section,
    .ev-panel {{
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 22px;
      background: rgba(255,255,255,0.025);
      min-width: 0;
    }}

    .fighter-header,
    .prop-card-head,
    .best-props-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }}

    .section-label-row {{
      margin-bottom: 10px;
    }}

    .corner-label {{
      display: inline-flex;
      border: 1px solid rgba(96,165,250,0.45);
      background: rgba(96,165,250,0.12);
      color: #93c5fd;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 12px;
    }}

    .fighter-card h2 {{
      margin: 0 0 8px;
      font-size: clamp(28px, 3vw, 44px);
      line-height: 1.05;
    }}

    .moneyline-section h2,
    .fight-props h2,
    .best-props h2,
    .ev-panel h2 {{
      margin-top: 0;
      font-size: 30px;
    }}

    .prop-card h3 {{
      margin: 0;
      font-size: 22px;
    }}

    .small-link {{
      display: inline-block;
      margin-top: 2px;
    }}

    .pillrow {{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:18px;
    }}

    .quick-summary {{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:12px;
      margin-top:18px;
    }}

    .quick-summary div,
    .section-block,
    .prop-card,
    .best-market {{
      border:1px solid var(--line);
      border-radius:14px;
      padding:14px;
      background:rgba(255,255,255,0.015);
    }}

    .quick-summary span {{
      display:block;
      font-size:12px;
      margin-bottom:6px;
    }}

    .quick-summary strong {{
      font-size:20px;
      letter-spacing: 0.03em;
    }}

    .section-block {{
      margin-top:14px;
    }}

    .section-block h3,
    .prop-market h4,
    .best-market h3 {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 15px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}

    .stats-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }}

    table {{
      width:100%;
      border-collapse:collapse;
      margin-top:4px;
    }}

    td, th {{
      padding:8px 6px;
      border-bottom:1px solid var(--line);
      text-align:left;
      vertical-align: top;
    }}

    td:last-child {{
      text-align:right;
      font-weight:700;
    }}

    .ml-table {{
      margin-top: 16px;
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
    }}

    .ml-row {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      border-bottom: 1px solid var(--line);
    }}

    .ml-row:last-child {{
      border-bottom: none;
    }}

    .ml-header {{
      background: rgba(255,255,255,0.04);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--muted);
    }}

    .ml-implied {{
      background: rgba(96,165,250,0.06);
      color: var(--muted);
      font-size: 13px;
    }}

    .ml-overround {{
      background: rgba(96,165,250,0.04);
      color: var(--muted);
      font-size: 13px;
    }}

    .ml-book,
    .ml-price {{
      padding: 10px 12px;
    }}

    .ml-price {{
      text-align: right;
      font-weight: 700;
      font-size: 15px;
    }}

    .ml-price.ml-best {{
      color: #22c55e;
    }}

    .ml-best-strip {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin: 16px 0;
    }}

    .ml-best-card {{
      border: 1px solid rgba(34,197,94,0.35);
      border-radius: 14px;
      padding: 14px;
      background: rgba(34,197,94,0.07);
    }}

    .ml-best-card span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}

    .ml-best-card strong {{
      display: block;
      font-size: 28px;
      color: #22c55e;
      font-weight: 900;
      margin-bottom: 4px;
    }}

    .ml-best-card small {{
      color: var(--muted);
      font-size: 13px;
    }}

    .arb-banner {{
      margin: 14px 0;
      padding: 14px 16px;
      border: 1px solid rgba(34,197,94,0.6);
      border-radius: 14px;
      background: rgba(34,197,94,0.1);
      color: #86efac;
      font-size: 14px;
      line-height: 1.6;
    }}

    .no-arb-note {{
      margin: 10px 0;
      color: var(--muted);
      font-size: 13px;
    }}

    .recent-list {{
      display:flex;
      flex-direction:column;
      gap:8px;
      margin-top:10px;
    }}

    .recent-fight {{
      border:1px solid var(--line);
      border-radius:10px;
      padding:10px;
      background:rgba(255,255,255,0.015);
    }}

    .fight-meta {{
      margin-top:22px;
    }}

    .props-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(330px, 1fr));
      gap: 14px;
    }}

    .best-props-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 14px;
      margin-top: 16px;
    }}

    .best-row {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      margin-top: 8px;
      background: rgba(15,22,33,0.85);
    }}

    .best-row.outlier-row {{
      border-color: rgba(249,115,22,0.65);
      background: rgba(249,115,22,0.08);
    }}

    .best-row span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }}

    .outlier-badge {{
      display: inline-flex;
      margin-top: 8px;
      border: 1px solid rgba(249,115,22,0.65);
      background: rgba(249,115,22,0.16);
      color: #fdba74;
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 12px;
      font-weight: 900;
    }}

    .value-note {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
    }}

    .best-right {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
    }}

    .best-price {{
      color: #22c55e;
      font-weight: 900;
      white-space: nowrap;
    }}

    .ev-load-btn {{
      border: 1px solid rgba(96,165,250,0.4);
      background: rgba(96,165,250,0.12);
      color: #93c5fd;
      border-radius: 10px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}

    .ev-load-btn:hover {{
      background: rgba(96,165,250,0.22);
    }}

    .tracker-link-btn {{
      border: 1px solid rgba(34,197,94,0.45);
      background: rgba(34,197,94,0.12);
      color: #86efac;
      border-radius: 10px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}

    .tracker-link-btn:hover {{
      background: rgba(34,197,94,0.22);
      text-decoration: none;
    }}

    .summary-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 14px;
      margin: 22px 0;
    }}

    .summary-card {{
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      background: rgba(255,255,255,0.025);
    }}

    .summary-card span,
    .summary-card small {{
      display: block;
      color: var(--muted);
      font-size: 13px;
    }}

    .summary-card strong {{
      display: block;
      margin: 8px 0 4px;
      font-size: 18px;
      color: #22c55e;
    }}

    .fight-tabs {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 22px 0;
    }}

    .tab-btn {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 10px 14px;
      background: rgba(255,255,255,0.025);
      color: var(--muted);
      font-weight: 800;
      cursor: pointer;
    }}

    .tab-btn.active {{
      background: rgba(96,165,250,0.18);
      border-color: rgba(96,165,250,0.65);
      color: #93c5fd;
    }}

    .tab-panel {{
      display: none;
    }}

    .tab-panel.active {{
      display: block;
    }}

    .ev-panel {{
      margin-top: 0;
    }}

    .ev-picked {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
      margin-top: 18px;
    }}

    .ev-picked div {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: rgba(15,22,33,0.75);
    }}

    .ev-picked span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
      font-weight: 800;
    }}

    .ev-picked strong {{
      color: #93c5fd;
      font-size: 18px;
    }}

    .ev-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-top: 18px;
    }}

    .ev-grid label,
    .ev-result {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: rgba(15,22,33,0.75);
      color: var(--muted);
      font-weight: 800;
    }}

    .ev-grid input {{
      width: 100%;
      margin-top: 8px;
      padding: 10px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #0F1621;
      color: white;
      font-size: 16px;
    }}

    .ev-result span {{
      display: block;
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 8px;
    }}

    .ev-result strong {{
      font-size: 28px;
      color: #22c55e;
    }}

    .ev-result.positive {{
      border-color: rgba(34,197,94,0.45);
      background: rgba(34,197,94,0.08);
    }}

    .ev-result.negative {{
      border-color: rgba(239,68,68,0.45);
      background: rgba(239,68,68,0.08);
    }}

    .prop-market {{
      border-top: 1px solid var(--line);
      margin-top: 14px;
      padding-top: 14px;
    }}

    .prop-row {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      margin-top: 8px;
      background: rgba(15,22,33,0.75);
    }}

    .prop-row strong {{
      color: #22c55e;
      white-space: nowrap;
    }}

    @media (max-width: 1100px) {{
      .matchup-grid {{
        grid-template-columns:1fr;
      }}

      .stats-grid {{
        grid-template-columns:1fr;
      }}

      .ml-best-strip {{
        grid-template-columns: 1fr;
      }}
    }}

    @media (max-width: 720px) {{
      .fight-page {{
        padding: 20px 14px 48px;
      }}

      .fight-shell {{
        padding: 18px;
      }}

      .quick-summary {{
        grid-template-columns:1fr;
      }}

      .prop-row,
      .best-row {{
        flex-direction: column;
      }}

      .best-right {{
        align-items: flex-start;
      }}

      .ml-row {{
        grid-template-columns: 1fr 1fr 1fr;
        font-size: 13px;
      }}

      .ml-book,
      .ml-price {{
        padding: 8px 8px;
      }}
    }}
  </style>
</head>
<body>
  <main class="fight-page">
    <div class="fight-shell">
      <div class="fight-hero">
        <div>
          <p class="muted">
            <a href="{BASE_PATH}/">UFC Hub</a> /
            <a href="{BASE_PATH}/events/{event_slug}/">{event_name}</a> /
            Fight
          </p>

          <h1>{html_escape(title)}</h1>

          <div class="meta-pills">
            <span class="meta-pill">{weight}</span>
            <span class="meta-pill">{bout}</span>
            <span class="meta-pill">Status: {status}</span>
            <span class="meta-pill">Odds: {'✅ ' + str(ml_book_count) + ' books' if ml_book_count else '⏳ None yet'}</span>
            <span class="meta-pill">Prop Books: {len(props)}</span>
            <span class="meta-pill">Value Spots: {outlier_count}</span>
          </div>
        </div>
      </div>

      {render_market_summary_cards(props, odds_event, red_name, blue_name)}

      <nav class="fight-tabs">
        <button class="tab-btn active" data-tab="overview">Overview</button>
        <button class="tab-btn" data-tab="best-odds">Best Odds</button>
        <button class="tab-btn" data-tab="props">Bookmaker Props</button>
        <button class="tab-btn" data-tab="stats">Stats &amp; Form</button>
        <button class="tab-btn" data-tab="value">EV Tool</button>
      </nav>

      <section class="tab-panel active" id="tab-overview">
        <div class="matchup-grid">
          {fighter_panel(red, odds_event, "Left Side")}
          {fighter_panel(blue, odds_event, "Right Side")}
        </div>
      </section>

      <section class="tab-panel" id="tab-best-odds">
        {render_best_odds_tab(red_name, blue_name, odds_event, props)}
      </section>

      <section class="tab-panel" id="tab-props">
        {render_fight_props(props)}
      </section>

      <section class="tab-panel" id="tab-stats">
        <div class="matchup-grid">
          {fighter_panel(red, odds_event, "Left Side")}
          {fighter_panel(blue, odds_event, "Right Side")}
        </div>
      </section>

      <section class="tab-panel" id="tab-value">
        {render_ev_calculator()}
      </section>

      <div class="fight-meta">
        <h2>Fight Meta</h2>
        <table>
          <tr><td>Bout</td><td>{bout}</td></tr>
          <tr><td>Weight Class</td><td>{weight}</td></tr>
          <tr><td>Status</td><td>{status}</td></tr>
          <tr><td>Odds Books</td><td>{ml_book_count}</td></tr>
          <tr><td>Prop Books Matched</td><td>{len(props)}</td></tr>
          <tr><td>Value Spots</td><td>{outlier_count}</td></tr>
        </table>
      </div>

      <hr style="margin:24px 0; border-color:#1f2a3a;">
      <p class="muted">Fight ID: {html_escape(fight_id)} • Generated: {generated}</p>
    </div>
  </main>

  <script>
    function activateTab(tabName) {{
      document.querySelectorAll(".tab-btn").forEach(b => {{
        b.classList.remove("active");
      }});

      document.querySelectorAll(".tab-panel").forEach(p => {{
        p.classList.remove("active");
      }});

      const btn = document.querySelector('.tab-btn[data-tab="' + tabName + '"]');
      const panel = document.getElementById("tab-" + tabName);

      if (btn) btn.classList.add("active");
      if (panel) panel.classList.add("active");
    }}

    document.querySelectorAll(".tab-btn").forEach(btn => {{
      btn.addEventListener("click", () => {{
        activateTab(btn.dataset.tab);
      }});
    }});

    function setBoxState(element, value) {{
      if (!element) return;

      element.classList.remove("positive");
      element.classList.remove("negative");

      if (value > 0) {{
        element.classList.add("positive");
      }} else if (value < 0) {{
        element.classList.add("negative");
      }}
    }}

    function money(value) {{
      return "£" + Number(value || 0).toFixed(2);
    }}

    function updateEV() {{
      const probPercent = Number(document.getElementById("ev-prob")?.value || 0);
      const prob = probPercent / 100;
      const odds = Number(document.getElementById("ev-odds")?.value || 0);
      const bankroll = Number(document.getElementById("ev-bankroll")?.value || 0);

      const verdict = document.getElementById("ev-verdict");
      const impliedOut = document.getElementById("ev-implied");
      const edgeOut = document.getElementById("ev-edge");
      const evOut = document.getElementById("ev-output");
      const kellyOut = document.getElementById("ev-kelly");

      if (!verdict || !impliedOut || !edgeOut || !evOut || !kellyOut) return;

      if (!prob || !odds || odds <= 1) {{
        verdict.textContent = "Enter valid numbers";
        impliedOut.textContent = "—";
        edgeOut.textContent = "—";
        evOut.textContent = "—";
        kellyOut.textContent = "—";
        return;
      }}

      const implied = 1 / odds;
      const edge = prob - implied;
      const ev = ((prob * odds) - 1);

      const b = odds - 1;
      const q = 1 - prob;
      let kellyFraction = 0;

      if (b > 0) {{
        kellyFraction = ((b * prob) - q) / b;
      }}

      if (kellyFraction < 0) {{
        kellyFraction = 0;
      }}

      const kellyStake = bankroll * kellyFraction;

      verdict.textContent = ev > 0 ? "Positive EV" : ev < 0 ? "Negative EV" : "Break-even";
      impliedOut.textContent = (implied * 100).toFixed(2) + "%";
      edgeOut.textContent = (edge * 100).toFixed(2) + "%";
      evOut.textContent = (ev * 100).toFixed(2) + "%";
      kellyOut.textContent = money(kellyStake);

      verdict.style.color = ev >= 0 ? "#22c55e" : "#ef4444";
      edgeOut.style.color = edge >= 0 ? "#22c55e" : "#ef4444";
      evOut.style.color = ev >= 0 ? "#22c55e" : "#ef4444";

      setBoxState(verdict.closest(".ev-result"), ev);
      setBoxState(edgeOut.closest(".ev-result"), edge);
      setBoxState(evOut.closest(".ev-result"), ev);
    }}

    document.querySelectorAll(".ev-load-btn").forEach(btn => {{
      btn.addEventListener("click", () => {{
        const selection = btn.dataset.selection || "Selected bet";
        const bookmaker = btn.dataset.bookmaker || "—";
        const odds = btn.dataset.odds || "2.00";

        activateTab("value");

        const selectionBox = document.getElementById("ev-selection");
        const bookmakerBox = document.getElementById("ev-bookmaker");
        const oddsInput = document.getElementById("ev-odds");

        if (selectionBox) selectionBox.textContent = selection;
        if (bookmakerBox) bookmakerBox.textContent = bookmaker;
        if (oddsInput) oddsInput.value = odds;

        updateEV();

        const valuePanel = document.getElementById("tab-value");
        if (valuePanel) {{
          valuePanel.scrollIntoView({{ behavior: "smooth", block: "start" }});
        }}
      }});
    }});



    function addBetTrackerLinks() {{
      const fightTitle = document.querySelector("h1")?.textContent?.trim() || "";

      document.querySelectorAll(".ev-load-btn").forEach(btn => {{
        if (btn.parentElement.querySelector(".tracker-link-btn")) return;

        const row = btn.closest(".best-row");
        const market = row?.closest(".best-market")?.querySelector("h3")?.textContent?.trim() || "";
        const selection = btn.dataset.selection || "";
        const bookmaker = btn.dataset.bookmaker || "";
        const oddsText = row?.querySelector(".best-price")?.textContent?.replace("⭐", "")?.trim() || btn.dataset.odds || "";

        const params = new URLSearchParams({{
          sport: "UFC",
          event: fightTitle,
          market: market,
          selection: selection,
          bookmaker: bookmaker,
          odds: oddsText
        }});

        const trackerBase = window.location.protocol === "file:"
          ? "../../tracker/index.html"
          : "/odds-board/ufc/tracker/";

        const link = document.createElement("a");
        link.className = "tracker-link-btn";
        link.href = trackerBase + "?" + params.toString();
        link.textContent = "Add to Bet Tracker →";
        link.style.border = "1px solid rgba(34,197,94,0.45)";
        link.style.background = "rgba(34,197,94,0.12)";
        link.style.color = "#86efac";
        link.style.borderRadius = "10px";
        link.style.padding = "6px 10px";
        link.style.fontSize = "12px";
        link.style.fontWeight = "700";
        link.style.textDecoration = "none";
        link.style.whiteSpace = "nowrap";
        link.style.display = "inline-flex";
        link.style.alignItems = "center";
        link.style.justifyContent = "center";

        btn.parentElement.appendChild(link);
      }});
    }}

    addBetTrackerLinks();

    document.addEventListener("input", updateEV);
    updateEV();
  </script>
</body>
</html>
"""


def main():
    events = load_events()
    fighters_by_slug = load_fighter_details()
    odds_events = load_odds()
    props_by_key = load_all_props()

    print(f"✅ Loaded {len(events)} events")
    print(f"✅ Loaded {len(odds_events)} OddsAPI moneyline events")
    print(f"✅ Loaded {len(props_by_key)} unique prop fight keys")

    if DEBUG_PROP_MATCHING:
        print("")
        print("PROP KEYS LOADED:")
        for key in list(props_by_key.keys())[:40]:
            print(f" - {key}")

    FIGHTS_DIR.mkdir(parents=True, exist_ok=True)

    keep = FIGHTS_DIR / ".keep"

    if not keep.exists():
        keep.write_text("", encoding="utf-8")

    fights_written = 0
    missing_ids = 0

    for event in events:
        if not event.get("slug"):
            continue

        for fight in event.get("fights", []) or []:
            fight_id = get_fight_id(fight)

            if not fight_id:
                missing_ids += 1
                continue

            out_dir = FIGHTS_DIR / fight_id
            out_dir.mkdir(parents=True, exist_ok=True)

            html = build_fight_page(
                event,
                fight,
                fight_id,
                fighters_by_slug,
                odds_events,
                props_by_key,
            )

            (out_dir / "index.html").write_text(html, encoding="utf-8")
            fights_written += 1

    print(f"✅ Wrote {fights_written} fight pages to {FIGHTS_DIR}")

    if missing_ids:
        print(f"⚠️ Skipped {missing_ids} fights with no id key")

    if fights_written == 0:
        raise SystemExit("❌ Generated 0 fight pages. Check events.json schema.")


if __name__ == "__main__":
    main()