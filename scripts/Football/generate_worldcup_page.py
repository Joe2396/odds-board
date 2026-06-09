#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PADDY_PATH          = ROOT / "football" / "data" / "paddypower_worldcup_moneylines.json"
BOYLE_PATH          = ROOT / "football" / "data" / "boylesports_worldcup_moneylines.json"
BETVICTOR_PATH      = ROOT / "football" / "data" / "betvictor_worldcup_moneylines.json"
UNIBET_PATH         = ROOT / "football" / "data" / "unibet_worldcup_moneylines.json"
LIVESCOREBET_PATH   = ROOT / "football" / "data" / "livescorebet_worldcup_moneylines.json"
WILLIAMHILL_PATH    = ROOT / "football" / "data" / "williamhill_worldcup_moneylines.json"
EIGHTEIGHTEIGHT_PATH= ROOT / "football" / "data" / "888sport_worldcup_moneylines.json"
LADBROKES_PATH      = ROOT / "football" / "data" / "ladbrokes_worldcup_moneylines.json"
MIDNITE_PATH        = ROOT / "football" / "data" / "midnite_worldcup_moneylines.json"

PADDY_PROPS_PATH    = ROOT / "football" / "data" / "paddypower_worldcup_props.json"
BOYLE_PROPS_PATH    = ROOT / "football" / "data" / "boylesports_worldcup_props.json"
UNIBET_PROPS_PATH   = ROOT / "football" / "data" / "unibet_worldcup_props.json"
LIVESCORE_PROPS_PATH= ROOT / "football" / "data" / "livescorebet_worldcup_props.json"
EIGHTSPORT_PROPS_PATH= ROOT / "football" / "data" / "888sport_worldcup_props.json"
WILLIAMHILL_PROPS_PATH= ROOT / "football" / "data" / "williamhill_worldcup_props.json"
BETVICTOR_PROPS_PATH  = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
LADBROKES_PROPS_PATH  = ROOT / "football" / "data" / "ladbrokes_worldcup_props.json"
MIDNITE_PROPS_PATH    = ROOT / "football" / "data" / "midnite_worldcup_props.json"

OUT_DIR  = ROOT / "football" / "world-cup"
OUT_PATH = OUT_DIR / "index.html"
HUB_PATH = ROOT / "football" / "index.html"
BASE     = "/odds-board"

