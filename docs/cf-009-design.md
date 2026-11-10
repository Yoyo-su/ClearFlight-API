# CF-009 flight positions — design spec (draft for owner approval)

**Status:** r3, **approved by the owner 2026-11-10** (decisions C1–C6, §8; revised after the Codex design critique of r2, §11).
**Sources:**
- Plan v1.1:
  - §2 feature 2;
  - §3 (quota model, fail closed, no background collection);
  - §4 (`/aircraft`, `no_aircraft` vs `coverage_unknown`);
  - §5 CF-009 (exit: recorded fixtures pass, a live probe shows aircraft at all three pilot airports, budget enforced);
  - §8 data-licence gate.
- D-010; owner decisions P4 (OpenSky dev/educational only) and P6 (no background collection).
- A live probe (2026-11-10 00:50Z) of both providers at EGLL, KJFK and RJBB, recorded in `tests/testfiles/opensky/` and `tests/testfiles/adsblol/`.

## 1. What CF-009 delivers
- **`GET /v1/airports/{code}/aircraft`:** the aircraft positions currently reported within a fixed radius of the airport.
  - For each aircraft: its source and position age.
  - The response states whether that means "no aircraft" or "coverage unknown".
- No UI. The map is CF-010, which adds the frontend schema and fixtures then (D-008). CF-009 is backend only.
- **Behind one interface, two adapters:**
  - OpenSky (development and educational use only, P4);
  - adsb.lol.
- **Licence gate:** a setting selects the provider, and OpenSky also needs an explicit educational-use flag (§6).

## 2. What the providers give (live probe, 2026-11-10)
| | OpenSky `/api/states/all` (anonymous) | adsb.lol `/v2/point/{lat}/{lon}/{nm}` |
|---|---|---|
| Query | bounding box (`lamin`/`lomin`/`lamax`/`lomax`) | centre and radius (nm, max 250) |
| Allowance | **400 credits/day anonymous** (4,000 with an account); about 1 credit for a box up to 25 sq°; header `x-rate-limit-remaining` | keyless today; no rate headers; "keys announced, limits dynamic" (RQ-002) |
| Aircraft found (EGLL/KJFK/RJBB) | 8 / 134 / 29 | 12 / 106 / 23 |
| Row | 18-element array: icao24, callsign, …, lon, lat, baro_alt (m), on_ground, velocity (m/s), track, vertical_rate, …, geo_alt, squawk, spi, position_source, category (usually 0) | object: `hex`, `flight`, `r` (registration), `t` (type), `lat`, `lon`, `alt_baro` (ft or `"ground"`), `gs` (kt), `track`, `baro_rate`, `seen_pos` (s), `category`, `dbFlags` |
| Position age | up to about **5 min** (`time - time_position`) | `seen_pos`, normally seconds |
| Privacy flags | none | `dbFlags` bit 8 = **LADD** (FAA privacy list; 7 aircraft at KJFK), bit 4 = PIA |
| Licence | non-profit research and educational only; live use needs a written licence | ODbL 1.0: attribution; share-alike for public derived databases |

**Quirks:**
- An OpenSky box around EGLL also returns aircraft at Gatwick, so results are filtered by true distance (§3).
- Callsigns are space-padded.
- A callsign is not a flight number (RQ-002, CF-013).

## 3. The area, targets and the result
- **Area:** a circle of **R = 25 nm** around the airport's reference point from the catalogue (**[C3]**).
  - adsb.lol is queried with that radius.
  - OpenSky is queried with the circle's bounding box (about 0.83° × 0.83°/cos(lat); under 25 sq° up to about ±88° latitude, so 1 credit). The rows are then filtered by great-circle distance.
  - A box crossing the antimeridian is split into two queries, both reserved and charged.
  - An airport without coordinates → `unavailable` / `no_location`.
- **Normalisation** to one model, per target:
  - `id`: ICAO 24-bit hex, lower case;
  - `callsign`: trimmed; null when empty or a placeholder such as `@@@@@@@@`;
  - `latitude`, `longitude`;
  - `altitude_ft`: barometric, else geometric; null when on the ground or missing;
  - `on_ground`;
  - `ground_speed_kt`, `track_deg`, `vertical_rate_fpm`;
  - `category`: the ADS-B emitter category, or null;
  - `kind`;
  - `position_at`: when the position was reported, from the provider;
  - `expires_at` = `position_at` + 60 s;
  - `distance_nm`.

  Each field is validated (D-006 style ranges). A row with an invalid or missing position or position time is **dropped** and counted in `dropped`.
