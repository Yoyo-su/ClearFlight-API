# ClearFlight-API
An API which provides real-time traffic & weather information for airports, routings and flight numbers.


## Architecture

![Airport API](https://github.com/user-attachments/assets/e697753b-2f7a-42d4-9bd0-607756f326f8)


## Endpoints
### GET /health
Liveness check: `{"status": "ok"}` (`GET /` returns the same).

### GET /v1/airports/{code}/conditions
Observed weather conditions at an airport, from the latest METAR report. `code` is an IATA (3 letters) or ICAO (4 characters) code, in any case.

example: `/v1/airports/LHR/conditions`. This illustrative, abridged response is based on a recorded report with 1.3 km visibility in mist and overcast at 200 ft:
```json
{
  "airport": {"code": "EGLL", "icao": "EGLL", "iata": "LHR", "name": "London Heathrow Airport",
              "city": "London", "country": "United Kingdom", "country_code": "GB",
              "timezone": "Europe/London"},
  "observation": {"source": "Aviation Weather Center", "station": "EGLL",
                  "observed_at": "2026-10-30T07:20:00Z", "fetched_at": "2026-10-30T07:55:02Z",
                  "age_minutes": 35, "raw_text": "METAR EGLL 300720Z 07004KT ... BR OVC002 10/10 Q1029",
                  "wind_speed_kt": 4, "visibility_m": 1304, "sky_condition": "clouds",
                  "ceiling_ft": 200, "weather_phenomena": ["BR"], "...": "..."},
  "conditions": {"version": "0.1", "score": 8, "level": "severe",
                 "factors": [{"name": "visibility", "value": 1304, "unit": "m", "score": 8,
                              "detail": "1.3 km"}, "..."],
                 "explanation": "Observed conditions index 8/10 (severe), mainly from visibility of 1.3 km and a cloud ceiling at 200 ft.",
                 "disclaimer": "Experimental index of the weather reported at the airport. It is not a forecast and does not predict delays, cancellations or flight safety."},
  "data_status": "current",
  "unavailable_reason": null,
  "last_observed_at": "2026-10-30T07:20:00Z",
  "current_until": "2026-10-30T08:50:00Z",
  "stale_until": "2026-10-30T10:20:00Z"
}
```
**`data_status`:**
- `current`: observed within `METAR_CURRENT_MAX_MINUTES` (90). Scored if the inputs are adequate.
- `stale`: observed within `METAR_STALE_MAX_MINUTES` (180). The observation is shown, but not scored.
- `unavailable` (`200`, never `404` for a known airport), with `observation: null` and an `unavailable_reason`:
  - `no_metar_station`: the airport has no ICAO code;
  - `no_report`: the station has no current report;
  - `observation_too_old`: older than the stale limit; `last_observed_at` gives its time.

**`current_until` / `stale_until`** (D-008): when the observation stops being current (it loses its score) and when it expires (its values should no longer be shown). The backend computes them from its configured thresholds, so a client keeping a response on screen can age it without knowing the thresholds. They're `null` when there's no observation.

**Conditions index v0.1 (D-007):** an experimental 0–10 severity of the *observed* conditions; higher is more severe. It is not a forecast and does not predict delays, cancellations or flight safety. The index is the highest of four components:

| Score | Wind (kt, higher of speed and gust) | Visibility | Ceiling (lowest BKN/OVC) |
|---|---|---|---|
| 0 | < 10 | ≥ 8 km | none, or > 3000 ft |
| 2 | 10–19 | | |
| 3 | | 4.8–8 km | 1000–3000 ft |
| 4 | 20–29 | | |
| 6 | 30–39 | 1.6–4.8 km | 500–999 ft |
| 8 | 40–49 | 0.8–1.6 km | 200–499 ft |
| 10 | ≥ 50 | < 800 m | < 200 ft |

Visibility arrives from the provider in statute miles rounded to 0.01. Band comparisons allow 10 m for that rounding, so a reported 8000 m (sent as 4.97 SM = 7998 m) scores 0.

- **Reported weather:**
  - thunderstorm 8 (heavy 10);
  - hail, squall, funnel cloud, volcanic ash, dust or sandstorm 10;
  - freezing rain or drizzle 8;
  - snow, ice pellets or snow pellets 3 / 5 / 8 (light / moderate / heavy);
  - rain, drizzle, showers, snow grains, ice crystals or unknown precipitation 1 / 3 / 5;
  - blowing snow, sand or dust 3;
  - mist, haze, fog and smoke 0 (visibility covers them);
  - weather "in the vicinity" (VC) is capped at 5;
  - an unrecognised code makes the weather factor unknown (see below). It is named in the factor detail and recorded for later scoring.
- **Levels:** low 0–2, moderate 3–5, high 6–7, severe 8–10, or `unknown`.
- **When there's no score:** a score needs a `current` observation with known wind speed, visibility, ceiling and weather. Otherwise the level is `unknown` and the explanation names what's missing or couldn't be interpreted. The one exception: if the known components already reach 10, the score is 10, because the missing one can't change it. Examples are dense fog with the sky obscured, or a gust of 50 kt or more when the sustained speed is missing.
- **Unrecognised weather codes** are logged and counted in Redis, once per observation, with the last example report. List them with `docker compose exec clearflightapi python scripts/unrecognised_weather.py` so the scoring table can be extended.

**Errors** (body `{"detail": "...", "reason": "..."}`):
- `400` `invalid_code`;
- `404` `airport_not_found`;
- `502` `provider_error`;
- `503` `rate_limited`, with `Retry-After` (the server's own METAR request budget is used up);
- `504` `provider_timeout`.

`429` (a per-client rate limit, plan §4) isn't implemented yet; the server-wide METAR budget returns `503`.

**Known limitations (v0.1):**
- The index bands are heuristic and not yet validated with travellers (CF-007).
- A garbled report whose wind, visibility and cloud fields still parse is scored normally; the provider's quality flags aren't used.
- The METAR request budget is per server process.
- A provider timeout can make a lookup take up to about 21 s.

### GET /airport (deprecated)
Legacy prototype route: airport metadata and weather from AviationStack and WeatherStack. Replaced by `/v1/airports/{code}/conditions`; it will be removed in CF-006, before public deployment. It currently fails against the AviationStack trial, which returns each airport twice.

example: `/airport/KJFK` or `/airport/JFK`

<img width="386" height="629" alt="image" src="https://github.com/user-attachments/assets/c66bc2e2-2396-4c6a-ba16-ba8f4a1a2b04" />


### GET /v1/airports/search
Searches the local airport catalogue (OurAirports data, no provider call) by IATA or ICAO code, name or city. Matching ignores case and accents.

Parameters: `q` (2–64 characters, required), `limit` (1–25, default 10).

example: `/v1/airports/search?q=heathrow` returns
```json
{
  "query": "heathrow",
  "count": 1,
  "results": [
    {
      "code": "EGLL", "icao": "EGLL", "iata": "LHR",
      "name": "London Heathrow Airport", "city": "London",
      "country": "United Kingdom", "country_code": "GB",
      "type": "large_airport", "timezone": "Europe/London",
      "latitude": 51.470748, "longitude": -0.459909
    }
  ]
}
```
- Results are ordered: exact IATA/ICAO code, then name or city starting with `q`, then a word starting with `q`, then any other match; ties go to larger airports, then by name.
- `code` is the ICAO code, or the IATA code when the airport has no ICAO code. `icao`, `iata`, `city`, `country` and `timezone` can be `null`.
- `timezone` is an IANA zone ID. A few remote airports have none (`null`); the API never substitutes a fixed offset.
- No match returns `200` with an empty `results` list. A missing, too short or too long `q`, or an invalid `limit`, returns `400`.

The catalogue covers large, medium and small airports with an IATA or ICAO code (about 11,000). It is a committed snapshot in `app/data/airports.csv`; see [Updating the airport catalogue](#updating-the-airport-catalogue).

### GET /route - To be implemented

### GET /flight - To be implemented



## 🚀 Setup & Deployment

This project uses GitHub Actions for continuous integration and deployment, the workflow automatically runs tests and checks. 

The CI pipeline (`CF_deploy.yaml`) is triggered on:
  - Pushes to `main` and `pilot/**` branches
  - Pull requests into `main`

### Continuous Integration  
The run-tests job performs the following steps:

 - Configures the Python environment and installs dependencies
 - Runs python security, format (`black --check`) and linting checks
 - Runs pytests and enforces at least 80% test coverage (branch-aware)
 - Audits dependencies for known vulnerabilities

The docker-build job then builds the Docker image without publishing it. Tests mock all provider calls, so CI uses dummy API keys.

### Release
Publishing the Docker Hub image is handled separately by `release.yaml`, which publishes only for version tags (`v*`; a manual run must be started on such a tag), repeats the checks and uses the `release` GitHub environment.

### Local Setup
Docker is used to run the API. To set it up, follow these steps:

1. Ensure you have Docker installed on your machine. If not, you can download it from [Docker's official website](https://www.docker.com/get-started).

2. Clone the repository to your local machine:
   ```bash
   git clone https://github.com/Yoyo-su/ClearFlight-API.git
   ```

3. Navigate to the project directory:
   ```bash
   cd ClearFlight-API
   ```

4. Copy `.env.template` to `.env` and add your own API credentials. Inside Docker Compose Redis is reachable as `redis` (not `localhost`).

5. Keep `.env` private. Do not commit API keys. Redis is internal to Docker Compose; only the API is bound to `127.0.0.1:8000`.

6. Build and run the Docker container:
   ```bash
   docker compose up --build
   ```

7. Access the API at `http://localhost:8000`. Status should be `ok` if everything is set up correctly.

8. To stop the container, use:
   ```bash
   docker compose down
   ```

### Running the checks locally
`make run-checks` runs the same Python checks as CI (bandit, black, flake8, pytest, the coverage gate and pip-audit). It needs Python 3.13 available as `python`. `make frontend-checks` runs the frontend's CI checks (see [Frontend](#frontend)); it needs Node 24.

```bash
make requirements dev-setup   # creates ./venv and installs dependencies
export PYTHONPATH=$PWD        # lets the tests import the app package, as CI does
export AVIATIONSTACK_API_KEY=ci-dummy-key WEATHERSTACK_API_KEY=ci-dummy-key
make run-checks
```

The tests mock the providers, so dummy keys are enough, and no real credentials are needed. Without the keys (or a `.env`), test collection fails with a settings validation error. Without `PYTHONPATH`, it fails with `ModuleNotFoundError: No module named 'app'`. If the project directory is moved, recreate `venv` (`rm -rf venv && make requirements dev-setup`), because a virtual environment's paths are fixed when it is created.

### Frontend
The traveller-facing web app lives in `frontend/`: React 19, TypeScript, Vite and react-router, with no other runtime dependencies. The design is in [docs/cf-005-design.md](docs/cf-005-design.md).

- **Pages:** search (`/`), with results as you type, recently viewed airports (stored only in your browser) and the pilot airports; an airport page (`/airport/EGLL`); and a not-found page.
- **Airport page:** local and UTC clocks; the observation with its age; the experimental conditions index with its factors; and every unavailable or error state, with wording from the spec. It refreshes every 5 minutes while visible; the Refresh button has a 60 s cooldown.

```bash
cd frontend
npm ci
npm run dev          # http://localhost:5173, proxies /v1 and /health to the API on :8000
npm test             # unit and component tests (Vitest), 80% coverage gate
npm run e2e          # end-to-end tests on desktop and mobile Chromium, with axe checks
npm run build        # production build in dist/
```
Run the API with `docker compose up` for `npm run dev`. Set `VITE_API_BASE_URL` at build time when the API is on another origin (CF-006); empty means same origin.

**Contract with the API:** `frontend/tests/fixtures/` holds API responses recorded from the real code (`python scripts/record_frontend_fixtures.py`, deterministic, no network).
- The backend test `tests/test_frontend_fixtures.py` fails if they no longer match the Pydantic models exactly or what the API produces now.
- The frontend's `tests/unit/contract.test.ts` validates them against the runtime schema in `frontend/src/api/types.ts` (names, value types, nullability, allowed values). The TypeScript types are derived from that schema, and the client validates every live response with it too.

After changing a v1 model, re-record the fixtures and update `frontend/src/api/types.ts`.

**Checks** (`make frontend-checks`, also run as a separate CI job):
- `npm ci`;
- `npm audit`: no advisories in runtime dependencies, and nothing high or above in any dependency;
- lint, typecheck, unit tests with coverage, build;
- Playwright end-to-end tests.

### METAR observations
`app/services/metar.py` fetches the latest METAR observation for a station from the [Aviation Weather Center](https://aviationweather.gov/data/api/) data API. The conditions endpoint uses it.
- **Observation fields:**
  - `observed_at` comes from the observation itself, not the report time; `fetched_at` is when the provider was called.
  - `raw_text`, temperature and dew point (°C).
  - Wind direction (null when variable, with `wind_variable`), speed and gust in knots.
  - Visibility in metres, converted from statute miles. `visibility_at_least` marks values such as `10+`.
  - `sky_condition` (`clear`, `cavok`, `clouds`, `obscured`, `unknown`), cloud layers, and `ceiling_ft` (the lowest broken or overcast layer). A null `ceiling_ft` means "no ceiling" only when `sky_condition` is `clear`, `cavok` or `clouds`; when it's `obscured` or `unknown` (including a broken or overcast layer whose height wasn't reported), the ceiling is unknown.
  - `pressure_hpa` and weather codes (e.g. `-RA`, `BR`).
- Missing or implausible values are `null`; nothing is defaulted or guessed.
- **Freshness** (computed on every read): `current` up to `METAR_CURRENT_MAX_MINUTES` (90), `stale` up to `METAR_STALE_MAX_MINUTES` (180), then `expired`.
- **Provider protection:**
  - Observations are cached in Redis for `METAR_CACHE_TTL` (600 s), and "no report" for `METAR_NO_DATA_CACHE_TTL` (300 s).
  - Requests send `METAR_USER_AGENT` and are capped at `METAR_RATE_LIMIT_PER_MINUTE` (30) per process.
  - One retry with a short backoff on timeouts, 429 and 5xx (worst case about 2 × `PROVIDER_TIMEOUT` + 1 s).
  - If Redis is unavailable, lookups go to the provider, still under the cap.
- **Errors:** `MetarTimeout`, `MetarUpstreamError` and `MetarRateLimited`, each with a machine-readable `reason` (see D-006). A station without a report returns `None`, not an error.

Live check for the pilot airports (real requests; not part of CI):
```bash
python scripts/metar_smoke.py            # EGLL, RJBB, KJFK
python scripts/metar_smoke.py EGKK LFPG  # other stations
```

### Updating the airport catalogue
`app/data/airports.csv` is built from [OurAirports](https://ourairports.com/data/) by `scripts/import_ourairports.py`, which also derives each airport's IANA timezone from its coordinates with `timezonefinder`. The script and its dependencies are not needed to run the API or the tests. To refresh the snapshot:
```bash
python -m venv .venv-import && .venv-import/bin/pip install -r requirements.txt -r requirements-import.txt
.venv-import/bin/python scripts/import_ourairports.py
```
The new snapshot is validated first (codes, coordinates, timezone IDs, the three pilot airports, and a row count within 10% of the current one; pass `--allow-size-change` to accept a bigger change). If validation fails, the current files are left unchanged. `app/data/airports.meta.json` records the source, date, library versions and airports without a timezone. To correct an airport's timezone, add a row to `app/data/timezone_overrides.csv` and rerun the script. Review the diff before committing.

Data sources: airport data from [OurAirports](https://ourairports.com/data/) (public domain); timezone boundaries via [timezonefinder](https://github.com/jannikmi/timezonefinder) (MIT) and [timezone-boundary-builder](https://github.com/evansiroky/timezone-boundary-builder) (ODbL); timezone rules from the [IANA tz database](https://www.iana.org/time-zones); METAR observations from the [NOAA Aviation Weather Center](https://aviationweather.gov/) (US government data).

## Future Features
- Visual dashboard
- AI Advisor (GPT)
- Predictive weather and traffic (ML)


## Pilot development

See [Development Plan v1.0](docs/development-plan.md) and [CF-001 recovery baseline](docs/cf-001-baseline.md). The pilot adds a traveller-facing airport weather dashboard, but is not yet publicly deployed.
