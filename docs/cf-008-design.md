# CF-008 forecast outlook — design spec (draft for owner approval)

**Status:** r3, **approved by the owner 2026-11-09** (decisions F1–F5, §7; revised after the Codex design critique of r2, §9).
**Sources:**
- Plan v1.1 §1 (claims rules), §2 feature 3, §4 (`/forecast`), §5 (CF-008), §7 (gates); D-010.
- The existing METAR adapter and conditions index (D-006, D-007, D-009).
- A live AWC TAF probe (2026-11-09) of 21 stations, recorded in `tests/testfiles/awc/taf_*.json`.

## 1. What the user gets
On the airport page, below the current conditions, a **"Forecast (next 12 hours)"** section:
- one cell per hour, in local time with UTC on hover/expand;
- in each cell, the **forecast** conditions index for the expected (prevailing) conditions;
- where the forecast says conditions may temporarily be worse, an **"up to N"** mark with its wording ("temporarily", "30% chance");
- expanding an hour shows its factors in plain English, as on the current card;
- the source ("NOAA Aviation Weather Center: Terminal Aerodrome Forecast"), issue time, validity, and the raw TAF in a disclosure;
- the disclaimer: a forecast, not observed weather; it doesn't predict delays or flight safety.

Forecast values are always visibly distinct from the observed index: a "Forecast" label and a different style (dashed outline, no filled level chip). They're never merged with the current conditions card.

## 2. What the provider gives (live probe, 2026-11-09)
`GET https://aviationweather.gov/api/data/taf?ids={ICAO}&format=json` returns a list. An unknown station or a station with no TAF returns **200 with `[]`**; many small airfields issue no TAF. Each TAF has:
- the issue and validity times;
- `rawTAF`;
- `fcsts`: decoded periods, each with `timeFrom`, `timeTo`, `timeBec`, `fcstChange`, `probability`, wind (`wdir` incl. "VRB", `wspd`, `wgst`), `visib`, `vertVis`, `wxString`, `clouds` and `notDecoded`.

| `fcstChange` | Meaning | How AWC decodes it |
|---|---|---|
| none | base forecast | full state |
| `FM` | from this time, a complete new state | full state |
| `BECMG` | changing gradually between `timeFrom` and `timeBec` | AWC carries unchanged elements forward (full state); the new state is complete at `timeBec` |
| `TEMPO` | temporary fluctuations, less than half the period | **only the changed elements** (others null) |
| `PROB` (30/40) | a chance of these conditions | only the changed elements; may be combined with TEMPO (`probability` set on a TEMPO period) |

**Quirks:**
- `visib` can be a number (SM), `"6+"`, or `""` (missing).
- Cloud covers include `NSC`, `SKC`, `OVX` and `CB`/`TCU` types.
- `vertVis` is feet when given; **a base `VV///` (sky obscured, height unknown) is not decoded at all**: clouds are just `[]`.
- `wxString` can be `NSW` (no significant weather), which isn't in our weather scoring table.

