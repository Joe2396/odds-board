from pathlib import Path

PATH = Path("scripts/generate_ufc_fights.py")

text = PATH.read_text(encoding="utf-8")

old = '''def render_fight_props(prop_items):
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
    """'''

new = '''def render_fight_props(prop_items):
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

        market_html += render_market_block("Fight Betting", item.get("fight_betting"))
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
              <h3>{html_escape(item.get("fight_name") or item.get("fight") or item.get("name"))}</h3>
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
    """'''

if old not in text:
    raise SystemExit("Could not find old render_fight_props function. Stop and send screenshot.")

text = text.replace(old, new)

PATH.write_text(text, encoding="utf-8")

print("✅ Patched render_fight_props to show Fight Betting books like 888Sport")