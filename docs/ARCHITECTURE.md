# Architecture

This document separates **what exists today** from the **planned pilot architecture**. The planned design is defined in [development-plan.md §3–4](development-plan.md). If the two disagree, the plan is the source of truth.

## Current implementation (as of 2026-10-18, `main` @ d13a35c)

```text
Client ──HTTP──> FastAPI (app/main.py, gunicorn + uvicorn worker, Docker)
                  ├── GET /                       health check {"status": "ok"}
                  └── GET /airport/{airport_code} legacy prototype (IATA or ICAO)
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
| Config | `app/core/config.py` (pydantic-settings); variables in `.env.template` |
| Runtime | `Dockerfile` (python:3.13-slim, non-root user), `docker-compose.yml` (API on `127.0.0.1:8000`, Redis internal only) |
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
