“””
ShotCart Event Scout
Finds and scores photography opportunities in Wayne County / Metro Detroit.
Runs every 2 days via GitHub Actions and writes index.html for GitHub Pages.
“””

import json
import requests
import os
from datetime import datetime, timedelta

from anthropic import Anthropic

# ── Config ──────────────────────────────────────────────────────────────────

with open(“config.json”) as f:
CONFIG = json.load(f)

WEIGHTS    = CONFIG[“scoring_weights”]
CENTER     = CONFIG[“location_center”]
QUERIES    = CONFIG[“search_queries”]
DAYS_AHEAD = CONFIG.get(“days_ahead”, 30)

client     = Anthropic(api_key=os.environ[“ANTHROPIC_API_KEY”])
SERPER_KEY = os.environ[“SERPER_API_KEY”]

# ── Search ───────────────────────────────────────────────────────────────────

def serper_search(query):
headers = {“X-API-KEY”: SERPER_KEY, “Content-Type”: “application/json”}
payload = {“q”: query, “gl”: “us”, “hl”: “en”, “num”: 10}
try:
r = requests.post(
“https://google.serper.dev/search”,
headers=headers, json=payload, timeout=15
)
return r.json() if r.ok else {}
except Exception as e:
print(f”  ⚠️  Search error: {e}”)
return {}

# ── Geocoding (Open-Meteo, free) ─────────────────────────────────────────────

def geocode(location_name):
“”“Return (lat, lng) or fall back to Detroit center.”””
try:
r = requests.get(
“https://geocoding-api.open-meteo.com/v1/search”,
params={“name”: location_name, “count”: 1, “language”: “en”, “format”: “json”},
timeout=10
)
results = r.json().get(“results”, [])
if results:
return results[0][“latitude”], results[0][“longitude”]
except Exception as e:
print(f”  ⚠️  Geocode error for ‘{location_name}’: {e}”)
return CENTER[“lat”], CENTER[“lng”]

# ── Weather (Open-Meteo, free) ───────────────────────────────────────────────

WMO = {
0:  (“Clear Sky”,          “☀️”,  100),
1:  (“Mainly Clear”,       “🌤️”,  92),
2:  (“Partly Cloudy”,      “⛅”,   80),
3:  (“Overcast”,           “☁️”,   72),   # soft diffuse — great for portraits
45: (“Foggy”,              “🌫️”,  38),
48: (“Icy Fog”,            “🌫️”,  30),
51: (“Light Drizzle”,      “🌦️”,  22),
53: (“Drizzle”,            “🌦️”,  14),
55: (“Heavy Drizzle”,      “🌧️”,   8),
61: (“Light Rain”,         “🌧️”,  18),
63: (“Rain”,               “🌧️”,   8),
65: (“Heavy Rain”,         “🌧️”,   4),
71: (“Light Snow”,         “🌨️”,  28),
73: (“Snow”,               “❄️”,   18),
75: (“Heavy Snow”,         “❄️”,    8),
77: (“Snow Grains”,        “❄️”,   14),
80: (“Light Showers”,      “🌦️”,  18),
81: (“Showers”,            “🌧️”,   8),
82: (“Heavy Showers”,      “⛈️”,   4),
85: (“Snow Showers”,       “🌨️”,  14),
86: (“Heavy Snow Showers”, “❄️”,    4),
95: (“Thunderstorm”,       “⛈️”,   0),
96: (“T-Storm + Hail”,     “⛈️”,   0),
99: (“Severe T-Storm”,     “⛈️”,   0),
}

def get_weather(lat, lng, date_str):
try:
r = requests.get(
“https://api.open-meteo.com/v1/forecast”,
params={
“latitude”: lat, “longitude”: lng,
“daily”: “weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max”,
“timezone”: “America/Detroit”,
“start_date”: date_str,
“end_date”:   date_str,
},
timeout=10
)
d = r.json().get(“daily”, {})
if not d or not d.get(“time”):
return None

