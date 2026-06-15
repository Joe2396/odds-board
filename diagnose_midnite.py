import re

def is_frac(s):
    return bool(re.match(r"^\d+\/\d+$", s.strip()))

def frac(s):
    from fractions import Fraction
    s = (s or "").strip().upper()
    if s in ("EVS", "EVENS"): return 2.0
    try: return round(float(Fraction(s)) + 1.0, 4)
    except: return None

lines = open('football/debug/midnite_players_debug_belgium-v-egypt.txt', encoding='utf-8').readlines()
lines = [l.strip() for l in lines]

# Find Player Shots on Target section
idx = lines.index('Player Shots on Target')
seg = lines[idx:idx+500]

# Collect names (before first frac) and fracs
names = []
fracs = []
for l in seg[1:]:
    if is_frac(l):
        fracs.append(l)
        continue
    if fracs:
        continue  # stop collecting names once odds start
    # Skip junk
    if re.match(r'^[A-Z]{2,4}(\s+\d+)?$', l): continue
    if re.match(r'^\d+$', l): continue
    if re.match(r'^\d+\+$', l): continue
    if l.lower() in {'all','belgium','egypt','show all','show less','1+','2+','3+','4+'}: continue
    if len(l) < 4: continue
    names.append(l)

print(f"Names ({len(names)}): {names[:5]}...{names[-3:]}")
print(f"Fracs ({len(fracs)}): first 5={fracs[:5]}, last 5={fracs[-5:]}")

# Where is Omar Marmoush?
if 'Omar Marmoush' in names:
    pi = names.index('Omar Marmoush')
    print(f"\nOmar Marmoush is at position {pi}")
    n_players = len(names)
    col_keys = ['1+','2+','3+','4+']
    n_cols = len(col_keys)
    # Try to find best n_cols
    for nc in range(n_cols, 0, -1):
        if len(fracs) % nc == 0:
            n_cols = nc
            col_keys = col_keys[:nc]
            break
    n_players_calc = len(fracs) // n_cols
    print(f"n_cols={n_cols}, len(fracs)={len(fracs)}, n_players_calc={n_players_calc}, actual names={len(names)}")
    print(f"\nWith n_players=len(names)={len(names)}:")
    for ci, ck in enumerate(col_keys):
        idx2 = ci * len(names) + pi
        val = fracs[idx2] if idx2 < len(fracs) else 'OOB'
        print(f"  {ck}: idx={idx2} -> {val} (decimal={frac(val) if val != 'OOB' else 'N/A'})")
    print(f"\nWith n_players=n_players_calc={n_players_calc}:")
    for ci, ck in enumerate(col_keys):
        idx2 = ci * n_players_calc + pi
        val = fracs[idx2] if idx2 < len(fracs) else 'OOB'
        print(f"  {ck}: idx={idx2} -> {val} (decimal={frac(val) if val != 'OOB' else 'N/A'})")
else:
    print("Omar Marmoush NOT IN NAMES")
    print("Names:", names)