# ── Helpers ────────────────────────────────────────────────────────────────────

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def esc(s):
    return str(s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")

def slugify(s):
    s = str(s or "").lower().replace("&","and")
    return re.sub(r"[^a-z0-9]+","-",s).strip("-")

def load_json(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except: return {}

def fractional_to_decimal(value):
    value = str(value or "").strip().upper()
    if value in {"EVS","EVENS","EVEN"}: return 2.0
    if "/" in value:
        try:
            a,b = value.split("/",1)
            return (float(a)/float(b))+1
        except: return 0
    try:
        v = float(value)
        if v > 1: return v
    except: pass
    return 0

def display_team(s):
    s = str(s or "").strip()
    return {"Bosnia & Herzegovina":"Bosnia & Herzegovina","Bosnia and Herzegovina":"Bosnia & Herzegovina",
            "Czech Republic":"Czechia","Turkey":"Türkiye","Turkiye":"Türkiye","Curaçao":"Curacao"}.get(s,s)

def key_team(s):
    s = display_team(s).lower()
    for f,t in [("&","and"),("herzegovina",""),("türkiye","turkiye"),("turkey","turkiye"),("curaçao","curacao")]:
        s = s.replace(f,t)
    s = re.sub(r"[^a-z0-9]+"," ",s).strip()
    return {"bosnia and":"bosnia","czech republic":"czechia","ivory coast":"ivory coast",
            "curacao":"curacao","turkiye":"turkiye","dr congo":"dr congo","usa":"usa"}.get(s,s)

def fixture_key(home,away):   return f"{key_team(home)}__{key_team(away)}"
def loose_fixture_key(h,a):   return "__".join(sorted([key_team(h),key_team(a)]))

def normalize_text_key(value):
    value = clean(value).lower().replace("&","and").replace("/","_").replace("?","")
    return re.sub(r"[^a-z0-9]+","_",value).strip("_")

def normalize_prop_market_key(name):
    k = normalize_text_key(name)
    if k.startswith("total_goals_by_") or k.startswith("team_total_goals"): return k
    return {
        "match_odds":"match_betting","match_betting":"match_betting",
        "over_under_goals_markets":"total_goals","over_under_goals":"total_goals",
        "total_goals_over_under":"total_goals","total_goals":"total_goals",
        "total_goals_over_under_markets":"total_goals",
        "1st_half_over_under_goals":"first_half_goals","1st_half_goals_over_under":"first_half_goals",
        "first_half_goals":"first_half_goals",
        "both_teams_to_score_markets":"btts","both_teams_to_score":"btts","btts":"btts",
        "result_both_to_score":"btts_result","result_btts":"btts_result",
        "both_teams_to_score_and_match_result":"btts_result","result_and_both_teams_to_score":"btts_result",
        "correct_score":"correct_score","double_chance":"double_chance",
        "half_time_result":"half_time_result","half_time_full_time":"ht_ft","ht_ft":"ht_ft",
        "handicaps":"handicap","handicap":"handicap",
        "match_result_and_total_goals":"result_total_goals","result_total_goals":"result_total_goals",
        "1_goal_ahead":"one_goal_ahead","one_goal_ahead":"one_goal_ahead",
        "main_goalscorer_markets":"anytime_scorer","player_to_score":"anytime_scorer",
        "anytime_goalscorer":"anytime_scorer","anytime_scorer":"anytime_scorer",
        "first_goalscorer":"first_goalscorer","first_scorer":"first_goalscorer",
        "scorer_2_plus":"scorer_2_plus",
        "shots_on_target":"shots_on_target","player_s_shots_on_target":"shots_on_target",
        "shots":"shots","player_s_shots":"shots",
        "player_to_assist":"player_to_assist","to_give_an_assist":"player_to_assist",
        "player_to_get_a_card":"player_to_get_a_card","to_get_a_card":"player_to_get_a_card",
        "player_fouls_committed":"player_fouls_committed","fouls_committed":"player_fouls_committed",
        "player_fouls_won":"player_fouls_won","fouls_won":"player_fouls_won",
        "total_shots_on_target":"total_shots_on_target","total_shots":"total_shots",
        "total_match_cards":"total_match_cards","total_cards":"total_match_cards",
    }.get(k,k)

def pretty_market_name(name):
    k = normalize_prop_market_key(name)
    return {
        "match_betting":"Match Betting","total_goals":"Total Goals Over/Under",
        "first_half_goals":"1st Half Goals","btts":"Both Teams To Score",
        "btts_result":"Result & Both Teams To Score","correct_score":"Correct Score",
        "double_chance":"Double Chance","handicap":"Handicap",
        "half_time_result":"Half Time Result","ht_ft":"Half Time / Full Time",
        "result_total_goals":"Result & Total Goals","one_goal_ahead":"1 Goal Ahead",
        "anytime_scorer":"Anytime Goalscorer","first_goalscorer":"First Goalscorer",
        "scorer_2_plus":"To Score 2+","shots_on_target":"Shots On Target",
        "shots":"Shots","player_to_assist":"To Assist","player_to_get_a_card":"To Get A Card",
    }.get(k, clean(name).replace("_"," ").title())

PLAYER_MARKET_KEYS = {"anytime_scorer","first_goalscorer","scorer_2_plus",
                       "shots_on_target","shots","player_to_assist","player_to_get_a_card",
                       "player_fouls_committed","player_fouls_won"}
MATCH_MARKET_KEYS  = {"match_betting","total_goals","first_half_goals","btts","btts_result",
                       "correct_score","double_chance","handicap","half_time_result","ht_ft",
                       "result_total_goals","one_goal_ahead",
                       "total_shots_on_target","total_shots","total_match_cards"}
GROUPED_OU_KEYS    = {"total_goals","first_half_goals"}

def is_player_market(name):
    return normalize_prop_market_key(name) in PLAYER_MARKET_KEYS

def is_team_market(name, home="", away=""):
    k = normalize_prop_market_key(name)
    n = name.lower()
    if k.startswith("total_goals_by_") or k.startswith("team_total_goals"): return True
    if "team total" in n or "total goals by" in n: return True
    if home and f"by {home.lower()}" in n: return True
    if away and f"by {away.lower()}" in n: return True
    return False

def normalize_prop_selection_key(market_name, selection_name):
    mk = normalize_prop_market_key(market_name)
    s  = clean(selection_name).lower().replace("&","and")
    s  = re.sub(r"\s+"," ",s).strip()

    if mk == "correct_score":
        m = re.search(r"(\d+)\s*-\s*(\d+)",s)
        if m: return f"score_{m.group(1)}_{m.group(2)}"

    m = re.search(r"\b(over|under)\b\s*(\d+(?:\.\d+)?)",s)
    if m: return f"{m.group(1)}_{m.group(2)}"

    if mk in {"anytime_scorer","first_goalscorer","scorer_2_plus","player_to_score"}:
        if re.search(r"\banytime\b",s):
            p = re.sub(r"\banytime\s*goalscorer\b","",s).strip()
            return "anytime__"+re.sub(r"[^a-z0-9]+","_",p).strip("_")
        if re.search(r"\bfirst\s+goalscorer\b",s):
            p = re.sub(r"\bfirst\s+goalscorer\b","",s).strip()
            return "first__"+re.sub(r"[^a-z0-9]+","_",p).strip("_")
        if re.search(r"\bto score 2\b|\b2 or more\b",s):
            p = re.sub(r"\bto score 2.*$|\b2 or more.*$","",s).strip()
            return "score2__"+re.sub(r"[^a-z0-9]+","_",p).strip("_")
        return normalize_text_key(s)

    if mk in {"shots_on_target","shots","player_to_assist","player_to_get_a_card"}:
        m2 = re.search(r"\b(over|under)\b\s*(\d+(?:\.\d+)?)",s)
        player = re.sub(r"\b(over|under)\b.*$","",s).strip()
        player = re.sub(r"\b(shots on target|shots|to assist|to get a card)\b","",player).strip()
        pk = re.sub(r"[^a-z0-9]+","_",player).strip("_")
        if m2: return f"{m2.group(1)}_{m2.group(2)}__{pk}"
        return normalize_text_key(s)

    if mk == "btts":
        side = None
        if re.search(r"(?:^|\b|[- ])yes(?:$|\b)",s): side="yes"
        elif re.search(r"(?:^|\b|[- ])no(?:$|\b)",s):  side="no"
        if side:
            if "first half" in s:   return f"btts_first_half_{side}"
            if "both halves" in s:  return f"btts_both_halves_{side}"
            if "no draw" in s:      return f"btts_no_draw_{side}"
            if "two or more" in s:  return f"btts_two_or_more_{side}"
            return f"btts_{side}"
        return normalize_text_key(s)

    if mk == "double_chance":
        s_lower = s.lower()
        parts = [p.strip() for p in re.split(r"\bor\b", s_lower)]
        team_count = sum(1 for p in parts if "draw" not in p)
        draw_count = sum(1 for p in parts if "draw" in p)
        if team_count == 2:
            return "home_or_away"
        if team_count == 1 and draw_count == 1:
            if "1x" in s_lower or s_lower.startswith("home") or s_lower.endswith("draw") and parts[0] != "draw":
                if parts[0] != "draw": return "home_or_draw"
            if "x2" in s_lower or s_lower.startswith("draw") or (len(parts)>1 and parts[1] != "draw"):
                return "away_or_draw"
            return "home_or_draw"
        return normalize_text_key(s)

    return normalize_text_key(s)

def pretty_selection_label_dc(selection_name):
    return {
        "home_or_draw": "Home or Draw",
        "away_or_draw": "Away or Draw",
        "home_or_away": "Home or Away",
    }.get(selection_name, selection_name.replace("_"," ").title())

def pretty_selection_label(market_name, selection_name):
    mk = normalize_prop_market_key(market_name)
    s  = clean(selection_name)
    lo = s.lower()
    if mk == "btts":
        yes = bool(re.search(r"(?:^|\b|[- ])yes(?:$|\b)",lo))
        no  = bool(re.search(r"(?:^|\b|[- ])no(?:$|\b)",lo))
        side = "Yes" if yes else ("No" if no else None)
        if side:
            if "first half"  in lo: return f"{side} - 1st Half"
            if "both halves" in lo: return f"{side} - Both Halves"
            if "no draw"     in lo: return f"{side} - No Draw"
            if "two or more" in lo: return f"{side} - 2+ Goals"
            return side
    return s

# ── Data loading ───────────────────────────────────────────────────────────────

def load_book(bookmaker, path):
    data = load_json(path)
    rows, generated = [], data.get("generated_at","")
    for m in data.get("matches") or []:
        home = display_team(m.get("home_team"))
        away = display_team(m.get("away_team"))
        if not home or not away: continue
        rows.append({
            "bookmaker": bookmaker,
            "date_label": m.get("date_label",""),
            "time": m.get("time",""),
            "match": f"{home} v {away}",
            "home_team": home, "away_team": away,
            "odds": m.get("odds") or {},
            "source_url": m.get("source_url",""),
            "strict_key": fixture_key(home,away),
            "loose_key": loose_fixture_key(home,away),
        })
    return rows, generated

def load_midnite_moneylines():
    """Load Midnite moneylines — decimal odds schema, kickoff string as date."""
    data = load_json(MIDNITE_PATH)
    rows = []
    for m in data.get("matches") or []:
        home = display_team(m.get("home",""))
        away = display_team(m.get("away",""))
        if not home or not away: continue
        kickoff = m.get("kickoff","")
        def dec_str(v):
            try: return str(round(float(v),4)) if v else ""
            except: return ""
        rows.append({
            "bookmaker": "Midnite",
            "date_label": kickoff,
            "time": kickoff,
            "match": f"{home} v {away}",
            "home_team": home, "away_team": away,
            "odds": {
                "home": dec_str(m.get("home_odds")),
                "draw": dec_str(m.get("draw_odds")),
                "away": dec_str(m.get("away_odds")),
            },
            "source_url": m.get("url",""),
            "strict_key": fixture_key(home,away),
            "loose_key": loose_fixture_key(home,away),
        })
    return rows

def _dec_to_str(v):
    """Return decimal odd as display string, empty if invalid."""
    try:
        f = float(v)
        return f"{f:.4g}" if f > 1 else ""
    except:
        return ""

MIDNITE_JUNK_NAMES = {
    "mex", "rsa", "goalscorers", "multi", "method", "time",
    "carded anytime", "sent off anytime", "carded first",
    "to score", "first", "last", "anytime goalscorer",
}

def _is_valid_midnite_player(name):
    """Return True if name looks like a real player, not a column header or team abbrev."""
    if not name: return False
    n = name.strip()
    if re.match(r"^[A-Z]{2,4}(\s+\d+)?$", n): return False  # MEX, RSA, MEX 21
    if n.lower() in MIDNITE_JUNK_NAMES: return False
    if len(n) < 4: return False
    return True

def load_midnite_props():
    """Load Midnite props — flat dict schema per market."""
    data = load_json(MIDNITE_PROPS_PATH)
    out  = {}
    for m in data.get("matches") or []:
        home = display_team(m.get("home",""))
        away = display_team(m.get("away",""))
        if not home or not away: continue

        raw = m.get("markets") or {}
        markets = []

        # Total Goals O/U
        tg = raw.get("total_goals")
        if isinstance(tg, dict):
            sels = []
            for k,v in sorted(tg.items()):
                if not v: continue
                if k.startswith("over_"):
                    line = k[5:].replace("_",".")
                    sels.append({"selection":f"Over {line}","odds":_dec_to_str(v)})
                elif k.startswith("under_"):
                    line = k[6:].replace("_",".")
                    sels.append({"selection":f"Under {line}","odds":_dec_to_str(v)})
            if sels: markets.append({"market":"Total Goals Over/Under","selections":sels})

        # BTTS — main Yes/No only
        btts = raw.get("btts")
        if isinstance(btts, dict):
            sels = []
            if btts.get("yes"): sels.append({"selection":"Both Teams To Score - Yes","odds":_dec_to_str(btts["yes"])})
            if btts.get("no"):  sels.append({"selection":"Both Teams To Score - No","odds":_dec_to_str(btts["no"])})
            if sels: markets.append({"market":"Both Teams To Score","selections":sels})

        # Double Chance
        dc = raw.get("double_chance")
        if isinstance(dc, dict):
            mapping = {
                "home_or_draw": f"{home} or Draw",
                "away_or_draw": f"{away} or Draw",
                "home_or_away": f"{home} or {away}",
            }
            sels = []
            for k,label in mapping.items():
                if dc.get(k): sels.append({"selection":label,"odds":_dec_to_str(dc[k])})
            if sels: markets.append({"market":"Double Chance","selections":sels})

        # Half Time Result
        hr1 = raw.get("half_result_1h")
        if isinstance(hr1, dict):
            sels = []
            if hr1.get("home"): sels.append({"selection":home,"odds":_dec_to_str(hr1["home"])})
            if hr1.get("draw"): sels.append({"selection":"Draw","odds":_dec_to_str(hr1["draw"])})
            if hr1.get("away"): sels.append({"selection":away,"odds":_dec_to_str(hr1["away"])})
            if sels: markets.append({"market":"Half Time Result","selections":sels})

        # Player Carded — Anytime (no " Anytime" suffix since market name already implies it)
        pc = raw.get("player_carded")
        if isinstance(pc, dict):
            sels = []
            for player, pdata in pc.items():
                if not _is_valid_midnite_player(player): continue
                if isinstance(pdata, dict) and pdata.get("carded_anytime"):
                    sels.append({"selection":player,"odds":_dec_to_str(pdata["carded_anytime"])})
            if sels: markets.append({"market":"To Get A Card","selections":sels})

        # Player Shots on Target (1+)
        psot = raw.get("player_shots_on_target")
        if isinstance(psot, dict):
            sels = []
            for player, pdata in psot.items():
                if not _is_valid_midnite_player(player): continue
                if isinstance(pdata, dict) and pdata.get("1+"):
                    sels.append({"selection":f"{player} Over 0.5 Shots On Target","odds":_dec_to_str(pdata["1+"])})
            if sels: markets.append({"market":"Shots On Target","selections":sels})

        # Player to Score — Anytime
        pts = raw.get("player_to_score")
        if isinstance(pts, dict):
            sels = []
            for player, pdata in pts.items():
                if not _is_valid_midnite_player(player): continue
                if isinstance(pdata, dict) and pdata.get("to_score"):
                    sels.append({"selection":f"Anytime Goalscorer {player}","odds":_dec_to_str(pdata["to_score"])})
            if sels: markets.append({"market":"Anytime Goalscorer","selections":sels})

        # Player Fouls Committed (1+)
        pfc = raw.get("player_fouls_committed")
        if isinstance(pfc, dict):
            sels = []
            for player, pdata in pfc.items():
                if not _is_valid_midnite_player(player): continue
                if isinstance(pdata, dict) and pdata.get("1+"):
                    sels.append({"selection":f"{player} Over 0.5 Fouls","odds":_dec_to_str(pdata["1+"])})
            if sels: markets.append({"market":"Player Fouls Committed","selections":sels})

        # Player Fouls Won (1+)
        pfw = raw.get("player_fouls_won")
        if isinstance(pfw, dict):
            sels = []
            for player, pdata in pfw.items():
                if not _is_valid_midnite_player(player): continue
                if isinstance(pdata, dict) and pdata.get("1+"):
                    sels.append({"selection":f"{player} Over 0.5 Fouls Won","odds":_dec_to_str(pdata["1+"])})
            if sels: markets.append({"market":"Player Fouls Won","selections":sels})

        # Total Shots on Target (combined match)
        tsot = raw.get("total_shots_on_target")
        if isinstance(tsot, dict):
            sels = []
            for k, v in sorted(tsot.items(), key=lambda x: float(x[0].replace("over_",""))):
                if v: sels.append({"selection":f"Over {k.replace('over_','')}+","odds":_dec_to_str(v)})
            if sels: markets.append({"market":"Total Shots On Target","selections":sels})

        # Total Shots (combined match)
        ts = raw.get("total_shots")
        if isinstance(ts, dict):
            sels = []
            for k, v in sorted(ts.items(), key=lambda x: float(x[0].replace("over_",""))):
                if v: sels.append({"selection":f"Over {k.replace('over_','')}+","odds":_dec_to_str(v)})
            if sels: markets.append({"market":"Total Shots","selections":sels})

        # Total Match Cards
        tc = raw.get("total_cards")
        if isinstance(tc, dict):
            sels = []
            for k, v in sorted(tc.items(), key=lambda x: float(x[0].replace("over_",""))):
                if v: sels.append({"selection":f"Over {k.replace('over_','')}+","odds":_dec_to_str(v)})
            if sels: markets.append({"market":"Total Match Cards","selections":sels})

        if not markets: continue
        fk = fixture_key(home, away)
        out[fk] = {
            "bookmaker": "Midnite",
            "match": f"{home} v {away}",
            "home_team": home, "away_team": away,
            "source_url": m.get("url",""),
            "market_count": len(markets),
            "markets": markets,
        }
    return out

def split_match_name(s):
    s = clean(s)
    if re.search(r"\s+v\s+",s,re.I):
        h,a = re.split(r"\s+v\s+",s,maxsplit=1,flags=re.I)
        return display_team(h), display_team(a)
    return "",""

def convert_market(raw, internal_name=""):
    if not isinstance(raw,dict): return None
    name = raw.get("market") or raw.get("label") or raw.get("name") or pretty_market_name(internal_name) or ""
    name = pretty_market_name(name)
    mk   = normalize_prop_market_key(name)
    sels = []
    for rs in raw.get("selections") or []:
        if not isinstance(rs,dict): continue
        sel  = clean(rs.get("selection") or rs.get("name") or rs.get("label") or "")
        odds = clean(rs.get("odds") or rs.get("price") or rs.get("fractional") or "").upper()
        if not sel or not odds: continue
        sel_lower = sel.lower()
        if mk == "player_to_get_a_card" and ("shots" in sel_lower): continue
        if mk == "shots_on_target" and "card" in sel_lower: continue
        sels.append({"selection":sel,"normalized_selection":normalize_text_key(sel),"odds":odds})
    if not name or not sels: return None
    return {"market":name,"normalized_market":mk,"selection_count":len(sels),"selections":sels}

def convert_markets(raw_markets):
    markets = []
    if isinstance(raw_markets,list):
        for rm in raw_markets:
            m = convert_market(rm)
            if m: markets.append(m)
    elif isinstance(raw_markets,dict):
        for k,rm in raw_markets.items():
            if not isinstance(rm,dict): continue
            rm = dict(rm)
            rm.setdefault("market", rm.get("label") or pretty_market_name(k))
            m = convert_market(rm, k)
            if m: markets.append(m)
    seen,unique = set(),[]
    for m in markets:
        k = m["normalized_market"]
        if k not in seen:
            seen.add(k); unique.append(m)
    return unique

def repair_markets(bookmaker, markets):
    fixed = []
    for market in markets or []:
        if not isinstance(market,dict): continue
        mk  = normalize_prop_market_key(market.get("market",""))
        sel = market.get("selections") or []
        if mk == "btts" and len(sel) == 2:
            labels = [clean(s.get("selection","")).lower() for s in sel]
            has_yn = any(re.search(r"(?:^|\b|[- ])yes(?:$|\b)",x) or re.search(r"(?:^|\b|[- ])no(?:$|\b)",x) for x in labels)
            if not has_yn:
                repaired = []
                for i,s in enumerate(sel):
                    side = "Yes" if i==0 else "No"
                    repaired.append({**s,"selection":f"Both Teams To Score - {side}","normalized_selection":normalize_text_key(f"Both Teams To Score - {side}")})
                market = {**market,"market":"Both Teams To Score","normalized_market":"btts","selection_count":len(repaired),"selections":repaired}
        fixed.append(market)
    return fixed

def load_props_file(bookmaker, path):
    data = load_json(path)
    raw  = data.get("matches") or data.get("results") or (data if isinstance(data,list) else [])
    generated = data.get("generated_at","") if isinstance(data,dict) else ""
    source_url = data.get("source_url","") if isinstance(data,dict) else ""
    out = {}
    for m in raw:
        if not isinstance(m,dict): continue
        home = display_team(m.get("home_team"))
        away = display_team(m.get("away_team"))
        if not home or not away:
            home,away = split_match_name(m.get("match") or m.get("name",""))
        if not home or not away: continue
        markets = convert_markets(m.get("markets") or {})
        markets = repair_markets(bookmaker, markets)
        if not markets: continue
        out[fixture_key(home,away)] = {
            "bookmaker": bookmaker,
            "match": m.get("match") or f"{home} v {away}",
            "home_team": home, "away_team": away,
            "source_url": m.get("source_url") or m.get("url") or source_url,
            "market_count": len(markets),
            "markets": markets,
        }
    return out, generated

def add_book_rows(fixtures, si, li, rows, bookmaker):
    for row in rows:
        tk = si.get(row["strict_key"]) or li.get(row["loose_key"])
        if tk:
            fixtures[tk]["bookmakers"][bookmaker] = {"bookmaker":bookmaker,"odds":row["odds"],"source_url":row["source_url"]}
        else:
            k = row["strict_key"]
            fixtures[k] = {
                "key":k,"loose_key":row["loose_key"],
                "slug":slugify(f"{row['home_team']}-v-{row['away_team']}"),
                "date_label":row["date_label"],"time":row["time"],
                "match":row["match"],"home_team":row["home_team"],"away_team":row["away_team"],
                "bookmakers":{bookmaker:{"bookmaker":bookmaker,"odds":row["odds"],"source_url":row["source_url"]}},
                "props":{},
            }
            si[k]=k; li[row["loose_key"]]=k

def date_sort_key(label):
    label = str(label or "")
    days  = {"Monday":1,"Tuesday":2,"Wednesday":3,"Thursday":4,"Friday":5,"Saturday":6,"Sunday":7,
             "Mon":1,"Tue":2,"Wed":3,"Thu":4,"Fri":5,"Sat":6,"Sun":7}
    parts = label.split()
    day   = days.get(parts[0],999) if parts else 999
    num   = next((int(p) for p in parts if p.isdigit()),999)
    return (num, day, label)

def load_all():
    paddy_rows,   paddy_gen    = load_book("PaddyPower",   PADDY_PATH)
    boyle_rows,   boyle_gen    = load_book("BoyleSports",  BOYLE_PATH)
    betv_rows,    betv_gen     = load_book("BetVictor",    BETVICTOR_PATH)
    unibet_rows,  unibet_gen   = load_book("Unibet",       UNIBET_PATH)
    lsb_rows,     lsb_gen      = load_book("LiveScoreBet", LIVESCOREBET_PATH)
    wh_rows,      wh_gen       = load_book("WilliamHill",  WILLIAMHILL_PATH)
    eee_rows,     eee_gen      = load_book("888Sport",     EIGHTEIGHTEIGHT_PATH)
    ladb_rows,    ladb_gen     = load_book("Ladbrokes",    LADBROKES_PATH)
    midnite_rows               = load_midnite_moneylines()

    paddy_props,  paddy_p_gen  = load_props_file("PaddyPower",   PADDY_PROPS_PATH)
    boyle_props,  boyle_p_gen  = load_props_file("BoyleSports",  BOYLE_PROPS_PATH)
    unibet_props, unibet_p_gen = load_props_file("Unibet",       UNIBET_PROPS_PATH)
    lsb_props,    lsb_p_gen    = load_props_file("LiveScoreBet", LIVESCORE_PROPS_PATH)
    eee_props,    eee_p_gen    = load_props_file("888Sport",     EIGHTSPORT_PROPS_PATH)
    wh_props,     wh_p_gen     = load_props_file("WilliamHill",  WILLIAMHILL_PROPS_PATH)
    betv_props,   betv_p_gen   = load_props_file("BetVictor",    BETVICTOR_PROPS_PATH)
    ladb_props,   ladb_p_gen   = load_props_file("Ladbrokes",    LADBROKES_PROPS_PATH)
    midnite_props              = load_midnite_props()

    fixtures = {}
    for row in paddy_rows:
        k = row["strict_key"]
        fixtures[k] = {
            "key":k,"loose_key":row["loose_key"],
            "slug":slugify(f"{row['home_team']}-v-{row['away_team']}"),
            "date_label":row["date_label"],"time":row["time"],
            "match":row["match"],"home_team":row["home_team"],"away_team":row["away_team"],
            "bookmakers":{"PaddyPower":{"bookmaker":"PaddyPower","odds":row["odds"],"source_url":row["source_url"]}},
            "props":{},
        }

    si = {f["key"]:k for k,f in fixtures.items()}
    li = {f["loose_key"]:k for k,f in fixtures.items()}

    for rows,bk in [(boyle_rows,"BoyleSports"),(betv_rows,"BetVictor"),(unibet_rows,"Unibet"),
                    (lsb_rows,"LiveScoreBet"),(wh_rows,"WilliamHill"),(eee_rows,"888Sport"),
                    (ladb_rows,"Ladbrokes"),(midnite_rows,"Midnite")]:
        add_book_rows(fixtures,si,li,rows,bk)

    for bk,bk_props in [("PaddyPower",paddy_props),("BoyleSports",boyle_props),
                         ("Unibet",unibet_props),("LiveScoreBet",lsb_props),
                         ("888Sport",eee_props),("WilliamHill",wh_props),
                         ("BetVictor",betv_props),("Ladbrokes",ladb_props),
                         ("Midnite",midnite_props)]:
        for pk,pd in bk_props.items():
            lk = loose_fixture_key(pd.get("home_team",""),pd.get("away_team",""))
            tk = si.get(pk) or li.get(lk)
            if tk and tk in fixtures:
                fixtures[tk].setdefault("props",{})
                fixtures[tk]["props"][bk] = pd

    fl = sorted(fixtures.values(), key=lambda x:(date_sort_key(x.get("date_label")),x.get("time",""),x.get("match","")))
    generated = paddy_p_gen or boyle_p_gen or unibet_p_gen or lsb_p_gen or eee_p_gen or wh_p_gen or betv_p_gen or ladb_p_gen or eee_gen or wh_gen or lsb_gen or unibet_gen or betv_gen or boyle_gen or paddy_gen or ladb_gen
    bk_count  = len({b for f in fl for b in f.get("bookmakers",{})})
    return fl, bk_count, generated

# ── Odds helpers ───────────────────────────────────────────────────────────────

def best_price(fixture, side):
    best = None
    for bk,info in fixture.get("bookmakers",{}).items():
        raw = (info.get("odds") or {}).get(side)
        dec = fractional_to_decimal(raw)
        if raw and dec > 1 and (not best or dec > best["decimal"]):
            best = {"bookmaker":bk,"odds":raw,"decimal":dec}
    return best

def all_prices(fixture, side):
    rows = []
    for bk,info in sorted(fixture.get("bookmakers",{}).items()):
        raw = (info.get("odds") or {}).get(side)
        dec = fractional_to_decimal(raw)
        if raw and dec > 1: rows.append({"bookmaker":bk,"odds":raw,"decimal":dec})
    best = best_price(fixture,side)
    bk   = (best["bookmaker"],best["odds"]) if best else None
    for r in rows: r["is_best"] = bk==(r["bookmaker"],r["odds"])
    return rows

def build_comparison_data(props):
    comp = {}
    for bk,pd in sorted(props.items()):
        for market in pd.get("markets") or []:
            mn  = market.get("market","")
            mk  = normalize_prop_market_key(mn)
            if is_team_market(mn): continue
            for sel in market.get("selections") or []:
                sn   = sel.get("selection","")
                odds = sel.get("odds","")
                dec  = fractional_to_decimal(odds)
                if not sn or not odds or dec <= 1: continue
                sk  = normalize_prop_selection_key(mn,sn)
                key = (mk,sk)
                if key not in comp:
                    comp[key] = {"market":pretty_market_name(mn),"market_key":mk,
                                 "selection":pretty_selection_label(mn,sn),"selection_key":sk,"offers":[]}
                comp[key]["offers"].append({"bookmaker":bk,"odds":odds,"decimal":dec})
    return comp

# ── CSS ────────────────────────────────────────────────────────────────────────

SHARED_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0f1621;
  color: #fff;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  min-height: 100vh;
}
a { color: #60a5fa; text-decoration: none; }
.page { max-width: 1300px; margin: 0 auto; padding: 34px 24px 70px; }
.nav { color: #91a0b5; margin-bottom: 28px; display: flex; gap: 10px; flex-wrap: wrap; font-size: 14px; }
.nav a { color: #60a5fa; }
.hero { border: 1px solid #223047; border-radius: 28px; padding: 32px; background: rgba(17,24,39,0.86); margin-bottom: 28px; }
.eyebrow { display: inline-flex; border: 1px solid rgba(34,197,94,0.45); background: rgba(34,197,94,0.1); color: #86efac; border-radius: 999px; padding: 7px 12px; font-size: 12px; font-weight: 900; text-transform: uppercase; margin-bottom: 14px; }
h1 { font-size: clamp(34px,5vw,64px); letter-spacing: -0.05em; line-height: .95; margin-bottom: 10px; }
.meta { color: #91a0b5; font-size: 14px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid #223047; color: #c7d2fe; font-size: 14px; }
th { color: #91a0b5; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
td strong { color: #22c55e; font-size: 19px; }
.best-row { background: rgba(34,197,94,0.08); }
.best-row td:last-child { color: #86efac; font-weight: 900; font-size: 12px; }
.best-cell strong { color: #22c55e !important; }
.panel { border: 1px solid #223047; border-radius: 20px; padding: 18px; background: rgba(17,24,39,0.72); margin-bottom: 14px; }
.panel h2 { font-size: 20px; margin-bottom: 14px; }
.panel h3 { font-size: 16px; margin-bottom: 10px; color: #facc15; }
.grid3 { display: grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap: 14px; margin-bottom: 24px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit,minmax(380px,1fr)); gap: 14px; margin-bottom: 14px; }
.sub-nav { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }
.sub-nav a { border: 1px solid rgba(96,165,250,0.45); background: rgba(96,165,250,0.08); color: #bfdbfe; border-radius: 999px; padding: 9px 16px; font-size: 13px; font-weight: 900; text-transform: uppercase; }
.sub-nav a.active { background: rgba(96,165,250,0.25); border-color: #60a5fa; color: #fff; }
.section-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.section-head h2 { font-size: 26px; }
.section-head a { border: 1px solid rgba(96,165,250,0.45); background: rgba(96,165,250,0.08); color: #bfdbfe; border-radius: 999px; padding: 7px 11px; font-size: 12px; font-weight: 900; text-transform: uppercase; }
.best-summary { display: grid; grid-template-columns: repeat(auto-fill,minmax(200px,1fr)); gap: 10px; margin-bottom: 8px; }
.best-pill { border: 1px solid #223047; border-radius: 12px; padding: 10px 12px; background: rgba(255,255,255,0.03); }
.best-pill .mkt { color: #91a0b5; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 4px; }
.best-pill .sel { font-size: 13px; font-weight: 600; margin-bottom: 2px; }
.best-pill .price { color: #22c55e; font-size: 18px; font-weight: 900; }
.best-pill .book { color: #91a0b5; font-size: 11px; }
.footer-note { color: #91a0b5; font-size: 13px; margin-top: 28px; line-height: 1.6; }
.goalscorer-table td:first-child { font-weight: 600; color: #e2e8f0; min-width: 150px; }
@media (max-width: 700px) {
  .page { padding: 20px 14px 50px; }
  .hero { padding: 22px; border-radius: 22px; }
  .grid3, .grid2 { grid-template-columns: 1fr; }
}
"""

# ── Index page ─────────────────────────────────────────────────────────────────

def render_index(fixtures, bk_count, generated):
    grouped = {}
    for f in fixtures:
        grouped.setdefault(f.get("date_label") or "Upcoming",[]).append(f)

    groups = ""
    for date,items in grouped.items():
        cards = ""
        for f in items:
            home,away,slug = f["home_team"],f["away_team"],f["slug"]
            bh = best_price(f,"home"); bd = best_price(f,"draw"); ba = best_price(f,"away")
            bk_count_f = len(f.get("bookmakers",{}))
            has_props = bool(f.get("props"))
            props_badge = f'<span style="color:#86efac;font-weight:900;font-size:12px;margin-left:8px;">Props ✓</span>' if has_props else ""

            def box(label,best):
                if not best: return f'<div class="odd-box"><span>{esc(label)}</span><strong>—</strong><em></em></div>'
                return f'<div class="odd-box"><span>{esc(label)}</span><strong>{esc(best["odds"])}</strong><em>{esc(best["bookmaker"])}</em></div>'

            cards += f"""
            <article style="border:1px solid #223047;border-radius:20px;padding:18px;background:rgba(17,24,39,0.72)">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px">
                <div>
                  <h3 style="font-size:17px;letter-spacing:-0.02em;margin-bottom:4px">{esc(home)} <span style="color:#91a0b5;font-weight:500">v</span> {esc(away)}</h3>
                  <p style="color:#91a0b5;font-size:13px">{esc(f.get("time",""))} · {bk_count_f} bookmaker{"s" if bk_count_f!=1 else ""}{props_badge}</p>
                </div>
                <a href="{BASE}/football/world-cup/{slug}/" style="white-space:nowrap;border:1px solid rgba(250,204,21,0.4);color:#fde68a;background:rgba(250,204,21,0.08);border-radius:999px;padding:6px 10px;font-size:11px;font-weight:900;text-transform:uppercase">View →</a>
              </div>
              <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">
                {box(home,bh)}{box("Draw",bd)}{box(away,ba)}
              </div>
            </article>"""

        groups += f"""
        <section style="margin-top:30px">
          <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #223047;padding-bottom:10px;margin-bottom:12px">
            <h2 style="font-size:22px">{esc(date)}</h2>
            <span style="border:1px solid rgba(96,165,250,0.35);color:#bfdbfe;background:rgba(96,165,250,0.08);border-radius:999px;padding:4px 10px;font-size:12px;font-weight:800">{len(items)} match{"es" if len(items)!=1 else ""}</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px">{cards}</div>
        </section>"""

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>FIFA World Cup Odds — BeatTheBooks</title>
<style>
{SHARED_CSS}
.odd-box{{border:1px solid #223047;border-radius:14px;padding:10px;background:rgba(15,22,33,0.82);text-align:center}}
.odd-box span{{display:block;color:#91a0b5;font-size:12px;margin-bottom:6px;min-height:28px}}
.odd-box strong{{display:block;color:#22c55e;font-size:20px;font-weight:950}}
.odd-box em{{display:block;color:#91a0b5;font-size:11px;font-style:normal;margin-top:4px}}
</style></head><body>
<main class="page">
  <nav class="nav"><a href="{BASE}/football/">Football</a><span>›</span><span>FIFA World Cup</span></nav>
  <section class="hero"
    style="background:radial-gradient(circle at top left,rgba(34,197,94,0.14),transparent 40%),radial-gradient(circle at top right,rgba(96,165,250,0.1),transparent 40%),rgba(17,24,39,0.86)">
    <div class="eyebrow">⚽ Football Odds</div>
    <h1>FIFA World Cup<br>Odds</h1>
    <p class="meta" style="margin-top:10px">Best odds across {bk_count} bookmakers · Props from PaddyPower, BoyleSports, Unibet, LiveScoreBet, 888Sport, William Hill &amp; Midnite</p>
    <p class="footer-note" style="margin-top:14px">Updated: {esc(generated)}</p>
  </section>
  {groups}
  <p class="footer-note">Odds may change. Always verify with the bookmaker before placing a bet.</p>
</main></body></html>"""

# ── Match page ─────────────────────────────────────────────────────────────────

def render_match_page(fixture):
    home,away,slug = fixture["home_team"],fixture["away_team"],fixture["slug"]
    props = fixture.get("props") or {}
    has_match_props  = any(any(normalize_prop_market_key(m["market"]) in MATCH_MARKET_KEYS for m in pd.get("markets",[])) for pd in props.values())
    has_player_props = any(any(is_player_market(m["market"]) for m in pd.get("markets",[])) for pd in props.values())

    def price_table(side_label, rows):
        body = "".join(f'<tr class="{"best-row" if r["is_best"] else ""}"><td>{esc(r["bookmaker"])}</td><td><strong>{esc(r["odds"])}</strong></td><td>{"BEST" if r["is_best"] else ""}</td></tr>' for r in rows)
        if not body: body='<tr><td colspan="3">No prices</td></tr>'
        return f'<div class="panel"><h2>{esc(side_label)}</h2><table><thead><tr><th>Bookmaker</th><th>Odds</th><th></th></tr></thead><tbody>{body}</tbody></table></div>'

    home_rows  = all_prices(fixture,"home")
    draw_rows  = all_prices(fixture,"draw")
    away_rows  = all_prices(fixture,"away")
    mono_html  = f'<div class="grid3">{price_table(home,home_rows)}{price_table("Draw",draw_rows)}{price_table(away,away_rows)}</div>'

    comp = build_comparison_data(props)
    SUMMARY_MARKETS = ["btts","total_goals","double_chance","anytime_scorer","first_goalscorer","shots_on_target","player_to_get_a_card"]
    pills = ""
    for mk in SUMMARY_MARKETS:
        items = [(sk,item) for (imk,sk),item in comp.items() if imk==mk]
        if not items: continue
        best_item = None; best_dec = 0
        for sk,item in items:
            for offer in item["offers"]:
                if offer["decimal"] > best_dec:
                    best_dec = offer["decimal"]; best_item = (item,offer)
        if best_item:
            item,offer = best_item
            pills += f'<div class="best-pill"><div class="mkt">{esc(item["market"])}</div><div class="sel">{esc(item["selection"])}</div><div class="price">{esc(offer["odds"])}</div><div class="book">{esc(offer["bookmaker"])}</div></div>'

    summary_html = ""
    if pills:
        summary_html = f'<div class="panel"><div class="section-head"><h2>Best Prop Prices</h2></div><div class="best-summary">{pills}</div></div>'

    subnav = f'<nav class="sub-nav"><a href="./index.html" class="active">Odds</a>'
    if has_match_props:  subnav += f'<a href="match-props/index.html">Match Props</a>'
    if has_player_props: subnav += f'<a href="player-props/index.html">Player Props</a>'
    subnav += '</nav>'

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{esc(home)} v {esc(away)} Odds — BeatTheBooks</title>
<style>{SHARED_CSS}</style></head><body>
<main class="page">
  <nav class="nav"><a href="{BASE}/football/">Football</a><span>›</span><a href="{BASE}/football/world-cup/">World Cup</a><span>›</span><span>{esc(home)} v {esc(away)}</span></nav>
  <section class="hero">
    <div class="eyebrow">⚽ Match Odds</div>
    <h1>{esc(home)} v {esc(away)}</h1>
    <p class="meta">{esc(fixture.get("date_label",""))} · {esc(fixture.get("time",""))} · {len(fixture.get("bookmakers",{}))} bookmakers</p>
  </section>
  {subnav}
  {mono_html}
  {summary_html}
  <p class="footer-note">Odds may change. Always verify with the bookmaker before placing a bet.</p>
</main></body></html>"""

# ── Match Props page ───────────────────────────────────────────────────────────

def render_match_props_page(fixture):
    home,away,slug = fixture["home_team"],fixture["away_team"],fixture["slug"]
    props = fixture.get("props") or {}
    comp  = build_comparison_data(props)

    subnav = f'<nav class="sub-nav"><a href="../index.html">Odds</a><a href="./index.html" class="active">Match Props</a>'
    has_player = any(any(is_player_market(m["market"]) for m in pd.get("markets",[])) for pd in props.values())
    if has_player: subnav += f'<a href="../player-props/index.html">Player Props</a>'
    subnav += '</nav>'

    def ou_tables():
        html = ""
        for mk in ["total_goals","first_half_goals"]:
            lines_data = {}
            for (imk,sk),item in comp.items():
                if imk != mk: continue
                m2 = re.match(r"^(over|under)_(\d+(?:\.\d+)?)$",sk)
                if not m2: continue
                side,line = m2.group(1),m2.group(2)
                lines_data.setdefault(line,{})[side] = item
            if not lines_data: continue
            rows = ""
            for line in sorted(lines_data.keys(),key=lambda x:float(x)):
                sides = lines_data[line]
                def best_offer(item):
                    if not item: return None
                    offs = [o for o in item["offers"] if o["decimal"]>1]
                    return max(offs,key=lambda x:x["decimal"]) if offs else None
                ob = best_offer(sides.get("over")); ub = best_offer(sides.get("under"))
                WANTED_LINES = {
                    "total_goals": {"1.5","2.5"},
                    "first_half_goals": {"0.5","1.5"},
                }
                wanted = WANTED_LINES.get(mk)
                if wanted and line not in wanted: continue
                def ol(o): return f'{esc(o["bookmaker"])} <strong>{esc(o["odds"])}</strong>' if o else "—"
                rows += f"<tr><td><strong>{esc(line)}</strong></td><td>{ol(ob)}</td><td>{ol(ub)}</td></tr>"
            if rows:
                html += f'<div class="panel"><h2>{esc(pretty_market_name(mk))}</h2><table><thead><tr><th>Line</th><th>Best Over</th><th>Best Under</th></tr></thead><tbody>{rows}</tbody></table></div>'
        return html

    def standard_cards():
        html = ""
        WANTED_MARKETS = {"btts", "double_chance", "half_time_result"}
        for (mk,sk),item in sorted(comp.items(),key=lambda x:(x[1]["market"],x[1]["selection"])):
            if mk not in WANTED_MARKETS: continue
            if mk == "btts" and sk not in {"btts_yes","btts_no"}: continue
            offs = item["offers"]
            by_bk = {}
            for o in offs:
                bk = o["bookmaker"]
                if bk not in by_bk or o["decimal"]>by_bk[bk]["decimal"]: by_bk[bk]=o
            offs = sorted(by_bk.values(),key=lambda x:x["decimal"],reverse=True)
            if not offs: continue
            best = offs[0]
            label = pretty_selection_label_dc(sk) if mk == "double_chance" else item["selection"]
            rows = f'<tr class="best-row"><td>{esc(best["bookmaker"])}</td><td><strong>{esc(best["odds"])}</strong></td><td>BEST</td></tr>'
            html += f'<div class="panel"><h3>{esc(item["market"])} — {esc(label)}</h3><table><thead><tr><th>Bookmaker</th><th>Odds</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>'
        return html

    def bookmaker_cards():
        html = ""
        for bk,pd in sorted(props.items()):
            markets = [m for m in pd.get("markets",[]) if normalize_prop_market_key(m["market"]) in MATCH_MARKET_KEYS]
            if not markets: continue
            cards = ""
            for market in markets:
                rows = "".join(f'<tr><td>{esc(s["selection"])}</td><td><strong>{esc(s["odds"])}</strong></td></tr>' for s in market.get("selections",[]))
                if rows: cards += f'<div class="panel"><h3>{esc(market["market"])}</h3><table><thead><tr><th>Selection</th><th>Odds</th></tr></thead><tbody>{rows}</tbody></table></div>'
            if cards:
                link = f'<a href="{esc(pd.get("source_url",""))}" target="_blank" rel="noopener">Open bookmaker →</a>'
                html += f'<section><div class="section-head"><h2>{esc(bk)} Match Props</h2>{link}</div><div class="grid2">{cards}</div></section>'
        return html

    ou_html  = ou_tables()
    std_html = standard_cards()
    bk_html  = bookmaker_cards()

    if not ou_html and not std_html and not bk_html:
        content = '<p style="color:#91a0b5">No match props available yet.</p>'
    else:
        content = f"""
        {'<section><div class="section-head"><h2>Best Prices — Over/Under</h2></div>' + ou_html + '</section>' if ou_html else ''}
        {'<section style="margin-top:20px"><div class="section-head"><h2>Best Prices — Markets</h2></div><div class="grid2">' + std_html + '</div></section>' if std_html else ''}
        {'<section style="margin-top:28px">' + bk_html + '</section>' if bk_html else ''}
        """

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{esc(home)} v {esc(away)} Match Props — BeatTheBooks</title>
<style>{SHARED_CSS}</style></head><body>
<main class="page">
  <nav class="nav"><a href="{BASE}/football/">Football</a><span>›</span><a href="{BASE}/football/world-cup/">World Cup</a><span>›</span><a href="{BASE}/football/world-cup/{slug}/">{esc(home)} v {esc(away)}</a><span>›</span><span>Match Props</span></nav>
  <section class="hero">
    <div class="eyebrow">⚽ Match Props</div>
    <h1>{esc(home)} v {esc(away)}</h1>
    <p class="meta">{esc(fixture.get("date_label",""))} · {esc(fixture.get("time",""))}</p>
  </section>
  {subnav}
  {content}
  <p class="footer-note">Odds may change. Always verify with the bookmaker before placing a bet.</p>
</main></body></html>"""

# ── Player Props page ──────────────────────────────────────────────────────────

def render_player_props_page(fixture):
    home,away,slug = fixture["home_team"],fixture["away_team"],fixture["slug"]
    props = fixture.get("props") or {}
    comp  = build_comparison_data(props)

    subnav = f'<nav class="sub-nav"><a href="../index.html">Odds</a>'
    has_match = any(any(normalize_prop_market_key(m["market"]) in MATCH_MARKET_KEYS for m in pd.get("markets",[])) for pd in props.values())
    if has_match: subnav += f'<a href="../match-props/index.html">Match Props</a>'
    subnav += f'<a href="./index.html" class="active">Player Props</a></nav>'

    def goalscorer_tables():
        html = ""
        for scorer_type,type_label in [("anytime","Anytime Goalscorer"),("first","First Goalscorer"),("score2","To Score 2+")]:
            players = {}
            all_books = set()
            for (mk,sk),item in comp.items():
                if mk not in {"anytime_scorer","first_goalscorer","scorer_2_plus","player_to_score"}: continue
                m2 = re.match(rf"^{scorer_type}__(.+)$",sk)
                if not m2: continue
                pk = m2.group(1)
                pn = pk.replace("_"," ").title()
                all_books.update(o["bookmaker"] for o in item["offers"])
                by_bk = {}
                for o in item["offers"]:
                    bk = o["bookmaker"]
                    if bk not in by_bk or o["decimal"]>by_bk[bk]["decimal"]: by_bk[bk]=o
                if pk not in players: players[pk]={"name":pn,"offers":{}}
                players[pk]["offers"].update(by_bk)

            if not players or len(all_books)<1: continue
            books = sorted(all_books)
            heads = "".join(f"<th>{esc(b)}</th>" for b in books)
            rows  = ""
            for pd in sorted(players.values(),key=lambda x:max((o["decimal"] for o in x["offers"].values()),default=0),reverse=True):
                bd = max((o["decimal"] for o in pd["offers"].values()),default=0)
                cells = ""
                for bk in books:
                    o = pd["offers"].get(bk)
                    if o:
                        is_best = o["decimal"]==bd
                        cells += f'<td{"  class=\"best-cell\"" if is_best else ""}><strong>{esc(o["odds"])}</strong></td>'
                    else:
                        cells += "<td>—</td>"
                rows += f'<tr><td>{esc(pd["name"])}</td>{cells}</tr>'
            if rows:
                html += f'<div class="panel goalscorer-table"><h2>{esc(type_label)}</h2><div style="overflow-x:auto"><table><thead><tr><th>Player</th>{heads}</tr></thead><tbody>{rows}</tbody></table></div></div>'
        return html

    def stat_tables():
        html = ""
        STAT_MARKETS = [
            ("shots_on_target","Shots On Target"),
            ("shots","Shots"),
            ("player_to_assist","To Assist"),
            ("player_to_get_a_card","To Get A Card"),
            ("player_fouls_committed","Fouls Committed"),
            ("player_fouls_won","Fouls Won"),
        ]
        for mk,label in STAT_MARKETS:
            players = {}
            all_books = set()
            lines_set = set()
            for (imk,sk),item in comp.items():
                if imk != mk: continue
                m2 = re.match(r"^(over|under)_([\d_]+)__(.+)$",sk)
                if m2:
                    side,line_raw,pk = m2.group(1),m2.group(2),m2.group(3)
                    line = line_raw.replace("_",".")
                    lines_set.add(line)
                    pn = pk.replace("_"," ").title()
                    by_bk = {}
                    for o in item["offers"]:
                        bk=o["bookmaker"]
                        if bk not in by_bk or o["decimal"]>by_bk[bk]["decimal"]: by_bk[bk]=o
                    all_books.update(by_bk.keys())
                    if pk not in players: players[pk]={"name":pn,"lines":{}}
                    players[pk]["lines"].setdefault(line,{}).update(by_bk)
                else:
                    pk = sk; pn = pk.replace("_"," ").title()
                    by_bk = {}
                    for o in item["offers"]:
                        bk=o["bookmaker"]
                        if bk not in by_bk or o["decimal"]>by_bk[bk]["decimal"]: by_bk[bk]=o
                    all_books.update(by_bk.keys())
                    if pk not in players: players[pk]={"name":pn,"lines":{}}
                    players[pk]["lines"].setdefault("—",{}).update(by_bk)
                    lines_set.add("—")

            if not players: continue
            books = sorted(all_books)
            lines = sorted(lines_set, key=lambda x:(float(x) if re.match(r'[\d\.]+',x) else 999))

            if lines == ["—"]:
                heads = "".join(f"<th>{esc(b)}</th>" for b in books)
                rows  = ""
                for pd in sorted(players.values(),key=lambda x:max((max(o["decimal"] for o in ls.values()) for ls in x["lines"].values() if ls),default=0),reverse=True):
                    bd = max((o["decimal"] for ls in pd["lines"].values() for o in ls.values()),default=0)
                    cells=""
                    for bk in books:
                        o = pd["lines"].get("—",{}).get(bk)
                        if o: cells+=f'<td{"  class=\"best-cell\"" if o["decimal"]==bd else ""}><strong>{esc(o["odds"])}</strong></td>'
                        else: cells+="<td>—</td>"
                    rows+=f'<tr><td>{esc(pd["name"])}</td>{cells}</tr>'
                if rows:
                    html+=f'<div class="panel goalscorer-table"><h2>{esc(label)}</h2><div style="overflow-x:auto"><table><thead><tr><th>Player</th>{heads}</tr></thead><tbody>{rows}</tbody></table></div></div>'
            else:
                col_heads = "".join(f"<th>Over {esc(l)}</th>" for l in lines if l!="—")
                rows=""
                for pd in sorted(players.values(),key=lambda x:max((max((o["decimal"] for o in ls.values()),default=0) for ls in x["lines"].values()),default=0),reverse=True):
                    cells=""
                    for line in lines:
                        if line=="—": continue
                        ls = pd["lines"].get(line,{})
                        if ls:
                            best = max(ls.values(),key=lambda o:o["decimal"])
                            cells+=f'<td><strong>{esc(best["odds"])}</strong><br><span style="color:#91a0b5;font-size:11px">{esc(best["bookmaker"])}</span></td>'
                        else: cells+="<td>—</td>"
                    rows+=f'<tr><td>{esc(pd["name"])}</td>{cells}</tr>'
                if rows:
                    html+=f'<div class="panel goalscorer-table"><h2>{esc(label)}</h2><div style="overflow-x:auto"><table><thead><tr><th>Player</th>{col_heads}</tr></thead><tbody>{rows}</tbody></table></div></div>'
        return html

    def bookmaker_cards():
        html=""
        for bk,pd in sorted(props.items()):
            markets=[m for m in pd.get("markets",[]) if is_player_market(m["market"])]
            if not markets: continue
            cards=""
            for market in markets:
                rows="".join(f'<tr><td>{esc(s["selection"])}</td><td><strong>{esc(s["odds"])}</strong></td></tr>' for s in market.get("selections",[]))
                if rows: cards+=f'<div class="panel"><h3>{esc(market["market"])}</h3><table><thead><tr><th>Selection</th><th>Odds</th></tr></thead><tbody>{rows}</tbody></table></div>'
            if cards:
                link=f'<a href="{esc(pd.get("source_url",""))}" target="_blank" rel="noopener">Open bookmaker →</a>'
                html+=f'<section style="margin-top:24px"><div class="section-head"><h2>{esc(bk)} Player Props</h2>{link}</div><div class="grid2">{cards}</div></section>'
        return html

    gs_html   = goalscorer_tables()
    stat_html = stat_tables()
    bk_html   = bookmaker_cards()

    if not gs_html and not stat_html and not bk_html:
        content='<p style="color:#91a0b5">No player props available yet.</p>'
    else:
        content=f"""
        {'<section><div class="section-head"><h2>Goalscorer Comparison</h2></div>' + gs_html + '</section>' if gs_html else ''}
        {'<section style="margin-top:24px"><div class="section-head"><h2>Player Stats</h2></div>' + stat_html + '</section>' if stat_html else ''}
        {'<div style="margin-top:32px">' + bk_html + '</div>' if bk_html else ''}
        """

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{esc(home)} v {esc(away)} Player Props — BeatTheBooks</title>
<style>{SHARED_CSS}</style></head><body>
<main class="page">
  <nav class="nav"><a href="{BASE}/football/">Football</a><span>›</span><a href="{BASE}/football/world-cup/">World Cup</a><span>›</span><a href="{BASE}/football/world-cup/{slug}/">{esc(home)} v {esc(away)}</a><span>›</span><span>Player Props</span></nav>
  <section class="hero">
    <div class="eyebrow">⚽ Player Props</div>
    <h1>{esc(home)} v {esc(away)}</h1>
    <p class="meta">{esc(fixture.get("date_label",""))} · {esc(fixture.get("time",""))}</p>
  </section>
  {subnav}
  {content}
  <p class="footer-note">Odds may change. Always verify with the bookmaker before placing a bet.</p>
</main></body></html>"""

# ── Football hub ───────────────────────────────────────────────────────────────

def render_hub(fixtures, bk_count, generated):
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Football — BeatTheBooks</title>
<style>{SHARED_CSS}
.card{{display:block;border:1px solid #223047;border-radius:22px;padding:24px;background:rgba(255,255,255,0.03);transition:transform .15s,border-color .15s}}
.card:hover{{transform:translateY(-2px);border-color:rgba(96,165,250,0.55)}}
.pill{{border:1px solid #223047;border-radius:999px;padding:6px 10px;color:#bfdbfe;font-size:13px;font-weight:800}}
</style></head><body>
<main class="page">
  <section class="hero">
    <div class="eyebrow">⚽ Football</div>
    <h1>Football Hub</h1>
    <p class="meta">World Cup odds, moneylines and props across tracked bookmakers.</p>
  </section>
  <a class="card" href="{BASE}/football/world-cup/">
    <h2 style="font-size:26px;margin-bottom:8px">FIFA World Cup</h2>
    <p style="color:#91a0b5;margin-bottom:14px">Best available match odds with Match Props and Player Props pages per fixture.</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <span class="pill">{len(fixtures)} fixtures</span>
      <span class="pill">{bk_count} bookmakers</span>
      <span class="pill">Match Props</span>
      <span class="pill">Player Props</span>
      <span class="pill">Updated {esc(generated)}</span>
    </div>
  </a>
</main></body></html>"""

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    fixtures, bk_count, generated = load_all()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HUB_PATH.parent.mkdir(parents=True, exist_ok=True)

    OUT_PATH.write_text(render_index(fixtures, bk_count, generated), encoding="utf-8")
    HUB_PATH.write_text(render_hub(fixtures, bk_count, generated), encoding="utf-8")

    match_pages = player_pages = 0

    for f in fixtures:
        d = OUT_DIR / f["slug"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(render_match_page(f), encoding="utf-8")

        props = f.get("props") or {}
        has_match  = any(any(normalize_prop_market_key(m["market"]) in MATCH_MARKET_KEYS  for m in pd.get("markets",[])) for pd in props.values())
        has_player = any(any(is_player_market(m["market"]) for m in pd.get("markets",[])) for pd in props.values())

        if has_match:
            mp = d / "match-props"; mp.mkdir(parents=True, exist_ok=True)
            (mp / "index.html").write_text(render_match_props_page(f), encoding="utf-8")
            match_pages += 1

        if has_player:
            pp = d / "player-props"; pp.mkdir(parents=True, exist_ok=True)
            (pp / "index.html").write_text(render_player_props_page(f), encoding="utf-8")
            player_pages += 1

    print(f"World Cup index:    {OUT_PATH}")
    print(f"Football hub:       {HUB_PATH}")
    print(f"Match pages:        {len(fixtures)}")
    print(f"Match props pages:  {match_pages}")
    print(f"Player props pages: {player_pages}")
    print(f"Bookmakers:         {bk_count}")

if __name__ == "__main__":
    main()