- **Classification** (`kind`), applied **before** any state or coverage decision ([r3: critique 6]). In the EGLL probe, 6 of 12 adsb.lol targets were airport vehicles and 2 were tower stations.
  - **`aircraft`:** emitter category A1–A7 or B1–B7.
  - **`surface`:** category C1–C7 (vehicles, obstacles), or adsb.lol type `TWR`/`GND`. These are **excluded** from `aircraft[]` and counted in `excluded`.
  - **`unclassified`:** no usable category, as with OpenSky's category 0. These are kept, marked `unclassified`, because they may be aircraft. The map (CF-010) can show them differently.
- **Freshness, per position** (**[C4]**; [r3: critique 1]):
  - A position is shown only while `now < expires_at`.
  - The server filters at **fetch time and again at every read**, including cache hits, using the read's own clock.
  - The response carries each target's `expires_at`, and the frontend (CF-010) drops each one at that time (the D-008 pattern).
  - Positions already past `expires_at` at fetch time count as `dropped`.
- **Privacy** (**[C5]**):
  - Aircraft flagged LADD or PIA (adsb.lol `dbFlags` & 12) are omitted and counted in `withheld`. Unreadable flags are treated as flagged (fail closed).
  - Registration, owner and type are never exposed.
  - OpenSky has no such flags. The response says `privacy_filter: "unavailable"`, and P4 already confines OpenSky to development.

## 4. States: no aircraft vs unknown coverage
`data_status` is one of `available`, `no_aircraft`, `coverage_unknown`, `quota_exhausted` or `unavailable`. This follows plan §4: an empty response alone never proves coverage. Rules, in order:
- **`available`:** one or more shown targets (aircraft or unclassified), **or**, with a fresh feed, an empty list where some targets were `withheld` for privacy. The latter is never reported as `no_aircraft`; a stale feed is `stale_feed` even when aircraft were withheld.
- **`coverage_unknown`**, with a reason:
  - `unusable_data` ([r3: critique 4]): the list is empty and some rows were `dropped` (bad or expired positions). The data couldn't establish current traffic.
  - `stale_feed`: the feed's data time (`time` / `now`) is more than 60 s from our clock.
  - `no_coverage_evidence`: a valid empty answer, but no coverage evidence for this area.
  - `busy`: single-flight wait timed out (§5).
- **`no_aircraft`:** the provider answered with a valid structure and a fresh data time, **and** the area had **no rows at all after the distance filter** apart from `surface` targets (none dropped, none withheld), **and** the area has **coverage evidence**: this provider reported at least one *airborne* target there within the last 24 h (**[C6]**).
  - Airborne targets are used because surface vehicles never prove coverage of the air.
  - The evidence is a Redis marker `positions:coverage:{provider}:{airport code}`, 24 h TTL, refreshed whenever an airborne target is seen **in a fresh feed** (data time within 60 s of the fetch).
- **`quota_exhausted`:** the credit budget is used up or can't be checked (§5). The HTTP status is 200 with this state, and `retry_at` gives when the budget resets.
- **`unavailable`:** `no_location`, or `provider_disabled` when the licence gate blocks the configured provider or its credentials are incomplete (§6).
- **Provider failures:** 502 (including `provider_auth_failed`), 503 (local rate cap, with `Retry-After`) and 504, as for METAR (D-006).

The state is computed at every read, from the cached raw-normalised result and the read's clock. A cached `available` becomes `coverage_unknown` / `unusable_data` once all its positions have expired.

**Keys** ([r3: critique 5]): every Redis key uses the airport's **canonical code** from the catalogue (`airport.code`, unique; ICAO, or IATA when there's no ICAO), never `icao`, which can be null.

## 5. Budget, cache and single-flight (plan §3 quota model)
- **Cache:** one raw-normalised result per (provider, airport code) for **30 s** (plan §3: one query per airport per 30 s at most). All viewers share it. There is no background polling (P6): a request triggers a fetch only when the cache is empty.
- **Operation deadline** ([r3: critique 3]):
  - A whole fetch shares a **20 s deadline**: token request, query(ies) and the one retry.
  - Each attempt's timeout is the smaller of `PROVIDER_TIMEOUT` and the time left. No new attempt starts with under 2 s left.
