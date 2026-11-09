# ClearFlight — Development Plan v1.1

**Status:** **Approved by the owner 2026-11-09** (r3 with decisions P1–P6, §11; revised after the Codex design critique of r2, §13)
**Date:** 8 November 2026 (v1.0: 18 October 2026, in git history up to `d379dd6`)
**Repository:** https://github.com/Yoyo-su/ClearFlight-API
**Product name:** ClearFlight ("Airport weather, explained")
**Public beta:** deferred until Phase 2 is built (owner, 2026-11-07); no date set
**Capacity:** 5–10 hours per week
**Monthly operating budget cap:** £30 (unchanged hard constraint); Phase 2 uses **free data only** (owner, 2026-11-08)

## 0. Changes from v1.0

| Area | v1.0 | v1.1 |
|---|---|---|
| Scope | Weather-only pilot; flight tracking, delays and prediction explicitly deferred | **Phase 2 adds flight data:** live aircraft around the airport on a map, observed departures/arrivals, disruption signals, an on-demand flight lookup with best-effort delays, and a forecast outlook (§2) |
| Release order | CF-006 deploy, then CF-007 validation, after the weather MVP | **CF-006/CF-007 deferred** until Phase 2 is complete (owner, 2026-11-07) |
| Positioning | "Not a flight-delay prediction or tracking service" | Shows **observed** flight movements and **heuristic** disruption/forecast signals, each labelled. Still not a flight-safety assessment, not an official delay source, and no claim that a score predicts a particular flight's delay (§1) |
| Data sources | OurAirports, Aviation Weather Center (METAR) | Adds OpenSky Network (development/educational use only), adsb.lol (alternative), FAA NAS Status (US airports), AeroDataBox free tier (on-demand lookups), Aviation Weather Center TAFs (§3, §8) |
| Persistence | None beyond Redis cache; "database of historical observations" deferred | Still none: baselines come from provider history plus short-lived Redis data (§3) |
| Roadmap | CF-001–CF-007 | CF-001–CF-005 done; cleanup done (PRs #20–#22); **Phase 2: CF-008–CF-013** (forecast first); then CF-006, CF-007 only after all of Phase 2 (§5) |

Phase 1 (CF-001 to CF-005) is complete and merged. Its scope, contract and decisions stay as recorded in D-001 to D-009 and `docs/API.md`.

## 1. Product and positioning

ClearFlight is a traveller-facing view of **what is observed at an airport**: weather, aircraft and movements, plus clearly labelled **heuristic** signals (a conditions index, a forecast outlook, disruption signals).

**Claims rules (all Phase 2 features):**
- Observed data is labelled "observed" with its source and age; forecasts are labelled "forecast" with their validity period.
- A heuristic signal is never presented as an official delay, a prediction for a particular flight, or a safety assessment. Every page keeps the disclaimer.
- Delays are shown only where a scheduled time is known for that flight, and are labelled **"partial: not every flight is covered"**. There is no complete delay board on free data (RQ-002, 2026-11-08).
- Missing or uncertain data shows as unknown or unavailable, never as a reassuring value (as in v1.0 §7).

**"Predictive scoring" in v1.1** means:
- (a) a **forecast outlook**: the conditions index applied to the official airport forecast (TAF) for the next hours;
- (b) **disruption signals** derived from observed traffic.

A statistical or machine-learning model that predicts delays for a particular flight is **out of scope for v1.1**: free data lacks the complete schedules and history it would need. Revisit it in a later plan (§10) (owner decision P1, 2026-11-08).

## 2. Phase 2 features

### Must have before public beta (in addition to the v1.0 MVP)
1. **Airport map:** the airport, its weather, and live aircraft within a radius (about 40 km), refreshed every 15–30 s while the page is visible. Each aircraft shows its callsign, altitude, speed and heading, plus registration and type where the feed has them. Shown as observed data, with its source and age.
2. **Observed movements:** recent departures and arrivals at the airport, with observed times derived from position data (an aircraft becoming airborne or landing within the airport area). Shown by callsign; the flight number is added where a lookup or match provides it. Labelled as observed and possibly incomplete.
3. **Forecast outlook:** the airport's TAF (Aviation Weather Center) for the next 6–12 hours, with the conditions index applied per forecast period. Labelled as a forecast, keeping TAF semantics: TEMPO, BECMG and PROB periods are shown as such.
4. **Disruption signals:** heuristic, observation-based indicators for any airport.
   - departures and arrivals in the last hour compared with this airport's usual rate for that hour and weekday;
   - aircraft in holding patterns nearby;
   - go-arounds (aborted landings);
   - each shown with its basis and a level (normal, elevated, high, unknown).
   - For US airports, **FAA NAS Status** airport events (delay programmes, ground stops, closures) are shown alongside as an official source.
5. **Flight lookup:** look up a flight by number (e.g. BA123) or callsign. It shows the scheduled times from AeroDataBox's free tier (cached and attributed; at most ~400 units a month) next to the observed times where matched.
   - A **delay figure** is shown only when both times describe **the same event**: scheduled runway takeoff/landing vs observed takeoff/landing, or the source's own actual gate times vs scheduled gate times.
   - Gate times are never compared with runway times, because the difference would include taxiing. Otherwise both times are shown side by side ("Scheduled departure 10:05 (gate) · Observed takeoff 10:31") with no delay figure.
   - **Matching a flight instance** requires all of: the flight number or callsign; the flight date in the airport's local time; the origin and destination airports; and an observed time within a plausible window of the scheduled time.
   - Repeated daily flights, multi-leg services and codeshares that don't resolve to exactly one instance are "not matched".
6. **Honest states for all of the above:** a source unavailable, an exhausted quota, no aircraft in range, no TAF for the airport, no FAA data (non-US), or a flight not found.

### Still deferred
- Complete delay boards.
- Per-flight delay prediction models (P1).
- Paid flight-data subscriptions.
- Alerts, accounts, native apps, offline mode.
- A historical database.
- Commercial use.

### Validation set
EGLL, RJBB and KJFK remain the pilot airports. Each Phase 2 feature is validated at all three (KJFK is the only one with FAA data). Coverage gaps are documented rather than hidden.

## 3. Architecture (Phase 2 additions)

```text
Browser (React + TS + Vite)
  ├─ airport page: weather · conditions · forecast outlook · disruption signals
  ├─ airport map: aircraft layer (polled) · weather
  └─ flight lookup
        │
FastAPI (/v1)
  ├─ existing: catalogue, METAR adapter, conditions index
  ├─ TAF adapter (Aviation Weather Center)                 ── free
  ├─ positions adapter: OpenSky (dev) | adsb.lol (alternative) ── free; swappable (§8 gate)
  ├─ movements service: airborne/landing transitions within the airport area,
  │     recent movements + collection-window metadata kept in Redis (short TTL, e.g. 6 h)
  │     (positions are polled only while someone views the airport: no background collection, P6)
  ├─ baselines: hourly movement counts from OpenSky historical flights (nightly-batch
  │     data, previous days), cached; no own database
  ├─ disruption service: rate vs baseline, holding, go-arounds  (heuristic, versioned)
  ├─ FAA NAS Status adapter (US airports)                  ── free
  └─ schedules adapter: AeroDataBox free tier (on-demand only, cached ≤ 7 days, attributed)
        │
      Redis (cache, short-lived movements, quota counters)
```

Principles carried over from Phase 1:
- Every provider sits behind an adapter with timeouts, typed errors, caching and a request/credit budget below the provider limit (D-006).
- Freshness comes from a single authority with explicit eligibility times (D-007/D-008).
- Recorded fixtures and contract tests are kept on both sides (D-008).
- No live calls in CI.

**Request/credit budgets (to verify at implementation):**
- **OpenSky:** an authenticated account gets 4,000 state credits/day; a ≤25 sq° box costs 1 credit. So the map needs **on-demand polling only while a page is open, shared through the cache**: one bounding-box query per airport per 30 s at most, plus a daily cap with a clear "limit reached" state. That's about 2,880 credits/day for one airport viewed continuously.
- **AeroDataBox free:** 400 units/month at 1 req/s, endpoint tiers 1/2/6 units. On-demand lookups only, cached and counted against a monthly budget.
- **FAA NAS Status:** cached, polled at most every few minutes.

**Completeness rule for traffic-based signals.** A movement count is valid only for a window with **continuous collection**, which is recorded as coverage metadata: poll times, gaps, provider errors and quota stops.
- A disruption signal from the current hour needs at least 90% of the window covered with no gap over 5 minutes (thresholds to confirm in CF-012). Otherwise the signal is `unknown`.
- Cold starts, restarts, outages and quota exhaustion make the window incomplete.
- The current count and its baseline must use **the same movement definition and source type**: either both from live-position detection, or a validated adjustment between the live detector and the provider's historical flights. Otherwise the rate signal is `unknown`.
- Tests cover gaps, cold starts, quota stops and source mismatch.

**No background collection (owner decision P6, 2026-11-09):** positions are polled only while someone views an airport, shared through the cache.
- The traffic-rate signal (movements vs the usual rate) is therefore valid only when the current window is complete under the rule above. That usually means someone has watched the airport for the whole window, so the signal will **often be `unknown`**, and that's expected.
- Holding and go-around signals work from what is observed while the page is open.
- Revisit background collection only with a licensed or permitted source and a budget (a plan increment).

**Quota and rate model** (for every provider with a hard limit):
- **Reservation:** an atomic reserve-before-call per request (a Redis script that checks and increments the period counter and the per-second slot together). Retries are charged too.
- **Single-flight:** one caller per uncached key; concurrent cache misses wait for that one request instead of each calling.
- **Fail closed:** if Redis is unavailable, providers with a hard monthly or daily quota (AeroDataBox, OpenSky credits) are **not called**, and the state is `quota_exhausted` or unavailable. Keyless providers fall back as METAR does (D-006).
- **Counter loss:** where the provider reports remaining quota (e.g. RapidAPI rate-limit headers, to verify), that is the source of truth and the counter is reset from it. Otherwise, a counter missing mid-period is treated as exhausted until the period resets.
- Tests cover concurrency, Redis down, retries and counter loss.

**Open technical questions for implementation planning** (verified per milestone, live probes allowed in development):
- The OpenSky endpoints and fields for positions and historical flights, and its departures interval inconsistency (RQ-002).
- How reliably movements can be detected from position data at each pilot airport (on-ground flags, coverage near the ground).
- Which TAF format the AWC API returns.
- The current FAA NAS Status endpoint.
- AeroDataBox endpoint tiers and fields.
- Map tiles: the provider, usage policy and attribution (OpenStreetMap's tile policy forbids heavy use; a small research item, RQ-003).

## 4. API contract additions (proposed; finalised per milestone)

| Endpoint | Purpose |
|---|---|
| `GET /v1/airports/{code}/forecast` | TAF periods with per-period conditions index (forecast) |
| `GET /v1/airports/{code}/aircraft` | Live aircraft within the airport area (observed positions, source, age) |
| `GET /v1/airports/{code}/movements` | Recent observed departures/arrivals (observed times, callsign, matched flight number if known) |
| `GET /v1/airports/{code}/disruption` | Disruption signals with basis and level; FAA events for US airports |
| `GET /v1/flights/{number}` | Flight lookup: scheduled times (AeroDataBox), observed times where matched, best-effort delay |

Errors and states follow v1.0 §4 and D-007:
- 400 for an invalid code or number;
- 404 for an unknown airport or flight;
- 502, 503 (with Retry-After) and 504 for provider failures;
- a known airport without data is **200 with an unavailable state**, not 404.

New states:
- `quota_exhausted`: a provider budget is used up;
- `no_aircraft`: the feed answered for the area and reported no aircraft (a valid empty result);
- `coverage_unknown`: the feed couldn't be queried or its coverage of the area isn't established. An empty response alone never proves coverage, so zero traffic is reported as observed zero only with a healthy feed;
- `not_applicable`: FAA outside the US.

## 5. Roadmap (Phase 2, then release)

Estimates assume 5–10 h/week. They are rough planning figures, refined in each milestone's plan.

| Milestone | Work | Estimate | Exit evidence |
|---|---|---:|---|
| **CF-008 Forecast outlook** | TAF adapter + parser, per-period conditions index, `/forecast`, UI | 10–14 h | TAF fixtures incl. TEMPO/BECMG/PROB; forecast never shown as observed |
| **CF-009 Flight positions** | Positions adapter (OpenSky, adsb.lol alternative behind one interface), credit budget, cache; `/aircraft` endpoint | 8–10 h | Recorded fixtures pass; live dev probe shows aircraft at all three pilot airports; budget enforced |
| **CF-010 Airport map** | Map page/section (map library + tiles per RQ-003), aircraft and weather layers, polling only while visible, attribution | 8–12 h | Desktop/mobile e2e with axe; no polling in background tabs; honest empty/limit states |
| **CF-011 Observed movements** | Movement detection from positions (polled while viewed), coverage metadata, Redis short-term store, `/movements`, UI list | 10–12 h | Detection tests on recorded tracks; coverage-gap tests; P5 thresholds checked against airport boards for a busy hour per pilot airport |
| **CF-012 Disruption signals** | Baselines from historical flights, rate/holding/go-around signals (heuristic v0.1, versioned), FAA NAS adapter, `/disruption`, UI | 12–16 h | Deterministic signal tests; KJFK FAA events; non-US shows `not_applicable` for FAA; no "delay prediction" wording |
| **CF-013 Flight lookup + best-effort delays** | AeroDataBox adapter (quota model, single-flight, cache, attribution), flight-instance matching (number/callsign, local date, route, time window), `/flights/{number}`, UI | 10–14 h | Quota/rate never exceeded in concurrency tests; delay only for same-event times; tests for taxi offsets, repeated numbers, multi-leg and codeshares; "partial" label |
| **CF-006 Public deployment** | as v1.0, plus the **data-licence gate** (§8); only after CF-008–CF-013 are all done (P2) | 8–10 h | v1.0 checklist + gate passed |
| **CF-007 Traveller validation** | as v1.0, now including flight features | 6–8 h | as v1.0 |

**Phase 2 total:** about 58–78 h, roughly 7–16 weeks at 5–10 h/week.

Each milestone follows the Phase 1 workflow: its own design or plan; a CORMORANT critique where eligible; tests on both sides; reviews; a PR from a branch.

## 6. Definition of done (unchanged from v1.0, plus)
- Every new provider:
  - is behind an adapter with recorded fixtures and a contract test;
  - has a budget below its documented limit, enforced in code and tested;
  - has its attribution displayed where its terms require it.
- Every heuristic signal has a version, documented components, deterministic tests and claims-wording tests (as for the conditions index).

## 7. Acceptance gates (additions to v1.0 §7)
- **Map:** aircraft near each pilot airport render on desktop and mobile; source, age and attribution are visible; no requests from background tabs.
- **Movements:** detection is validated against a documented manual sample at each pilot airport, for at least one busy hour each, against the airport's published board. Proposed thresholds **(owner decision P5, 2026-11-09)**: at least 90% of movements detected and at most 5% false movements. An airport that misses them shows movements as "experimental" and has no traffic-rate signal.
- **Forecasts:** forecast periods are labelled as forecast; the observed and forecast indices are visually distinct.
- **Disruption signals:** they never use "delay prediction" or safety wording; they show their basis; an unknown baseline gives "unknown".
- **Flight lookup:** quota exhaustion degrades to a clear state; delays are labelled partial.
- **Data licences:** see §8.

## 8. Data sources, costs and licences

| Source | Use | Cost | Terms (RQ-002, 2026-11-08; re-verify at implementation) |
|---|---|---|---|
| Aviation Weather Center (METAR, TAF) | Weather, forecast | $0 | US government data |
| OurAirports | Airport catalogue | $0 | Public domain |
| OpenSky Network REST | Positions, historical flights (baselines) | $0 | "Non-profit research and educational use only"; **any operational use in a live product needs a written licence** (owner read the terms, 2026-11-08). **Development/educational use only** (owner decision) |
| adsb.lol | Positions (alternative) | $0 | Public API, ODbL 1.0 (attribution, share-alike on derived databases); keys announced, limits dynamic |
| FAA NAS Status | US airport events | $0 | Public; endpoint/terms to re-verify |
| AeroDataBox (RapidAPI free) | Scheduled times for lookups | $0 (400 units/month) | Attribution required; cache ≤ 7 days; commercial use generally needs a paid plan |
| Map tiles | Map background | $0 target | RQ-003: a provider whose usage policy allows this app |
| Hosting (CF-006) | as v1.0 | about $7/month | as v1.0 |

**Data-licence gate before CF-006 (public deployment):**
- **every** OpenSky dependency is covered: live positions, historical flights, the **baselines derived from them**, and any cached copies. That means either OpenSky's written licence covering all of them, or all of them switched to a permitted source;
- adsb.lol is the researched alternative for positions; its daily historical dumps are a candidate for baselines (to verify). ODbL obligations (attribution; share-alike for derived databases made public) must be met;
- after a switch, OpenSky-derived caches and baselines are purged and rebuilt from the new source, and the purge is verified;
- AeroDataBox attribution and caching terms met;
- map tile usage policy met.

No paid data without owner approval. The £30/month cap is unchanged.

## 9. Main risks (additions)

| Risk | Impact | Mitigation |
|---|---|---|
| OpenSky terms forbid public live use | Feature can't ship as built | Adapter design; adsb.lol alternative; licence gate (§8) |
| Free quotas (OpenSky credits, AeroDataBox 400 units) run out | Empty maps or lookups | Shared cache; polling only while visible; budgets in code; quota states in the UI |
| Movement detection is unreliable at some airports (ground coverage) | Wrong or missing movements | Validate per pilot airport; label as observed and possibly incomplete; show coverage gaps |
| Users read heuristic signals as predictions | Loss of trust | Claims rules (§1), wording tests, factors shown |
| Callsign↔flight-number mismatch (e.g. UAE58E = EK408) | Wrong or missing delays | Exact matches only, otherwise "not matched"; partial label |
| Scope growth (six milestones before any public release, P2) | A long gap before feedback from real travellers | Milestones independently mergeable and usable locally; the owner can revisit P2 by a plan version increment |
| Provider terms change | Rework | Re-verify terms at each milestone and at CF-006 |

## 10. Later (not in v1.1)
Revisit after Phase 2 and, ideally, traveller feedback:
- Per-flight delay prediction (needs complete schedules and history, probably paid).
- A paid schedule source for complete delays (AeroDataBox paid tiers reportedly from about $7.50/month, to verify).
- Popular airports, and a visual redesign.

## 11. Owner decisions (2026-11-08)
- **P1:** "Predictive scoring" in v1.1 = forecast outlook (TAF) + heuristic disruption signals; per-flight delay prediction is deferred (§1, §10).
- **P2:** No public release until all of Phase 2 (CF-008–CF-013) is done.
- **P3:** Forecast outlook first (CF-008), then positions → map → movements → disruption → lookup.
- **P4:** OpenSky is for development/educational use only; a licence or source decision is mandatory before CF-006 (§8).
- **Free data only** for Phase 2; complete per-flight delays are not possible on free data, so they're best-effort and labelled partial.

- **P5 (2026-11-09):** movement detection must find at least 90% of movements with at most 5% false at a busy hour per pilot airport; otherwise "experimental" and no traffic-rate signal (§7).
- **P6 (2026-11-09):** no background collection; positions are polled only while viewed, so traffic-rate signals are often `unknown` (§3).
- Still to decide later: map tiles (RQ-003, in CF-010) and an adsb.lol key (before CF-006).

## 12. Change policy
Scope or acceptance-criteria changes need a documented version increment (v1.2 for the next substantive change). New features found during building go to a prioritised backlog, not straight into scope.

## 13. Design critique (CORMORANT, r2 → r3)
Codex critique of the frozen r2 (2026-11-08): 4 High and 1 Medium, all confirmed, none refuted.
1. The licence gate missed the baselines and caches derived from OpenSky history. Fixed: the gate covers every OpenSky dependency, with a verified purge after any switch.
2. Delay compared gate times with runway times and resolved flights by number only. Fixed: same-event rule plus instance matching by date, route and time window.
3. `no_coverage` conflated a valid empty result with unknown coverage. Fixed: split into `no_aircraft` and `coverage_unknown`.
4. No completeness rule for the current traffic window, and no comparability with the baselines. Fixed: coverage metadata, a continuity threshold and a like-for-like rule. The owner then chose no background collection (P6), so the signal is often `unknown` by design.
5. No quota failure or recovery model. Fixed: atomic reservation, single-flight, fail closed, counter-loss rule and tests.
