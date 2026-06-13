#!/usr/bin/env python3
import re
import json
from pathlib import Path
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests
    print("✓ curl_cffi loaded")
except ImportError:
    print("Run: pip install curl_cffi")
    raise SystemExit(1)


ROOT = Path(__file__).resolve().parents[2]

OUT_PATH = ROOT / "football" / "debug" / "boylesports_partial_market_test.json"
HTML_PATH = ROOT / "football" / "debug" / "boylesports_partial_market_test.html"

URL = "https://www.boylesports.com/sports/football/event/international-world-cup/qatar-v-switzerland?partial=true&mm=1615"


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_player_market(html):
    soup = BeautifulSoup(html, "lxml")
    selections = []

    for player_el in soup.select(".player-name"):
        player = clean(player_el.get_text(" ", strip=True))
        if not player:
            continue

        row = player_el

        for _ in range(8):
            row = row.parent
            if row is None:
                break

            prices = row.select("[data-price]")

            if len(prices) >= 2:
                for price_el in prices:
                    threshold = clean(price_el.get("data-name", ""))
                    price = clean(price_el.get("data-price", ""))

                    if not threshold or not price:
                        continue

                    selections.append({
                        "player": player,
                        "threshold": threshold,
                        "price": price,
                        "name": f"{player} {threshold}",
                        "market_id": price_el.get("data-marketid", ""),
                        "selection_id": price_el.get("data-selectionid", ""),
                    })

                break

    final = []
    seen = set()

    for s in selections:
        sig = (s["player"], s["threshold"], s["price"])
        if sig in seen:
            continue
        seen.add(sig)
        final.append(s)

    return final


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session(impersonate="chrome124")

    headers = {
        "accept": "text/html",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "referer": "https://www.boylesports.com/sports/football/event/international-world-cup/qatar-v-switzerland",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    }

    print(f"Fetching: {URL}")

    resp = session.get(URL, headers=headers, timeout=30)

    print(f"Status: {resp.status_code}")
    print(f"Length: {len(resp.text)}")

    HTML_PATH.write_text(resp.text, encoding="utf-8")

    if "Verify you are human" in resp.text or "security verification" in resp.text:
        print("⚠ Boyle security verification returned")
        return

    selections = parse_player_market(resp.text)

    output = {
        "url": URL,
        "status": resp.status_code,
        "count": len(selections),
        "selections": selections,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Selections: {len(selections)}")
    print(f"Saved JSON → {OUT_PATH}")
    print(f"Saved HTML → {HTML_PATH}")

    for s in selections[:40]:
        print(f"{s['player']:<25} {s['threshold']:<10} {s['price']}")


if __name__ == "__main__":
    main()