# ShotCart Scout — Iteration Notes

Reference for the May 2026 hardening pass. Captures what changed, why, and what to consider for future expansion to other metro areas.

---

## What changed in this iteration

### Bug fixes

**1. Out-of-area events leaked into the dashboard.**
"Detroit Pistons vs Cleveland Cavaliers" at Rocket Mortgage FieldHouse and a Wayne County, Indiana 5K were appearing as if they were local Detroit events.

Fixed via four independent layers in `main.py`:
- `allowed_cities` allow-list in `config.json` — 40+ Metro Detroit / Wayne County, MI cities including Ann Arbor.
- `blocked_venues` deny-list — out-of-area pro arenas (Rocket Mortgage FieldHouse, Fiserv Forum, etc.) keyword-matched against title/venue/address.
- Haversine distance check vs `location_center` with `max_distance_miles=60` as a structural backstop.
- Stronger Claude prompt with explicit reject examples: Wayne County IN/NY/OH, "<Detroit team> at <opponent>" = away game.

**2. Most events showed "Date TBD".**
Farmers markets and recurring events with known weekly cadence had no concrete date.

Fixed via `resolve_recurring_date()` which:
1. Parses the LLM-extracted `recurrence_pattern` field (e.g., "Saturdays 9am–3pm May through October").
2. Falls back to scanning the event title and description for weekday names when no pattern is provided.
3. Computes the next concrete occurrence within `days_ahead`, respecting any season window.

Events that remain date-less after this step are quarantined into a separate "Unconfirmed Dates" section at the bottom of the dashboard rather than mixed into Top Picks.

**3. Speculative reseller playoff listings.**
StubHub, Vivid Seats, SeatGeek and similar sites pre-list hypothetical playoff games with placeholder 1:00 PM tip-offs before brackets are decided. The LLM was taking these at face value.

Fixed via `is_speculative_reseller_event()` — drops events whose URL is from a known reseller domain AND whose title or description references playoffs / conference finals / "Game N" / World Series / Stanley Cup. Both the post-extraction filter and an explicit prompt rule are in place.

**4. "Detroit X at TBA" away-game placeholders.**
The word "at" in a sports title indicates an away game. A Detroit team "at" anywhere is not local.

Fixed in `is_placeholder_title()` — any title matching `<Detroit team> at <anything>` is rejected, regardless of how the LLM tagged the city.

### Behavior changes

**Top Picks is date-windowed.**
Header reads "Top Picks · Next 5 Days" (configurable via `top_picks_window_days`). Eligibility requires a confirmed date in the window AND real weather + golden-hour data. A high-scoring event 25 days out cannot appear in Top Picks.

**Category sections sort by date ascending.**
Sports / Festivals / Markets list events nearest-date first. Previously they followed the order returned by source pages, which for MLB schedule landing pages was reverse-chronological.

**Proximity multiplier on the final score.**
After the weighted sum of weather / golden hour / attendance / parking, the score is multiplied by a proximity factor: 0–3 days ×1.10, 4–7 ×1.00, 8–14 ×0.92, 15–21 ×0.85, 22+ ×0.78. Capped at 100. The four user-facing weights stay clean and unchanged.

**Honest breakdown display.**
When weather data isn't available (event is beyond Open-Meteo's ~16-day forecast horizon) or golden hour can't be computed (no start time), the breakdown shows `—` instead of a fake 50. The fake 50 still flows through scoring as a neutral fallback, but the display is now truthful.

**Broader Recreational Events queries.**
Expanded from athletics-only to outdoor concerts, classic-car cruises (Woodward Dream Cruise), Belle Isle and Riverfront events, fireworks, outdoor movie nights, holiday markets, kite/balloon festivals, pet/community gatherings. 29 total queries across all categories (was 17).

### Workflow / infra

- Removed `MAIN_PY_B64` secret indirection in `.github/workflows/scout.yml`. The workflow now runs the committed `main.py` directly — single source of truth, visible in PR diffs.
- Workflow pull-rebases against `main` before pushing the dashboard, with 3 retries. Fixes the race condition where a manual push during a workflow run caused the dashboard commit to be rejected with "fetch first".

---

## Future expansion: other metro areas

The scout is currently single-region. Region parameters live in `config.json`:

- `location_center` — geocoded lat/lng of the metro
- `max_distance_miles` — geofence radius
- `allowed_cities` — region-specific allow-list
- `blocked_venues` — out-of-region pro venues (largely universal)
- `search_queries` — region-specific (city names, team names, neighborhoods)

To add a new metro (Chicago, Twin Cities, Phoenix, etc.), the cleanest path:

**Step 1 — multi-config.** Replace the single `config.json` with a `regions/` directory containing one config per metro. Pass the active region as a workflow input or env var. Each region produces its own `index.html` (e.g., `regions/chicago/index.html`) and gets served at a distinct path under GitHub Pages.

**Step 2 — region-aware Claude prompt.** The current prompt hardcodes "Wayne County and Metro Detroit, MICHIGAN ONLY." Promote that string to a `region_name` config field so the LLM gets the right framing per region. Reject examples (e.g., "Wayne County, IN") will need to be region-appropriate.

**Step 3 — shared deny-list.** `blocked_venues` is largely universal — any pro stadium not in the active region qualifies. Promote it to a shared file, then strip the active region's own home venues at load time.

**Step 4 — multi-region landing page.** A single root `index.html` linking out to each region's dashboard.

**Things that already generalize without changes:**
- Open-Meteo geocoding and weather: global.
- Sunrise-Sunset golden hour: global.
- Scoring math and proximity multiplier: region-agnostic.
- Reseller speculative-listing filter: domains are league-agnostic.
- Recurring date resolution: weekday/month parsing has no region dependency.

**Things that don't generalize as-is:**
- `KEYWORD_ATT` (attendance inference) and `DETROIT_TEAMS` lists are Detroit-specific. Move into the region config or derive from a team list.
- `infer_parking()` hardcodes Detroit downtown/suburban heuristics. Generalize via region-defined `downtown_keywords` / `suburban_keywords`.
- Category icons in `generate_html()` are fine as-is, but a region may want a localized category set (e.g., a beach city would want "Coastal Events").

**Cost note:** each region multiplies API usage. Current setup is well under free tiers (29 queries × ~15 runs/month ≈ 435 Serper calls/month against a 2,500/month free quota). A four-region rollout would still fit comfortably.
