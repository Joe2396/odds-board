from curl_cffi import requests
from pathlib import Path

s = requests.Session(impersonate="chrome124")
r = s.get("https://www.boylesports.com/sports/football/event/international-world-cup/usa-v-paraguay")
Path("football/debug/boylesports_usa_paraguay.html").write_text(r.text, encoding="utf-8")
print("done", r.status_code)