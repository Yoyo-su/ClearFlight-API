# ClearFlight — Development Plan v1.0

**Status:** Finalised planning baseline  
**Date:** 18 October 2026  
**Repository:** https://github.com/Yoyo-su/ClearFlight-API  
**Pilot name:** ClearFlight Airport Pulse  
**Target public beta:** 6 December 2026  
**Initial pilot review:** 13 December 2026  
**Capacity:** 5–10 hours per week  
**Monthly operating budget cap:** £30 (hard constraint, excluding optional one-off domain purchase)

## 1. Confirmed decisions and objectives

| Topic | Locked decision |
|---|---|
| Business vs career value | Commercial validation and portfolio value equally important |
| Audience | Everyday travellers |
| MVP scope | Airport profile + observed weather + explainable experimental conditions index |
| Frontend | Mobile-first responsive web app; React + TypeScript + Vite |
| Backend | Existing FastAPI codebase, incrementally refactored |
| Authentication | None in pilot |
| Pricing | Free for pilot testers; no payment systems |
| Delivery | Solo, AI-assisted; small GitHub issues and reviewed pull requests |
| Data | OurAirports metadata and Aviation Weather Center METAR observations, subject to provider policy and coverage validation |
| Operational cost | Under £30/month; prefer fixed or capped tiers |

### Outcomes

1. **Engineering outcome:** A reproducible, documented, public HTTPS application that uses an API, validated weather source, Redis caching, automated tests and CI/CD controls.
2. **Product outcome:** Evidence from actual travellers about whether an understandable, shareable airport-conditions page solves a problem better than their current alternatives.
3. **Portfolio outcome:** A readable repository, architecture diagram, decisions/limitations notes, tests, working demo, and concise case study that demonstrates end-to-end development.

**Positioning:** ClearFlight is a traveller-facing presentation of *observed airport weather*. It is not a certified aviation briefing, flight-safety assessment, flight-delay prediction or flight-tracking service. Do not imply that a numeric score means a flight will be delayed or is safe/unsafe.

## 2. In-scope product features

### Must have before public beta

- Search airports by name, city, IATA code or ICAO code (with sensible matching and clear no-result state).
- Airport name, codes, city/country and IANA timezone.
- Live airport-local clock calculated in browser from the IANA timezone, including DST handling; UTC also available.
- Latest available airport observation: temperature, wind speed/direction and gusts when reported, visibility, cloud/ceiling information and present weather where available; pressure and dew point if available.
- Source attribution, UTC observation timestamp, last-fetched timestamp and freshness status.
- Explainable 0–10 **experimental conditions index** only when the required data exists and is sufficiently recent; otherwise `unknown`. Give reasons for the score.
- Mobile-friendly layouts, accessibility basics, loading/retry/error/stale/unknown states.
- Shareable airport URLs, e.g. `/airport/EGLL`.
- Documented versioned backend responses, public HTTPS, monitoring and bounded provider requests.

### Explicitly deferred

Flight-number tracking; arrivals/departures boards; airport traffic index; predictive flight delay models; routes/itineraries; account creation; paid subscriptions; AI chat; alerts; native applications; a full PWA/offline mode; a database of historical observations. Do not buy a paid flight-data subscription for the weather-only pilot.

### Initial airport validation set

EGLL / LHR (London Heathrow), RJBB / KIX (Kansai International), KJFK / JFK (John F Kennedy). Validate each station's actual METAR coverage before declaring support. Broader airport searching may be enabled for stations whose metadata and observation coverage pass checks; unsupported stations must show honest unavailable states.

## 3. Architecture

```text
Browser (React + TS + Vite, Cloudflare Pages)
   |
   +--> GET /v1/airports/search?q=...
   +--> GET /v1/airports/{iata_or_icao}/conditions
                         |
                 FastAPI on Render
                         |
          +--------------+--------------+
          |              |              |
      metadata       Redis cache     METAR adapter
      (OurAirports)   (Upstash)       (Aviation Weather Center)
          |              |              |
      airport        expiry/         HTTPS, timeout,
      indices +      resilience      retries + rate cap
      IANA zone
```

Use local Docker Compose for development with Redis available only on the internal Compose network. For hosted Redis, support authenticated `rediss://` connection settings; do not expose port 6379 publicly. Keep environment secrets outside source control and browser bundles. Use a provider adapter so weather sources can later be replaced without changing the public response schema.