```
    code   = d["weathercode"][0]
    label, emoji, w_score = WMO.get(code, (f"Code {code}", "🌡️", 50))
    tmax_c = d["temperature_2m_max"][0]
    tmin_c = d["temperature_2m_min"][0]
    tmax_f = round(tmax_c * 9 / 5 + 32)
    tmin_f = round(tmin_c * 9 / 5 + 32)
    precip = d["precipitation_sum"][0]
    wind_k = d["windspeed_10m_max"][0]
    wind_m = round(wind_k * 0.621371)

    # Temperature bonus / penalty
    if 55 <= tmax_f <= 85:
        w_score = min(100, w_score + 6)
    elif tmax_f < 28 or tmax_f > 98:
        w_score = max(0, w_score - 20)

    return {
        "code": code, "label": label, "emoji": emoji,
        "weather_score": w_score,
        "temp_max_f": tmax_f, "temp_min_f": tmin_f,
        "precipitation_mm": precip, "wind_mph": wind_m,
    }
except Exception as e:
    print(f"  ⚠️  Weather error: {e}")
    return None
```

# ── Golden Hour (Sunrise-Sunset API, free) ───────────────────────────────────

def get_golden_hour(lat, lng, date_str):
try:
r = requests.get(
“https://api.sunrise-sunset.org/json”,
params={“lat”: lat, “lng”: lng, “date”: date_str, “formatted”: 0},
timeout=10
)
data = r.json()
if data.get(“status”) != “OK”:
return None
res = data[“results”]

```
    def to_local(utc_str):
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        month = dt.month
        offset = -4 if 3 <= month <= 11 else -5   # EDT / EST
        return dt + timedelta(hours=offset)

    sunrise = to_local(res["sunrise"])
    sunset  = to_local(res["sunset"])
    gm_s = sunrise
    gm_e = sunrise + timedelta(minutes=60)
    ge_s = sunset  - timedelta(minutes=60)
    ge_e = sunset

    def fmt(dt): return dt.strftime("%-I:%M %p")

    return {
        "sunrise": sunrise, "sunset": sunset,
        "golden_morning": (gm_s, gm_e),
        "golden_evening": (ge_s, ge_e),
        "sunrise_str":         fmt(sunrise),
        "sunset_str":          fmt(sunset),
        "golden_morning_str":  f"{fmt(gm_s)}–{fmt(gm_e)}",
        "golden_evening_str":  f"{fmt(ge_s)}–{fmt(ge_e)}",
    }
except Exception as e:
    print(f"  ⚠️  Golden hour error: {e}")
    return None
```

def gh_score(start_hour, gh_data):
“”“Return 0–100 score for golden-hour proximity. 50 if time unknown.”””
if not gh_data or start_hour is None:
return 50

```
sunrise  = gh_data["sunrise"]
sunset   = gh_data["sunset"]
gm_start = sunrise.hour + sunrise.minute / 60
gm_end   = gm_start + 1
ge_end   = sunset.hour  + sunset.minute  / 60
ge_start = ge_end - 1

def prox(eh, ws, we):
    if ws <= eh <= we:
        return 100
    d = min(abs(eh - ws), abs(eh - we))
    if d <= 1: return 80
    if d <= 2: return 60
    if d <= 3: return 40
    return 20

return max(prox(start_hour, gm_start, gm_end),
           prox(start_hour, ge_start, ge_end))
```

# ── Claude Event Extraction ──────────────────────────────────────────────────

def extract_events(search_results, category, query):
today      = datetime.now()
future     = (today + timedelta(days=DAYS_AHEAD)).strftime(”%Y-%m-%d”)
organic    = search_results.get(“organic”, [])[:8]
results_tx = “\n\n”.join(
f”Title: {r.get(‘title’,’’)}\nURL: {r.get(‘link’,’’)}\nSnippet: {r.get(‘snippet’,’’)}”
for r in organic
)

```
prompt = f"""You are an event extraction assistant for a photography platform in Metro Detroit.
```

Category: {category}
Query used: {query}
Today: {today.strftime(”%Y-%m-%d”)}
Extract events between now and {future}.

Search results:
{results_tx}

Return ONLY a valid JSON array — no markdown, no backticks, no commentary.

Each event object fields:

