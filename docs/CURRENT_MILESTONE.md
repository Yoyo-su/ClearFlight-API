# Current milestone: CF-008 Forecast outlook (Phase 2 begins)

**Status:** Implemented on `feat/cf-008-forecast-outlook`; in review (design approved 2026-11-09, D-011)
**Source of truth:** [docs/development-plan.md](development-plan.md) v1.1 (§2 feature 3, §4, §5, §7); decision D-010
**Last updated:** 2026-11-09

## Goal
Show each airport's official forecast (TAF) for the next hours, with the conditions index applied per forecast period, clearly labelled as a forecast.

## Next task
Finish CF-008 reviews (quality-reviewer and Codex), then open the PR for owner merge. Design: [cf-008-design.md](cf-008-design.md).
- **Done:** the TAF adapter and parser (live AWC probe, recorded fixtures), the hourly outlook and index, `GET /v1/airports/{code}/forecast`, and the frontend forecast section with ageing, contract fixtures, unit tests and e2e/axe tests.

## Phase 2 order (plan v1.1)
CF-008 forecast → CF-009 positions → CF-010 map → CF-011 movements → CF-012 disruption signals → CF-013 flight lookup. Then CF-006 public deployment (with the data-licence gate) and CF-007 validation.

## Completed since CF-005
- Cleanup PRs #20 (housekeeping), #21 (search ranking, visibility, zone names) and #22 (README rewrite; docs/API.md, docs/DEVELOPMENT.md), merged 2026-11-06/08.
- RQ-002 free flight-data research (closed, follow-up), and plan v1.1 with its design critique.

## Previous milestones
- CF-005 frontend MVP: done. PR #19 merged 2026-11-04 (`5a07e60`), issue #6 closed. Spec: [cf-005-design.md](cf-005-design.md); decision D-008.
- CF-004 conditions API: done. PR #18 merged 2026-11-02 (`2325b4a`), issue #5 closed.
- CF-003 METAR weather adapter: done. PR #17 merged 2026-10-30 (`22a8a7b`), issue #4 closed.
- CF-002 airport catalogue: done. PR #16 merged 2026-10-30 (`618c726`), issue #3 closed.
- CF-001 baseline recovery: done. Issue #2 closed 2026-10-18; [cf-001-baseline.md](cf-001-baseline.md).

## Known limitations carried forward
- Index bands are heuristic (v0.1) until traveller validation (CF-007).
- The METAR rate cap is per process; a shared limit is needed before scaling out (CF-006).
- Worst-case lookup latency is about 21 s on provider timeouts; the frontend times out at 25 s.

## Follow-ups (not scheduled)
- `httpx==0.28.1` in `requirements.txt` looks unused at runtime (no imports; tests now use `httpx2`); check it and remove it.
- A deeper visual redesign (D6) and a site-wide "popular airports" list once there's traffic (D5).
