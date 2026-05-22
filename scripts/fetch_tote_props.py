import json
import re
from pathlib import Path
from datetime import datetime, timezone

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ufc" / "data" / "tote_props.json"

URL = "https://tote-prod.abetting.co/java-graphql/graphql"

def clean(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()

def flip_name(name):
    name = clean(name)
    if "," in name:
        last, first = [clean(p) for p in name.split(",", 1)]
        return clean(f"{first} {last}")
    return name

def fix_fight_name(name):
    name = clean(name).replace(" vs. ", " vs ")
    if " vs " not in name:
        return name
    a, b = name.split(" vs ", 1)
    return f"{flip_name(a)} vs {flip_name(b)}"

payload = {
    "operationName": "betSync",
    "query": """
query betSync($channel:String,$segment:String,$region:String,$language:String,$sports:[String],$marketTypes:[String],$filters:[Filter],$slice:Interval,$sort:Sort,$nonTradingFilters:[NodeFilterType]){
  betSync(cmsSegment:$segment,region:$region,language:$language,channel:$channel){
    sports(sports:$sports,eSports:false,filters:$nonTradingFilters){
      code
      events(filters:$filters,slice:$slice,sort:$sort){
        data{
          id
          compId
          compName
          name
          numMarkets
          participants{name}
          keyMarkets(types:$marketTypes){
            type
            selections{
              name
              price{
                fractional
                decimal
              }
            }
          }
        }
      }
    }
  }
}
""",
    "variables": {
        "channel": "TOTE_MASTER",
        "segment": "tote-ie",
        "region": "ie",
        "language": "en",
        "sports": ["MMA"],
        "marketTypes": ["MMA:FT:ML"],
        "filters": [
            {"field": "outright", "value": "false"},
            {"field": "displayed", "value": "true"},
        ],
        "slice": {"from": 0, "to": 100, "ignoreUndisplayed": True},
        "sort": {"field": "eventTime", "descending": True},
        "nonTradingFilters": ["DISPLAYED"],
    },
}

print("RUNNING TOTE UFC API SCRAPER")

r = requests.post(URL, json=payload, timeout=30)
print("STATUS:", r.status_code)
r.raise_for_status()

data = r.json()
events = data["data"]["betSync"]["sports"][0]["events"]["data"]

fights = []

for ev in events:
    comp = ev.get("compName") or ""
    if "UFC" not in comp:
        continue

    fight_name = fix_fight_name(ev.get("name"))
    if " vs " not in fight_name:
        continue

    left, right = fight_name.split(" vs ", 1)

    fight_betting = []
    for market in ev.get("keyMarkets") or []:
        for sel in market.get("selections") or []:
            sel_name = flip_name(sel.get("name"))
            price = sel.get("price") or {}
            odds = price.get("fractional") or price.get("decimal")
            if sel_name and odds:
                fight_betting.append({"selection": sel_name, "odds": str(odds)})

    if len(fight_betting) < 2:
        continue

    fights.append({
        "bookmaker": "Tote",
        "fight": fight_name,
        "fight_name": fight_name,
        "event": comp,
        "url": f"https://tote.co.uk/sports/en/sports/mma/event/{ev.get('id')}",
        "markets": {
            "fight_betting": fight_betting
        },
        "tote_event_id": ev.get("id"),
        "num_markets": ev.get("numMarkets"),
    })

out = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "source": "tote",
    "bookmaker": "Tote",
    "count": len(fights),
    "fights": fights,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"✅ Saved {len(fights)} Tote fights")
print(OUT)