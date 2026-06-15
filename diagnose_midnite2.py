import re
from fractions import Fraction

def is_frac(s):
    return bool(re.match(r"^\d+\/\d+$", s.strip()))

def frac(s):
    s = (s or "").strip().upper()
    if s in ("EVS","EVENS"): return 2.0
    try: return round(float(Fraction(s)) + 1.0, 4)
    except: return None

lines = [l.strip() for l in open('football/debug/midnite_players_debug_belgium-v-egypt.txt', encoding='utf-8').readlines()]
idx = lines.index('Player Shots on Target')
seg = lines[idx:idx+500]

# Walk the segment recording, in order, every token that is either
# a threshold header (1+/2+/3+/4+), a player name, or a frac.
names = []
# columns[label] = list of fracs that appeared under that header
columns = {}
current_col = None
header_re = re.compile(r'^\d+\+$')

# First pass: collect names (everything before the first frac/header that's a real name)
seen_first_frac = False
events = []  # ("name", val) / ("header", val) / ("frac", val)
for l in seg[1:]:
    if header_re.match(l):
        events.append(("header", l)); continue
    if is_frac(l):
        events.append(("frac", l)); continue
    if re.match(r'^[A-Z]{2,4}(\s+\d+)?$', l): continue
    if re.match(r'^\d+$', l): continue
    if l.lower() in {'all','belgium','egypt','show all','show less'}: continue
    if len(l) < 4: continue
    events.append(("name", l))

# Names are all the name-events that occur before the first header
names = [v for (t,v) in events if t=="name" and events.index((t,v)) < next((i for i,(tt,_) in enumerate(events) if tt=="header"), len(events))]
# simpler/robust: names before first header
first_header_i = next((i for i,(t,_) in enumerate(events) if t=="header"), len(events))
names = [v for (t,v) in events[:first_header_i] if t=="name"]

# Now read fracs grouped by header
for t,v in events[first_header_i:]:
    if t=="header":
        current_col = v
        columns.setdefault(current_col, [])
    elif t=="frac" and current_col is not None:
        columns[current_col].append(v)

print(f"names={len(names)}")
for col,vals in columns.items():
    print(f"  col {col}: {len(vals)} fracs, first5={vals[:5]}")

if 'Omar Marmoush' in names:
    pi = names.index('Omar Marmoush')
    print(f"\nMarmoush at name-index {pi}")
    for col,vals in columns.items():
        v = vals[pi] if pi < len(vals) else 'OOB'
        print(f"  {col}: {v} (dec={frac(v) if v!='OOB' else 'NA'})")