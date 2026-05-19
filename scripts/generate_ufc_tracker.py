#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "ufc" / "tracker"
OUT_FILE = OUT_DIR / "index.html"

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bet Tracker</title>

  <link rel="stylesheet" href="/odds-board/ufc/assets/ufc.css">

  <style>
    :root{
      --bg:#0b1220;
      --panel:#111827;
      --panel2:#0f172a;
      --line:#1f2937;
      --text:#f8fafc;
      --muted:#94a3b8;
      --blue:#60a5fa;
      --green:#22c55e;
      --red:#ef4444;
      --orange:#f97316;
    }

    *{
      box-sizing:border-box;
    }

    body{
      margin:0;
      background:var(--bg);
      color:var(--text);
      font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }

    a{
      color:var(--blue);
      text-decoration:none;
    }

    a:hover{
      text-decoration:underline;
    }

    .tracker-wrap{
      width:100%;
      max-width:1500px;
      margin:0 auto;
      padding:40px 28px 80px;
    }

    .tracker-hero{
      border:1px solid var(--line);
      border-radius:26px;
      padding:30px;
      background:rgba(255,255,255,0.025);
      margin-bottom:28px;
    }

    .tracker-hero h1{
      font-size:clamp(42px,5vw,72px);
      line-height:0.98;
      margin:18px 0 14px;
      font-weight:950;
      letter-spacing:-0.055em;
    }

    .tracker-hero p{
      color:var(--muted);
      font-size:18px;
      line-height:1.6;
      max-width:900px;
      margin:0;
    }

    .tracker-pill{
      display:inline-flex;
      align-items:center;
      border:1px solid rgba(96,165,250,0.45);
      background:rgba(96,165,250,0.12);
      color:#93c5fd;
      border-radius:999px;
      padding:7px 11px;
      font-size:12px;
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:0.08em;
    }

    .stats-grid{
      display:grid;
      grid-template-columns:repeat(5,minmax(0,1fr));
      gap:16px;
      margin-bottom:28px;
    }

    .stat-card{
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:20px;
      padding:20px;
      min-height:116px;
    }

    .stat-label{
      color:var(--muted);
      font-size:13px;
      font-weight:800;
      text-transform:uppercase;
      letter-spacing:0.08em;
      margin-bottom:12px;
    }

    .stat-value{
      font-size:32px;
      line-height:1;
      font-weight:950;
      letter-spacing:-0.04em;
    }

    .positive{
      color:var(--green);
    }

    .negative{
      color:var(--red);
    }

    .tracker-layout{
      display:grid;
      grid-template-columns:430px minmax(0,1fr);
      gap:22px;
      align-items:start;
    }

    .tracker-panel{
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:24px;
      padding:24px;
    }

    .tracker-panel h2{
      margin:0 0 8px;
      font-size:30px;
      letter-spacing:-0.03em;
    }

    .muted{
      color:var(--muted);
    }

    .form-grid{
      display:grid;
      gap:14px;
      margin-top:20px;
    }

    label{
      display:block;
      color:var(--muted);
      font-size:13px;
      font-weight:800;
      text-transform:uppercase;
      letter-spacing:0.07em;
    }

    input,
    select,
    textarea{
      width:100%;
      margin-top:8px;
      padding:12px 13px;
      border:1px solid var(--line);
      border-radius:13px;
      background:var(--panel2);
      color:var(--text);
      font-size:15px;
      outline:none;
    }

    textarea{
      min-height:82px;
      resize:vertical;
    }

    input:focus,
    select:focus,
    textarea:focus{
      border-color:rgba(96,165,250,0.75);
      box-shadow:0 0 0 3px rgba(96,165,250,0.12);
    }

    .two-col{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:12px;
    }

    .btn-row{
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      margin-top:18px;
    }

    button{
      cursor:pointer;
      font-weight:900;
      font-size:14px;
    }

    .primary-btn{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      padding:13px 18px;
      border-radius:999px;
      background:rgba(34,197,94,0.16);
      border:1px solid rgba(34,197,94,0.55);
      color:#86efac;
    }

    .secondary-btn{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      padding:13px 18px;
      border-radius:999px;
      background:rgba(96,165,250,0.12);
      border:1px solid rgba(96,165,250,0.45);
      color:#93c5fd;
    }

    .danger-btn{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      padding:9px 12px;
      border-radius:999px;
      background:rgba(239,68,68,0.12);
      border:1px solid rgba(239,68,68,0.45);
      color:#fca5a5;
    }

    .mini-btn{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      padding:8px 10px;
      border-radius:999px;
      background:rgba(96,165,250,0.10);
      border:1px solid rgba(96,165,250,0.35);
      color:#93c5fd;
      font-size:12px;
      white-space:nowrap;
    }

    .bets-head{
      display:flex;
      justify-content:space-between;
      align-items:flex-start;
      gap:14px;
      flex-wrap:wrap;
      margin-bottom:18px;
    }

    .bets-list{
      display:grid;
      gap:12px;
    }

    .bet-card{
      border:1px solid var(--line);
      border-radius:18px;
      padding:16px;
      background:rgba(15,23,42,0.72);
    }

    .bet-top{
      display:flex;
      justify-content:space-between;
      gap:14px;
      align-items:flex-start;
      margin-bottom:10px;
    }

    .bet-title{
      font-size:18px;
      font-weight:950;
      letter-spacing:-0.02em;
      margin:0 0 6px;
    }

    .bet-sub{
      color:var(--muted);
      font-size:13px;
      line-height:1.5;
    }

    .sport-pill{
      display:inline-flex;
      border-radius:999px;
      padding:5px 9px;
      margin-bottom:8px;
      font-size:11px;
      font-weight:950;
      text-transform:uppercase;
      letter-spacing:0.08em;
      border:1px solid rgba(96,165,250,0.45);
      color:#93c5fd;
      background:rgba(96,165,250,0.10);
    }

    .status-pill{
      display:inline-flex;
      border-radius:999px;
      padding:6px 10px;
      font-size:12px;
      font-weight:950;
      text-transform:uppercase;
      letter-spacing:0.08em;
      white-space:nowrap;
      border:1px solid var(--line);
      color:var(--muted);
      background:rgba(255,255,255,0.03);
    }

    .status-won{
      color:#86efac;
      border-color:rgba(34,197,94,0.45);
      background:rgba(34,197,94,0.10);
    }

    .status-lost{
      color:#fca5a5;
      border-color:rgba(239,68,68,0.45);
      background:rgba(239,68,68,0.10);
    }

    .status-void{
      color:#cbd5e1;
      border-color:rgba(148,163,184,0.45);
      background:rgba(148,163,184,0.10);
    }

    .bet-metrics{
      display:grid;
      grid-template-columns:repeat(4,minmax(0,1fr));
      gap:10px;
      margin:12px 0;
    }

    .metric{
      border:1px solid var(--line);
      border-radius:13px;
      padding:10px;
      background:rgba(255,255,255,0.02);
    }

    .metric span{
      display:block;
      color:var(--muted);
      font-size:12px;
      margin-bottom:5px;
      font-weight:800;
    }

    .metric strong{
      display:block;
      font-size:16px;
    }

    .bet-actions{
      display:flex;
      justify-content:space-between;
      gap:10px;
      align-items:center;
      flex-wrap:wrap;
      margin-top:12px;
    }

    .status-actions{
      display:flex;
      gap:8px;
      flex-wrap:wrap;
    }

    .empty-state{
      border:2px dashed #243041;
      border-radius:20px;
      padding:42px 22px;
      text-align:center;
      color:var(--muted);
      background:rgba(255,255,255,0.015);
    }

    .notice{
      margin-top:14px;
      border:1px solid rgba(96,165,250,0.35);
      background:rgba(96,165,250,0.08);
      color:#bfdbfe;
      border-radius:16px;
      padding:13px;
      font-size:14px;
      line-height:1.55;
    }

    .prefill-notice{
      display:none;
      margin-top:16px;
      border:1px solid rgba(34,197,94,0.45);
      background:rgba(34,197,94,0.08);
      color:#bbf7d0;
      border-radius:16px;
      padding:13px;
      font-size:14px;
      line-height:1.55;
    }

    .prefill-notice.show{
      display:block;
    }

    @media(max-width:1150px){
      .stats-grid{
        grid-template-columns:repeat(2,minmax(0,1fr));
      }

      .tracker-layout{
        grid-template-columns:1fr;
      }
    }

    @media(max-width:700px){
      .tracker-wrap{
        padding:22px 14px 52px;
      }

      .tracker-hero{
        padding:22px;
      }

      .stats-grid,
      .two-col,
      .bet-metrics{
        grid-template-columns:1fr;
      }

      .bet-top{
        flex-direction:column;
      }
    }
  </style>
