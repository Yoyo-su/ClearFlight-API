# ClearFlight development notes

How the parts fit together, how they are checked, and how to refresh the data. For setup, see the [README](../README.md); for the API, [API.md](API.md); for design and decisions, [ARCHITECTURE.md](ARCHITECTURE.md) and [DECISIONS.md](DECISIONS.md).

## Checks
- `make run-checks`: the Python checks CI runs (bandit, black, flake8, pytest with the 80% branch-aware coverage gate, pip-audit). It needs Python 3.13 as `python` and a venv from `make requirements dev-setup`.
- `make frontend-checks`: the frontend checks CI runs as a separate job (`npm ci`, `npm audit`, lint, typecheck, Vitest with the 80% gate, build, Playwright on desktop and mobile Chromium with axe). It needs Node 24.

```bash
make requirements dev-setup   # creates ./venv and installs dependencies
export PYTHONPATH=$PWD        # lets the tests import the app package, as CI does
export AVIATIONSTACK_API_KEY=ci-dummy-key WEATHERSTACK_API_KEY=ci-dummy-key
make run-checks
make frontend-checks
```
The tests mock every provider, so dummy keys are enough. Without the keys (or a `.env`), test collection fails with a settings validation error. Without `PYTHONPATH`, it fails with `ModuleNotFoundError: No module named 'app'`. If the project directory is moved, recreate `venv`, because a virtual environment's paths are fixed when it is created.

**Running the frontend on the host** (instead of the Compose `frontend` service, which already uses port 5173):
```bash
docker compose up -d clearflightapi redis   # the API and Redis only, in the background
cd frontend
npm ci                                      # host packages; the container keeps its own
npx playwright install chromium             # once, for npm run e2e (Linux: add --with-deps)
npm run dev                                 # http://localhost:5173, proxies /v1 and /health to :8000
npm test                                    # unit and component tests (Vitest), 80% coverage gate
npm run e2e                                 # Playwright on desktop and mobile Chromium, with axe
npm run build                               # production build in dist/
```
Set `VITE_API_BASE_URL` at build time when the API is on another origin; empty means same origin.

## Frontend–API contract
`frontend/tests/fixtures/` holds API responses recorded from the real code (`python scripts/record_frontend_fixtures.py`, deterministic, no network).
- The backend test `tests/test_frontend_fixtures.py` fails if they no longer match the Pydantic models exactly or what the API produces now.
- The frontend's `tests/unit/contract.test.ts` validates them against the runtime schema in `frontend/src/api/types.ts` (names, value types, nullability, allowed values). The TypeScript types are derived from that schema, and the client validates every live response with it too.

After changing a v1 model, re-record the fixtures and update `frontend/src/api/types.ts`.

**Checks** (`make frontend-checks`, also run as a separate CI job):
- `npm ci`;
- `npm audit`: no advisories in runtime dependencies, and nothing high or above in any dependency;
- lint, typecheck, unit tests with coverage, build;
- Playwright end-to-end tests.

## METAR observations
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

## Updating the airport catalogue
`app/data/airports.csv` is built from [OurAirports](https://ourairports.com/data/) by `scripts/import_ourairports.py`, which also derives each airport's IANA timezone from its coordinates with `timezonefinder`. The script and its dependencies are not needed to run the API or the tests. To refresh the snapshot:
```bash
python -m venv ~/.venvs/clearflight-import   # outside the repo, so the checks don't scan it
~/.venvs/clearflight-import/bin/pip install -r requirements.txt -r requirements-import.txt
~/.venvs/clearflight-import/bin/python scripts/import_ourairports.py
```
The new snapshot is validated first (codes, coordinates, timezone IDs, the three pilot airports, and a row count within 10% of the current one; pass `--allow-size-change` to accept a bigger change). If validation fails, the current files are left unchanged. `app/data/airports.meta.json` records the source, date, library versions and airports without a timezone. To correct an airport's timezone, add a row to `app/data/timezone_overrides.csv` and rerun the script. Review the diff before committing.

Data sources: airport data from [OurAirports](https://ourairports.com/data/) (public domain); timezone boundaries via [timezonefinder](https://github.com/jannikmi/timezonefinder) (MIT) and [timezone-boundary-builder](https://github.com/evansiroky/timezone-boundary-builder) (ODbL); timezone rules from the [IANA tz database](https://www.iana.org/time-zones); METAR observations from the [NOAA Aviation Weather Center](https://aviationweather.gov/) (US government data).