- “title”: string
- “date”: “YYYY-MM-DD” or null
- “start_time”: “HH:MM” 24h or null
- “start_hour”: decimal float (e.g. 14.5) or null
- “end_time”: “HH:MM” or null
- “location”: string (venue or area)
- “address”: string or null
- “city”: string (Wayne County or Metro Detroit city)
- “category”: “{category}”
- “url”: string
- “description”: one sentence max
- “recurring”: boolean
- “parking”: “excellent”|“good”|“limited”|“poor”|null
- “estimated_attendance”: “low”|“medium”|“high”|“very_high”|null

Only include events that:

1. Are real and specific (not generic placeholders)
1. Are in Wayne County or Metro Detroit
1. Appear to be occurring within the next {DAYS_AHEAD} days

Return [] if nothing found.”””

```
try:
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    events = json.loads(text)
    return events if isinstance(events, list) else []
except Exception as e:
    print(f"  ⚠️  Claude extraction error: {e}")
    return []
```

# ── Scoring ──────────────────────────────────────────────────────────────────

ATTENDANCE_MAP = {“very_high”: 100, “high”: 75, “medium”: 50, “low”: 25}
PARKING_MAP    = {“excellent”: 100, “good”: 70, “limited”: 35, “poor”: 10}

KEYWORD_ATT = {
“tigers”: 90, “pistons”: 85, “red wings”: 88, “lions”: 93,
“marathon”: 80, “half marathon”: 75, “triathlon”: 70,
“festival”: 70, “fair”: 65, “expo”: 62, “parade”: 75,
“5k”: 60, “10k”: 62, “fun run”: 55,
“farmers market”: 45, “market”: 40,
“tournament”: 58, “championship”: 72, “open”: 50,
“concert”: 75, “pickleball”: 42, “charity”: 50,
}

def infer_attendance(title):
t = title.lower()
for kw, score in KEYWORD_ATT.items():
if kw in t:
return score
return 42

def infer_parking(title):
t = title.lower()
downtown = [“tigers”, “pistons”, “red wings”, “lions”, “comerica”, “little caesars”,
“ford field”, “fox theatre”, “downtown detroit”]
suburban = [“farmers market”, “dearborn”, “livonia”, “westland”, “garden city”,
“allen park”, “taylor”, “trenton”, “wyandotte”, “grosse pointe”]
if any(x in t for x in downtown): return 38
if any(x in t for x in suburban): return 68
return 55

def score_event(event, weather, gh_data):
s = {}
title = event.get(“title”, “”)

```
# Weather
s["weather"] = weather["weather_score"] if weather else 50

# Golden hour
s["golden_hour"] = gh_score(event.get("start_hour"), gh_data)

# Attendance
att = event.get("estimated_attendance")
s["attendance"] = ATTENDANCE_MAP.get(att, infer_attendance(title))

# Parking
park = event.get("parking")
s["parking"] = PARKING_MAP.get(park, infer_parking(title))

total = sum(s[k] * WEIGHTS.get(k, 0.25) for k in s)
return round(min(total, 100), 1), s
```

# ── HTML Generation ──────────────────────────────────────────────────────────

def score_color(n):
if n >= 78: return “#f5a623”
if n >= 58: return “#7ec8a4”
if n >= 40: return “#6b9fd4”
return “#888”

def score_tier(n):
if n >= 78: return “PRIORITY”
if n >= 58: return “STRONG”
if n >= 40: return “MONITOR”
return “SKIP”

def fmt_date(ds):
if not ds: return “Date TBD”
try:
return datetime.strptime(ds, “%Y-%m-%d”).strftime(”%a %b %-d”)
except:
return ds

def fmt_time(ts):
if not ts: return “”
try:
return datetime.strptime(ts, “%H:%M”).strftime(”%-I:%M %p”)
except:
return ts