</head>

<body>
  <main class="tracker-wrap">

    <section class="tracker-hero">
      <a href="/odds-board/ufc/">← Back to UFC Hub</a>
      <div style="margin-top:22px;">
        <span class="tracker-pill">Bet Tracker</span>
      </div>
      <h1>Bet Tracker</h1>
      <p>
        Track bets across UFC, football, NBA, golf, darts and future sports. Bets are saved in this browser for now,
        so users can track picks without needing an account.
      </p>

      <div id="prefill-notice" class="prefill-notice">
        Bet details loaded from the odds page. Enter your stake, then save it.
      </div>
    </section>

    <section class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Total Bets</div>
        <div class="stat-value" id="stat-total-bets">0</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">Total Staked</div>
        <div class="stat-value" id="stat-total-staked">£0.00</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">Profit / Loss</div>
        <div class="stat-value" id="stat-profit-loss">£0.00</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">ROI</div>
        <div class="stat-value" id="stat-roi">0.00%</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">Win Rate</div>
        <div class="stat-value" id="stat-win-rate">0.00%</div>
      </div>
    </section>

    <section class="tracker-layout">

      <aside class="tracker-panel">
        <h2>Add Bet</h2>
        <p class="muted">
          Add manually, or use an “Add to Bet Tracker” button from an odds page to pre-fill everything except stake.
        </p>

        <form id="bet-form" class="form-grid">

          <div class="two-col">
            <label>
              Sport
              <input id="sport" type="text" placeholder="UFC">
            </label>

            <label>
              Bookmaker
              <input id="bookmaker" type="text" placeholder="PaddyPower">
            </label>
          </div>

          <label>
            Event / Match
            <input id="event_name" type="text" placeholder="Ilia Topuria vs Justin Gaethje">
          </label>

          <label>
            Selection / Pick
            <input id="selection" type="text" placeholder="Ilia Topuria by KO/TKO">
          </label>

          <div class="two-col">
            <label>
              Market
              <input id="market" type="text" placeholder="Method of Victory">
            </label>

            <label>
              Odds
              <input id="odds" type="text" placeholder="7/5, EVS, 2.40">
            </label>
          </div>

          <div class="two-col">
            <label>
              Stake £
              <input id="stake" type="number" min="0" step="0.01" placeholder="10">
            </label>

            <label>
              Date
              <input id="bet_date" type="date">
            </label>
          </div>

          <label>
            Notes
            <textarea id="notes" placeholder="Optional notes about the bet"></textarea>
          </label>

          <div class="btn-row">
            <button class="primary-btn" type="submit">Add Bet</button>
            <button class="secondary-btn" type="button" id="clear-form">Clear Form</button>
          </div>

          <div class="notice">
            V1 uses browser storage. Bets stay on this device/browser until cleared.
          </div>

        </form>
      </aside>

      <section class="tracker-panel">
        <div class="bets-head">
          <div>
            <h2>My Bets</h2>
            <p class="muted">
              Mark bets as won, lost or void to update your P/L.
            </p>
          </div>

          <button class="danger-btn" type="button" id="clear-all">Clear All Bets</button>
        </div>

        <div id="bets-list" class="bets-list"></div>
      </section>

    </section>
  </main>

  <script>
    const STORAGE_KEY = "bet_tracker_v1";

    const form = document.getElementById("bet-form");
    const betsList = document.getElementById("bets-list");

    const fields = {
      sport: document.getElementById("sport"),
      bookmaker: document.getElementById("bookmaker"),
      event_name: document.getElementById("event_name"),
      selection: document.getElementById("selection"),
      market: document.getElementById("market"),
      odds: document.getElementById("odds"),
      stake: document.getElementById("stake"),
      bet_date: document.getElementById("bet_date"),
      notes: document.getElementById("notes")
    };

    function todayDate(){
      return new Date().toISOString().slice(0, 10);
    }

    function getParam(name){
      const params = new URLSearchParams(window.location.search);
      return params.get(name) || "";
    }

    function loadPrefillFromUrl(){
      const sport = getParam("sport");
      const eventName = getParam("event") || getParam("event_name") || getParam("fight") || getParam("match");
      const selection = getParam("selection") || getParam("pick");
      const market = getParam("market");
      const bookmaker = getParam("bookmaker");
      const odds = getParam("odds");
      const notes = getParam("notes");

      let hasPrefill = false;

      if(sport){
        fields.sport.value = sport;
        hasPrefill = true;
      }

      if(eventName){
        fields.event_name.value = eventName;
        hasPrefill = true;
      }

      if(selection){
        fields.selection.value = selection;
        hasPrefill = true;
      }

      if(market){
        fields.market.value = market;
        hasPrefill = true;
      }

      if(bookmaker){
        fields.bookmaker.value = bookmaker;
        hasPrefill = true;
      }

      if(odds){
        fields.odds.value = odds;
        hasPrefill = true;
      }

      if(notes){
        fields.notes.value = notes;
        hasPrefill = true;
      }

      if(!fields.sport.value){
        fields.sport.value = "UFC";
      }

      if(!fields.bet_date.value){
        fields.bet_date.value = todayDate();
      }

      if(hasPrefill){
        document.getElementById("prefill-notice").classList.add("show");
        setTimeout(() => {
          fields.stake.focus();
        }, 250);
      }
    }

    function loadBets(){
      try{
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : [];
      }catch(err){
        return [];
      }
    }

    function saveBets(bets){
      localStorage.setItem(STORAGE_KEY, JSON.stringify(bets));
    }

    function money(value){
      const num = Number(value || 0);
      const sign = num < 0 ? "-£" : "£";
      return sign + Math.abs(num).toFixed(2);
    }

    function parseOddsToDecimal(value){
      const raw = String(value || "").trim().toUpperCase();

      if(!raw){
        return 0;
      }

      if(raw === "EVS" || raw === "EVENS"){
        return 2.0;
      }

      if(raw.includes("/")){
        const parts = raw.split("/");
        if(parts.length === 2){
          const a = Number(parts[0]);
          const b = Number(parts[1]);
          if(b > 0){
            return (a / b) + 1;
          }
        }
      }

      const decimal = Number(raw);
      if(decimal > 1){
        return decimal;
      }

      return 0;
    }

    function profitForBet(bet){
      const stake = Number(bet.stake || 0);
      const decimal = parseOddsToDecimal(bet.odds);

      if(bet.status === "won"){
        return stake * (decimal - 1);
      }

      if(bet.status === "lost"){
        return -stake;
      }

      if(bet.status === "void"){
        return 0;
      }

      return 0;
    }

    function statusClass(status){
      if(status === "won") return "status-won";
      if(status === "lost") return "status-lost";
      if(status === "void") return "status-void";
      return "";
    }

    function setStatClass(element, value){
      element.classList.remove("positive", "negative");

      if(value > 0){
        element.classList.add("positive");
      }else if(value < 0){
        element.classList.add("negative");
      }
    }

    function updateStats(bets){
      const totalBets = bets.length;
      const settled = bets.filter(b => b.status === "won" || b.status === "lost" || b.status === "void");
      const winLossOnly = bets.filter(b => b.status === "won" || b.status === "lost");

      const totalStaked = bets.reduce((sum, b) => sum + Number(b.stake || 0), 0);
      const settledStake = settled.reduce((sum, b) => sum + Number(b.stake || 0), 0);
      const profitLoss = bets.reduce((sum, b) => sum + profitForBet(b), 0);

      const roi = settledStake > 0 ? (profitLoss / settledStake) * 100 : 0;
      const wins = winLossOnly.filter(b => b.status === "won").length;
      const winRate = winLossOnly.length > 0 ? (wins / winLossOnly.length) * 100 : 0;

      document.getElementById("stat-total-bets").textContent = totalBets;
      document.getElementById("stat-total-staked").textContent = money(totalStaked);

      const plEl = document.getElementById("stat-profit-loss");
      plEl.textContent = money(profitLoss);
      setStatClass(plEl, profitLoss);

      const roiEl = document.getElementById("stat-roi");
      roiEl.textContent = roi.toFixed(2) + "%";
      setStatClass(roiEl, roi);

      document.getElementById("stat-win-rate").textContent = winRate.toFixed(2) + "%";
    }

    function renderBets(){
      const bets = loadBets();

      updateStats(bets);

      if(!bets.length){
        betsList.innerHTML = `
          <div class="empty-state">
            <strong>No bets tracked yet.</strong>
            <br><br>
            Add your first bet using the form, or from an odds page.
          </div>
        `;
        return;
      }

      betsList.innerHTML = bets.map((bet, index) => {
        const decimal = parseOddsToDecimal(bet.odds);
        const profit = profitForBet(bet);
        const status = bet.status || "pending";

        return `
          <article class="bet-card">
            <div class="bet-top">
              <div>
                <span class="sport-pill">${escapeHtml(bet.sport || "Sport")}</span>
                <h3 class="bet-title">${escapeHtml(bet.selection || "Unnamed pick")}</h3>
                <div class="bet-sub">
                  ${escapeHtml(bet.event_name || "Unknown event")}<br>
                  ${escapeHtml(bet.market || "Market")} • ${escapeHtml(bet.bookmaker || "Bookmaker")}
                  ${bet.bet_date ? `<br>${escapeHtml(bet.bet_date)}` : ""}
                </div>
              </div>

              <span class="status-pill ${statusClass(status)}">${escapeHtml(status)}</span>
            </div>

            <div class="bet-metrics">
              <div class="metric">
                <span>Odds</span>
                <strong>${escapeHtml(bet.odds || "—")}</strong>
              </div>

              <div class="metric">
                <span>Decimal</span>
                <strong>${decimal ? decimal.toFixed(2) : "—"}</strong>
              </div>

              <div class="metric">
                <span>Stake</span>
                <strong>${money(bet.stake)}</strong>
              </div>

              <div class="metric">
                <span>P/L</span>
                <strong class="${profit > 0 ? "positive" : profit < 0 ? "negative" : ""}">${money(profit)}</strong>
              </div>
            </div>

            ${bet.notes ? `<p class="muted">${escapeHtml(bet.notes)}</p>` : ""}

            <div class="bet-actions">
              <div class="status-actions">
                <button class="mini-btn" onclick="setStatus(${index}, 'pending')">Pending</button>
                <button class="mini-btn" onclick="setStatus(${index}, 'won')">Won</button>
                <button class="mini-btn" onclick="setStatus(${index}, 'lost')">Lost</button>
                <button class="mini-btn" onclick="setStatus(${index}, 'void')">Void</button>
              </div>

              <button class="danger-btn" onclick="deleteBet(${index})">Delete</button>
            </div>
          </article>
        `;
      }).join("");
    }

    function escapeHtml(value){
      return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function clearForm(){
      Object.values(fields).forEach(field => {
        field.value = "";
      });

      fields.sport.value = "UFC";
      fields.bet_date.value = todayDate();
      document.getElementById("prefill-notice").classList.remove("show");
    }

    function addBet(event){
      event.preventDefault();

      const bet = {
        id: Date.now(),
        sport: fields.sport.value.trim() || "UFC",
        event_name: fields.event_name.value.trim(),
        selection: fields.selection.value.trim(),
        market: fields.market.value.trim(),
        bookmaker: fields.bookmaker.value.trim(),
        odds: fields.odds.value.trim(),
        stake: Number(fields.stake.value || 0),
        bet_date: fields.bet_date.value || todayDate(),
        notes: fields.notes.value.trim(),
        status: "pending",
        created_at: new Date().toISOString()
      };

      if(!bet.event_name){
        alert("Add an event / match first.");
        return;
      }

      if(!bet.selection){
        alert("Add a selection / pick first.");
        return;
      }

      if(!bet.odds){
        alert("Add odds first.");
        return;
      }

      if(!bet.stake || bet.stake <= 0){
        alert("Add a stake greater than 0.");
        return;
      }

      const bets = loadBets();
      bets.unshift(bet);
      saveBets(bets);

      clearForm();
      renderBets();
    }

    function setStatus(index, status){
      const bets = loadBets();
      if(!bets[index]) return;

      bets[index].status = status;
      saveBets(bets);
      renderBets();
    }

    function deleteBet(index){
      const bets = loadBets();
      if(!bets[index]) return;

      if(!confirm("Delete this bet?")){
        return;
      }

      bets.splice(index, 1);
      saveBets(bets);
      renderBets();
    }

    function clearAllBets(){
      if(!confirm("Clear all tracked bets?")){
        return;
      }

      localStorage.removeItem(STORAGE_KEY);
      renderBets();
    }

    form.addEventListener("submit", addBet);

    document.getElementById("clear-form").addEventListener("click", clearForm);
    document.getElementById("clear-all").addEventListener("click", clearAllBets);

    fields.bet_date.value = todayDate();
    fields.sport.value = "UFC";

    loadPrefillFromUrl();
    renderBets();
  </script>
</body>
</html>
"""

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(HTML, encoding="utf-8")
    print(f"Generated {OUT_FILE}")

if __name__ == "__main__":
    main()