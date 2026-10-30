# Current milestone: CF-002 Airport catalogue

**Status:** In review (branch `feat/cf-002-airport-catalogue`; PR pending)
**Source of truth:** [docs/development-plan.md](development-plan.md), §5 roadmap and §7 acceptance gates
**Tracking:** [GitHub issue #3](https://github.com/Yoyo-su/ClearFlight-API/issues/3)
**Target window / estimate:** 26 Oct – 1 Nov 2026 · ~8 h
**Last updated:** 2026-10-30

## Goal
Travellers' airport lookups are backed by a local OurAirports catalogue with validated IANA timezones, searchable by IATA, ICAO, name and city.

## Scope (from plan §5 and issue #3)
- Import OurAirports metadata.
- Index IATA / ICAO / name / city for search.
- Validate IDs and the IANA timezone mapping, including DST, for the pilot airports EGLL, RJBB and KJFK.

## Out of scope
- METAR weather adapter (CF-003), conditions index and v1 response models (CF-004), frontend (CF-005), deployment (CF-006).
- Everything in plan §2 "Explicitly deferred".

## Acceptance criteria (issue #3)
- [x] Search endpoint works; timezone/DST tests pass.
- [x] Relevant automated checks pass and user-visible errors are covered.
- [x] README / API contract updated where applicable.
- [ ] Work delivered in a PR from a separate branch; do not commit directly to main. (Branch ready; PR not yet opened.)

Plan exit evidence: "Search endpoints and timezone tests pass for 3 pilot airports."

Related plan constraints:
- Use IANA timezone IDs, never a fixed GMT offset. Derive or cross-check from coordinates and a maintained mapping (plan §3).
- Proposed route: `GET /v1/airports/search?q=...`. Invalid search returns 400, no result returns a clear empty or 404 state (plan §4).
- Preserve the legacy `/airport/{airport_code}` route for now.

## Tasks
| ID | Task | Status | PR |
|---|---|---|---|
| CF-002.1 | Import script + committed OurAirports snapshot with IANA zones (D-005) | Done | |
| CF-002.2 | In-memory catalogue: lookup by IATA/ICAO, ranked search | Done | |
| CF-002.3 | `GET /v1/airports/search` with 400/empty states; startup validation | Done | |
| CF-002.4 | Pilot timezone, DST and snapshot integrity tests | Done | |
| CF-002.5 | README, ARCHITECTURE, DECISIONS (D-005) | Done | |

## Verification evidence
- 2026-10-30: `make run-checks` passes: 170 tests, total coverage 95.60% branch-aware (92% on `main` before), no known vulnerabilities after bumping `certifi` and `setuptools` for new advisories. Docker image rebuilt; the search endpoint was smoke-tested in the container.
- Reviews, round 1: quality-reviewer "ready with minor fixes" (1 Medium refuted for the current image, but `tzdata` was added as a fallback; 3 Low fixed, 1 not changed); Codex "ready with minor fixes" (1 Low: the snapshot and metadata moves aren't atomic as a pair; documented and tested; import-script tests added); requirements-validator "ready to open the PR" (attribution line and endpoint code tests added).
- Snapshot: 11,251 airports from the 2026-10-30 OurAirports export; 3 without a timezone (PLPA, SCGC, SCPZ); 1 override (YBCG).
- Pilot zones: EGLL Europe/London, RJBB Asia/Tokyo, KJFK America/New_York. They match the AviationStack trial and OpenFlights; the DST changeovers for 2026 are tested.
- Cross-check against OpenFlights: same January/July offsets for 5,312 of 5,365 shared airports. The differences are mostly OpenFlights' stale data; see D-005.

## Carried over from CF-001 (issue #2 closed)
- [x] Configure required reviewers on the GitHub `release` environment (done 2026-10-18: reviewer Yoyo-su, self-review allowed).
- Deferred to CF-004: mapping provider failures to 400/404/502/504, and removing API access keys from URLs hashed into cache keys.

## Risks / open questions
- Choice of timezone derivation source (dependency or dataset), which needs a decision recorded in `docs/DECISIONS.md`.
- How the OurAirports data is stored and refreshed (build-time import vs. committed snapshot).

## Follow-ups (discovered, not in scope)
- Search relevance: ties are broken alphabetically, so "london" lists Gatwick before Heathrow, and "kennedy" ranks Gahcho Kue (city "Kennedy Lake") above JFK. Consider ranking airports with scheduled service higher (OurAirports `scheduled_service`) before the CF-005 frontend.
- The legacy `/airport/{code}` route fails against the AviationStack trial (each airport is returned twice; owner decided 2026-10-30 not to fix it). Replace it with the catalogue in CF-004.
- `docs/development-plan.md` §6 still shows CF-001 task checkboxes unticked, although issue #2 is closed. `docs/cf-001-baseline.md` has the actual status.
- **Test task (test-engineer):** `app/api/airport.py` has 18% statement coverage (it has no branches; lines 30-44 of `airport_query` and 61-114 of `generate_airport_profile` untested; 2026-10-19), although the repo total is 92%. Delegate to the `test-engineer` agent (tests/ only, mocked providers): cover `airport_query`'s success path and its `ValueError` and unexpected-error paths, and `generate_airport_profile`'s output and its own exception path. If CF-002 replaces this module, test the replacement instead.

## Next task
Reviews (quality-reviewer, Codex, requirements-validator), then open the CF-002 PR.
