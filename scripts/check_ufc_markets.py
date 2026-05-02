import os
import requests
import json

API_KEY = os.getenv(98fb91f398403151a3eece97dc514a0b)

SPORT = "mma_mixed_martial_arts"
REGIONS = "uk"
MARKETS = "h2h,totals"

url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"

params = {
    "apiKey": API_KEY,
    "regions": REGIONS,
    "markets": MARKETS,
    "oddsFormat": "decimal",
}

res = requests.get(url, params=params, timeout=30)

print("Status:", res.status_code)
print("Remaining:", res.headers.get("x-requests-remaining"))
print("Used:", res.headers.get("x-requests-used"))

data = res.json()

print(json.dumps(data[:2], indent=2))
