# CF-011 observed movements — design spec (draft for owner approval)

**Status:** r3, **approved by the owner 2026-11-15** (decisions V1–V6, P5-a, P5-b in §10; revised after the Codex design critique of r2, §13).
**Sources:**
- Plan v1.1:
  - §2.2 (observed movements);
  - §3 (completeness rule, no background collection P6);
  - §4 (`/movements`);
  - §5 CF-011 exit (detection tests on recorded tracks, coverage-gap tests, P5 checked against airport boards for a busy hour per pilot airport);
  - §7 (P5: at least 90% found, at most 5% false, else "experimental");
  - §8.
- D-012 (positions), D-013 (map).
- Two live probes (2026-11-15), §2. Recordings are in `.local-smoke/movements/` (local only); selected tracks become fixtures.

## 1. What the user gets
On the airport page, below the live map, a **"Recent movements"** list:
- **Rows:** departures and arrivals, newest first, each with its time (to the minute, local and UTC), callsign and kind.
- **Labels:** each row is labelled **"observed"** (seen on the ground and in the air) or **"inferred"** (seen only in the air, low near the runway).
- **Coverage line:** for example "Watched 07:10–07:55 · gap 07:20–07:31 · inferred movements only at this airport". Movements during unwatched time aren't known.
- **States:**
  - **no movements yet:** watching only began recently;
  - **can't detect here right now:** no recent receiver data near this airport, and coverage is unknown. We never claim an airport "isn't covered" from an absence of data;
  - **experimental:** P5 isn't met yet at this airport.
- **Disclaimer:** "Detected from volunteer receiver data while this page was open. May be incomplete; not an official departures board."
- **Flight numbers:** none. They come from CF-013.

## 2. Evidence (live adsb.lol probes, 30 s polls, 15 min each, 2026-11-15)
| Airport | Observed (ground and air seen) | Inferred (air only, low near the field) | Notes |
|---|---|---|---|
| KJFK (20:30 local) | 10 dep, 5 arr | 0 | Transitions 0.6–1.4 nm from the reference point; first airborne fix at 75–375 ft |
| RJBB (10:30 local) | 5 dep, 5 arr | 0 | |
| YSSY | 5 dep, 6 arr | 0 | |
| RKSI | 1 dep, 5 arr | 1 dep, 3 arr | Mixed: inferred arrivals last seen at 75–175 ft |
| WSSS | **0** (no ground fixes at all) | **7 dep, 7 arr** | Arrivals last seen at 200–300 ft, 1.1–1.3 nm out |

- **No coverage at all** at midday: ZSPD, VIDP, VABB, RPLL, WIII, VVTS, WMKK and NZAA (0–1 aircraft within 8 nm).
- **Neighbouring fields:** EGLL has RAF Northolt at 5.2 nm, KJFK has KLGA at 9.3 nm, RJBB has none within 10 nm.
- **Ground truth not yet checked:** these counts show the method is feasible. P5 accuracy is measured against the boards (§9).

## 3. Detection
**Input:** the CF-009 feed result for an airport. The detector runs **once per fresh provider fetch**, inside the existing single-flight section, so:
- it only runs while the airport is being viewed (P6);
- withheld (LADD/PIA), surface vehicles and towers never reach it;
- helicopters (category A7) are ignored (**[V6]**).

**Usable polls** [r3: critique 4]:
- A fetch is a **usable poll** only if all of these hold:
  - the provider's data time is within 60 s of the fetch time;
  - the data time is **newer** than the last processed poll for this airport (a repeated or stale timestamp is not a new poll);
  - the result isn't unusable (some targets are valid, or the feed is a fresh, empty answer).
- **Failed fetches** (timeout, provider error, `quota_exhausted`, `busy`) and unusable results are recorded as **failed polls**. A failed poll **ends the watched window**, even if successful polls fall either side of it within 90 s.
- Only usable polls count as observations: for movements, for "absence" when confirming an inferred arrival, and for coverage counters.

