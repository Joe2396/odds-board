import json, re, unicodedata
from pathlib import Path

ROOT = Path(r'C:\Users\joete\odds-board')

def clean_selection(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def selection_key(s):
    text = clean_selection(s).lower()
    text = re.sub(r"^[a-z\s\.]+ by ", "", text)
    text = re.sub(r"^[a-z\s\.]+ via ", "", text)
    text = re.sub(r"^[a-z\s\.]+\s+-\s+", "", text)
    text = re.sub(r"goes?\s+the\s+distance\s*[-\u2013]?\s*", "", text)
    text = re.sub(r"\([\d\s\.\-]+\)", "", text)
    text = re.sub(r"\s+rounds?\b", "", text)
    text = re.sub(r"[/,]", " ", text)
    text = re.sub(r"\bor\b", " ", text)
    text = re.sub(r"\band\b", " ", text)
    text = text.replace("knockout", "ko").replace("tko", "ko")
    text = text.replace("disqualification", "dq")
    text = text.replace("submission", "sub")
    text = text.replace("technical decision", "dec").replace("technical dec", "dec")
    text = text.replace("unanimous decision", "dec").replace("unanimous", "dec")
    text = text.replace("split decision", "dec").replace("split", "dec")
    text = text.replace("majority decision", "dec").replace("majority", "dec")
    text = text.replace("decision", "dec").replace("points", "dec")
    has_ko  = "ko" in text.split()
    has_sub = "sub" in text.split()
    has_dec = "dec" in text.split() or "dq" in text.split()
    if has_ko or has_sub or has_dec:
        if not any(x in text for x in ["over", "under", "round", "yes", "no", ".5", ".0"]):
            text = "ko" if has_ko else ("sub" if has_sub else "dec")
    text = re.sub(r"[^a-z0-9\s\.]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

# Load PaddyPower and BoyleSports
pp = json.loads((ROOT / 'ufc/data/props.json').read_text(encoding='utf-8'))
bs = json.loads((ROOT / 'ufc/data/boylesports_props_filtered.json').read_text(encoding='utf-8'))

# Find McGregor fight in each
def find_fight(data, name):
    for f in data.get('fights', []):
        fight = f.get('fight') or f.get('name') or ''
        if name.lower() in fight.lower():
            return f
    return None

pp_fight = find_fight(pp, 'mcgregor')
bs_fight = find_fight(bs, 'mcgregor')

print("=== PaddyPower MOV selections ===")
if pp_fight:
    for item in (pp_fight.get('markets') or {}).get('method_of_victory', []):
        sel = item.get('selection', '')
        print(f"  {sel!r:50} -> key: {selection_key(sel)!r}")
else:
    print("  Not found")

print("\n=== BoyleSports MOV selections ===")
if bs_fight:
    for item in (bs_fight.get('markets') or {}).get('method_of_victory', []):
        sel = item.get('selection', '')
        print(f"  {sel!r:50} -> key: {selection_key(sel)!r}")
else:
    print("  Not found")