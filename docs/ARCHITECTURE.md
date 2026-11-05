# Architecture

This document separates **what exists today** from the **planned pilot architecture**. The planned design is defined in [development-plan.md §3–4](development-plan.md). If the two disagree, the plan is the source of truth.

## Current implementation (as of 2026-11-05, `main` after CF-005, PR #19)

```text
Browser ── React + TS + Vite app (frontend/; dev: Compose `frontend` service or npm run dev,
   │         Vite proxy /v1 → API :8000)
   │         routes: / (search, recently viewed) · /airport/:code · not found
   │
Client ──HTTP──> FastAPI (app/main.py, gunicorn + uvicorn worker, Docker)
                  ├── GET / and GET /health       health check {"status": "ok"}
                  ├── GET /v1/airports/{code}/conditions
                  │       │
                  │       app/api/conditions.py           code → airport (catalogue) → METAR
                  │       │                               adapter → freshness → index; errors (D-006)
                  │       ├── app/services/metar.py       Aviation Weather Center observations
                  │       └── app/services/conditions.py  conditions index v0.1 (D-007)
                  ├── GET /v1/airports/search     catalogue search (code, name, city)
                  │       │
                  │       app/api/airport_search.py      parameter checks (400), response model
                  │       └── app/services/airport_catalogue.py  in-memory index, loaded and
                  │                                               validated at startup from
                  │                                               app/data/airports.csv
                  └── GET /airport/{airport_code} legacy prototype (deprecated; removed in CF-006)
                          │
                          app/api/airport.py      airport_query → generate_airport_profile
                          ├── app/services/aviationstack.py  airport metadata (Aviationstack API)
                          ├── app/services/weatherstack.py   current weather (Weatherstack API)
                          ├── app/services/cache.py          Redis cache (REDIS_URL or REDIS_HOST/PORT)
                          ├── app/services/redact.py         strips access keys from request errors
                          └── app/core/utils.py              unit conversions, heuristic weather risk,
                                                             fixed-offset local time (not IANA/DST)
```

| Area | Detail |
|---|---|
| Airport catalogue | `app/data/airports.csv`: committed OurAirports snapshot with IANA timezones precomputed (D-005). Rebuilt offline by `scripts/import_ourairports.py` (transforms/validation in `app/services/airport_import.py`; `timezonefinder` from `requirements-import.txt`, not a runtime or CI dependency). Overrides in `app/data/timezone_overrides.csv`; provenance in `airports.meta.json`. DST rules come from the system tz database via `zoneinfo`. |
| Frontend | `frontend/` (D-008): React 19 + react-router; `src/api` (types mirroring the v1 models, fetch client), `src/hooks` (conditions with ownership/refresh/cooldown/retry; debounced search), `src/lib` (formatting, Intl clock, D11 ageing, recently viewed), `src/pages`. Tests: Vitest (unit/component, 80% gate) and Playwright (desktop + mobile, axe). Contract fixtures in `frontend/tests/fixtures`, recorded by `scripts/record_frontend_fixtures.py` and checked by `tests/test_frontend_fixtures.py`. `make frontend-checks`; CI job `frontend`. Not deployed until CF-006. |
| v1 API | `app/api/models.py` (Pydantic response models), `app/api/conditions.py`, `app/api/airport_search.py`; errors return `{"detail", "reason"}` (D-007). |
| METAR adapter | `app/services/metar.py` (CF-003): Aviation Weather Center `api/data/metar` → normalised `Observation`, freshness, Redis cache `metar:v1:{ICAO}`, per-process rate cap, typed errors (D-006). Live check: `scripts/metar_smoke.py`. |
| Config | `app/core/config.py` (pydantic-settings); variables in `.env.template` |
| Runtime | `Dockerfile` (python:3.13-slim, non-root user), `docker-compose.yml` (API on `127.0.0.1:8000`, development web app on `127.0.0.1:5173`, Redis internal only) |
| Tests | `tests/` with pytest; providers and Redis are mocked; fixtures in `tests/testfiles/` |
| Quality | `Makefile` → `make run-checks`: bandit, black --check, flake8, pytest, coverage, pip-audit |
| CI | `.github/workflows/CF_deploy.yaml`: checks + Docker build (no push) on push to `main`/`pilot/**` and PRs into `main` |
| Release | `.github/workflows/release.yaml`: tag-gated (`v*`) Docker Hub publish through the `release` environment. No app deployment. |

Known limitations are listed in [cf-001-baseline.md](cf-001-baseline.md).

## Planned pilot architecture (from development plan v1.0)

```text
Browser (React + TS + Vite, Cloudflare Pages)
   ├─> GET /v1/airports/search?q=...
   └─> GET /v1/airports/{iata_or_icao}/conditions
                    │
            FastAPI on Render
       ┌────────────┼─────────────┐
   metadata     Redis cache     METAR adapter
  (OurAirports)  (Upstash)    (Aviation Weather Center)
```

Milestone mapping: catalogue (CF-002), METAR adapter (CF-003), v1 contract and conditions index (CF-004), frontend (CF-005), deployment (CF-006). Provider access stays behind adapters so sources can change without changing the public schema.

## Keeping this document current
Update the "Current implementation" section in the same PR that changes the structure, endpoints, providers or CI. Record why a change was made in [DECISIONS.md](DECISIONS.md).