**Fix states** [r3: critique 1]:
- **Ground:** adsb.lol `alt_baro == "ground"`, or OpenSky `on_ground == true`.
- **Airborne:** the provider says not on the ground **and** gives a numeric altitude (barometric or geometric).
- **Unknown:** anything else (e.g. a missing or invalid altitude). An unknown fix is **no evidence** either way. It neither completes nor breaks a transition, and it's never the attributed fix.

**Observed movements** (both sides seen):
- **Departure:** the same aircraft has a **ground** fix at usable poll N and an **airborne** fix at usable poll N+1. **Arrival:** the reverse.
- Polls N and N+1 must be **consecutive usable polls in one watched window**, at most 90 s apart.
- **Attributed fix:** the **ground fix** (the last ground fix for a departure, the first for an arrival).

**Inferred movements** (fallback when there's no ground fix; **[V1]**, **[V3]**):
- **Inferred departure:** the aircraft is **first seen airborne** at a usable poll that isn't the first of a watched window. That fix is:
  - **low:** below 1,500 ft above field elevation;
  - **close:** within 2 nm of the attributed airport's reference point;
  - **climbing:** above +200 fpm.
- **Inferred arrival:** the aircraft is **last seen airborne** low, close and **descending** (below −200 fpm), and is **absent from the next 2 consecutive usable polls in the same window**.
- **Never inferred:**
  - at window edges;
  - when the aircraft has an observed transition within 10 min;
  - when it reappears airborne within 10 min (a recorded inferred arrival is then withdrawn).
- **Field elevation:** OurAirports `elevation_ft` (§6). Without an elevation, there's no inferred movement at that airport.

**Attribution** (**[V2]**):
- The attributed fix goes to the **nearest catalogue airport** within **4 nm**.
- If the second-nearest is within **1 nm** of the nearest's distance, the movement is **dropped as ambiguous**.
- Movements attributed to an airport other than the one being viewed are discarded.

**De-duplication:** at most one departure and one arrival per aircraft per 10 min per airport. **Time:** the window between the two polls; the list shows the later one to the minute, and the API returns both.

## 4. Coverage
**Watched windows:**
- **Usable polls** at most 90 s apart, with **no failed poll between them**, form a watched window.
- Windows (with their failed polls and the reasons) are kept for 6 h and returned by the API. They're the completeness metadata for CF-012 (provider errors and quota stops included).

**Coverage mode per airport,** from the last 24 h of usable polls (Redis counters, 24 h TTL) [r3: critique 2]:
- **surface:** at least one observed movement, **or** at least 3 ground fixes within 4 nm;
- **airborne_only:** at least one low airborne fix near the field (below 1,500 ft above field, within 2 nm) and no ground fixes;
- **unknown:** everything else, with a reason:
  - `not_enough_watching` (under 10 usable polls);
  - `no_low_traffic_seen`: traffic, but none low near the field;
  - `no_recent_data`: no airborne targets within 25 nm. This is **not** a claim of no coverage, since a cold start, lost state or a quiet period look the same.

The mode is a label, not a gate. Movements are listed in any mode, each labelled observed or inferred.

## 5. Store and API
**Store:** Redis keys per (provider, airport code):
- movements;
- aircraft state;
- watched windows and failed polls;
- coverage counters;
- `last_poll`: the data time of the last processed usable poll.

Every key has a TTL: movements, windows and polls 6 h, refreshed on write; aircraft state 15 min; coverage counters 24 h [r3: critique 7].

**Exactly-once processing** [r3: critique 5]:
- **Poll identity:** the provider's data time.
- **The detector runs first,** as one Lua script that:
  - checks the poll is newer than `last_poll`;
  - applies the movement, state, window and counter updates;
  - sets `last_poll`.
  
  So a replayed or concurrent poll with the same data time is a no-op.
- **Only then is the positions cache published.**
- **If the detector fails** (Redis error or timeout), the poll is recorded as a **failed poll**, which ends the window, and the cache is still published for the map. A detector result that's lost in transit is also harmless: re-running the same poll is a no-op.
- **Cache hits never run detection.**
- **Partial state loss:** missing aircraft state or `last_poll` is treated as a window break, so no movements are inferred across it.

**As built** (2026-11-15, replaces the multi-key Lua design above; same guarantees): one JSON state key per (provider, airport) holds movements, aircraft state, windows and coverage counters, with a separate `:last` key holding `last_poll`. A Lua script writes both only if `:last` still equals the value read (compare-and-set), so a replayed or concurrent poll is a no-op. Retention (6 h) is trimmed on write and filtered on read; the key's TTL is 24 h. A missing or out-of-step `:last` is a window break (`ended_by: "state_lost"`). Detector failures are failed polls with `ended_by: "detector_error"`, and a storage failure `store_error`.

**API:** `GET /v1/airports/{code}/movements`
```text
{
  airport, source: {...as /aircraft},
  movements: [ { kind: "departure" | "arrival", method: "observed" | "inferred",
                 callsign, id, time_from, time_to, distance_nm } ],   // newest first, up to 100, none older than 6 h
  watched: [ { from, to, ended_by: null | "gap" | "provider_error" | "quota_exhausted" | "busy" | "unusable"
                                     | "store_error" | "detector_error" | "state_lost" } ],
  coverage_mode: "surface" | "airborne_only" | "unknown", coverage_reason: null | "not_enough_watching" | "no_low_traffic_seen" | "no_recent_data",
  validation: { observed: "validated" | "experimental", inferred: "validated" | "experimental",
                airport: "validated" | "experimental" },     // §9
  data_status: "available" | "unavailable", unavailable_reason: null | "not_watched" | "store_unavailable",
  disclaimer
}
```
**Reads:** the API reads only the store and filters out movements older than 6 h at read time. The frontend also drops rows at `time_to` + 6 h, even while refreshes fail.

## 6. Catalogue change
- Add `elevation_ft` to the OurAirports import and the snapshot: nullable, validated range −1,500 to 15,000.
- Re-import, add a contract check, and the existing snapshot tests.

## 7. Frontend
- **List:** a "Recent movements" card under the map, with an accessible table (time, kind, callsign, method).
- **Coverage line:** the watched windows and the coverage mode.
- **States:** the labels and empty states from §1.
- **Polling:** reuses the gated hook (`active` = the map section on screen).
- **Labelling:** observed and inferred are labelled in text, never by colour alone.
- **Contract:** a schema, fixtures, and contract tests on both sides (D-008).

## 8. Privacy
- **Sources:** movements come only from already filtered targets (no LADD/PIA, no registration, owner or type). Only callsign and hex are stored, for 6 h.
- **Scope:** no movement is recorded for an unwatched airport.

## 9. P5 validation (exit criterion)
- **Recording:** for each pilot airport (EGLL, KJFK, RJBB), during a **busy local hour**, a dev recorder polls exactly as the app does (30 s) and runs the detector. Recording in development counts as viewing.
- **Ground truth:** the airport's **published departures and arrivals board** for that hour, captured by Claude (or pasted by the owner if the page can't be fetched; **[V5]**). It's saved as a dated document in `docs/validation/` with flight, scheduled time, status and **actual time and its type** (gate/off-block or runway/airborne, as the board states).

