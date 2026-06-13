#!/usr/bin/env python3
import json
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

BASE_PROPS_PATH = ROOT / "football" / "data" / "boylesports_worldcup_props.json"
OUT_PATH = ROOT / "football" / "debug" / "boylesports_mm_discovery.json"
HTML_DIR = ROOT / "football" / "debug" / "boyles_mm_html"

MAX_MATCHES = 15

TARGET_WORDS = [
    "shots on target",
    "player shots on target",
    "player shots",
    "shots over",
    "shot on target",
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def extract_mm_candidates(html):
    soup = BeautifulSoup(html, "lxml")
    found = {}

    # 1) Find explicit mm= links
    for tag in soup.find_all(True):
        text = clean(tag.get_text(" ", strip=True))

        attrs = []
        for attr_name, attr_val in tag.attrs.items():
            if isinstance(attr_val, list):
                attr_val = " ".join(attr_val)
            attrs.append(str(attr_val))

        attr_blob = " ".join(attrs)

        for blob in [attr_blob, text]:
            for mm in re.findall(r"(?:mm=|mm:|mm&quot;:|mm['\"]?\s*[:=]\s*)['\"]?(\d+)", blob, flags=re.I):
                if mm not in found:
                    found[mm] = {
                        "mm": mm,
                        "labels": set(),
                        "interesting": False,
                    }

                if text and len(text) < 300:
                    found[mm]["labels"].add(text)

    # 2) Find nearby labels around all mm IDs in raw HTML
    for m in re.finditer(r"(?:mm=|mm:|mm&quot;:|mm['\"]?\s*[:=]\s*)['\"]?(\d+)", html, flags=re.I):
        mm = m.group(1)
        start = max(0, m.start() - 800)
        end = min(len(html), m.end() + 800)
        snippet_html = html[start:end]
        snippet_text = clean(BeautifulSoup(snippet_html, "lxml").get_text(" ", strip=True))

        if mm not in found:
            found[mm] = {
                "mm": mm,
                "labels": set(),
                "interesting": False,
            }

        if snippet_text:
            found[mm]["labels"].add(snippet_text[:500])

    # 3) Mark interesting
    results = []
    for mm, item in found.items():
        labels = sorted(item["labels"])
        blob = " ".join(labels).lower()

        interesting = any(word in blob for word in TARGET_WORDS)

        results.append({
            "mm": mm,
            "labels": labels[:5],
            "interesting": interesting,
        })

    return sorted(results, key=lambda x: (not x["interesting"], int(x["mm"])))


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    if not BASE_PROPS_PATH.exists():
        raise FileNotFoundError(f"Missing {BASE_PROPS_PATH}")

    base = json.loads(BASE_PROPS_PATH.read_text(encoding="utf-8"))
    matches = base.get("matches", [])[:MAX_MATCHES]

    session = requests.Session(impersonate="chrome124")

    all_results = []

    for idx, match in enumerate(matches, 1):
        name = match["match"]
        url = match["url"]

        print(f"\n[{idx}/{len(matches)}] {name}")
        print(f"  {url}")

        headers = {
            "accept": "text/html",
            "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
            "referer": "https://www.boylesports.com/sports/football/competition/international-world-cup",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        }

        try:
            resp = session.get(url, headers=headers, timeout=30)
        except Exception as e:
            print(f"  ⚠ Error: {e}")
            all_results.append({
                "match": name,
                "url": url,
                "status": "error",
                "error": str(e),
                "mm_candidates": [],
            })
            continue

        print(f"  Status: {resp.status_code}, length={len(resp.text)}")

        html_path = HTML_DIR / f"{slugify(name)}.html"
        html_path.write_text(resp.text, encoding="utf-8")

        if "Verify you are human" in resp.text or "security verification" in resp.text:
            print("  ⚠ Security verification returned")
            candidates = []
        else:
            candidates = extract_mm_candidates(resp.text)

        interesting = [c for c in candidates if c["interesting"]]

        if interesting:
            print("  🎯 Interesting mm IDs:")
            for c in interesting[:20]:
                preview = " | ".join(c["labels"])[:250]
                print(f"    mm={c['mm']}  {preview}")
        else:
            print("  - no obvious shots mm IDs found")

        all_results.append({
            "match": name,
            "url": url,
            "status": resp.status_code,
            "html_path": str(html_path),
            "mm_candidates": candidates,
        })

    OUT_PATH.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ Saved discovery → {OUT_PATH}")


if __name__ == "__main__":
    main()