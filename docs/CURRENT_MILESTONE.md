# Current milestone: CF-002 Airport catalogue

**Status:** Not started (no CF-002 branch or PR yet)
**Source of truth:** [docs/development-plan.md](development-plan.md), §5 roadmap and §7 acceptance gates
**Tracking:** [GitHub issue #3](https://github.com/Yoyo-su/ClearFlight-API/issues/3)
**Target window / estimate:** 26 Oct – 1 Nov 2026 · ~8 h
**Last updated:** 2026-10-18

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
- [ ] Search endpoint works; timezone/DST tests pass.
- [ ] Relevant automated checks pass and user-visible errors are covered.
- [ ] README / API contract updated where applicable.
- [ ] Work delivered in a PR from a separate branch; do not commit directly to main.

Plan exit evidence: "Search endpoints and timezone tests pass for 3 pilot airports."

Related plan constraints:
- Use IANA timezone IDs, never a fixed GMT offset. Derive or cross-check from coordinates and a maintained mapping (plan §3).
- Proposed route: `GET /v1/airports/search?q=...`. Invalid search returns 400, no result returns a clear empty or 404 state (plan §4).
- Preserve the legacy `/airport/{airport_code}` route for now.

## Tasks
| ID | Task | Status | PR |
|---|---|---|---|
| — | Break down into small tasks at the start of CF-002 | Not started | |

## Verification evidence
None recorded yet for CF-002.

## Carried over from CF-001 (issue #2 closed)
- [ ] Configure required reviewers on the GitHub `release` environment (manual GitHub setting; see `docs/cf-001-baseline.md`).
- Deferred to CF-004: mapping provider failures to 400/404/502/504, and removing API access keys from URLs hashed into cache keys.

## Risks / open questions
- Choice of timezone derivation source (dependency or dataset), which needs a decision recorded in `docs/DECISIONS.md`.
- How the OurAirports data is stored and refreshed (build-time import vs. committed snapshot).

## Follow-ups (discovered, not in scope)
- `docs/development-plan.md` §6 still shows CF-001 task checkboxes unticked, although issue #2 is closed. `docs/cf-001-baseline.md` has the actual status.

## Next task
Branch `feat/cf-002-airport-catalogue` from `main`, then plan the OurAirports import and timezone approach for approval.
