"""Run from C:\\Users\\joete\\odds-board to fix conflict markers in events.json"""
import re, json, pathlib

p = pathlib.Path("ufc/data/events.json")
t = p.read_text(encoding="utf-8")

# Strip conflict markers - keep the "ours" side (before =======)
fixed = re.sub(r"<<<<<<< [^\n]*\n(.*?)=======\n.*?>>>>>>> [^\n]*\n", r"\1", t, flags=re.DOTALL)

# Verify it's valid JSON before writing
try:
    json.loads(fixed)
    p.write_text(fixed, encoding="utf-8")
    print("Fixed and saved events.json successfully")
except json.JSONDecodeError as e:
    print(f"Still invalid JSON after fix attempt: {e}")
    print("Will try keeping the OTHER side instead...")
    fixed2 = re.sub(r"<<<<<<< [^\n]*\n.*?=======\n(.*?)>>>>>>> [^\n]*\n", r"\1", t, flags=re.DOTALL)
    try:
        json.loads(fixed2)
        p.write_text(fixed2, encoding="utf-8")
        print("Fixed using other side - saved successfully")
    except json.JSONDecodeError as e2:
        print(f"Both sides failed: {e2}")
        print("Manual fix needed - open ufc/data/events.json and remove conflict markers by hand")
