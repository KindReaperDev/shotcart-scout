# ShotCart Scout — Project Documentation

## What It Does
Finds and scores photography opportunities in Wayne County & Metro Detroit.
Runs every 2 days via GitHub Actions and publishes a scored dashboard to GitHub Pages.

## Live Dashboard
https://kindreaperdev.github.io/shotcart-scout/

## GitHub Repo
https://github.com/KindReaperDev/shotcart-scout

---

## Architecture

| Piece | Tool | Cost |
|---|---|---|
| Scheduler | GitHub Actions | Free |
| Agent brain | Anthropic API (Claude Haiku) | ~$1-2/month |
| Event discovery | Serper.dev (Google search API) | Free (2,500 queries/month) |
| Weather forecasts | Open-Meteo API | Free |
| Golden hour data | Sunrise-Sunset.org API | Free |
| Dashboard hosting | GitHub Pages | Free |

**Flow:** GitHub Actions wakes up every 2 days → `main.py` searches Serper for events → passes results to Claude Haiku to extract structured data → pulls weather + golden hour for each event → scores everything → writes `index.html` → commits to repo → GitHub Pages serves the dashboard.

---

## File Structure

```
shotcart-scout/
├── main.py               # Main agent script
├── config.json           # Editable scoring weights, filters, and search queries
├── index.html            # Auto-generated dashboard (do not edit manually)
├── SHOTCART_SCOUT.md     # This file — project documentation
├── ITERATION_NOTES.md    # Detailed changelog + future-expansion roadmap
└── .github/
    └── workflows/
        └── scout.yml     # GitHub Actions scheduler
```

---

## GitHub Secrets Required

Set in repo Settings → Secrets and variables → Actions:

| Secret Name | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key from console.anthropic.com |
| `SERPER_API_KEY` | Your Serper.dev API key from serper.dev |

---

## Editing the Scoring Weights

Open `config.json`. The four weights must always add up to 1.0.

```json
"scoring_weights": {
  "weather":     0.35,
  "golden_hour": 0.30,
  "attendance":  0.20,
  "parking":     0.15
}
```

---

## Editing Search Queries

Also in `config.json` under `search_queries`. Add, remove, or tweak any query string per category.

```json
"search_queries": {
  "Farmers Markets": [...],
  "Sports Events": [...],
  "Festivals & Fairs": [...],
  "Recreational Events": [...]
}
```

---

## Editing Location Filters

Several config fields control which events are accepted:

- `location_center` — lat/lng anchor for distance checks.
- `max_distance_miles` — geofence radius (default 60). Events further from center are dropped.
- `allowed_cities` — explicit allow-list of Metro Detroit / Wayne County, MI cities.
- `blocked_venues` — name fragments of out-of-area pro arenas/stadiums (Rocket Mortgage FieldHouse, etc.).
- `low_confidence_domains` — ticket-reseller domains (StubHub, Vivid Seats, etc.).
- `speculative_event_keywords` — playoff/finals language used to drop reseller-pre-listed games when paired with a low-confidence domain.

---

## Top Picks Window

- `top_picks_window_days` (default 5) — Top Picks only includes events within this window AND with complete weather + golden-hour data. Adjust if you want a tighter or looser near-term focus.
- `days_ahead` (default 30) — outer horizon for event extraction. Events past this don't get pulled.

---

## Scoring System

Each event is scored 0-100 across four factors:

**Weather (35%)** — Based on WMO weather codes from Open-Meteo. Clear sky = 100, thunderstorm = 0. Overcast scores 72 (soft diffuse light is great for portraits). Temperature bonus applied for 55-85°F.

**Golden Hour (30%)** — Proximity of event start time to sunrise/sunset golden hour windows. Exact match = 100, within 1hr = 80, within 2hrs = 60, etc. Unknown time = 50 (neutral).

**Attendance (20%)** — Inferred from event type keywords (Tigers/Lions = 90+, festivals = 70, farmers markets = 45) or from Claude's extracted estimated_attendance field.

**Parking (15%)** — Inferred from venue type. Downtown Detroit venues score lower (~38), suburban venues score higher (~68).

### Proximity Multiplier

After the weighted sum, the score is multiplied by a proximity factor based on how soon the event is:

| Days from today | Multiplier |
|---|---|
| 0–3 | ×1.10 |
| 4–7 | ×1.00 |
| 8–14 | ×0.92 |
| 15–21 | ×0.85 |
| 22+ | ×0.78 |

Capped at 100. This keeps the user-facing weights clean while ensuring near-term events outrank weak-signal far-future ones.

### Score Tiers

| Score | Label |
|---|---|
| 78-100 | PRIORITY |
| 58-77 | STRONG |
| 40-57 | MONITOR |
| 0-39 | SKIP |

---

## Triggering a Manual Run

1. Go to your GitHub repo
2. Click the Actions tab
3. Click ShotCart Event Scout in the left sidebar
4. Click Run workflow

Run takes approximately 3 minutes.

---

## Quality Filters (applied before scoring)

The May 2026 hardening pass added several filtering layers — see `ITERATION_NOTES.md` for the full story. Brief overview:

1. **Placeholder titles** — rejects "vs opponent", "vs TBA", "at TBA", and any `<Detroit team> at <anything>` (always an away game).
2. **City allow-list** — events whose `city` field isn't in `allowed_cities` are dropped.
3. **Blocked venues** — any event whose venue name fragment matches `blocked_venues` is dropped (catches out-of-area pro arenas regardless of how the LLM labels the city).
4. **Distance check** — events geocoded further than `max_distance_miles` from `location_center` are dropped.
5. **Reseller speculative listings** — events from `low_confidence_domains` whose title contains a `speculative_event_keyword` (playoff/Game N/finals/etc.) are dropped.
6. **Past-date guard** — events whose resolved date is in the past are dropped.

Events that pass all filters but lack a confirmable date are routed to a separate "Unconfirmed Dates" section at the bottom of the dashboard (excluded from Top Picks and ranked category lists).

---

## Useful Claude Code Prompts for Future Edits

- "Update the scoring weights in config.json to weight attendance more heavily"
- "Add a new search query category for outdoor concerts"
- "Add email notifications when a PRIORITY event is found"
- "Make the dashboard show a 7-day weather forecast instead of just the event day"
- "Add a filter to only show events happening on weekends"

---

## Future ShotCart Platform Integration

This scout tool is the prototype for a future ShotCart platform feature: a built-in event scoring/discovery feed for photographers. The scoring logic (weather + golden hour + attendance + parking) would pre-populate suggested high-value events for photographers based on their location and preferences. Reference this project when building that feature.

---

## Technical Notes

- Model: `claude-haiku-4-5-20251001`
- All files (`main.py`, `config.json`, `.github/workflows/scout.yml`) are tracked in the repo and edited directly. The earlier `MAIN_PY_B64` secret indirection was removed in May 2026.
- GitHub Pages serves from the root of the main branch.
- The workflow runs at 9am ET every 2 days (cron: `0 13 */2 * *`).
- The dashboard push step pull-rebases against `main` before pushing, with up to 3 retries — avoids race conditions when a manual push lands during a workflow run.

---

## Expanding to Other Metro Areas

The scout is currently single-region. For a step-by-step path to multi-metro support — what already generalizes (weather, golden hour, scoring, recurring-date logic) and what's still Detroit-specific (team keywords, parking heuristics, prompt framing) — see `ITERATION_NOTES.md`.
