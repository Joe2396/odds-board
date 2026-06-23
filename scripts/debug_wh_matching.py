import json, re, unicodedata
from pathlib import Path

ROOT = Path(r'C:\Users\joete\odds-board')

def normalize_person_name(name):
    text = unicodedata.normalize('NFKD', str(name or ''))
    text = text.encode('ascii', 'ignore').decode('ascii').lower()
    text = text.replace("'", '').replace("\u2019", '').replace('.', '').replace('-', ' ')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def canonical_person_key(name):
    return ' '.join(sorted([w for w in normalize_person_name(name).split() if w]))

def fight_key(name):
    text = unicodedata.normalize('NFKD', str(name or '')).encode('ascii','ignore').decode('ascii').lower()
    for a, b in [(' versus ',' v '),(' vs. ',' v '),(' vs ',' v '),(' v. ',' v ')]:
        text = text.replace(a, b)
    text = re.sub(r'\s+', ' ', text).strip()
    if ' v ' in text:
        l, r = text.split(' v ', 1)
        return ' v '.join(sorted([canonical_person_key(l), canonical_person_key(r)]))
    return canonical_person_key(text)

wh = json.loads((ROOT / 'ufc/data/williamhill_props.json').read_text(encoding='utf-8'))
ev = json.loads((ROOT / 'ufc/data/events.json').read_text(encoding='utf-8'))

wh_keys = {fight_key(f.get('fight_name', '')): f.get('fight_name') for f in wh.get('fights', [])}
ev_keys = {fight_key(f.get('bout', '')): f.get('bout') for e in ev.get('events', []) for f in e.get('fights', [])}

print('WH keys:')
for k, v in wh_keys.items():
    print(f'  {repr(k)} <- {v}')

print()
print('Match results:')
for k, v in wh_keys.items():
    if k in ev_keys:
        print(f'  MATCH:    {v}')
    else:
        print(f'  NO MATCH: {v}  (key={repr(k)})')