**Matching protocol** [r3: critique 6], fixed before any comparison:
- **Identity:** a callsign matches a board flight when the airline's ICAO prefix maps to the board's IATA code (a fixed mapping table in the validation file, e.g. BAW→BA, DAL→DL) and the numbers match. Codeshare duplicates on the board are collapsed to the operating flight. Matching is **one-to-one**.
- **Time:** detected runway times are compared with the board's actual time and its type:
  - a **departure** matches if it's 0 to +45 min after an actual **off-block** time, or −5 to +5 min of an actual **airborne** time;
  - an **arrival** matches if it's −30 to 0 min before an actual **on-block** time, or −5 to +5 min of an actual **landed** time.
  
  Flights with only scheduled times are left out of the denominator.
- **Window:** board movements whose actual time falls inside the hour form the denominator. A detected movement up to 45 min outside the hour that matches a board entry isn't counted as false.
- **Measures:**
  - **found** = matched ÷ board movements;
  - **false** = unmatched detections ÷ detections.
  
  Computed for observed, for inferred, and for **all movements combined**.
- **Result:**
  - The **airport** is `validated` when the combined figures meet P5 (at least 90% found, at most 5% false); this airport-level result is the plan's P5 gate and decides CF-012's traffic-rate eligibility.
  - Each **method** is `validated` when its own figures meet P5. A method below P5 is shown as "experimental" at that airport, even if the airport passes overall.