**Timezone:** OurAirports does not provide authoritative IANA timezone IDs for every airport. Derive/cross-check timezones using coordinates and a maintained mapping; start by explicitly validating the three pilot airports and test DST boundaries. Never rely on a fixed GMT offset.

**Weather:** Aviation Weather Center's API supports JSON METAR responses worldwide but coverage and fields vary. It specifies a maximum 100 requests/minute, recommends limiting query scope/frequency and sets no browser CORS access. All provider requests go through the backend. Apply stricter application-level throttling, a descriptive User-Agent and cache responses. Confirm appropriate use and attribution obligations before any commercial launch.

**Cache policy proposal:** airport metadata downloaded/imported at development/build time or via infrequent update; cached METAR API responses for ~10–15 minutes (configurable, to reduce redundant requests); keep source `observed_at` separately from the cache `fetched_at`. An observation <=90 minutes old is eligible to be called current, 90–180 minutes old is shown as stale, and >180 minutes old is unavailable for numeric scoring. These are *pilot thresholds to validate*, not statements about all stations' publication schedules. Redis outage must degrade cleanly to tightly rate-limited provider requests or a controlled 503, not bring down the process.

**Conditions index v0.1:** Build an explicitly heuristic 0–10 *observed conditions severity* index with documented components and deterministic fixtures. Candidate factors: sustained wind/gusts, visibility, reported cloud ceiling and reported phenomena. Avoid treating any cloud-cover percentage or precipitation accumulation as present when METAR omits it. Do not infer risk to any particular flight or aircraft; exclude a score when source fields are inadequate. Expose score factors and a one-sentence explanation. No ML or aviation-operational claims.

## 4. Backend API contract (proposed for CF-004)

| Endpoint | Purpose |
|---|---|
| `GET /health` | Lightweight liveness response |
| `GET /v1/airports/search?q=...` | Name/city/IATA/ICAO search |
| `GET /v1/airports/{code}/conditions` | Normalized airport metadata, observation, freshness and score |

Preserve the old `/airport/{airport_code}` temporarily to avoid regressions, then document its replacement. Canonical airport routes use ICAO codes while accepting IATA lookups.

Example shape (illustrative unavailable-data response, **not live data**):

```json
{
  "airport": {
    "name": "Heathrow Airport",
    "iata": "LHR",
    "icao": "EGLL",
    "city": "London",
    "country": "United Kingdom",
    "timezone": "Europe/London"
  },
  "observation": {
    "source": "Aviation Weather Center",
    "observed_at": null,
    "fetched_at": null,
    "temperature_c": null,
    "wind_speed_kt": null,
    "wind_gust_kt": null,
    "wind_direction_deg": null,
    "visibility_m": null,
    "ceiling_ft": null,
    "pressure_hpa": null,
    "weather_phenomena": []
  },
  "conditions": {
    "score": null,
    "level": "unknown",
    "factors": [],
    "explanation": "No current observation is available."
  },
  "data_status": "unavailable"
}
```

Errors: 400 invalid search/code format, 404 airport not found, 429 app rate-limit, 502 failed upstream response, 503 temporarily unavailable. **A known airport without a current METAR is not a 404:** return valid airport metadata with `data_status=unavailable` and `score=null`, or a documented degraded response. Never return a synthetic observation. Use Pydantic models, response validation, timeouts, explicit upstream HTTP status handling, and error-safe logs.

## 5. Eight-week implementation roadmap

| Milestone | Target window | Estimated hours | Work | Exit evidence |
|---|---|---:|---|---|
| **CF-001 — Baseline recovery** | 19–25 Oct | 7 | Branch, local Docker run, dependency audit, pytest baseline, secure Compose/Redis config, add PR CI, fix README | Docker/API runs; tests and CI pass; no public Redis port; clean instructions |
| **CF-002 — Airport catalogue** | 26 Oct–1 Nov | 8 | Import OurAirports; index IATA/ICAO/name/city; validate IDs, timezone mapping, DST | Search endpoints and timezone tests pass for 3 pilot airports |
| **CF-003 — Weather adapter** | 2–8 Nov | 10 | METAR integration; parsing, missing fields, provider errors, retry/backoff, cache and data freshness | Mocked/recorded fixtures pass; real smoke lookups demonstrate source/age |
| **CF-004 — Conditions API** | 9–15 Nov | 8 | Pydantic response models; define cautious heuristic index; explanations, tests, API docs | Stable v1 contract; deterministic scoring; stale/missing never presented as low risk |
| **CF-005 — Frontend MVP** | 16–29 Nov | 16 | React/Vite/TS app; airport search; responsive dashboard; local clock; status messages; shareable URL | End-to-end flows pass on desktop/mobile, including unavailable/stale cases |
| **CF-006 — Public deployment** | 30 Nov–6 Dec | 8 | Cloudflare Pages, Render, Upstash; secrets, CORS, limits, HTTPS, logs, smoke checks | Public release checklist passes; release `v0.1.0`; pilot URL works |
| **CF-007 — Traveller validation** | 7–13 Dec | 6 | Recruit testers, survey, inspect errors and costs, prioritise next improvements | 10–20 testers targeted; summary and documented go/iterate/stop decision |

