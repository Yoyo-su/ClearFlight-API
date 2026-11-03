# Current milestone: CF-005 Frontend MVP

**Status:** In review (branch `feat/cf-005-frontend`; PR pending)
**Source of truth:** [docs/cf-005-design.md](cf-005-design.md) (approved r3), [docs/development-plan.md](development-plan.md) §1–2, §7
**Tracking:** [GitHub issue #6](https://github.com/Yoyo-su/ClearFlight-API/issues/6)
**Target window / estimate:** 16–29 Nov 2026 · ~16 h
**Last updated:** 2026-11-03

## Goal
A mobile-first, accessible web app where a traveller can search for an airport and open a shareable page with its local time, latest observed weather, how recent it is, and the experimental conditions index with its reasons. Every loading, unavailable, stale and error state has honest wording.

## Scope (from plan §5, issue #6 and the approved spec)
- React/TypeScript/Vite app in `frontend/`: search, airport page, not-found page; clocks; status, stale and error UI; shareable canonical URLs.
- Owner decisions D1–D11 (D-008), including the backend `current_until`/`stale_until` fields.
- Contract tests between the backend models, recorded fixtures and the TypeScript types.
- `make frontend-checks` and separate CI and release jobs.

## Out of scope
- Deployment, CORS, the public URL, the per-client rate limit (CF-006); traveller validation (CF-007).
- A site-wide "popular airports" list (D5), a deeper visual redesign (D6), and backend search-ranking changes.

## Acceptance criteria (issue #6)
- [x] End-to-end user flows work on mobile and desktop; accessible controls.
- [x] Relevant automated checks pass and user-visible errors are covered.
- [x] README / API contract updated where applicable.
- [ ] Work delivered in a PR from a separate branch; do not commit directly to main. (Branch ready; PR not yet opened.)

Plan exit evidence: "End-to-end flows pass on desktop/mobile, including unavailable/stale cases."

## Tasks
| ID | Task | Status | PR |
|---|---|---|---|
| CF-005.0 | Design spec + mock-up; owner walkthrough D1–D11; Codex design critique (1 High, 5 Medium, all addressed) | Done | |
| CF-005.1 | Backend: `current_until`/`stale_until` (D11); fixture recorder + contract test | Done | |
| CF-005.2 | Frontend scaffold (pinned packages), lint/typecheck/test/build | Done | |
| CF-005.3 | Search, airport page, all states, ageing, refresh/cooldown, request ownership, recently viewed | Done | |
| CF-005.4 | Unit/component tests and Playwright end-to-end tests (desktop + mobile, axe) | Done | |
| CF-005.5 | `make frontend-checks`, CI and release jobs, docs (README, ARCHITECTURE, D-008) | Done | |

## Verification evidence
- 2026-11-03 (after review fixes): `make run-checks` passes: 465 tests, coverage 97.83%, pip-audit clean.
- `make frontend-checks` passes:
  - `npm audit` reports 0 runtime advisories; the 11 moderate dev-only advisories (minimatch in the lint tooling) are below the high gate;
  - 118 unit/component tests, coverage 98.2% statements / 94.85% branches / 99.52% lines;
  - the build succeeds;
  - 40 Playwright tests on desktop and mobile Chromium pass, with axe (WCAG 2.1 A/AA) clean on every page and state, including all four level colours, and no horizontal scroll.
- Live smoke (2026-11-02, Docker backend + Vite dev server, desktop and Pixel 7):
  - `/airport/lhr` is rewritten to `/airport/EGLL` (4/10 moderate, gusts 23 kt); `KIX` becomes `/airport/RJBB`; KJFK showed 0/10 low; no horizontal overflow.
  - The provider's CDN again served a 2-hour-old RJBB report on one request, which the page correctly showed as stale and unscored. A minute later the next request got the current report.
  - The smoke run found a mobile layout bug (container padding reset on phones), now fixed.

- Reviews:
  - Round 1: quality-reviewer 2 Medium + 3 Low; Codex 3 Medium + 1 Low; requirements-validator spec deviations. All confirmed findings fixed:
    - the clock now ticks at each boundary;
    - superseded 503 retries are cancelled;
    - responses are validated against a runtime schema that the types derive from;
    - requests time out after 25 s;
    - every page has an h1, and the 400/404/not-found pages have a search field;
    - the shortcuts are always shown;
    - axe now covers moderate and high.
  - Round 2 (scoped Codex): 1 Medium (inconsistent responses could disable ageing), fixed with cross-field rules. Stopped per the rounds rule.
- One end-to-end failure seen once before the fixes was never reproduced (2 full runs + 144 repeats passed). The likely cause was a reused stale preview server; Playwright now always starts a fresh build.

## Risks / open questions
- Zone abbreviations depend on the browser (Chromium shows "UTC+0" for London, Node shows "GMT (UTC+0)"); the offset is always right.
- "6+" statute-mile visibility from the provider shows as "9.7 km or more" (a European report would say "10 km or more").
- Index bands remain heuristic (v0.1) until traveller validation (CF-007).

## Previous milestones
- CF-004 conditions API: done. PR #18 merged 2026-11-02 (`2325b4a`), issue #5 closed.
- CF-003 METAR weather adapter: done. PR #17 merged 2026-10-30 (`22a8a7b`), issue #4 closed.
- CF-002 airport catalogue: done. PR #16 merged 2026-10-30 (`618c726`), issue #3 closed.

## Follow-ups (discovered, not in scope)
- Search relevance: ties are broken alphabetically, so "london" lists Gatwick before Heathrow, and "kennedy" ranks Gahcho Kue (city "Kennedy Lake") above JFK. Consider ranking airports with scheduled service higher (OurAirports `scheduled_service`).
- Remove the deprecated legacy `/airport/{code}` route and its AviationStack/WeatherStack services in CF-006 (owner decision 2026-11-02).
- A deeper visual redesign (D6) and a site-wide "popular airports" list once there's traffic (D5).
- `docs/development-plan.md` §6 still shows CF-001 task checkboxes unticked, although issue #2 is closed. `docs/cf-001-baseline.md` has the actual status.

## Next task
Reviews (quality-reviewer, Codex, requirements-validator), then open the CF-005 PR.