- **Boards without actual times (owner decision P5-b):**
  - The comparison uses **scheduled times**, with wider tolerances: a departure matches −15 to +75 min after its scheduled departure, an arrival −60 to +30 min around its scheduled arrival.
  - It's labelled **"scheduled-time comparison (weaker evidence)"** in the validation document and the result.
- **Identity by route (owner decision, 2026-11-15, after the first EGLL run failed on identity; applies to every later recording):** many airlines fly ATC callsigns (`BAW35LF`, `SHT6Q`) that aren't flight numbers.
  - A callsign of the form ICAO prefix + flight number that matches a board flight's ICAO identifier is matched as above.
  - Otherwise its route is looked up once in adsbdb (`api.adsbdb.com/v0/callsign/<callsign>`, free, crowd-sourced). The detection matches a board flight of the same airline (callsign prefix, through a fixed alias table kept in the validation script, e.g. `SHT`→`BAW` for BA Shuttle) and movement type whose other airport (destination for a departure, origin for an arrival) equals the route's other end, within the same time tolerances, one-to-one, closest first.
  - A detection whose callsign has neither form of identity (no callsign, or unknown to adsbdb) is **unidentified**: listed separately with its count, left out of the false-rate denominator, and never counted as found.
  - Lookups are recorded in the validation document, so the result can be reproduced.
