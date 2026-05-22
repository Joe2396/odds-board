import glob
import re
from pathlib import Path

files = glob.glob("ufc/data/debug/tote_probe_full_*.json")
terms = ["Topuria", "Gaethje", "Pereira", "Gane", "market", "selection", "odds", "price"]

found = 0

for f in files:
    txt = Path(f).read_text(encoding="utf-8", errors="ignore")

    if any(t.lower() in txt.lower() for t in terms):
        print("\nFOUND IN:", f)

        m = re.search(r"Topuria.{0,2000}", txt, re.I | re.S)
        if m:
            print(m.group(0)[:2000])
        else:
            print(txt[:2000])

        found += 1

print("\nMATCH FILES:", found)