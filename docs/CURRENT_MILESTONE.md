# Current milestone: CF-004 Conditions API

**Status:** In review (branch `feat/cf-004-conditions-api`; PR pending)
**Source of truth:** [docs/development-plan.md](development-plan.md), §3 conditions index, §4 API contract, §7 acceptance gates
**Tracking:** [GitHub issue #5](https://github.com/Yoyo-su/ClearFlight-API/issues/5)
**Target window / estimate:** 9–15 Nov 2026 · ~8 h
**Last updated:** 2026-11-02

## Goal
A stable `/v1/airports/{code}/conditions` contract returns airport metadata, the latest observation with its age, and an explainable, experimental conditions index. Stale or missing data is never presented as a low score.

## Scope (from plan §5 and issue #5)
- Pydantic v1 response models; the conditions endpoint on the airport catalogue and METAR adapter.
- Conditions index v0.1 with factors, a one-sentence explanation and a fixed disclaimer.
- Safe unknown, stale and unavailable states; provider error mapping (D-006).
- `GET /health`; CF-001 carry-over: legacy cache keys without access keys.

## Out of scope
- Frontend (CF-005), deployment, CORS and removing the legacy route (CF-006), traveller validation of the index (CF-007).
- A per-client rate limit (429).

## Acceptance criteria (issue #5)
- [x] Stable `/v1/airports/{code}/conditions` contract, deterministic score tests, no misleading safe/delay claims.
- [x] Relevant automated checks pass and user-visible errors are covered.
- [x] README / API contract updated where applicable.
- [ ] Work delivered in a PR from a separate branch; do not commit directly to main. (Branch ready; PR not yet opened.)

Plan exit evidence: "Stable v1 contract; deterministic scoring; stale/missing never presented as low risk."

## Tasks
| ID | Task | Status | PR |
|---|---|---|---|
| CF-004.1 | v1 response models (`app/api/models.py`) and the conditions endpoint | Done | |
| CF-004.2 | Conditions index v0.1 (`app/services/conditions.py`, D-007) | Done | |
| CF-004.3 | Freshness/unavailable states, error mapping, `/health` | Done | |
| CF-004.4 | Legacy cache keys without access keys (CF-001 carry-over) | Done | |
| CF-004.5 | Tests: index bands, weather groups, wording, endpoint, composed adapter paths | Done | |
| CF-004.6 | README, ARCHITECTURE, DECISIONS (D-007) | Done | |

## Verification evidence
- 2026-11-02: `make run-checks` passes: 438 tests, total coverage 97.83% branch-aware (97.21% before), pip-audit clean.
- Recorded fixtures through the endpoint:
  - EGLL 8 severe (1.3 km, ceiling 200 ft); RJBB 5 moderate (+SHRA); KJFK 2 low (11 kt); EGKK 10 severe (145 m fog, sky obscured);
  - PANC 6 high (gusts 33 kt); ZBAA 4 moderate (gusts 27 kt); LEMD 0 low (CAVOK).
- Live, 2026-11-02, in the container (Aviation Weather Center):
  - EGLL scored 3 moderate (BKN022), 31 min old.
  - KJFK scored 0 low, 60 min old.
  - RJBB at first returned `unavailable` / `observation_too_old`: AWC's CDN served a 09:30Z report at 12:49Z, although a 12:30Z report had been received at 12:37Z. Observations that aren't current are now cached for only 60 s (D-007).
  - AAI gave `no_metar_station`; `XX` → 400; `ZZZ` → 404.
- Cached latency under light load (300 requests over the three pilot airports): sequential p95 4.9 ms; 5 concurrent clients p95 10.8 ms (plan §7 target ≤ 1 s).
- Composed tests through the real adapter cover a cache hit with no second provider call, Redis down falling back to the provider, budget exhaustion giving 503 + Retry-After, a 204 giving `no_report` (cached), and timeouts giving 504.

## Risks / open questions
- Index bands are heuristic (v0.1); validate them with travellers in CF-007.
- Unrecognised weather groups make the score `unknown`; review them with `scripts/unrecognised_weather.py` and extend the scoring table.
- A garbled report whose wind, visibility and cloud fields still parse is scored normally (DNMM fixture scores 0). AWC's `qcField` isn't used yet.
- Worst-case lookup latency is about 21 s (2 × `PROVIDER_TIMEOUT` + backoff); consider a shorter METAR timeout before CF-006.
- The METAR rate cap is per process; a shared limit is needed before scaling out (CF-006).

## Previous milestones
- CF-003 METAR weather adapter: done. PR #17 merged 2026-10-30 (`22a8a7b`), issue #4 closed.
- CF-002 airport catalogue: done. PR #16 merged 2026-10-30 (`618c726`), issue #3 closed.

## Follow-ups (discovered, not in scope)
- Search relevance: ties are broken alphabetically, so "london" lists Gatwick before Heathrow, and "kennedy" ranks Gahcho Kue (city "Kennedy Lake") above JFK. Consider ranking airports with scheduled service higher (OurAirports `scheduled_service`) before the CF-005 frontend.
- Remove the deprecated legacy `/airport/{code}` route and its AviationStack/WeatherStack services in CF-006 (owner decision 2026-11-02). It fails against the AviationStack trial (duplicate records).
- `docs/development-plan.md` §6 still shows CF-001 task checkboxes unticked, although issue #2 is closed. `docs/cf-001-baseline.md` has the actual status.

## Next task
Reviews (quality-reviewer, Codex, requirements-validator), then open the CF-004 PR.