- **Bounded requests** (review rounds 1–5, then the owner chose an async rewrite, 2026-11-10): synchronous HTTP clients can't be cancelled. A peer that trickles bytes, slow DNS, a multi-address connect or a stalled TLS handshake can hold a blocking call open, and an abandoned thread can even send its request late. So:
  - Every provider request is an **asyncio task** on one background event loop, using a shared `httpx.AsyncClient`, run under `asyncio.timeout_at(deadline)`.
  - Cancellation stops DNS waits, connect, TLS, headers and body reads alike, and closes the socket, so **nothing is sent or read after the deadline**. The loop's clock is `time.monotonic`, the same as the callers' deadlines.
  - Redirects aren't followed, since each would be another provider call.
  - **At most 8 connections** are open at once. When all are busy, the request fails within 0.5 s with `requests_busy` (502, not retried) instead of queueing.
  - Compression is declined (`Accept-Encoding: identity`). gzip/deflate sent anyway is decoded incrementally, covering multi-member gzip, zlib-wrapped or raw deflate, and trailing zero padding. The **decoded** size is capped at 8 MB and the stream end is verified (a truncated body is `invalid_response`). Other encodings are rejected.
  - Errors map to the typed errors (a timeout gives 504, others 502). A busy pool or connection error during the OpenSky token request keeps its own reason, not `provider_auth_failed`.
  - **For CF-006:** the client ignores proxy and CA environment settings (`trust_env=False`, certifi's CAs). A deployment behind a proxy or a private CA needs this revisited.
  - Tests on 127.0.0.1 use a real server:
    - the peer sees the connection closed at the deadline while headers trickle;
    - slow DNS leads to **no connection** after the deadline (a control with fast DNS connects);
    - a saturated pool fails fast with no extra request;
    - trickled chunk framing, redirects, chunked bodies, multi-member gzip and truncation are all covered.
- **Single-flight:**
  - On a miss, the caller takes `positions:v1:{provider}:{code}:lock` with `SET NX PX 40000` and a random owner token. The lease (40 s) is longer than the worst-case fetch (30 s), so it can't expire mid-fetch.
  - After taking the lock, the caller re-checks the cache, in case another request filled it in between. It caches its result **before** releasing the lock.
  - If the fetch fails, the fetching request records the failure for 5 s (`…:failed`), tagged with its lock-owner token.
    - Waiting requests re-raise that error at once rather than waiting out the deadline, but only for the fetch they were waiting on: a record from an earlier fetch is ignored.
    - They also stop waiting as soon as that lock is gone without a result.
  - A cached entry is used only if it parses **and** validates (timestamps with a timezone, counts and coordinates of the right type). Otherwise it's a miss.
  - The lock is released only by its owner, via a compare-and-delete Lua script.
  - Other callers poll the cache every 250 ms for up to 20 s. Then they get `coverage_unknown` / `busy`, and never fetch themselves.
- **OpenSky credits** ([r3: critique 2, 7]), all in Lua scripts, called through the Redis client directly. Redis errors raise, so they fail closed, and are never treated as a cache miss.
  - **Keys:**
    - `budget:opensky:{UTC date}`: credits used, expires 48 h after creation;
    - `budget:opensky:started:{UTC date}`: a sentinel set when that day's counter is first created;
    - `budget:opensky:slot:{UTC second}`: the per-second slot (plan §3), expires after 2 s.
  - **Reservation (atomic, one script):**
    - If the slot is taken → `busy`. The caller waits until the next second, within the deadline.
    - If the day counter is missing:
      - if the sentinel exists, the counter was lost → **exhausted until UTC midnight** (plan: counter loss);
      - otherwise this is the first use of the day: create both at 0.
    - If `used + cost > budget` → exhausted.
    - Otherwise increment by `cost`, take the slot, and return.
    - Retries and both antimeridian halves each reserve.
  - **Budget:** `OPENSKY_DAILY_CREDIT_BUDGET`, default **3,600** when account credentials are configured (90% of 4,000; C2), else 360 (90% of the anonymous 400). A configured value outside 1 to the provider limit disables the provider (`provider_disabled`).
  - **Order:** the token is obtained **before** the per-second slot is reserved, so the slot covers only the call it was reserved for.
  - **Reservations** never exceed the budget. The provider's own count, applied by raise-only reconciliation, can, which only makes the counter safer.
  - **Reconciliation failures** (Redis) are logged and not fatal, since the reservation already counted the call. A Redis failure **during reservation** fails closed (`budget_unavailable`).
  - **Header reconciliation, raise-only:** after a response with a valid integer `x-rate-limit-remaining`, a script sets `used = max(used, provider_limit - remaining)`.
    - It **never lowers** the counter, so concurrent reservations and late or out-of-order headers can't erase spending.
    - A missing or malformed header changes nothing.
    - `provider_limit` is 4,000 for an account and 400 anonymous (config).
  - **Provider 429:** → `quota_exhausted`, and the counter is raised to the budget for the rest of the day. `retry_at` uses `x-rate-limit-retry-after-seconds` when it's a valid integer, else UTC midnight.
  - **Redis unavailable:** OpenSky is **not called** → `quota_exhausted` / `budget_unavailable`.
  - **Both keys lost** (a full Redis wipe) can't be told apart from first use. The raise-only header reconciliation on the first call then restores usage from the provider's own count. This limitation is accepted and documented.
- **adsb.lol:**
  - It has no published quota, so a local cap applies: `ADSBLOL_RATE_LIMIT_PER_MINUTE`, default 30, using the token bucket.
  - It's a keyless provider: when Redis is down it degrades like METAR, with no shared cache or single-flight, but still capped.
- One retry on timeout, connection error or 5xx, within the deadline. No retry on 429.

## 6. Licence gate (plan §8, P4)
- `POSITIONS_PROVIDER`: `adsblol` (default, **[C1]**) | `opensky`.
- `OPENSKY_EDUCATIONAL_USE`: must be `true` for the OpenSky adapter to run. Otherwise the endpoint returns `unavailable` / `provider_disabled`.
  - `.env.example` documents it, and it defaults to `false`.
  - CF-006 will check that it's false in production, unless OpenSky's written licence is recorded.
- **Attribution in every response:**
  - `source.name`: e.g. "adsb.lol (ODbL 1.0)" or "OpenSky Network (educational use)";
  - `source.attribution_url`.
- **OpenSky account (C2; [r3: critique 8]):**
  - **Credentials:** `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET` come from `.env` (git-ignored; mode 600), via OAuth2 client credentials.
    - **Both set** → account access.
    - **Neither set** → anonymous, with the smaller budget.
    - **Only one set** → `unavailable` / `provider_disabled` (misconfiguration; nothing is called).
    - `source.access` says `"anonymous"` or `"account"`.
  - **Token:** requested from OpenSky's token endpoint (URL in config; verified by a live probe once the owner has added credentials, before the PR) within the operation deadline.
    - Token requests cost no credits and are not reserved.
    - The token is cached in memory until 60 s before it expires.
  - **Token failure:** the token endpoint failing, timing out or returning a malformed token → 502 `provider_auth_failed`, and **no states call** is made.
  - **401 from a states call:** the cached token is cleared, a new token is fetched **once**, and the call is retried **once**, with a fresh reservation. A second 401 → 502 `provider_auth_failed`.
  - **Call limit:** at most **two states calls per box**, shared between 5xx/timeout retries and the 401 refresh. At most **one token refresh per operation**, including both antimeridian halves, so at most two token requests.
  - **States field:** an OpenSky 200 must contain `states`. `null` means an empty area; a missing field is `invalid_response` (502), never an empty result.
  - **Token server timeout:** → 504 (`token_timeout`), not `provider_auth_failed`.
  - **Secrecy:** the client id, secret and token are never logged, returned or committed. Errors name only the failure kind.

## 7. API: `GET /v1/airports/{code}/aircraft`
```text
{
  airport: {...as /conditions},
  area: { latitude, longitude, radius_nm },
  source: { provider: "adsblol" | "opensky", name, attribution_url, access: "keyless" | "anonymous" | "account",
            privacy_filter: "applied" | "unavailable" },
  observed_at: datetime | null,      // the provider's data time
  fetched_at: datetime | null,
  aircraft: [ { id, callsign, latitude, longitude, altitude_ft, on_ground, ground_speed_kt, track_deg,
                vertical_rate_fpm, category, kind: "aircraft" | "unclassified",
                position_at, expires_at, distance_nm } ],
  withheld: int, excluded: int, dropped: int,
  data_status: "available" | "no_aircraft" | "coverage_unknown" | "quota_exhausted" | "unavailable",
  unavailable_reason: null | "no_location" | "provider_disabled" | "no_coverage_evidence" | "stale_feed" | "busy"
                      | "unusable_data" | "daily_budget" | "budget_unavailable",
  retry_at: datetime | null,         // quota_exhausted only
  disclaimer: "Live positions from volunteer receiver networks. Coverage is incomplete and positions can be delayed; not for navigation or safety use."
}
```
Targets are sorted by distance. `no_aircraft` is valid until `observed_at` + 60 s, and the frontend treats it as expired after that (CF-010).

## 8. Owner decisions (2026-11-10)
| # | Decision | Chosen |
|---|---|---|
| C1 | Default provider | **adsb.lol** for development, with OpenSky behind the same interface and gate. Reasons: adsb.lol is keyless, has no daily credit cap, gives fresher positions, flags LADD/PIA, and its ODbL licence allows live use with attribution, so it doesn't block CF-006. OpenSky stays available with the flag, for comparison. |
| C2 | OpenSky access | **Register an account** (owner's choice; the recommendation was anonymous): 4,000 credits/day, budget 3,600, with OAuth2 client credentials the owner puts in `.env`. Anonymous is the fallback when they're absent. |
| C3 | Area radius | **25 nm**: covers approaches and departures without pulling in much en-route traffic. (EGLL's box at 25 nm still includes Gatwick traffic, which is correct for "near the airport".) |
| C4 | Maximum position age | **60 s**: older positions are dropped, not shown. |
| C5 | Privacy | **Omit LADD/PIA-flagged aircraft; never expose registration, owner or type**; count withheld aircraft. Callsign and ICAO hex are shown, as in other public trackers. |
| C6 | Evidence for "no aircraft" | Report `no_aircraft` only with **coverage seen in the last 24 h**; otherwise `coverage_unknown`. |

## 9. Tests
- **Parsers:**
  - the recorded responses for both providers at all three airports;
  - field validation, padding, `"ground"` altitude, missing positions;
  - age and distance filters;
  - LADD/PIA withheld;
  - unit conversions (m → ft, m/s → kt, m/s → fpm).
- **Area:** box and radius maths, the antimeridian split, high latitudes, and distance filtering (the Gatwick case).
- **States:**
  - available, no_aircraft (with and without coverage evidence), coverage_unknown (stale feed, busy);
  - quota_exhausted (daily budget, 429, Redis down, counter loss);
  - provider_disabled;
  - no_location.
- **Budget:**
  - concurrent misses make one fetch (single-flight);
  - the reservation is atomic under concurrency;
  - retries are charged;
  - the header resets the counter;
  - fail closed without Redis.
- **Endpoint:** errors (400/404/502/503/504), the response model, and attribution.
- **r3 additions:**
  - **Expiry:** read-time filtering on cache hits, and the change to `unusable_data` once all positions expire.
  - **Counter:** raise-only reconciliation with concurrent and out-of-order headers; the per-second slot; first use vs counter loss (sentinel); a malformed header; Redis errors fail closed (not a miss).
  - **Lock:** lease ownership and the deadline (a slow fetch can't let a second fetch start).
  - **Data:** dropped-only empties give `unusable_data`.
  - **Keys:** IATA-only airports get distinct keys.
  - **Classification:** surface and tower exclusion (the EGLL fixture); coverage evidence only from airborne targets.
  - **OAuth**, mocked: both, neither or one credential; token failure; 401 → one refresh then failure; secrets never in logs or responses.
- **Live probe** (development only, not CI): aircraft at EGLL, KJFK and RJBB through the finished adapter (CF-009 exit).

## 10. Out of scope
- The map and any UI (CF-010).
- Movements (CF-011).
- Historical data and baselines.
- Background collection (P6).
- Flight numbers (CF-013).
- The adsb.lol API key (before CF-006).

## 11. Design critique (CORMORANT, r2 → r3)
Codex critique of the frozen r2 (2026-11-10): 5 High and 3 Medium, all confirmed, none refuted. No new policy choice was needed.
1. **Expiry was only checked at fetch.** Fixed: per-position `expires_at`, filtered at every read and on the client (§3).
2. **Header reconciliation could erase reservations, and there was no per-second slot.** Fixed: raise-only reconciliation and an atomic per-second slot (§5).
3. **The lock could expire mid-fetch.** Fixed: a 20 s operation deadline under a 30 s owner-token lease, with compare-and-delete release.
4. **Dropped rows could produce a false zero.** Fixed: `unusable_data`; `no_aircraft` requires no dropped or withheld rows.
5. **ICAO-keyed Redis keys collided for IATA-only airports.** Fixed: canonical airport code.
6. **Ground vehicles and towers counted as aircraft.** Fixed: classification before any decision; surface targets excluded; coverage evidence from airborne targets only.
7. **Counter initialisation and recovery were undefined.** Fixed: a day sentinel distinguishes first use from loss; Redis errors fail closed; a full wipe is a documented limitation.
8. **OAuth failure handling was unbounded.** Fixed: the credential combinations, a bounded refresh (one), `provider_auth_failed`, and mocked tests; the token endpoint is verified live before the PR.
