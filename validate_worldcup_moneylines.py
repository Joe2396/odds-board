import json
from pathlib import Path

REQUIRED = {
    "PaddyPower": ("football/data/paddypower_worldcup_moneylines.json", 60),
    "BoyleSports": ("football/data/boylesports_worldcup_moneylines.json", 60),
    "Unibet": ("football/data/unibet_worldcup_moneylines.json", 60),
    "LiveScoreBet": ("football/data/livescorebet_worldcup_moneylines.json", 60),
    "WilliamHill": ("football/data/williamhill_worldcup_moneylines.json", 60),
    "888Sport": ("football/data/888sport_worldcup_moneylines.json", 60),
}

bad = False

for name, (path, minimum) in REQUIRED.items():
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        count = int(data.get("match_count") or 0)
    except Exception as e:
        print(f"{name}: BROKEN - {e}")
        bad = True
        continue

    if count < minimum:
        print(f"{name}: FAIL {count} / {minimum}")
        bad = True
    else:
        print(f"{name}: OK {count}")

if bad:
    print("\nSTOPPING: World Cup moneyline data is not safe to build/push.")
    raise SystemExit(1)

print("\nAll World Cup moneyline data checks passed.")