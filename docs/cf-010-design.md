# CF-010 airport map — design spec (draft for owner approval)

**Status:** r3, **approved by the owner 2026-11-11** (decisions M1–M6, §9; revised after the Codex design critique of r2, §11).

**Sources:**
- Plan v1.1 §5 CF-010. Exit: desktop/mobile e2e with axe, no polling in background tabs, honest empty/limit states.
- Plan §8 (data licences), §7 gates; D-008 (frontend contract and ageing), D-012 (positions).
- RQ-003 (map tiles; local research note, 2026-11-11).

## 1. What the user gets
On each airport page, below the forecast, a **"Live map"** section:
- **Basemap:** centred on the airport, showing the 25 nm area used for aircraft (the circle drawn faintly).
- **Aircraft layer:** live positions from `/aircraft`.
  - A plane symbol rotated to its track: filled when airborne, outlined on the ground, and a distinct dotted outline for `unclassified` targets.
  - Selecting one shows callsign, altitude, ground speed, distance and the position's age.
  - Each position disappears at its `expires_at`.
- **Weather layer:** **observed** conditions at the airport and at nearby reporting airports (§4).
  - A marker with the conditions index **number and level word**, never colour alone.
  - Selecting one shows the station, observation time and index.
  - Labelled "Observed weather", per plan §7: the observed and forecast indices are kept visually distinct.
- **Status line:** source, counts and freshness, e.g. "42 aircraft · adsb.lol · updated 12 s ago". It also covers the honest states:
  - no aircraft;
  - coverage unknown;
  - limit reached;
  - provider disabled;
  - map unavailable (tile or WebGL failure).
- **Attribution, always visible:** © OpenMapTiles © OpenStreetMap contributors (basemap), plus the aircraft source (adsb.lol ODbL / OpenSky), NOAA AWC, and RainViewer when radar is shown.
- **Accessible alternative:** an "Aircraft and weather near {airport}" list below the map, a table of the same data. Keyboard and screen-reader users get everything without the canvas. The map itself is keyboard-pannable and zoomable, with a skip link past it.
- **Disclaimer:** "Positions from volunteer receivers; coverage is incomplete and delayed. Not for navigation."

## 2. Basemap and library (RQ-003)
- **Basemap:** **OpenFreeMap** vector tiles (`https://tiles.openfreemap.org/styles/positron`, light and low clutter, so weather and aircraft stand out).
  - Free, with no key, no view limits and commercial use allowed.
  - No cookies; logs exclude IPs by default and are deleted after 7 days; may use Cloudflare.
  - No SLA.
  - The style URL is configurable (`VITE_MAP_STYLE_URL`), so the source can be swapped, for example to self-hosted PMTiles at CF-006.
- **Library:** **MapLibre GL JS 6.16.0** (BSD-3; the newest release at least 14 days old), pinned exactly.
  - It's **lazy-loaded** (dynamic import) only when the map section scrolls near the viewport, so the rest of the page isn't slowed down.
  - It's added to the npm audit gate.
- **Privacy:** loading the map sends the visitor's IP and the viewed area to OpenFreeMap (and Cloudflare).
  - The map does **not** auto-load tiles until the section is near the viewport.
  - A one-line note under the map says where the tiles come from.
  - No other third parties are involved, and no API keys reach the browser.