- **Identity by airline and aircraft type (owner decision, 2026-11-15, replaces the adsbdb route rule above, which a dry run showed unreliable: crowd-sourced routes are stale for reused ATC callsigns, and BA Shuttle callsigns are unknown). Fixed before the fresh EGLL, KJFK and RJBB recordings; every airport is judged only on a fresh hour recorded after this rule:**
  1. **Flight number:** a callsign of the form ICAO prefix + flight number that equals the board flight's ICAO identifier (or its IATA code through the fixed mapping table in the validation script).
  2. **Otherwise airline + aircraft type + movement:** the same airline (callsign prefix through the alias table, e.g. `SHT`→`BAW`) and the same ICAO aircraft type (from the raw recording's `t` field, read offline only and never stored by the app), within the time tolerance. Used only where the board publishes the aircraft type.
  - Matching is one-to-one: flight-number pairs first, then the closest time.
  - A detection with neither identity (no callsign, or no aircraft type where rule 2 is needed) is **unidentified**: counted and listed, left out of the false-rate denominator, never found.
  - **Board time types:** Heathrow's "Departed" is the airborne time and "Landed" the landing time. On the 2026-11-15 07:00 hour, flights matched by flight number alone were detected within −0.1 to +0.7 min of "Departed" (14) and +0.1 to +1.5 min of "Landed" (26), so the runway tolerance (±5 min) applies to both. A board whose time type is unknown uses the wider gate tolerances.
  - **Scheduled-only flights** on a board that publishes actual times stay out of the denominator, as above.
  - Identity matching is still required.
- **Too few identifiers:** if fewer than 80% of a board's flights can be matched by identifier, the comparison isn't run and the owner is told.

## 10. Owner decisions (2026-11-15)
| # | Decision | Chosen |
|---|---|---|
| V1 | Detection types | **Observed plus inferred**, always labelled; inferred only where no ground fix exists (needed for airports like WSSS and parts of RKSI) |
| V2 | Attribution | **Nearest catalogue airport within 4 nm; dropped if ambiguous** (second-nearest within 1 nm) |
| V3 | Inferred guards | **Below 1,500 ft above field, within 2 nm, climbing or descending above 200 fpm; arrivals confirmed after 2 absent polls; withdrawn on reappearance within 10 min** |
| V4 | Retention and list | **6 h store; the list shows the newest 100** |
| V5 | P5 board capture | **Claude captures each airport's public board during the recorded hour** (fetching the page, or the owner pastes it if the page can't be fetched) and writes the comparison; the owner reviews the result |
| V6 | Helicopters | **Excluded** (they use pads, not runways; they would create false movements) |
| **P5-a** | How method results relate to the airport's P5 gate | **The airport passes on the combined figures** (the plan's gate, and CF-012 eligibility); each method keeps its own label (§9) |
| **P5-b** | Boards without actual times | **Compare on scheduled times with wider tolerances, labelled as weaker evidence** (owner's choice; the recommendation was not to compare). Boards with too few identifiers are still not compared. |

## 11. Tests
- **Detector** (unit, synthetic plus recorded tracks from §2):
  - observed transitions;
  - a gap of more than 90 s gives no movement;
  - the ground fix is the one attributed;
  - inferred departure and arrival with each guard;
  - window edges;
  - reappearance withdrawal;
  - go-around;
  - de-duplication;
  - ambiguity (synthetic Northolt case);
  - helicopters, withheld targets and vehicles ignored;
  - field elevation missing.
- **Store:**
  - the atomic update under concurrent polls (fakeredis Lua);
  - replay of the same data time is a no-op;
  - a detector failure records a failed poll and the cache is still published;
  - partial state loss gives a window break;
  - TTLs and the 6 h read filter;
  - Redis down.
- **Usable polls and fix states:**
  - stale or repeated provider timestamps;
  - unusable results;
  - failed polls (error, quota, busy) end windows and never count as absence;
  - a missing-altitude fix is "unknown" and never completes a departure.
- **API and UI:** states, labels, coverage line, gating, schema and fixtures.
- **SHRIKE S1:** primary-path tests assert observed detection on a surface track. Inferred and fallback paths each get their own tests, and a fix's test is run against the pre-fix code.

## 12. Out of scope
- Flight numbers (CF-013).
- Runway identification.
- Traffic-rate and disruption signals (CF-012).
- Background collection (P6).
- Historical baselines.

## 13. Design critique (CORMORANT, r2 → r3)
Codex critique of the frozen r2 (2026-11-15): 5 High and 2 Medium, all confirmed, none refuted, plus two owner questions (now P5-a and P5-b).
1. **Not-on-ground with no altitude counted as airborne.** Fixed: explicit fix states, where "unknown" is no evidence.
2. **"No coverage" claimed from missing evidence, and undefined modes.** Fixed: modes are surface / airborne_only / unknown with reasons, and no absence claims.
3. **One airport-level validation flag couldn't express the per-method results.** Fixed: the observed / inferred / airport structure, with the airport gate on the combined figures (P5-a).
4. **Collection quality was undefined.** Fixed: usable polls; failed polls end windows and never count as absence; repeated timestamps are skipped.
5. **Exactly-once wasn't established.** Fixed: poll identity by data time, detector-first Lua with idempotent replay, failure recorded as a failed poll, and partial loss treated as a break.
6. **The P5 matching wasn't reproducible.** Fixed: the protocol (identity mapping, time tolerances by actual-time type, one-to-one matching, the window, combined and per-method results, and the insufficient-board rule, P5-b).
7. **Retention wasn't enforced.** Fixed: TTLs on every key, a 6 h read filter, and client-side expiry.
