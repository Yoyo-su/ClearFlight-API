# Current milestone: post-CF-005 cleanup (before CF-006)

**Status:** In progress (three small PRs). CF-006 public deployment waits until the owner has hosting set up.
**Source of truth:** owner's cleanup list, 2026-11-04 (items 1, 2, 3, 6, 7, 8, 9, 10)
**Last updated:** 2026-11-05

## Goal
Tidy the app, dev setup and docs before public deployment, without changing the v1 contract beyond the recorded fixes.

## Work
| PR | Items | Status |
|---|---|---|
| 1. Housekeeping | 6 Compose `frontend` dev service · 7 `httpx2` for Starlette's test client (removes the deprecation warning) · 8 milestone and ARCHITECTURE status · 10 development-plan §6 ticks | In review |
| 2. Search and wording | 1 rank airports with scheduled service higher · 2 "6+" visibility reads "10 km or more" · 3 full timezone name when the browser has no abbreviation | Planned |
| 3. README | 9 evaluate the README for portfolio readers; propose an outline for owner approval, then rewrite | Planned |

## Next milestone: CF-006 Public deployment (blocked on hosting)
**Tracking:** [GitHub issue #7](https://github.com/Yoyo-su/ClearFlight-API/issues/7). Plan §5: Cloudflare Pages, Render, Upstash; secrets, CORS, limits, HTTPS, logs, smoke checks; release `v0.1.0`. Also remove the deprecated legacy `/airport/{code}` route and its AviationStack/WeatherStack services (owner decision 2026-11-02). The AviationStack trial access ends around 2026-11-12 (per the owner, 2026-11-05), after which that route can't work at all; the pilot itself doesn't use AviationStack.

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
