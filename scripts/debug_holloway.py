import json, re
from pathlib import Path

ROOT = Path(r'C:\Users\joete\odds-board')

# Find McGregor fight ID
events = json.loads((ROOT / 'ufc/data/events.json').read_text(encoding='utf-8'))
fight_id = None
for e in events.get('events', []):
    for f in e.get('fights', []):
        if 'mcgregor' in f.get('bout','').lower() or 'holloway' in f.get('bout','').lower():
            fight_id = f['id']
            print(f"Fight: {f['bout']} | ID: {fight_id}")

if not fight_id:
    print("Fight not found in events.json")
    exit()

# Check the generated fight HTML for Holloway mentions
fight_path = ROOT / 'ufc' / 'fights' / fight_id / 'index.html'
if fight_path.exists():
    html = fight_path.read_text(encoding='utf-8', errors='ignore')
    # Look for Holloway in the best odds section
    holloway_count = html.lower().count('holloway')
    print(f"'Holloway' appears {holloway_count} times in fight HTML")
    
    # Check if any MOV cards mention Holloway
    import re
    mov_section = re.findall(r'(?:KO|Submission|Decision)[^\n]*Holloway[^\n]*', html, re.I)
    print(f"MOV+Holloway matches: {mov_section[:5]}")
else:
    print(f"Fight HTML not found: {fight_path}")