**Total planning effort:** approximately **63 hours** (average just under 8 hours per week). If actual available time remains closer to 5 hours/week, shift the release date rather than adding untested features. The schedule is contingent on METAR coverage, package compatibility and deployment availability.

### Definition of done for each engineering milestone

- Changes merged by pull request from a short-lived branch; `main` remains releasable.
- Relevant tests, lint and formatter checks pass; no new secret exposure or high-severity dependency issues.
- Endpoint/schema changes documented; meaningful edge cases covered.
- User-visible failure states reviewed, not only the success path.
- GitHub Issue includes evidence of what passed and outstanding constraints.

## 6. First milestone detailed tasks — CF-001

- [ ] **CF-001.1** Branch `pilot/cf-001-baseline`; record current main SHA and existing CI history.
- [ ] **CF-001.2** Reproduce Python/Docker environment, review dependency pins and check `.env.template` vs Docker Compose (`REDIS_HOST=redis` inside Compose).
- [ ] **CF-001.3** Run existing test suite; record count, failures and coverage rather than assuming old green CI guarantees current correctness.
- [ ] **CF-001.4** Improve GitHub Actions: pull-request validation, non-mutating formatter check, dependency audit, Docker build; reconsider existing Docker Hub push job until release process is defined.
- [ ] **CF-001.5** Remove public Redis port mapping for development unless specifically needed and bound to loopback; support future secure hosted REDIS_URL.
- [ ] **CF-001.6** Add provider timeouts/HTTP error guards where necessary to establish a stable baseline; deep METAR adaptation belongs to CF-003.
- [ ] **CF-001.7** Confirm health endpoint, reproducible Docker command, sample tests and README setup instructions.

Note that GitHub Actions passed at the last recorded September 2025 commit; a fresh run on current dependencies is required. The old GitHub workflow builds and pushes to Docker Hub but does not itself deploy a publicly accessible web service.

## 7. Public pilot acceptance gates

### Function and data

- [ ] A traveller can search by airport name, city, IATA or ICAO and open an airport page without an account.
- [ ] EGLL, RJBB and KJFK metadata and timezone mappings verified; DST tests pass where applicable.
- [ ] Weather values and unit conversions match provider fixtures; source, observation age and timestamp visible.
- [ ] 204/no-observation, provider timeout, invalid code, rate limit and Redis outage produce sensible states and response codes.
- [ ] Score uses adequate **current** observations and displays its major factors; missing/stale observations show `unknown`, never reassuring numeric scores.
- [ ] There are no claims that conditions scores predict flight delays, flight safety or operational disruption.

### Engineering and operations

- [ ] Docker Compose builds locally and a fresh CI pipeline passes on pull requests and release branch.
- [ ] Key unit and endpoint paths are covered by automated tests; target >=80% coverage for new transformation/scoring logic, while prioritising meaningful tests over a single repository-wide number.
- [ ] HTTPS frontend and backend respond from the public URLs; only intended origins are CORS-allowed; secrets inaccessible to clients.
- [ ] Mobile and desktop smoke checks pass; keyboard accessible search, text labels and readable contrast.
- [ ] Observability includes health checks, server errors, source failures and approximate request counts without unnecessary personal-data collection.
- [ ] A measured pilot performance target is p95 cached API response <=1 second under light test load (not a promise for every real-world connection); slow/cold requests have visible loading states.
- [ ] Monthly forecast stays below **£30** and variable-cost services have quotas/alerts/caps.
- [ ] README, architecture diagram, API docs, data-source attribution, known limitations and deployment runbook are up to date.

### Launch validation

- [ ] Invite a target of 10–20 travellers (small exploratory sample, not statistically representative).
- [ ] Collect >=10 substantive usability responses if possible, plus aggregate observations about common failures and repeat-use reasons.
- [ ] Publish a short pilot retrospective with observations, severity-ranked issues, estimated follow-up costs and a **go / iterate / stop** recommendation.