## 3. Turning a TAF into an hourly outlook
1. **Selection and validation** (a trust boundary; [r3: critique 4]):
   - Use the TAF for the requested station with `mostRecent = 1`; if there's none, use the latest `issueTime`.
   - Required: `issueTime`, `validTimeFrom` < `validTimeTo`, a base period (no `fcstChange`) starting at `validTimeFrom`, and every period with `timeFrom < timeTo` inside the validity (`timeBec`, when present, is ≥ `timeFrom` and inside the validity; `timeBec > timeTo` is allowed and seen live).
   - A station mismatch, a missing base or a period outside the validity means the **payload is invalid**: a 502 `provider_error` with reason `invalid_forecast` (the D-006/D-007 mapping, which is truthful: the provider's data is unusable). It is not cached as success.
   - Unknown `fcstChange` values don't reject the TAF. Because they can't be matched to a raw group, the raw/decoded alignment fails and every hour shows as `unknown` (more cautious than marking only the hours they overlap).
   - Now > `validTimeTo` → `unavailable` / `forecast_expired`.
2. **Coverage per hour:**
   - an hour before `validTimeFrom` is `not_yet_valid` (no score; "Forecast starts at HH:MM");
   - an hour after `validTimeTo` is dropped (the horizon cuts there);
   - an hour within the validity that no prevailing state covers (a gap) is `unknown`.
3. **Field presence: omitted vs unknown** ([r3: critique 1]). Each decoded period is aligned with its raw change group: split `rawTAF` at `FM`, `BECMG`, `TEMPO` and `PROB30/40`, in order. The raw group decides *which* elements the group states:
   - **wind:** a `dddffKT` / `VRBffKT` token;
   - **visibility:** a 4-digit metres value, `nSM`, `PnSM` or `CAVOK`;
   - **weather:** weather groups or `NSW`;
   - **sky:** cloud groups, `NSC`, `SKC`, `CAVOK` or `VV`.
   
   The decoded values supply the numbers, except that a metric visibility token (e.g. `0150`, `9999`) is read from the raw text exactly, since AWC's statute-mile decode is rounded. For each element:
   - **Omitted** (no token in a TEMPO/PROB/BECMG group): **inherit** from the state it modifies. In a base/FM group, which must be complete, an omitted element is **unknown**.
   - **Stated and valid:** the decoded value (D-006 ranges and units; `"6+"` → 10 km for metric TAFs with `9999`/`CAVOK`, else 6 SM "or more"; `NSW` → no significant weather; `vertVis` → ceiling; `VV///` → obscured, height unknown; `CAVOK`/`NSC`/`SKC` → no cloud ceiling).
   - **Stated but unusable** (e.g. `""` decoded while the raw group has a visibility token, or a value out of range): **unknown**, never inherited.
   - If the raw groups don't align with the decoded periods (a different count or order of change types), every element of every period is **unknown** except what both sources agree on. In practice the TAF then shows as unknown. Never guess.
4. **Prevailing candidates per hour** (deterministic; F3; [r3: critique 3]): a timeline of **candidate states**, the set of conditions that could be in force:
   - start: {base};
   - `FM` at t: the candidates become {FM state} from t;
   - `BECMG` from `timeFrom` to `timeBec`: during the transition, candidates = (the candidates in force at `timeFrom`) ∪ {the new state}; from `timeBec`, candidates = {the new state};
   - a BECMG starting while an earlier one is still in transition takes **all** current candidates as its "old" set, so overlapping transitions accumulate candidates until each completes. For example, EGLL 11:00–12:00 has four candidates: the fog base, the BECMG-1 state, and the BECMG-2 change applied to each of those two;
   - **prevailing score** for an hour = the worst score over all candidates and all instants in the hour; "changing" when more than one candidate applies;
   - each BECMG's new state is AWC's carried-forward state, re-checked against the raw group (step 3).
5. **Possible variants** (TEMPO/PROB):
   - each TEMPO or PROB period overlapping the hour is applied to **each** prevailing candidate (its stated elements replace the candidate's), giving variants;
   - "up to N" is the worst variant score, with the label of the variant that produced it;
   - if a variant has an unknown input and isn't already 10, the hour shows **"may be worse (details unknown)"** instead of a number (F5).
6. **Index** ([r3: critique 6]):
   - The index's **scoring** (factor bands, max-10 exception) is shared; the **presentation** is per kind:
     - `evaluate_forecast()` produces "Forecast conditions index N/10 (level), mainly from …";
     - it uses the forecast disclaimer;
     - it has no `current` freshness requirement, since validity is checked in steps 1–2;
     - it keeps every other rule.
   - The observed `evaluate()` is unchanged (regression test).
   - The forecast `conditions` object has the same shape as the observed one, including `version` and `disclaimer`, so the frontend schema reuses it.
7. **Horizon:** the 12 hours starting with the current hour, cut at `validTimeTo` (F2).

## 4. API: `GET /v1/airports/{code}/forecast`
Same code handling, errors and provider-failure mapping as `/conditions` (D-007): 400, 404, 502, 503 (Retry-After), 504.
```text
{
  airport: {...same as /conditions},
  forecast: { source, station, issued_at, valid_from, valid_to, raw_text } | null,
  hours: [ {
    start, end,                       // UTC; one per hour
    prevailing: { conditions (version, score, level, factors, explanation),
                  changing: bool },   // inside a BECMG transition
    possible: [ { label: "temporarily" | "30% chance" | ..., probability: 30|40|null,
                  temporary: bool, conditions } ]
  } ],
  data_status: "available" | "unavailable",
  unavailable_reason: null | "no_metar_station" | "no_forecast" | "forecast_expired",
  // hour-level state: hours[].status = "forecast" | "not_yet_valid" | "unknown"
  disclaimer: "Forecast from the airport's official TAF. It is not observed weather and does not predict delays, cancellations or flight safety."
}
```
- Cache: the TAF per station for 30 minutes (TAFs are issued about every 6 hours and amended when needed), using the existing rate cap, retry and typed errors.
- An empty TAF response → `no_forecast`, cached for 30 minutes (like `no_report`). It means "no forecast available right now", **not** "this airport doesn't publish TAFs" [r3: critique 2].
- `hours` are computed at read time from the cached TAF, so they move on as time passes.

## 5. Frontend
- A forecast section on the airport page:
  - a horizontal hourly strip on desktop and a vertical list on phones;
  - a cell shows the local time, the forecast score with "Forecast" styling (outline, not filled), and "up to N" with its label when present;
  - selecting a cell opens its details.
- States:
  - loading;
  - no forecast ("No forecast is available for this airport right now");
  - expired ("The latest forecast has expired");
  - not yet valid (per hour);
  - errors, as on the conditions card.
- **Ageing on screen** [r3: critique 5], the same pattern as D-008/D11:
  - each hour drops once its `end` has passed;
  - the whole forecast is withdrawn (expired state) after `valid_to`;
  - this is checked at each hour boundary, on tab resume and while refreshes fail;
  - a failed refresh keeps the remaining valid hours and says it couldn't update;
  - tests cover the boundaries, tab resume and repeated failures.
- A schema and fixtures for the new response, with contract tests on both sides (D-008).
- Refreshing follows the conditions card: every 5 minutes while visible, plus manual refresh.

## 6. Tests
- **Selection and validation:** invalid payloads (station mismatch, no base, periods outside validity) → 502 `invalid_forecast`; not-yet-valid hours; gaps; unknown change types; `mostRecent` selection.
- **Presence:** omitted vs stated-unusable for each element (EGLL's cloud-only TEMPO with `""` visibility inherits; a raw visibility token with an unusable decode is unknown); misaligned groups → unknown.
- **Overlapping BECMG:** EGLL's 08–12/11–13 with the expected candidate sets and scores per hour.
- **Parser and normaliser:** the recorded TAFs (pilots plus five variants: FM groups, BECMG transitions, PROB30/PROB40, TEMPO combined with PROB, VV with height, base `VV///`, `NSW`, empty visibility, `6+` with `P6SM` vs `9999`). Also group alignment and the unknown-sky fallback on a mismatch.
- **Timeline:** exact hour boundaries; BECMG transitions (worse-of); TEMPO/PROB overlays; the 12-hour horizon cut at validity; an expired TAF.
- **Index:**
  - prevailing vs "up to";
  - unknown inputs and "may be worse (details unknown)";
  - an observed-index regression test (wording and disclaimer unchanged);
  - the claims-wording test on **generated** forecast text (explanations and factor details): no "observed", "delay" or "safe". The fixed forecast disclaimer is checked separately for its required wording.
- **Endpoint:** the composed adapter (cache, `[]` → `no_forecast`, errors, rate cap).
- **Frontend:** unit tests, end-to-end tests with axe, and a visual distinction between forecast and observed.

## 7. Owner decisions (2026-11-09)
| # | Decision | Chosen |
|---|---|---|
| F1 | Presentation | An hourly outlook with prevailing conditions plus "up to N" for TEMPO/PROB variants (§3), rather than listing the TAF groups as written |
| F2 | Horizon | The next 12 hours (TAFs usually cover 24–30 h); longer horizons are less useful and less certain |
| F3 | BECMG transition hours | Score the worse of the old and new states, labelled "changing" (cautious) |
| F4 | Visual distinction | "Forecast" label, outlined cells, no filled level chips; never on the observed card |
| **F5** (new, from the critique) | Hours where the possible conditions can't be scored | Show "may be worse (details unknown)" instead of a number, and not-yet-valid hours as "Forecast starts at HH:MM" (chosen 2026-11-09) |

## 8. Out of scope
- Other forecast products (area forecasts, model data).
- Temperature forecasts (TX/TN groups).
- Icing and turbulence groups.
- Wind shear.
- Combining the forecast with flight data (CF-012).

## 9. Design critique (CORMORANT, r2 → r3)
Codex critique of the frozen r2 (2026-11-09): 4 High and 2 Medium, all confirmed, none refuted.
1. Omitted vs unknown fields were conflated, so unknown visibility could be inherited as known. Fixed: field presence comes from the raw groups (§3.3).
2. An empty response was worded as "doesn't publish TAFs". Fixed: availability wording.
3. Overlapping BECMG transitions had no deterministic rule. Fixed: candidate sets (§3.4), with EGLL's expected outputs as a test.
4. Validation lacked coverage rules and a truthful invalid-payload result. Fixed: selection, required fields, `not_yet_valid` and gaps, 502 `invalid_forecast`.
5. Forecast hours could outlive their time on screen. Fixed: frontend ageing by `end`/`valid_to` with tests.
6. Reusing the index would have produced "observed" wording. Fixed: shared scoring, per-kind presentation, an observed regression test, and a scoped wording test.