def event_card(event, score, breakdown, gh_data, rank=None):
title    = event.get(“title”, “Unknown”)
date_str = fmt_date(event.get(“date”))
time_str = fmt_time(event.get(“start_time”, “”))
loc      = event.get(“location”, “”)
city     = event.get(“city”, “”)
desc     = event.get(“description”, “”)
url      = event.get(“url”, “#”)
weather  = event.get(”_weather”) or {}
recur    = “↺ Recurring” if event.get(“recurring”) else “”
color    = score_color(score)
tier     = score_tier(score)

```
rank_html = f'<div class="rank">#{rank}</div>' if rank else ""

weather_html = ""
if weather:
    weather_html = f"""
    <span class="pill weather">
      {weather.get('emoji','🌡️')} {weather.get('label','')} · {weather.get('temp_max_f','?')}°F
      {f"· 💨 {weather.get('wind_mph')} mph" if weather.get('wind_mph', 0) > 15 else ""}
    </span>"""

gh_html = ""
if gh_data:
    gh_html = f'<span class="pill golden">🌅 Golden Hour {gh_data.get("golden_evening_str","")}</span>'

bd_items = " &nbsp;·&nbsp; ".join(
    f'{k.replace("_"," ").title()} <b>{round(breakdown.get(k, 0))}</b>'
    for k in ["weather", "golden_hour", "attendance", "parking"]
)

loc_display = loc
if city and city.lower() not in loc.lower():
    loc_display = f"{loc}, {city}"

return f"""
```

<div class="card" data-score="{score}">
  {rank_html}
  <div class="score-col">
    <div class="score-ring" style="--c:{color}">
      <span class="score-num">{score}</span>
      <span class="score-tier" style="color:{color}">{tier}</span>
    </div>
  </div>
  <div class="card-body">
    <a class="card-title" href="{url}" target="_blank" rel="noopener">{title}</a>
    <div class="card-meta">
      {'📅 ' + date_str if date_str != 'Date TBD' else '📅 Date TBD'}
      {' · ⏰ ' + time_str if time_str else ''}
      {' · ' + recur if recur else ''}
      {(' · 📍 ' + loc_display) if loc_display else ''}
    </div>
    <div class="pills">
      {weather_html}
      {gh_html}
    </div>
    {f'<p class="desc">{desc}</p>' if desc else ''}
    <div class="breakdown">{bd_items}</div>
  </div>
</div>"""

def generate_html(events_with_scores, last_updated, gh_by_date):
# Sort all
ranked = sorted(events_with_scores, key=lambda x: x[1], reverse=True)
top3   = ranked[:3]

```
# Group by category
cats = {}
for ev, sc, bd in ranked:
    cat = ev.get("category", "Other")
    cats.setdefault(cat, []).append((ev, sc, bd))

cat_icons = {
    "Farmers Markets":     "🌾",
    "Sports Events":       "🏟️",
    "Festivals & Fairs":   "🎪",
    "Recreational Events": "🏃",
    "Other":               "📌",
}

top_cards = "".join(
    event_card(ev, sc, bd,
               gh_by_date.get(ev.get("date")),
               rank=i+1)
    for i, (ev, sc, bd) in enumerate(top3)
)

cat_sections = ""
for cat, items in cats.items():
    icon   = cat_icons.get(cat, "📌")
    cards  = "".join(
        event_card(ev, sc, bd, gh_by_date.get(ev.get("date")))
        for ev, sc, bd in items
    )
    cat_sections += f"""
```

<section class="cat-section">
  <h2 class="cat-heading">{icon} {cat} <span class="cat-count">{len(items)}</span></h2>
  {cards}
</section>"""

```
weights_row = "  ".join(
    f'{k.replace("_"," ").title()} <b>{round(v*100)}%</b>'
    for k, v in WEIGHTS.items()
)

total_events = len(events_with_scores)

return f"""<!DOCTYPE html>
```

<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ShotCart Scout — Wayne County</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#0a0a0a;
  --surface:#111;
  --surface2:#181818;
  --border:#222;
  --text:#e8e0d4;
  --muted:#5a5550;
  --accent:#f5a623;
  --accent2:#c8b08a;
  --green:#7ec8a4;
  --blue:#6b9fd4;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{
  background:var(--bg);
  color:var(--text);
  font-family:'DM Sans',sans-serif;
  font-weight:300;
  min-height:100vh;
  letter-spacing:0.01em;
}}

/* ── HEADER ── */
header{{
background:var(–bg);
border-bottom:1px solid var(–border);
padding:28px 40px 22px;
position:sticky;top:0;z-index:10;
backdrop-filter:blur(12px);
}}
.header-inner{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;max-width:960px;margin:0 auto}}
.wordmark{{
font-family:‘Playfair Display’,serif;
font-size:1.35rem;
font-weight:900;
color:var(–text);
letter-spacing:-0.01em;
}}
.wordmark em{{color:var(–accent);font-style:normal}}
.header-sub{{font-size:0.72rem;color:var(–muted);margin-top:3px;font-family:‘DM Mono’,monospace;letter-spacing:0.06em}}
.header-meta{{text-align:right}}
.updated{{font-size:0.7rem;color:var(–muted);font-family:‘DM Mono’,monospace}}
.weights{{
font-size:0.68rem;color:var(–muted);
font-family:‘DM Mono’,monospace;
margin-top:6px;
background:var(–surface);
border:1px solid var(–border);
padding:4px 10px;border-radius:4px;
letter-spacing:0.04em;
}}

/* ── MAIN ── */
main{{max-width:960px;margin:0 auto;padding:40px 24px 80px}}

/* ── TOP PICKS ── */
.top-picks{{
border:1px solid #2a2218;
background:linear-gradient(160deg,#131008 0%,#0d0d0d 100%);
border-radius:12px;
padding:28px 28px 20px;
margin-bottom:52px;
position:relative;
overflow:hidden;
}}
.top-picks::before{{
content:’’;
position:absolute;top:0;left:0;right:0;height:2px;
background:linear-gradient(90deg,transparent,var(–accent),transparent);
opacity:0.6;
}}
.section-label{{
font-family:‘DM Mono’,monospace;
font-size:0.68rem;
letter-spacing:0.14em;
color:var(–accent);
text-transform:uppercase;
margin-bottom:22px;
}}

/* ── CATEGORY ── */
.cat-section{{margin-bottom:48px}}
.cat-heading{{
font-family:‘Playfair Display’,serif;
font-size:1.05rem;
font-weight:700;
color:var(–accent2);
margin-bottom:18px;
padding-bottom:10px;
border-bottom:1px solid var(–border);
display:flex;align-items:center;gap:8px;
}}
.cat-count{{
font-family:‘DM Mono’,monospace;
font-size:0.7rem;
color:var(–muted);
font-weight:400;
margin-left:4px;
}}

/* ── CARD ── */
.card{{
background:var(–surface);
border:1px solid var(–border);
border-radius:10px;
padding:18px 20px;
margin-bottom:12px;
display:flex;
gap:18px;
position:relative;
transition:border-color .2s, transform .15s;
}}
.card:hover{{border-color:#333;transform:translateY(-1px)}}

.rank{{
position:absolute;top:-1px;right:16px;
background:var(–accent);
color:#000;
font-family:‘DM Mono’,monospace;
font-size:0.65rem;
font-weight:500;
padding:2px 8px;
border-radius:0 0 6px 6px;
letter-spacing:0.05em;
}}

/* ── SCORE RING ── */
.score-col{{flex-shrink:0;display:flex;align-items:flex-start;padding-top:2px}}
.score-ring{{
width:64px;height:64px;
border-radius:50%;
border:2.5px solid var(–c,#555);
display:flex;flex-direction:column;
align-items:center;justify-content:center;
background:var(–surface2);
flex-shrink:0;
}}
.score-num{{
font-family:‘DM Mono’,monospace;
font-size:1.25rem;
font-weight:500;
color:var(–text);
line-height:1;
}}
.score-tier{{
font-family:‘DM Mono’,monospace;
font-size:0.42rem;
letter-spacing:0.1em;
font-weight:500;
margin-top:2px;
text-transform:uppercase;
}}

/* ── CARD BODY ── */
.card-body{{flex:1;min-width:0}}
.card-title{{
font-size:0.97rem;
font-weight:500;
color:var(–text);
text-decoration:none;
display:block;
margin-bottom:5px;
line-height:1.4;
}}
.card-title:hover{{color:var(–accent)}}
.card-meta{{
font-size:0.75rem;
color:var(–muted);
margin-bottom:10px;
line-height:1.6;
font-family:‘DM Mono’,monospace;
letter-spacing:0.02em;
}}
.pills{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}}
.pill{{
font-size:0.72rem;
padding:3px 9px;
border-radius:20px;
border:1px solid var(–border);
color:var(–muted);
white-space:nowrap;
}}
.pill.weather{{border-color:#2a2a1a;background:#181810;color:#c8c080}}
.pill.golden{{border-color:#2a1f08;background:#160f02;color:var(–accent)}}
.desc{{font-size:0.78rem;color:#4a4540;margin:6px 0 8px;line-height:1.55}}
.breakdown{{
font-size:0.68rem;
color:var(–muted);
font-family:‘DM Mono’,monospace;
letter-spacing:0.03em;
}}
.breakdown b{{color:#6a6560}}

/* ── EMPTY ── */
.empty{{text-align:center;color:var(–muted);padding:48px;font-size:0.85rem;font-family:‘DM Mono’,monospace}}

/* ── FOOTER ── */
footer{{
border-top:1px solid var(–border);
padding:20px 40px;
text-align:center;
font-size:0.68rem;
color:var(–muted);
font-family:‘DM Mono’,monospace;
letter-spacing:0.04em;
}}

@media(max-width:580px){{
header{{padding:20px}}
main{{padding:24px 16px 60px}}
.card{{flex-direction:column;gap:12px}}
.score-ring{{width:52px;height:52px}}
.score-num{{font-size:1rem}}
}}
</style>

</head>
<body>

<header>
  <div class="header-inner">
    <div>
      <div class="wordmark">Shot<em>Cart</em> Scout</div>
      <div class="header-sub">WAYNE COUNTY &amp; METRO DETROIT &nbsp;·&nbsp; PHOTOGRAPHY OPPORTUNITY FINDER</div>
    </div>
    <div class="header-meta">
      <div class="updated">Updated {last_updated}</div>
      <div class="updated" style="margin-top:2px">{total_events} events · next run ~2 days</div>
      <div class="weights">Weights → {weights_row}</div>
    </div>
  </div>
</header>

<main>

  <div class="top-picks">
    <div class="section-label">⭐ &nbsp;Top Picks This Cycle</div>
    {top_cards if top_cards else '<div class="empty">No events found this cycle.</div>'}
  </div>

{cat_sections if cat_sections else ‘<div class="empty">No events discovered. Check back after the next scheduled run.</div>’}

</main>

<footer>ShotCart Scout &nbsp;·&nbsp; Runs every 2 days via GitHub Actions &nbsp;·&nbsp; Weather via Open-Meteo &nbsp;·&nbsp; Golden hour via Sunrise-Sunset.org</footer>

</body>
</html>"""

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
print(“📸 ShotCart Scout starting…\n”)
all_scored  = []
gh_by_date  = {}
today       = datetime.now().date()

```
for category, queries in QUERIES.items():
    print(f"── {category} ──")
    seen_titles = set()
    cat_events  = []

    for query in queries:
        print(f"  🔎  {query}")
        results = serper_search(query)
        events  = extract_events(results, category, query)
        print(f"      → {len(events)} events extracted")
        for ev in events:
            t = ev.get("title", "").lower().strip()
            if t and t not in seen_titles:
                seen_titles.add(t)
                cat_events.append(ev)

    for event in cat_events:
        date_str = event.get("date")
        location = (event.get("location") or event.get("city") or "Detroit") + ", Michigan"
        lat, lng = geocode(location)

        weather   = None
        gh_data   = None

        if date_str:
            try:
                ev_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if ev_date >= today:
                    weather = get_weather(lat, lng, date_str)
                    gh_data = get_golden_hour(lat, lng, date_str)
                    if gh_data and date_str not in gh_by_date:
                        gh_by_date[date_str] = gh_data
            except Exception:
                pass

        event["_weather"] = weather
        score, breakdown  = score_event(event, weather, gh_data)
        all_scored.append((event, score, breakdown))
        print(f"  ✅  {event.get('title','?')} — {score}")

    print()

last_updated = datetime.now().strftime("%B %-d, %Y  %-I:%M %p ET")
html = generate_html(all_scored, last_updated, gh_by_date)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"\n✅  index.html written — {len(all_scored)} total events scored.")
```

if **name** == “**main**”:
main()
