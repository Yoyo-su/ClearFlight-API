# Current milestone: CF-011 Observed movements

**Status:** Implementing on `feat/cf-011-observed-movements` (design r3 approved 2026-11-15, D-014); CF-010 merged (PR #26)
**Source of truth:** [docs/development-plan.md](development-plan.md) v1.1 (§5 CF-011, §7, §8); decisions D-012, D-013, D-014
**Last updated:** 2026-11-15

## Goal
Recent departures and arrivals on the airport map, detected from live positions while the page is open, labelled observed or inferred, honest about what was watched and validated against airport boards before being called validated.

## Next task
- **Done:** field elevation in the catalogue; detector, store and positions hook (recorded-track fixtures, 10-mutant sweep); `GET /v1/airports/{code}/movements`; the "Recent movements" list in the map section (unit, contract, e2e with axe).
- **P5 (open exit criterion; every airport `experimental`):** fresh hours under the adopted identity rule (design §9). EGLL 2026-11-15 16:00 UTC: found 88.0%, false 1.5%, not validated (7 of 9 misses at provider timeouts). KJFK: not assessed (no arrivals board for the hour, recording too short for gate times, regional-operator callsigns). RJBB 2026-11-16 09:00 JST: found 77.4%, false 24.2%, not validated (take-off dropouts, timeouts, cargo not on the board). Details in `docs/validation/`.
- **After P5 (owner, 2026-11-16):** inferred movements across up to 120 s of missed polls (design §3). Fresh P5 hours under the current rules are a follow-up, with JFK's three fixes and Kansai's board pasted by the owner.
- **Remaining:** Codex review of the gap rule; PR with every airport experimental.

## Previous: CF-010 Airport map (merged, PR #26)
- **Reviews:**
  - quality-reviewer: 3 Medium and 7 Low, fixed;
  - Codex: r1 1H/5M/2L, r2 0H/3M/4L, scoped r3 0H/1M/1L, all fixed with tests.
  
  The r3 fixes (total basemap outage, airport marker selection) weren't re-reviewed, as the review cap was reached with no open High.
- **Done:**
  - RQ-003 map tiles: OpenFreeMap, with MapLibre;
  - `/nearby-conditions` (AWC bbox) and `/map/radar` (RainViewer behind `RAINVIEWER_EDUCATIONAL_USE`);
  - the polling hook, with every request path gated on "active" and visibility;
  - the "Live map" section: lazy MapLibre, aircraft and station layers, the radar toggle (off by default), the always-visible list, and honest, expiring states;
  - contract fixtures;
  - unit tests, and e2e tests with axe (desktop and mobile), including request counting while hidden and the real WebGL canvas.

## Phase 2 order (plan v1.1)
CF-008 forecast → CF-009 positions → CF-010 map → CF-011 movements → CF-012 disruption signals → CF-013 flight lookup. Then CF-006 public deployment (with the data-licence gate) and CF-007 validation.

## Completed since CF-005
- CF-009 live positions: PR #25 merged 2026-11-11 (`b869095`). Spec: [cf-009-design.md](cf-009-design.md); decision D-012.
- CF-008 forecast outlook: PR #24 merged 2026-11-10 (`429d1ca`). Spec: [cf-008-design.md](cf-008-design.md); decision D-011.
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
- A deeper visual redesign (D6) and a site-wide "popular airports" list once there's traffic (D5).
