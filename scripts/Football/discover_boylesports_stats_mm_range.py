#!/usr/bin/env python3
import re
from pathlib import Path
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests
    print("✓ curl_cffi loaded")
except ImportError:
    print("Run: pip install curl_cffi")
    raise SystemExit(1)


ROOT = Path(__file__).resolve().parents[2]
DEBUG_DIR = ROOT / "football" / "debug" / "boyles_mm_range"

MATCH_URL = "https://www.boylesports.com/sports/football/event/international-world-cup/qatar-v-switzerland"

MM_START = 1500
MM_END = 1700


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def market_title(html):
    soup = BeautifulSoup(html, "lxml")

    text = clean(soup.get_text(" ", strip=True))

    targets = [
        "Player Shots On Target Over",
        "Player Shots Over",
        "Team Shots On Target Over",
        "Team Shots Over",
        "Total Shots On Target Over",
        "Total Shots Over",
        "Player To Be Booked",
        "Player To Be Sent Off",
        "Total Corners Over / Under",
        "Team Total Corners Over / Under",
    ]

    for t in targets:
        if t.lower() in text.lower():
            return t

    m = re.search(
        r"(Player|Team|Total|Match)[A-Za-z0-9 /+.-]{0,80}(Shots|Corners|Booked|Sent Off)[A-Za-z0-9 /+.-]{0,80}",
        text,
        flags=re.I,
    )

    return clean(m.group(0)) if m else ""


def main():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session(impersonate="chrome124")

    headers = {
        "accept": "text/html",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "referer": MATCH_URL,
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
    }

    print(f"Testing mm {MM_START} to {MM_END}")
    print(f"Match: {MATCH_URL}")

    for mm in range(MM_START, MM_END + 1):
        url = f"{MATCH_URL}?partial=true&mm={mm}"

        try:
            r = session.get(url, headers=headers, timeout=20)
        except Exception:
            continue

        if r.status_code != 200 or len(r.text) < 5000:
            continue

        title = market_title(r.text)

        if title:
            print(f"mm={mm} | {title} | length={len(r.text)}")

            path = DEBUG_DIR / f"mm_{mm}.html"
            path.write_text(r.text, encoding="utf-8")


if __name__ == "__main__":
    main()