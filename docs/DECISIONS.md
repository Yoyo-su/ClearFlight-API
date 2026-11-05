# Decisions log

Record technical and product decisions that constrain future work. Add new entries at the top. Each entry needs a date, the decision, the reason and a source (plan section, PR or issue). Do not record decisions here that have not actually been made.

Locked pilot decisions live in [development-plan.md §1](development-plan.md) and are not repeated here. Changing them requires a plan version increment (plan §11 change policy).

## Format

```markdown
### D-NNN: <title> (YYYY-MM-DD)
- **Decision:**
- **Why:**
- **Alternatives considered:**
- **Source:** PR #/issue #/plan §
- **Status:** accepted | superseded by D-NNN
```

## Entries

### D-009: Search ranks airports with scheduled service higher; "6+" visibility is 10 km; full zone names (2026-11-05)
- **Decision:**
  - **Snapshot (amends D-005):** the snapshot gains a `scheduled` column ("yes"/"no", from OurAirports' `scheduled_service`).
  - **Search order:** exact code match; then airports with scheduled airline service before those without; then the match tier (name/city prefix, word prefix, substring); then size, then name.
  - **"6+" visibility (amends D-006):** when the provider sends "6+" and the raw report contains a metric `9999` or `CAVOK` (10 km or more), the adapter reports 10,000 m with `visibility_at_least`. Any other "6+" (e.g. a North American `P6SM`, more than 6 SM) stays at 6 SM, about 9,656 m, "at least". Scores don't change (≥ 8000 m scores 0).
  - **Zone names (refines D-008):** the frontend shows the browser's abbreviation when it has a real one ("GMT", "BST", "EDT", "WET"), otherwise the full name ("Japan Standard Time"), and only an offset when the browser knows no name.
- **Why:** Owner cleanup list 2026-11-04:
  - "kennedy" ranked a small Canadian airport above JFK, and "paris" put the business-only Le Bourget before Orly; travellers search for airports they can fly to.
  - A European "9999" report read as "9.7 km or more".
  - London showed as "UTC+0" in the smoke test. That turned out to be Playwright's headless Chromium, which ships without zone names; full browsers show "GMT". The fallback still helps where a browser has no abbreviation: "Japan Standard Time (UTC+9)" instead of only "UTC+9". Guessing "GMT" for every UTC+0 zone would be wrong for Lisbon (WET).
- **Alternatives considered:**
  - Scheduled service as a tie-break within a match tier only. Implemented first, but it didn't fix "kennedy": Gahcho Kue's city "Kennedy Lake" is a prefix match.
  - A passenger-volume ranking (no data source).
  - Always the long zone name (longer on phones).
- **Source:** cleanup PR 2; snapshot regenerated from the 2026-11-05 OurAirports export (11,260 airports, +9 since 2026-10-30; 4,074 with scheduled service).
- **Status:** accepted 2026-11-05. The owner chose the cleanup items; the change in ranking rule from "within a tier" to "ahead of tiers" was made during implementation and is flagged for owner review in the PR.

### D-008: Frontend MVP design and the API ageing fields (2026-11-03)
- **Decision:** The CF-005 frontend follows `docs/cf-005-design.md` r3 with the owner's choices:
  - **D1:** both unit systems, metric first, no toggle.
  - **D2:** level colours slate blue / amber / orange / red, plus grey dashed for unknown. No green anywhere, and the number and level word always appear together.
  - **D3:** search as you type (2+ characters, 250 ms).
  - **D4:** auto-refresh every 5 minutes while visible, plus a Refresh button with a 60 s cooldown. A failed refresh keeps the last good data.
  - **D5:** pilot airports plus browser-only "recently viewed"; a site-wide "popular" list is deferred.
  - **D6:** the "calm instrument panel" look, with a redesign earmarked.
  - **D7:** `frontend/` in this repo.
  - **D8:** the URL is rewritten to the API's canonical `airport.code`.
  - **D9:** react-router.
  - **D10:** an 80% frontend coverage gate.
  - **D11:** the v1 conditions response adds `current_until` and `stale_until`, computed from the backend's thresholds (still the single freshness authority, D-007). The page withdraws the score after `current_until` and hides the values after `stale_until`, even while refreshes fail or after a background tab returns.
  - **Request ownership:** every request, retry and timer belongs to the airport on screen and is cancelled when leaving it; late responses are ignored.
  - **Contract:** recorded fixtures are checked against the Pydantic models (backend) and against a runtime schema in `frontend/src/api/` (frontend). The TypeScript types are derived from that schema, and the client validates every response with it, so field names, value types, nullability and enums can't drift. A malformed 200 is treated as a failure (`invalid_response`); during a refresh, the last good data is kept.
  - **Checks:** `make run-checks` stays Python-only; `make frontend-checks` runs in separate CI and release jobs. `npm audit` allows no runtime advisories and nothing high or above anywhere. A moderate `minimatch` advisory in the lint tooling, which isn't shipped, is accepted until upstream fixes it.
  - **Packages** are pinned exactly, at the newest release at least two weeks old (TypeScript 6.0.3: typescript-eslint 8.71 doesn't support TypeScript 7).
- **Why:** Plan §1–2 and §7 (mobile-first, accessible, no misleading safety/delay claims, honest unknown/stale states, shareable URLs). The owner chose each option in a walkthrough. The design critique (CORMORANT) found data that outlived its eligibility (High), the IATA-only canonical-URL case, an inaccurate cost note, contract drift, CI callers, and request ownership; all are addressed.
- **Alternatives considered:** a units toggle; traffic-light colours; search on submit; manual-only refresh; a separate frontend repo; a hand-written router; re-fetching at each age boundary instead of D11 (would blank the page during an outage).
- **Source:** CF-005 (issue #6); spec r3 and critique in `~/codex-reviews/clearflight-cf005-design/`; owner walkthrough 2026-11-03.
- **Status:** accepted 2026-11-03 by project owner, including the `npm audit` gate thresholds (approved 2026-11-03 after implementation).

### D-007: v1 conditions contract and conditions index v0.1 (2026-11-02)
- **Decision:**
  - **Route:** `GET /v1/airports/{code}/conditions` takes IATA (3 letters) or ICAO (4 alphanumerics) in any case. Anything else is `400 invalid_code`; an unknown airport is `404 airport_not_found`.
  - **Response:** `airport`, `observation`, `conditions`, `data_status`, `unavailable_reason`, `last_observed_at` (models in `app/api/models.py`).
  - **Freshness:** one authority, `metar.freshness`, with the configurable thresholds and one clock per request. `current` is scored; `stale` is shown but not scored.
  - **Unavailable:** older than the stale limit gives `unavailable` / `observation_too_old` with `observation: null` and `last_observed_at`. No report gives `no_report`. An airport without ICAO gives `no_metar_station`. All are `200`.
  - **Provider failures** follow D-006: 504 `provider_timeout`, 502 `provider_error`, 503 `rate_limited` with Retry-After. Error bodies are `{"detail", "reason"}`.
  - **Index v0.1:** the maximum of four components, with bands as in the README.
    - Wind uses the higher of speed and gust.
    - Visibility breakpoints are 8000 / 4800 / 1600 / 800 m (the common 5 / 3 / 1 statute-mile flight-category breakpoints, used only as severity bands), with a 10 m tolerance for AWC's mile rounding.
    - Ceiling breakpoints are 3000 / 1000 / 500 / 200 ft.
    - Weather groups are parsed as intensity + descriptor + phenomena. BL with SN/SA/DU scores 3, and DR (low drifting) is treated like mist, scoring 0. SG, IC and UP score with rain, as in plan r2.
  - **Score rules:** a score needs a current observation with known wind, visibility, ceiling and weather, except that known components already at 10 give 10. Levels: low 0–2, moderate 3–5, high 6–7, severe 8–10, unknown.
    - **Unrecognised weather group:** the weather factor is unknown (owner decision, 2026-11-02, after review; this replaces plan r2's "scores 0"). Groups are captured for later scoring: logged, and counted once per observation in Redis (`conditions:unrecognised_wx:counts` / `:examples`, no expiry). `scripts/unrecognised_weather.py` lists them.
    - **Gust without a sustained speed:** a gust ≥ 50 kt gives the wind factor 10; otherwise wind is unknown.
    - `age_minutes` is rounded up, so it never looks fresher than `data_status`.
  - **Adapter change (amends D-006):** an observation that isn't current when fetched is cached for 60 s instead of 600 s. On 2026-11-02, AWC's CDN served a 3-hour-old RJBB report although a newer one had been received 12 minutes earlier.
  - **Wording:** generated text never claims safety, delays or forecasts (tested). A fixed disclaimer is always included.
  - **Other routes:** `GET /health` added. The legacy `/airport/{code}` stays unchanged and deprecated, and is removed in CF-006.
  - **CF-001 carry-over:** the legacy provider cache keys now hash a key-free string.
- **Why:** Plan §3, §4 and §7 (stable contract; deterministic scoring; stale or missing data never presented as low). Taking the maximum avoids diluting a single severe factor. The max-10 exception scores dense fog honestly without ever producing a reassuring number from missing data. Expired values are withheld so old numbers can't be read as current. The design critique (CORMORANT case 3) found the weather-parsing ambiguity, the risk of two freshness authorities, the untestable Redis gate and a credential test that couldn't prove anything; all are fixed.
- **Alternatives considered:** a weighted average (dilutes single severe factors); always `unknown` when any input is missing (gives "unknown" in dense fog); returning expired values flagged (risks being shown as current); retiring or rebuilding the legacy route now.
- **Source:** CF-004 (issue #5); plan r2 and critique in `~/codex-reviews/clearflight-cf004-design/`; owner decisions 2026-11-02.
- **Status:** accepted 2026-11-02 by project owner (each decision chosen in a walkthrough).

### D-006: METAR observation contract, caching, rate cap and error mapping (2026-10-30)
- **Decision:**
  - **Source:** Aviation Weather Center `api/data/metar?ids={ICAO}&format=json`. The newest record by `obsTime` becomes `observed_at` (not `reportTime`, which can differ). Records more than 10 minutes in the future are ignored. 204 means no report and returns `None`, not an error.
  - **Units:** °C, kt (AWC converts MPS), metres for visibility (converted from statute miles; `visibility_at_least` for `N+`), feet for cloud bases, hPa.
  - **Validity rules:** each number must be finite and not a bool, within these ranges: temperature/dew point −90…60, direction 0…360, speed 0…250, gust 0…300 and not below the speed, visibility ≥ 0, pressure 850…1100, cloud base ≥ 0. Anything else becomes `null` for that field only. `rawOb` is never parsed for missing values.
  - **Sky:** `sky_condition` is `clear` (CLR/SKC/NCD/NSC), `cavok`, `clouds`, `obscured` (OVX) or `unknown`. `ceiling_ft` is the lowest BKN/OVC base, so a null ceiling must be read together with `sky_condition`. A BKN/OVC layer with a missing or invalid base makes `sky_condition` `unknown` with a null ceiling, because the ceiling could be at that unknown height.
  - **Freshness:** current ≤ 90 min, stale ≤ 180 min, then expired. These are configurable and computed at read time.
  - **Cache:** the normalised observation for 600 s and "no report" for 300 s. Malformed cached values are treated as misses. "No report" is cached only for a 204 or an empty list; a response whose records are all unusable returns `None` without caching, so it's retried on the next request (bounded by the rate cap).
  - **Provider protection:** User-Agent `METAR_USER_AGENT`; one retry after 0.5 s plus jitter on timeouts, connection errors, 429 (Retry-After capped at 2 s) and 5xx; an in-process token bucket of 30 requests/min, which retries also use.
  - **Status mapping for CF-004:** `MetarTimeout` → 504; `MetarUpstreamError` → 502; `MetarRateLimited` → **503 with Retry-After** (429 stays reserved for a future per-client limit). A known airport without a report is not a 404 (plan §4).
- **Why:** Plan §3–4 requirements. Live probes on 2026-10-30 showed the real formats: statute-mile visibility including "6+"/"10+", "VRB" wind, an obsTime that differs from reportTime, and garbled reports. The design critique (CORMORANT case 2) found the missing error contract, the missing validity rules, the cache JSON crash and the missing Compose settings; all are fixed.
- **Alternatives considered:** Parse `rawOb` ourselves (more precise visibility, but fragile); cache raw provider responses (re-parsed on every read, and freshness is easy to get wrong); a Redis-shared rate limit (deferred until there's more than one process); 429 for local budget exhaustion (it isn't the client's fault).
- **Source:** CF-003 (issue #4); plan r2 and critique in `~/codex-reviews/clearflight-cf003-design/`.
- **Status:** accepted 2026-10-30 by project owner (plan approval, including the 503 mapping and validity ranges).

### D-005: Airport catalogue is a committed snapshot with timezones derived at import time (2026-10-30)
- **Decision:** Airport metadata comes from OurAirports, filtered to large, medium and small airports with an IATA or ICAO code, and committed as `app/data/airports.csv`. Each airport's IANA zone is derived from its coordinates with `timezonefinder` 9.1.0 / `timezonefinder-data` 4.2026.5 when the snapshot is built (`scripts/import_ourairports.py`), with manual overrides in `app/data/timezone_overrides.csv`. A missing or `Etc/*` zone stays empty, never a fixed offset. The API loads and validates the snapshot at startup and fails to start if it is missing or invalid. DST rules come from the runtime's tz database through `zoneinfo`. Refresh is manual: rerun the script, which validates the new snapshot before replacing the old one.
- **Why:** No runtime or CI dependency on the 30 MB+ boundary data or on the network; reproducible, reviewable data changes; startup failure is better than 500s behind a green health check (owner decision, 2026-10-30). OurAirports + `timezonefinder` was the retained default from RQ-001. A one-off cross-check against OpenFlights (2026-10-30) found the same UTC offsets in January and July for 5,312 of 5,365 shared airports. Of the 53 differences, most come from OpenFlights' stale data (e.g. Yukon, Mexico and Chile rule changes). One was a real lookup error at a border airport, Gold Coast (YBCG), which is now an override.
- **Alternatives considered:** Download at build time (network needed for every build; data changes unreviewed); look up timezones at runtime (heavy dependency in the image); keep AviationStack for metadata (trial access only; returns duplicate records); include heliports, seaplane bases and closed airports (not useful for travellers).
- **Source:** CF-002 (issue #3); plan r2 with CORMORANT critique (`~/codex-reviews/clearflight-cf002-design/`); RQ-001 findings.
- **Status:** accepted 2026-10-30 by project owner (plan approval).

### D-004: Test suite must keep at least 80% coverage, branch-aware (2026-10-19)
- **Decision:** `make check-coverage` (part of `make run-checks`, so also CI) measures `app/` with `--cov-branch` and fails when the total is below 80% (`--cov-fail-under=80`). The total is coverage.py's total with branch measurement on, which counts executed statements and branch outcomes together; it is not a separate branch-only threshold. By review convention, not enforced by the gate, pull requests should not lower total coverage (note before/after in the PR), and exclusions (`# pragma: no cover`) need a stated reason.
- **Why:** Owner's standard for all Python projects. Coverage was reported but never enforced (statement-only: 89% at CF-001 close, 90% later; branch-aware: 91.62% on 2026-10-19, with no partial branches), so a large regression could merge unnoticed. This is a repository-wide floor; the plan §7 pilot gate still applies on top (≥80% for new transformation/scoring logic, with meaningful tests prioritised over the single number).
- **Alternatives considered:** Keep coverage report-only (no protection against regressions); a higher gate (would push towards tests written for the number); a separate branch-only threshold (needs extra tooling; branch coverage is already near 100%).
- **Source:** Owner instruction, 2026-10-19; PR #14.
- **Status:** accepted 2026-10-19 by project owner.

### D-003: Docker Hub publishing only from version tags (2026-10-18)
- **Decision:** CI builds the Docker image without pushing. Publishing happens only in `release.yaml` for `v*` tags, via the `release` GitHub environment.
- **Why:** Avoid publishing images from every push, and gate releases.
- **Source:** PR #11, `docs/cf-001-baseline.md`
- **Status:** accepted. Required reviewer (Yoyo-su) configured on `release` on 2026-10-18.

### D-002: Redis is internal to Docker Compose; hosted Redis via `REDIS_URL` (2026-10-18)
- **Decision:** Do not publish Redis port 6379 on the host. Optional `REDIS_URL` (authenticated `rediss://`) overrides `REDIS_HOST`/`REDIS_PORT`.
- **Why:** Security baseline (plan §3, CF-001.5).
- **Source:** PR #11, `docs/cf-001-baseline.md`
- **Status:** accepted

### D-001: Provider calls use timeouts, status checks and redacted errors (2026-10-18)
- **Decision:** Configurable `PROVIDER_TIMEOUT` (default 10 s). HTTP and provider error bodies are not cached. Access keys are redacted from request errors.
- **Why:** Stable baseline and no credential leakage (CF-001.6).
- **Source:** PR #11, `docs/cf-001-baseline.md`
- **Status:** accepted. Mapping failures to 4xx/5xx is deferred to CF-004.
