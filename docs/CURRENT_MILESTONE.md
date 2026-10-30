# Current milestone: CF-003 METAR weather adapter

**Status:** In review (branch `feat/cf-003-metar-adapter`; PR pending)
**Source of truth:** [docs/development-plan.md](development-plan.md), §3 weather and cache policy, §4 errors, §5 roadmap
**Tracking:** [GitHub issue #4](https://github.com/Yoyo-su/ClearFlight-API/issues/4)
**Target window / estimate:** 2–8 Nov 2026 · ~10 h
**Last updated:** 2026-10-30

## Goal
A provider adapter fetches Aviation Weather Center METAR observations, normalises them with honest missing values, and reports their source, observation time and freshness. Provider failures are handled and the provider is protected by caching and a rate cap.

## Scope (from plan §5 and issue #4)
- AWC METAR adapter with normalised parsing and handling of missing fields.
- Timeout, retry/backoff, a rate cap and typed provider errors.
- Caching, with `observed_at` kept separate from `fetched_at`, and freshness classification.
- Recorded fixtures plus live smoke lookups for EGLL, RJBB and KJFK.

## Out of scope
- The public `/v1/airports/{code}/conditions` endpoint, response models, HTTP status mapping and the conditions index (CF-004). CF-004 builds them on this adapter, using the error-to-status mapping in D-006.
- Frontend (CF-005), deployment (CF-006).

## Acceptance criteria (issue #4)
- [x] Mocked fixtures and live smoke lookups pass; no synthetic observations; missing data handled.
- [x] Relevant automated checks pass and user-visible errors are covered (as typed adapter errors; the HTTP mapping is CF-004).
- [x] README / API contract updated where applicable.
- [ ] Work delivered in a PR from a separate branch; do not commit directly to main. (Branch ready; PR not yet opened.)

Plan exit evidence: "Mocked/recorded fixtures pass; real smoke lookups demonstrate source/age."

## Tasks
| ID | Task | Status | PR |
|---|---|---|---|
| CF-003.1 | Observation model, normalisation and validity rules (D-006) | Done | |
| CF-003.2 | AWC requests: User-Agent, timeout, one retry with backoff, typed errors | Done | |
| CF-003.3 | Rate cap, Redis cache (incl. "no report"), freshness | Done | |
| CF-003.4 | Cache helper hardening (malformed JSON, Redis timeouts); Compose settings | Done | |
| CF-003.5 | Recorded fixtures, tests, live smoke script | Done | |
| CF-003.6 | README, ARCHITECTURE, DECISIONS (D-006) | Done | |

## Verification evidence
- 2026-10-30 live smoke (`scripts/metar_smoke.py`), source "Aviation Weather Center":
  - EGLL observed 07:20Z, 35 min old, current.
  - RJBB observed 07:30Z, 25 min old, current.
  - KJFK observed 06:51Z, 64 min old, current.
  - ZZZZ returned "no report available"; `LHR` was rejected as an invalid station code.
  - With Redis unreachable, lookups fell back to the provider.
- `make run-checks` passes: 261 tests, total coverage 97.21% branch-aware (95.60% before), pip-audit clean. A copy containing only the files git would commit also passes, so the fixtures reach CI. In the container, the forwarded settings were confirmed and a repeat lookup was a cache hit (TTL 600 s).
- Reviews (3 rounds, the workflow cap):
  - Round 1: Codex 1 High (fixtures ignored by `.gitignore`) and 2 Medium (crashes on malformed values); quality-reviewer 1 Medium; requirements-validator gaps.
  - Round 2: Codex 2 Medium (unknown ceiling height, huge integers); quality-reviewer 1 Medium (`Retry-After: nan`).
  - Round 3 (scoped): 1 Medium (rule precedence).
  - All confirmed findings are fixed and tested; no High is open.
- Recorded fixtures (AWC, 2026-10-30) cover the pilot stations, MPS wind with gusts (ZBAA), an obscured sky with fog (EGKK), variable wind with CAVOK (LEMD), an automated no-cloud SPECI (YSSY), `10+` visibility with gusts and rain (PANC), and a garbled report (DNMM).

## Risks / open questions
- Visibility arrives in statute miles, so metric reports lose a little precision (1300 m → 1304 m; 150 m → 145 m). Accepted in plan r2.
- Worst-case lookup latency is about 2 × `PROVIDER_TIMEOUT` (10 s) + backoff ≈ 21 s; CF-004 may want a shorter METAR timeout.
- The rate cap is per process (gunicorn runs one worker). A shared limit is needed before scaling out (CF-006).
- A few airports' ICAO codes differ from their METAR station IDs; airports without an ICAO code have no METAR. CF-004 shows these as unavailable.

## Previous milestone
CF-002 airport catalogue: done. PR #16 merged 2026-10-30 (`618c726`), issue #3 closed. Evidence is in the PR.

## Follow-ups (discovered, not in scope)
- Search relevance: ties are broken alphabetically, so "london" lists Gatwick before Heathrow, and "kennedy" ranks Gahcho Kue (city "Kennedy Lake") above JFK. Consider ranking airports with scheduled service higher (OurAirports `scheduled_service`) before the CF-005 frontend.
- The legacy `/airport/{code}` route fails against the AviationStack trial (each airport is returned twice; owner decided 2026-10-30 not to fix it). Replace it with the catalogue and METAR adapter in CF-004.
- Carried over from CF-001 (`docs/cf-001-baseline.md`), now for CF-004: map provider failures to 400/404/502/504, and remove API access keys from URLs that are hashed into cache keys (legacy AviationStack/WeatherStack services).
- `docs/development-plan.md` §6 still shows CF-001 task checkboxes unticked, although issue #2 is closed. `docs/cf-001-baseline.md` has the actual status.
- **Test task (test-engineer):** `app/api/airport.py` (legacy route) has low statement coverage. If CF-004 replaces the legacy route, test the replacement instead.

## Next task
Reviews (quality-reviewer, Codex, requirements-validator), then open the CF-003 PR.
