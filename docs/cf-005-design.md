# CF-005 frontend MVP — design spec (draft for owner approval)

> Note (2026-11-06): the README sections this spec cites ("Endpoints", "Frontend", "Running the checks locally") moved to [API.md](API.md) and [DEVELOPMENT.md](DEVELOPMENT.md).

**Status:** r3, **approved by the owner 2026-11-03** (decisions D1–D11 in §11). r3 addresses the Codex design critique of r2 (1 High, 5 Medium; see §13).
**Mock-up:** the "ClearFlight CF-005 mock-up" canvas (private artifact: https://claude.ai/artifact/BKt9cvXu6jBuoS2TAtazX3). Its artboards show the search page and the airport page on desktop and mobile. A "state" switch on the airport page shows every state in §4.
**Sources:**
- `docs/development-plan.md`: §1 locked decisions and positioning, §2 must-haves, §3 architecture, §7 gates, §8 hosting.
- Issue #6.
- The v1 API contract: README "Endpoints", D-005, D-006, D-007.

Decisions marked **[Dn]** are open for the owner; each has a recommendation. The full list is in §11.

## 1. What the frontend must do (from the plan)

A traveller, without an account, on a phone or desktop, can:

1. find an airport by name, city, IATA or ICAO code;
2. open its page and see:
   - the airport's name, codes, place and live local time, plus UTC;
   - the latest observed weather, with its source and age;
   - the experimental conditions index, with its reasons, when the data allows; otherwise "unknown";
3. share that page by URL (`/airport/EGLL`);
4. understand what happened when something goes wrong: loading, retry, error, stale and unknown states.

**Hard rule (plan §1):** nothing on screen may suggest that a score means a flight is safe, unsafe, delayed or on time. Every page carries the disclaimer, and the index is labelled "experimental".

## 2. Pages and routes

| Route | Page | Notes |
|---|---|---|
| `/` | Home / search | Search field, results, and shortcuts to the three pilot airports. |
| `/airport/:code` | Airport page | `code` is IATA or ICAO in any case. After loading, the URL is replaced with the API's canonical `airport.code`: ICAO when the airport has one, otherwise IATA. So `/airport/lhr` becomes `/airport/EGLL`, and `/airport/aai` becomes `/airport/AAI`. Shared links are stable **[D8]**. |
| anything else | Not found | Links back to search. |

The page title (`<title>`) is `London Heathrow (EGLL) – ClearFlight`, so tabs and shared links read well.

## 3. Screens

### 3.1 Home / search
- **Header:** "ClearFlight" wordmark and the strapline "Airport weather, explained".
- **Heading:** "Check the weather at an airport".
- **Search field:** a visible `<label>` reading "Airport name, city or code", with placeholder text "e.g. Heathrow, Osaka, JFK".
- **Results:** they appear as you type (from 2 characters, after a 250 ms pause) **[D3]**. Each result is a link (a real `<a>`, so Tab and Enter work with no custom keyboard code) showing:
  - the name;
  - the code chips "EGLL · LHR";
  - the city and country.
  
  A polite live region announces the count, e.g. "4 airports found".
- **Shortcuts [D5]:**
  - **Recently viewed:** shown once the visitor has opened airports. Up to 5, most recent first, with a **Clear** button. They're stored only in this browser (`localStorage`, never sent to the server), and the page works without them, e.g. in private windows or when storage is blocked.
  - **"Try one of our pilot airports":** London Heathrow · Osaka Kansai · New York JFK, always shown.
  - A site-wide "popular airports" list is deferred until there's traffic to rank (CF-006 request counts, CF-007 review).
- **States:**
  - fewer than 2 characters: hint text only;
  - searching: an inline spinner with the text "Searching…";
  - no results: "No airports match "zzqq". Try a city, an airport name or a 3–4 letter code.";
  - error: "Search isn't available right now." plus a **Retry** button.

### 3.2 Airport page (mobile-first; one column on phones, two from 900 px)
In page order:

1. **Top bar:** the wordmark (a link home) and a compact search field.
2. **Airport heading:** for example
   - the name as an `h1`, "London Heathrow Airport";
   - code chips "EGLL" and "LHR";
   - "London, United Kingdom".
3. **Clock card:**
   - "Local time 08:20", with "Mon 2 Nov · GMT (UTC+0)" underneath;
   - "UTC 08:20" beside it.
   
   It's calculated in the browser from the IANA timezone with `Intl.DateTimeFormat`, which handles DST, and updates every minute. When there's no timezone it shows UTC only and says "Local time unavailable for this airport".
4. **Status line** (freshness), always text and never colour alone:
   - current: "Observed 35 min ago · 07:20 UTC";
   - stale: an amber notice reading "This report is 2 h 5 min old, so it isn't scored. Showing it for reference.".
5. **Conditions card** (the experimental index):
   - the score as "8 / 10" with the level word ("Severe") on a chip, and the label "Experimental conditions index";
   - the explanation sentence from the API;
   - the four factors, each with its name, a small 0–10 bar, the API's detail text and its score. An unknown factor shows "Unknown" and a dashed, empty bar;
   - the disclaimer under the card, always visible: "Experimental index of the weather reported at the airport. It is not a forecast and does not predict delays, cancellations or flight safety."
   
   When the score is null, the card shows "Unknown" in place of the number, with the explanation (e.g. "No score: the cloud ceiling wasn't reported.") and the known factors.
6. **Observation card:** a definition list showing temperature, dew point, wind (direction, speed and gusts, or "Variable"), visibility, cloud (the sky condition plus the ceiling), weather (decoded words, e.g. "Mist", "Heavy rain showers", plus the code) and pressure. Missing values show "Not reported", never 0 or a dash that looks like a value. Units follow **[D1]**.
7. **Raw report:** a `<details>` disclosure titled "Raw METAR report", showing the text in monospace.
8. **Source and times:**
   - "Source: NOAA Aviation Weather Center";
   - "Observed 07:20 UTC · Fetched 07:55 UTC";
   - a **Refresh** button, with "Updates every 5 minutes while open" **[D4]**. After a press, the button is disabled for 60 s and shows "Checked just now".
9. **Footer:** data attribution (OurAirports, NOAA AWC) and the disclaimer again in small print.

### 3.3 Not found
"Page not found" plus the search field.

## 4. States of the airport page and their wording

Each state maps one-to-one onto the API's `data_status`, `unavailable_reason` and errors (D-007).

| State | Trigger | What the user sees |
|---|---|---|
| Loading | request in flight | The heading shows the code from the URL; the cards are grey skeletons with "Loading weather…" for screen readers. No spinner longer than 10 s without text; after that: "Still waiting for the weather service…". |
| Current, scored | `current`, score present | The full page as in §3.2. |
| Current, unknown | `current`, score null | The conditions card shows "Unknown" plus the explanation; the observation card is shown as normal. |
| Stale | `stale` | The amber notice (§3.2.4); the conditions card shows "Not scored: this report is too old to score."; the observation is shown with its age. The wording avoids hard-coding 90 minutes, since the thresholds are configurable. |
| No report | `unavailable` / `no_report` | Airport heading and clock; a panel reading "No current weather report. The weather station at this airport hasn't published a report recently." with a **Refresh** button. |
| Too old | `unavailable` / `observation_too_old` | As above, with "The latest weather report (07:20 UTC, 4 h ago) is too old to show." |
| No station | `unavailable` / `no_metar_station` | Airport heading and clock; "This airport doesn't have a weather station that publishes METAR reports, so ClearFlight can't show its weather." No Refresh button. |
| Invalid code | 400 | "“XX” isn't an airport code. Use a 3-letter IATA code (like LHR) or a 4-character ICAO code (like EGLL)." plus the search field. |
| Unknown airport | 404 | "We couldn't find an airport with the code ZZZ." plus the search field. |
| Weather service failed | 502 or 504 | "The weather service didn't respond. This is usually temporary." plus a **Try again** button. The heading shows the code from the URL. |
| Busy | 503 with Retry-After | "Lots of people are checking the weather right now. Trying again in 13 s…" The page retries automatically once after Retry-After; a **Try again** button is enabled when the countdown ends. |
| Offline / network error | fetch failed | "Can't reach ClearFlight. Check your connection." plus **Try again**. |

Auto-refresh **[D4]** never replaces good data with an error. If a refresh fails, the last good data stays on screen and the status line adds "Couldn't update just now — showing the report from 07:20 UTC".

**Ageing on screen [r3, critique finding 1; D11]:** data kept on screen must lose eligibility as it ages, even while refreshes fail or the tab is in the background. The API adds two timestamps to each response with an observation: `current_until` and `stale_until`. The backend computes them from its configurable thresholds, so it stays the single freshness authority (D-007). The page re-checks every minute, and as soon as the tab becomes visible again:
- after `current_until`: the score and level are withdrawn and the page shows the Stale state;
- after `stale_until`: the observation is removed and the page shows "Too old", keeping only "last report at …".

Tests cover each crossing, repeated failed refreshes, and returning from a background tab after both times have passed.

## 5. Units **[D1]**
**Recommended:** show both unit systems, with metric/aviation first and no toggle (nothing to remember or store):
- temperature "10 °C (50 °F)";
- wind "4 kt (7 km/h)";
- visibility "1.3 km (0.8 mi)", and "10 km or more" when the report says so;
- cloud ceiling "200 ft (60 m)";
- pressure "1029 hPa".

Alternatives: a °C/°F and km/mi toggle stored in the browser; or metric only.

## 6. The score's look **[D2]**
**Recommended:** level colours that never read as a "safe" traffic light:
- low: slate blue;
- moderate: amber;
- high: orange;
- severe: deep red;
- unknown: neutral grey with a dashed outline.

There's no green anywhere in the index. The number and the level word always appear together, so colour is never the only signal. Every colour pair meets WCAG AA contrast (4.5:1 for text).

## 7. Visual style **[D6]**
**Recommended look, "calm instrument panel":**
- a cool off-white ground (#F5F7FA) with white cards and thin borders;
- navy ink (#13213A) and one blue accent (#1F5FBF) for links and focus;
- IBM Plex Sans for text and IBM Plex Mono for codes and the raw METAR, loaded from Google Fonts with a system-font fallback;
- an 8 px spacing grid, 12 px card radius, no gradients, and nothing decorative beyond a small plane-and-cloud wordmark glyph.

## 8. Behaviour
- **Search [D3]:** results as you type, debounced at 250 ms, minimum 2 characters, cancelling the previous request with `AbortController`. Pressing Enter opens the first result. Up to 10 results.
- **Refresh [D4]:**
  - a manual Refresh button with a 60 s cooldown after each press, so a tab sends at most one manual request a minute. A per-client server limit is CF-006.
  - **Cost [r3, critique finding 3]:** there's no per-request charge (AWC is free; hosting is free or fixed tiers). Requests do count against free-tier quotas, though. A current report is cached for 10 minutes, so most refreshes never reach the provider. A report that isn't current is cached for only 60 s, and an unusable response isn't cached at all, so then a refresh can call the provider. Those calls are always bounded by the server-wide cap of 30 a minute (D-006, D-007).
  - automatic refresh every 5 minutes while the tab is visible (Page Visibility API), and none in background tabs;
  - after an auto-refresh, the relative ages ("35 min ago") update every minute without a request.
  
  See the cost note above.
- **Request ownership [r3, critique finding 6]:**
  - Every airport fetch, auto-refresh, Busy retry and cooldown timer belongs to the airport code on screen. Navigating to another airport, or leaving the page, aborts in-flight requests (`AbortController`) and clears all timers.
  - A response is applied only if it belongs to the latest request for the current code, so a late EGLL response can't overwrite KJFK or rewrite its URL.
  - Tests complete requests in reverse order and navigate during a retry countdown.
- **Canonical URL [D8]:** `/airport/lhr` is replaced in place with `/airport/EGLL` once the response arrives (no extra history entry).

## 9. Accessibility (plan §7 gate)
- Real `<button>`, `<a href>`, `<input>` with `<label>`; no clickable `<div>`s.
- Every interactive control works with the keyboard, and the focus outline is visible (2 px accent).
- Touch targets are at least 44 px.
- One `h1` per page and a logical heading order. The live region announces search counts and refresh results.
- Text contrast is at least 4.5:1 (3:1 for 24 px text and larger). Colour is never the only signal.
- `prefers-reduced-motion` disables skeleton shimmer and transitions.
- Checked automatically with axe in the end-to-end tests, on every page and state.

## 10. Technical design
- **Location [D7]:** a `frontend/` folder in this repo. One PR covers the API and UI, and CI runs both. The alternative is a separate repo.
- **Stack**, pinned to the newest releases at least two weeks old, checked with `npm view` on 2026-11-02:

  | Role | Packages |
  |---|---|
  | Runtime | React 19.3.1 and react-dom 19.3.1 |
  | Build | Vite 8.3.4, @vitejs/plugin-react 6.1.2 |
  | Language | TypeScript 6.0.3 (typescript-eslint doesn't support TypeScript 7 yet) |
  | Routing [D9] | react-router 8.4.0 |
  | Lint | ESLint 10.13.0, typescript-eslint 8.71.2, eslint-plugin-react-hooks 7.1.1 |
  | Unit tests | Vitest 5.0.5, jsdom 30.1.3, Testing Library (react 16.3.3, user-event 14.6.8, jest-dom 7.0.1) |
  | End-to-end tests | Playwright 1.64.1, @axe-core/playwright 4.14.0 |

  Node 24 (LTS) is used locally and in CI. There are no other runtime dependencies: data fetching uses `fetch` with small typed hooks, and styles are plain CSS modules.
- **API access:**
  - `VITE_API_BASE_URL` is set at build time (empty means same origin).
  - In development, Vite proxies `/v1` and `/health` to `http://localhost:8000`, so no CORS is needed until CF-006.
  - **Contract [r3, critique finding 4]:** TypeScript types mirror `app/api/models.py`, and recorded API responses live in `frontend/tests/fixtures/`. Two tests keep the three in step:
    - a **backend** pytest validates every fixture against the current Pydantic models and asserts that each fixture's field set matches the model's exactly, so adding, removing or renaming a field fails the Python checks until the fixtures are re-recorded;
    - the **frontend** type-checks the same fixtures against the TypeScript types (`satisfies ConditionsResponse`).
    
    A backend change can then only pass CI once fixtures and types are updated to match. A script re-records the fixtures from a running backend.
- **Tests:**
  - **Unit and component tests (Vitest + Testing Library):**
    - formatting (units, ages, weather words), the clock (London and New York DST changes, Tokyo), and the score card for every level and unknown;
    - every airport-page state in §4, search states, and refresh behaviour, using fake timers.
    - Coverage gate 80% **[D10]**.
  - **End-to-end tests (Playwright):**
    - flows: search → airport; open a shared link; each error state; refresh;
    - run on a mobile (Pixel-size) and a desktop project against a mocked API (route interception with recorded responses), plus axe on every state;
    - a manual live smoke run against the Docker backend, recorded as evidence.
- **CI [r3, critique finding 5]:**
  - `make run-checks` stays Python-only, so the existing CI and release jobs are unchanged.
  - A new `make frontend-checks` runs `npm ci`, lint, typecheck, unit tests with coverage, build, and Playwright (Chromium only, `npx playwright install --with-deps chromium`).
  - `CF_deploy.yaml` gains a separate `frontend` job with Node 24 that runs `make frontend-checks`, alongside the Python job.
  - `release.yaml` gains the same job so tags are checked too; the frontend isn't published until CF-006.
  - The README's "Running the checks locally" covers both targets.
- **Docs:** README section "Frontend" (setup, scripts, environment); ARCHITECTURE; a decision D-008 recording the choices made here.

## 11. Owner decisions (walkthrough, 2026-11-03)

| # | Decision | Owner's choice |
|---|---|---|
| D1 | Units | Both systems, metric first, no toggle |
| D2 | Score colours | Slate/amber/orange/red, grey dashed for unknown; never green; number + word always together |
| D3 | Search | As you type (2+ chars, 250 ms debounce), result links, Enter opens the first |
| D4 | Refresh | Auto every 5 min while visible, plus a Refresh button with a 60 s cooldown; a failed refresh keeps the last good data. Chosen after the owner asked about costs: a refresh is almost always answered from the backend cache (no provider call, no per-request charge), and automatic refresh generates more requests than manual. |
| D5 | Home shortcuts | Pilot airports + "Recently viewed" (browser-only, up to 5, Clear button). Site-wide "popular" deferred until there's traffic. |
| D6 | Visual style | "Calm instrument panel" for now; a deeper redesign is earmarked as a follow-up |
| D7 | Repo layout | `frontend/` in this repo |
| D8 | Canonical URL | Replace with the ICAO code after load |
| D9 | Routing library | react-router 8.4.0 |
| D10 | Frontend coverage gate | 80%, matching D-004 |
| **D11** (new, from the critique) | How on-screen data ages | **Recommended:** the API adds `current_until` and `stale_until` (from the backend's thresholds) and the page applies them as time passes. The alternative is to re-fetch at each boundary and drop the data if that fetch fails. That needs no contract change, but an outage would blank the page instead of showing "too old". **Owner chose: the API sends the times.** |

## 12. Out of scope (CF-005)
- Deployment, CORS, the public URL (CF-006).
- Analytics, cookies, accounts.
- Forecasts, maps, favourites, a PWA/offline mode.
- Search-ranking changes in the backend (a follow-up; see the milestone).
- A site-wide "popular airports" list (D5; needs traffic and backend counting).
- A deeper visual redesign (D6 follow-up).

## 13. Design critique (CORMORANT, r2 → r3)
Codex critique of the frozen r2 (`~/codex-reviews/clearflight-cf005-design/`): 1 High, 5 Medium, all confirmed, 0 refuted.
1. Kept data could outlive its scoring eligibility (High) → ageing rule, D11.
2. ICAO canonicalisation fails for IATA-only airports → use `airport.code`.
3. The cost explanation ignored the 60 s cache for non-current reports → corrected.
4. Recorded-fixture tests couldn't catch backend drift → a backend fixture/model test plus frontend type checks.
5. Adding frontend checks to `make run-checks` would break the existing jobs → a separate target and jobs.
6. No request ownership on airport navigation → abort, ownership and reverse-order tests.

## 14. Acceptance mapping (issue #6)

| Criterion | How it's shown |
|---|---|
| End-to-end flows on mobile and desktop; accessible controls | Playwright mobile and desktop projects; axe on every state; keyboard-only flow test |
| Checks pass; user-visible errors covered | Every §4 state has a component test and an e2e test; CI frontend job |
| README / API contract updated | README "Frontend"; contract test against recorded responses |
| PR from a branch | `feat/cf-005-frontend` |
