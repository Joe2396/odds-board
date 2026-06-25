import json, re, unicodedata
from pathlib import Path

ROOT = Path(r'C:\Users\joete\odds-board')

def clean_name(name):
    text = unicodedata.normalize('NFKD', str(name or ''))
    text = text.encode('ascii', 'ignore').decode('ascii').lower()
    text = text.replace("'", '').replace("'", '').replace('.', '').replace('-', ' ')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def canonical_person_key(name):
    return ' '.join(sorted([w for w in clean_name(name).split() if w]))

def fight_key(name):
    text = unicodedata.normalize('NFKD', str(name or '')).encode('ascii','ignore').decode('ascii').lower()
    for a, b in [(' versus ',' v '),(' vs. ',' v '),(' vs ',' v '),(' v. ',' v ')]:
        text = text.replace(a, b)
    text = re.sub(r'\s+', ' ', text).strip()
    if ' v ' in text:
        l, r = text.split(' v ', 1)
        return ' v '.join(sorted([canonical_person_key(l), canonical_person_key(r)]))
    return canonical_person_key(text)

TARGET_KEY = fight_key("Conor McGregor vs Max Holloway")
print(f"Target fight key: {TARGET_KEY!r}\n")

PROP_FILES = [
    ("PaddyPower",  ROOT / "ufc/data/props.json"),
    ("BoyleSports", ROOT / "ufc/data/boylesports_props_filtered.json"),
    ("BoyleSports", ROOT / "ufc/data/boylesports_moneylines.json"),
    ("BetVictor",   ROOT / "ufc/data/betvictor_props_filtered.json"),
    ("Coral",       ROOT / "ufc/data/coral_props.json"),
    ("Unibet",      ROOT / "ufc/data/unibet_props.json"),
    ("WilliamHill", ROOT / "ufc/data/williamhill_props.json"),
    ("888Sport",    ROOT / "ufc/data/888sport_props.json"),
    ("Bwin",        ROOT / "ufc/data/bwin_props.json"),
]

for bookmaker, path in PROP_FILES:
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding='utf-8'))
    for fight in data.get('fights', []):
        fname = fight.get('fight') or fight.get('fight_name') or fight.get('name') or ''
        fk = fight_key(fname)
        if fk != TARGET_KEY:
            continue
        markets = fight.get('markets') or {}
        mov = markets.get('method_of_victory') or []
        print(f"[{bookmaker}] {fname}")
        print(f"  MOV selections: {len(mov)}")
        for item in mov:
            sel = item.get('selection','')
            if 'holloway' in sel.lower():
                print(f"    HOLLOWAY: {sel!r} @ {item.get('odds')}")
        if not any('holloway' in (i.get('selection','').lower()) for i in mov):
            print(f"    (no Holloway MOV selections)")
        print()