## 3. Aircraft layer
- **Source:** the existing `GET /v1/airports/{code}/aircraft` (CF-009). No backend change.
- **Polling, only while useful** (plan §5 exit; P6):
  - every **30 s** (the server's cache period) while the tab is visible **and** the map section is on screen (IntersectionObserver);
  - stopped otherwise;
  - resumed on return, with an immediate refresh if the data is older than 30 s;
  - manual refresh, with a 30 s cooldown.
- **Ageing on screen** (the D-008 pattern) [r3: critique 1]:
  - Each aircraft is removed at its `expires_at`, even while refreshes fail.
  - A **state claim also expires**: `no_aircraft` and `coverage_unknown` are valid only until `observed_at` + 60 s (CF-009 §7), and `quota_exhausted` until its `retry_at`.
  - After that, while refreshes fail, the status becomes "Live positions couldn't be updated", never a stale "No aircraft".
  - When every position has expired, the status says so.
- **Every request path is gated by "active"** (tab visible **and** map on screen) [r3: critique 3]. That covers the first load, interval refreshes, resume, manual refresh, and the scheduled 503 retry.
  - A retry or refresh that comes due while inactive is **deferred**, not sent. It runs on becoming active again, if still due.
  - The polling hook gains an `active` input. The conditions and forecast hooks keep their current behaviour (always active).
- **States from `data_status`:**
  - **available:** as above;
  - **no_aircraft:** "No aircraft reported within 25 nm";
  - **coverage_unknown:** "Can't confirm traffic near this airport" plus the reason;
  - **quota_exhausted:** "Live positions limit reached; try again after HH:MM";
  - **unavailable:** "Live positions aren't available"; with `provider_disabled`, nothing more is said.
  - **Errors:** a 502/503/504 shows a short failure note, while the map and weather stay.
- `withheld`/`excluded` counts are shown in the list's caption, e.g. "3 aircraft not shown for privacy".

## 4. Weather layer: nearby observed conditions (new endpoint)
`GET /v1/airports/{code}/nearby-conditions`: the observed conditions at reporting stations within **R = 50 nm** (**[M3]**), including the airport itself.
- **Data:** one AWC METAR **bbox** query for the area (spec: `bbox` = lat0,lon0,lat1,lon1; at most 400 results; 100 requests per minute), filtered by true distance, through the existing METAR adapter's rate cap, retries and typed errors. [r3: critique 4]:
  - **Adapter extension:** `fetch_metar_records` gains a `params` argument (`bbox` instead of `ids`). A new `parse_nearby(records, area, now)` reuses the per-record parser (`select_observation` logic) and reads the record's `lat`/`lon`.
  - **Validation:** a record whose coordinates are missing or out of range, or whose station doesn't match the 4-character pattern, is **dropped and counted** (`dropped`).
  - **Deduplication:** one entry per station, the latest valid observation.
  - **Completeness:** if AWC returns 400 records (its cap), the response sets `complete: false`, and the UI says "Some nearby stations may be missing".
  - **The airport itself** isn't taken from this query. Its marker uses the page's own `/conditions` data, so a capped or partial bbox answer can never hide it.
  - **States:** an empty upstream answer → `no_stations`; a non-empty answer with nothing usable → `unavailable` / `unusable_data`.
- **Per station:** `station`, `name` (from the catalogue when known), `latitude`, `longitude`, `distance_nm`, `observed_at`, `current_until`, `stale_until`, and `conditions` (the observed index v0.1, D-007, wording unchanged).
  - **Freshness:** the same as `/conditions` (D-007). Stale stations are shown greyed, labelled "old report", and **not scored**; expired ones are dropped.
- **Cache:** per airport for **10 min**. An empty answer → `no_stations`, cached 5 min.
  - **D-007's stale-CDN rule** [r3: critique 6]: if **every** usable station in the answer is already stale when fetched (the signature of a stale CDN response), the result is cached for **60 s** instead, so it recovers quickly. Individual stale stations are normal and don't shorten the cache.
- **Frontend:** stations age on screen by `current_until`/`stale_until`, as on the conditions card. Refreshed every 10 min while visible, and with the manual refresh.
- **No forecast on the map** in CF-010; the forecast stays in its own section (§7 gate).

## 5. Radar overlay (gated; owner decision M4)
RainViewer's Weather Maps API allows "personal and educational use only", with attribution and no SLA. So, like OpenSky (P4), it runs only behind a licence gate.
- **Gate:** `RAINVIEWER_EDUCATIONAL_USE` (default **false**). The **backend** owns it; the browser never decides.
  - When it's off, the API reports `radar.enabled: false` and the UI shows no radar control at all.
  - CF-006 checks it's false in production unless a licence or another source exists.
- **Backend:** `GET /v1/map/radar` returns the radar frames.
  - **Index:** the backend fetches `https://api.rainviewer.com/public/weather-maps.json` through the bounded async HTTP client (D-012 §5) and caches it for **5 min**.
  - **Trust boundary, validated before anything reaches the browser:**
    - `host` must be exactly `https://tilecache.rainviewer.com`;
    - each `radar.past[].path` must match `^/v2/radar/[A-Za-z0-9]+$`;
    - `time` must be a sane epoch within the last 3 h.
    
    Anything else gives `unavailable` / `invalid_index`, so the browser is never pointed at another host.
  - **Response** [r3: critique 2]: `{ enabled: bool, data_status: "available" | "unavailable", unavailable_reason: null | "provider_disabled" | "invalid_index" | "no_frames", frame: { time, tile_url } | null, current_until, attribution }`.
    - **Gate off** → `enabled: false`, `data_status: "unavailable"`, `unavailable_reason: "provider_disabled"`, and nothing is fetched.
    - **Invalid index** → `invalid_index`; **no frames** → `no_frames`. Both are 200 with `enabled: true`, so the UI can tell failure from disabled.
    - Only the **latest valid frame** is returned (no animation in CF-010).
    - `tile_url` is a template: `{host}{path}/256/{z}/{x}/{y}/2/1_0.png` (colour scheme 2, smoothed, no snow split). `current_until` is that frame's time plus 20 min.
    - Provider failures map to 502/503/504, as elsewhere.
    - Runtime schema and recorded fixtures on both sides (D-008), like the other endpoints.
  - **Request budget** [r3: critique 5]:
    - a process rate cap of **6 index fetches per minute** (token bucket);
    - **single-flight** with the CF-009 Redis owner-token lock (waiters read the cache);
    - after a failure, a **negative cache for 60 s** (`radar:failed`), so an outage costs at most one fetch per minute per process;
    - without Redis it degrades like a keyless provider (capped, uncached).
- **Frontend:**
  - A **"Radar (observed)"** toggle, **off by default**. No RainViewer request is made until the visitor turns it on, since turning it on sends their IP and the viewed area to RainViewer.
  - When on, the **latest past frame** is shown as a raster layer at 60% opacity, under the aircraft and weather markers.
  - **Labelling:** frame time and "coarse at this zoom". Tiles stop at zoom 7, so at airport zoom radar is upscaled and approximate.
  - **Ageing:** the frame is hidden after its `current_until`, even if refreshes fail. The frame list is refreshed every 5 min while the map is active.
  - **Attribution** when shown: "Radar © RainViewer" with a link.
  - No animation in CF-010.
- **States:** disabled (no control), unavailable (the toggle shows "Radar unavailable"), and stale (hidden, with a note).

## 6. Frontend structure
- `components/AirportMap.tsx`:
  - lazy-loads `MapView` (MapLibre);
  - owns the IntersectionObserver;
  - renders the status line, attribution note, list, and states.
- `hooks/useAircraft.ts` and `hooks/useNearbyConditions.ts`: built on the existing polling hook (`useAirportData`), extended with "active" (visible and on screen) and per-hook intervals.
- **Layers:** MapLibre GeoJSON sources with symbol layers. The plane icon is an SDF image rotated by `track_deg`, with weather markers as text labels.
  - Aircraft and weather data are kept in React state and pushed to the map; the map holds no state of its own.
- **Contract:** runtime schemas and types for `/aircraft`, `/nearby-conditions` and `/map/radar`, with recorded fixtures checked on both sides (D-008).

## 7. Failure and degraded modes
- **No WebGL**, or a style/tile failure: the map area shows "The map couldn't load", and **the list still works**. Data polling continues only while the section is on screen.
- **Tile provider down:** the same, with a retry button.
- **Slow networks:** the map loads only near the viewport, and the list renders first.

## 8. Tests
- **Backend `/map/radar`:**
  - the gate (off → `enabled: false`, nothing fetched);
  - index validation (wrong host, bad path, odd times → `invalid_index`);
  - the cache, ageing and errors.
- **Backend `/nearby-conditions`:**
  - the bbox query and distance filter;
  - freshness (stale, expired);
  - the cache and the no-stations case;
  - errors and the rate cap;
  - the response model and fixtures.
- **r3 additions:**
  - `no_aircraft` expiry while refreshes fail;
  - 503 → hide → Retry-After elapses → **no request**, then show → the retry runs;
  - nearby: capped response, duplicates, bad coordinates, all-stale (60 s cache);
  - radar: the response states, the rate cap, single-flight and the negative cache.
- **Frontend unit:**
  - the hooks (active only while visible and on screen; intervals; cooldown; expiry of aircraft and weather);
  - the states and texts;
  - the list;
  - contract tests.
  
  MapLibre is mocked in unit tests.
- **e2e (desktop and mobile, with axe):**
  - the map section with fixtures, and tiles **stubbed by Playwright routing**, so no external requests;
  - the list has the same data;
  - **no `/aircraft` requests while the tab is hidden or the map is off screen** (request counting);
  - the honest states;
  - no horizontal scroll;
  - keyboard: a skip link past the map, with the list reachable.

## 9. Owner decisions (2026-11-11)
| # | Decision | Chosen |
|---|---|---|
| M1 | Basemap | **OpenFreeMap** (free, no key, commercial allowed, privacy-light), with a configurable style URL; self-host later if needed |
| M2 | Where the map lives | **A section on the airport page** (below the forecast), lazy-loaded; not a separate page |
| M3 | Weather layer | **Nearby observed conditions within 50 nm** (a new endpoint, one AWC bbox call per airport every 10 min), plus the airport itself |
| M4 | Radar | **Gated RainViewer radar** (owner's choice; the recommendation was "not now"): `RAINVIEWER_EDUCATIONAL_USE` defaults to false; the backend validates the index; an off-by-default toggle; latest frame only, labelled coarse (§5) |
| M5 | Aircraft polling | **Every 30 s only while the tab is visible and the map is on screen**, plus manual refresh (30 s cooldown) |
| M6 | Accessible list | **Always show the aircraft and weather list below the map** (not hidden behind a toggle) |

## 10. Out of scope
- Movements (CF-011) and disruption (CF-012).
- Flight lookup (CF-013).
- Radar animation, nowcast and satellite.
- Forecast on the map.
- Self-hosted tiles (CF-006).
- Map clustering.
- Historical tracks or trails.

## 11. Design critique (CORMORANT, r2 → r3)
Codex critique of the frozen r2 (2026-11-11): 2 High and 3 Medium, all confirmed, none refuted, plus one constraint conflict.
1. **`no_aircraft` had no expiry.** Fixed: state claims expire (`observed_at` + 60 s; `retry_at`).
2. **The radar response couldn't express its failures, and wasn't in the contract.** Fixed: `data_status`/reason, a single frame, schema and fixtures.
3. **Visibility gating missed the initial and 503-retry paths.** Fixed: every request path is gated, and due work is deferred while inactive, with a test.
4. **Nearby completeness and validation were unspecified.** Fixed: the adapter extension, validation, deduplication, `complete: false` at the cap, and the airport taken from `/conditions`.
5. **No radar request budget.** Fixed: a rate cap, single-flight and a 60 s negative cache.
6. **Constraint conflict, D-007's 60 s cache for stale-at-fetch data.** Resolved: applied when every station is stale. Recorded for the owner at approval.
