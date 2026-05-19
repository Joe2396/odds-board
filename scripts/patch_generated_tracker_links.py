from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIGHTS_DIR = ROOT / "ufc" / "fights"

INJECT = r'''
<script>
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".ev-load-btn").forEach(function (btn) {
    if (btn.parentElement.querySelector(".tracker-link-btn")) return;

    const row = btn.closest(".best-row") || btn.closest(".best-card");
    const market = row?.closest(".best-market")?.querySelector("h3")?.textContent?.trim() || "";
    const fightTitle = document.querySelector("h1")?.textContent?.trim() || "";
    const selection = btn.dataset.selection || "";
    const bookmaker = btn.dataset.bookmaker || "";
    const oddsText = row?.querySelector(".best-price")?.textContent?.replace("⭐", "")?.trim() || btn.dataset.odds || "";

    const params = new URLSearchParams({
      sport: "UFC",
      event: fightTitle,
      market: market,
      selection: selection,
      bookmaker: bookmaker,
      odds: oddsText
    });

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
  });
});
</script>
'''

count = 0

for path in FIGHTS_DIR.glob("*/index.html"):
    html = path.read_text(encoding="utf-8")

    if "Add to Bet Tracker" in html:
        continue

    if "</body>" not in html:
        continue

    html = html.replace("</body>", INJECT + "\n</body>")
    path.write_text(html, encoding="utf-8")
    count += 1

print(f"✅ Patched {count} fight pages with Bet Tracker links")