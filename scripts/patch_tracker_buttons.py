from pathlib import Path

p = Path("scripts/generate_ufc_fights.py")
s = p.read_text(encoding="utf-8")

start = s.find("    function addBetTrackerLinks()")
end = s.find("    document.addEventListener(\"input\", updateEV);")

if start == -1 or end == -1:
    raise SystemExit("Could not find broken tracker JS block.")

fixed = r'''
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

'''

s = s[:start] + fixed + s[end:]

p.write_text(s, encoding="utf-8")
print("✅ Fixed tracker JS braces")