## 8. Pilot hosting and financial guardrails

| Component | Pilot choice | Estimated monthly amount |
|---|---|---:|
| API compute | Render `0.5c-512mb` (formerly Starter) | **$7** |
| Static frontend | Cloudflare Pages | **$0** |
| Redis | Upstash free tier (up to 500K commands/month, subject to current policy) | **$0** |
| Airport data | OurAirports public-domain dataset | **$0** |
| METAR observations | Aviation Weather Center public data API | **$0 direct API subscription** |
| Domain | Use provider URLs at first | **$0 incremental** |

**Expected fixed hosting: about $7/month, plus applicable taxes, exchange-rate variation and unplanned usage**. This is a planning estimate, not a contractual price quotation. Allocate the unused budget to contingency; do not add a paid weather/flight API unless the cost and benefit are approved. Use the free Upstash tier rather than uncapped pay-as-you-go where possible; watch limits. Set alerts, provider request ceilings and deployment controls. Keep the maximum recurring total **under £30/month**.

Verify all plan pricing and service restrictions again at provisioning. No paid Aviationstack plan is needed for a weather-only pilot. Check data use/attribution permissions before commercialisation, even if no key or subscription is required for the public pilot.

Current references (18 Oct 2026):
- https://render.com/articles/fastapi-deployment-options
- https://render.com/docs/compute-plans-update
- https://developers.cloudflare.com/pages/functions/pricing/
- https://upstash.com/pricing/redis
- https://ourairports.com/data/
- https://aviationweather.gov/data/api/

## 9. Main risks and decisions

| Risk | Impact | Mitigation / trigger |
|---|---|---|
| Incomplete or absent METAR data at an airport | Misleading blank values or false confidence | Explicit `unavailable` and `unknown`; source/age; test 3 pilot stations before launch |
| Heuristic score interpreted as a flight disruption prediction | Loss of trust / unsafe interpretation | Use “experimental conditions indicator”; display factors and limitations; no prediction claims |
| Existing dependency stack fails in modern environment | Schedule slips | CF-001 baseline before new integrations; pin and test dependencies |
| Public provider rate limiting | Outages or blocks | 10–15 min caching; app-level request limit below provider cap; respect 204/429 responses |
| Free-tier limits or hidden hosting costs | Breach £30 budget | Provision fixed/capped plans; monitor usage; no paid flight data |
| Scope expands toward Flighty features | MVP doesn't ship | Weather-only release gate; feature requests go to v0.2 backlog |
| Weak differentiation from established flight apps | No repeat user demand | User tests; measure repeat-use reasons; pivot/stop if little evidence |

## 10. Product validation and portfolio deliverables

**Pilot feedback questions:** How easy was airport search? Did the conditions summary make sense? Could the user tell how recent the data was? What trip decision, if any, did it help with? What would make them return? What do they already use instead?

**Signals to continue:** Core workflow works reliably, multiple users identify a recurring reason to return, and there is one concrete, testable differentiation hypothesis. Ten to twenty users cannot prove product-market fit; use responses to decide whether to run a larger test.

**Portfolio case study:** Publish architecture and data-flow diagram, provider selection rationale, caching strategy and outage handling, example test results and CI history, live demo link, screenshots and a short retrospective. These outputs matter independently of the commercial outcome.

**Post-pilot branching decisions:**

- Strong request for actual flight delays => separately assess a *paid/limited flight-data* experiment with clear cost ceiling.
- Strong request for advance notice => investigate forecasts/TAF and an explanatory forecast module; not flight-delay prediction by assumption.
- Preference for easy, current airport conditions => iterate presentation, speed, coverage and sharing.
- Developer demand rather than traveller demand => consider documenting a developer-facing API.
- No recurring user value => keep the portfolio outcome and stop spending until positioning changes.

## 11. Next action

Start **CF-001**. Open one top-level GitHub Issue per milestone with the acceptance criteria above, and seven small CF-001 task issues or a single checklist if solo administration becomes burdensome. Work on `pilot/cf-001-baseline`; use a pull request into `main`, verify CI, and log the baseline before migrating data providers. Keep this document at `docs/development-plan.md` in the repository when ready to commit it.

**Change policy:** Scope or acceptance-criteria changes require a documented version increment (v1.1 for substantive changes). New features discovered during pilot testing go to a prioritised backlog, not directly into the release scope.