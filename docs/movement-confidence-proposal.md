# Proposal: movement confidence by coverage class (draft r4, for owner decision)

**Status:** draft r4, 2026-11-16 (r4: a scoped critique of r3, 3 High + 1 Medium, all confirmed; §12). r2 was revised after a CORMORANT critique of r1 (Codex: 3 High, 2 Medium, all confirmed). r3 applies the owner's answers: principle adopted; no airport gets special status; 4 sample airports per class; identity rules with no curated data (§12). If approved, this amends D-014 and plan v1.1 §7 / §11 P5 (a plan v1.2 increment), and sets CF-012's eligibility rule.
**Context:** CF-011 shipped with every airport labelled `experimental`, because P5 is defined per pilot airport against that airport's own board ([validation](validation/)). That can't scale to the 11,318 catalogue airports, and most of them publish no usable board.

## 1. Problem
- **Per-airport board checks don't scale.** Of the three pilot airports, only Heathrow and JFK can be checked automatically. Kansai blocks automated access, and Japan's open-data platform (ODPT) has no Kansai airport dataset (§6).
- **"Experimental" everywhere is honest but uninformative.** It can't tell an airport where receivers see every take-off from one where they see none.
- **CF-012 needs an eligibility rule.** It is currently "airport passed P5", which would leave traffic-rate signals unavailable almost everywhere.

## 2. Principle
Movement detection accuracy depends mainly on **what the receivers see at that airport** (ground coverage, low-altitude dropouts, provider reliability, nearby airfields), not on the airport's name. So:
1. **Validate the method once per coverage class**, at sample airports whose boards can be checked automatically.
2. **Measure every airport's coverage continuously** from the detector's own data (no board needed) and place it in a class.
3. **Every airport, pilots included, is rated the same way:** it inherits its class's validated accuracy only while its own **current** measurements stay inside the class bounds and it has been watched enough (§5a). Otherwise it is `unknown`.
4. **No airport has special status.** Board checks exist only to validate classes, at sample airports chosen by objective criteria (§5). A sample airport's own result feeds its class; it doesn't give that airport a label of its own. The pilot airports (EGLL, KJFK, RJBB) are ordinary airports under this rule, and their 2026-11-15/16 results stay on record as evidence.
5. **No curated data in validation.** Identity rules use only what the feed and the board publish, with no airline tables or aliases (§5).

The assumption in point 1 is itself tested, **on airports not used to set the class** (§5): thresholds come from two calibration airports, and two held-out airports, classified only by their measures, must also meet P5. If either misses, the class isn't used.

**Blind spot, and how it's covered:** the receivers' own statistics can't show movements they never saw. An airport could lose a whole runway and still show a high observed share. §3 therefore adds **conversion measures** with an independent denominator: aircraft seen low on approach or climb-out near the airport, against the movements recorded for them.

## 3. Coverage measures (per airport, from the detector's own data)
Each is computed over the **last 7 calendar days** (not 7 days of watching), from at least 60 watched minutes, and separately over the **last 24 hours** for the freshness check (§5a).

**Conversion measures** (new, the blind-spot check):
- **Approach conversion:** of aircraft seen descending through a low gate near the airport (proposal: below 2,000 ft above field, within 6 nm, on a track toward the airport), the share that got an arrival movement (observed or inferred) within 5 minutes.
- **Climb-out conversion:** the same for departures: aircraft first seen climbing through the low gate, the share that got a departure movement.

A runway or an apron that receivers can't see shows up as a low conversion, even when the observed share looks healthy.

The table below covers the existing measures.

| Measure | Meaning | Evidence it separates classes (recordings, 2026-11-15/16) |
|---|---|---|
| **Observed share** | observed ÷ all movements | EGLL 0.99, KJFK 0.99, RJBB 0.91, RKSI 0.08 (15 min), WSSS 0.00 (15 min) |
| **Ground fixes per poll** (within 4 nm) | do receivers see the surface? | EGLL 27.0, KJFK 24.4, RJBB 7.1, RKSI 3.1, WSSS 0.0 |
| **Gap-inferred share** | movements needing the §3 gap rule | (new counter; RJBB had 6 of 68) |
| **Failed-poll rate** | provider failures while watched | EGLL 4.7%, KJFK 7.6%, RJBB 0.9% |
| **Neighbour ambiguity** | catalogue airfields within 5 nm | fixed per airport (EGLL: Northolt) |
| **Watched minutes** | how much evidence there is | gate for any class |
| **Plain flight-number callsign share** | the traffic mix the validation can speak for (r4) | EGLL 41%, KJFK 92%, RJBB 97% |

The 15-minute RKSI and WSSS figures are short probes, indicative only.

## 4. Classes (thresholds to be set from the validation data, §5)
| Class | Description | Example | What users are told |
|---|---|---|---|
| **S — surface, clean** | high observed share, many ground fixes, few gap inferences | EGLL, KJFK | the class's validated found and false figures |
| **D — surface with runway dropouts** | ground seen, but aircraft lost low over the runway | RJBB, RKSI | figures for class D; inferred share shown |
| **A — airborne only** | no ground fixes | WSSS | inferred only; figures for class A, if validated |
| **U — unknown** | too little watching, measures outside every class, or class not validated | most airports at first | "not enough evidence yet" |

**Modifiers:**
- a **high failed-poll rate** (proposal: over 10%) drops an airport to U while it lasts;
- **neighbour ambiguity** is shown when relevant ("movements near Northolt are left out").

## 5. Validation of a class
- **Samples (owner, 2026-11-16):** **4 airports per class**, at least 3 busy hours each on different days. A sample airport must meet **objective criteria**, all checked automatically before it's chosen:
  1. a board source that can be captured automatically and passed a dry run (identity, access, time type, coverage; SHRIKE S23);
  2. **identity coverage:** at least 80% of its detected movements carry a plain flight-number callsign (3 letters + digits). Measured: KJFK 92%, RJBB 97%, EGLL 41% (BA and Shuttle fly ATC callsigns such as `BAW35LF`, `SHT6Q`), so EGLL can't be a sample;
  3. its coverage measures (§3) place it in the class.
- **Calibration and transfer test:** class bounds, including the conversion thresholds, are set from 2 calibration airports. The other 2 are **held out**. They're classified by their measures alone, and each must meet P5 on its own hours. Only then is the class validated. If a held-out airport misses, the class isn't used (U), whatever the calibration airports scored.
- **Identity rules, with no curated data (owner, 2026-11-16).** These replace the IATA→ICAO table and the airline aliases:
  1. **A plain flight-number callsign** (3 letters + digits) matches a board flight with **the same number**, the same movement type and a time within tolerance, **whatever the airline prefix**. Regional operators (`EDV5150` = DL5150), operating carriers (`LPE2691` = LA2691) and unlisted airlines (`ASL500` = JU500) need no table. Measured on the three recorded hours: 0 of 163 numbered detections had more than one candidate, and all 12 matches across different prefixes were the right flight.
  2. **Any other callsign** (an ATC callsign, or none) matches only on the aircraft type (feed and board), movement and time, and only if **exactly one** still-unmatched board flight fits:
     - **no fitting board flight** means unmatched, so it **counts as false**;
     - **several** fitting flights means **unidentified**;
     - a detection with **no aircraft type** is unidentified.
  - **Order:** rule 1 runs first over all detections, one-to-one, closest time first (several numbered candidates resolve to the closest). Rule 2 then runs on what remains, so its "exactly one" counts only board flights rule 1 left unmatched.
  - **Unidentified detections are bounded, not hidden:** each sample reports **false** (unmatched ÷ identified) and **worst-case false** ((unmatched + unidentified) ÷ all detections). The sample passes only if worst-case false is at most 5%. The false figure can then never understate spurious detections in the complete list by more than the P5 margin.
  - **Coincidence check, measured per sample:** both rules run again with the detections shifted by 3 hours, against the same board. Any match there is coincidental. The coincidental-match rate must be at most 1% of detections, or the sample fails. This measures unique-but-wrong matches, which uniqueness alone can't.
- **Time tolerances:** per source by its time type (runway ±5 min; gate times wider; recording to the hour's end plus 45 min for gate-time boards), fixed per source before recording.
- **Pass:** every sample airport meets P5 on its combined hours: ≥90% found, and **worst-case** false ≤5% (above). Each method (observed, inferred) is also assessed per class, so its own label can be inherited (§9).
- **Callsign mix is a class bound (r4, critique finding 2).** The share of plain flight-number callsigns is one of the class measures (§3). An airport inherits only if its share is within the range its class's samples covered. Airports dominated by ATC callsigns (EGLL, 41%) are therefore **U**: the validation hasn't tested traffic like theirs. Whether to lift this, and how, is owner decision 5.
- **Validity:** a class result carries the detector rule version and provider it was measured with. It expires after 12 months, or immediately on a new rule version or provider (§5a).

## 5a. Freshness and invalidation (read time)
An airport's inherited class figures are shown only if **all** of these hold when `/movements` is read; otherwise it is U:
- its 7-day measures are inside the class bounds, from at least 60 watched minutes, **and** its last-24-hour measures are too (when it was watched in the last 24 hours);
- it was watched within the last 7 days;
- its last-24-hour failed-poll rate is at most 10%;
- the class result is current: same provider, same detector rule version, not older than 12 months;
- its measure store is intact; a lost or unreadable store means U until rebuilt by watching.

The rules apply at read time, so a stale class can't persist just because no new poll arrived. Each rule has a test.

## 6. Ground-truth sources: dry runs (2026-11-16)
- **Heathrow (S):** the board is automated (runway times, aircraft types), but identity coverage is 41%, so it **can't be a sample** under §5. It is rated by its class like any airport.
- **JFK (S):** **sample candidate.** The public flight tracker, driven by time window, returns complete departure and arrival lists (1,089 arrival rows for 12:00–18:00 on 2026-11-15). Identity coverage is 92%. Its times are gate times, so recordings run to the hour's end plus 45 min. Regional operators are handled by identity rule 1, with no alias list. The earlier "no arrivals board" finding was my error: an unsorted list judged by its first and last rows. It is corrected in the [JFK validation note](validation/2026-11-15-kjfk-p5.md).
- **Kansai (D):** **no automated source.** The airport site blocks automated access. ODPT's catalogue has no Kansai airport or operator dataset (searches for 関西, kansai and KIX return none; none of its 138 organisations is Kansai's). Its JAL and ANA airline feeds need registration and would cover only those airlines' flights, about 3–4 of the 31 board movements in the RJBB hour. So class D needs **other sample airports** with automatable boards.
- **Still to find:** 4 sample airports per class meeting §5's criteria. JFK is 1 for class S, and Kansai would qualify on identity but has no automated board. **Method, fully automatic:**
  1. probe candidate busy airports with adsb.lol for coverage class and identity coverage (the same probes as CF-011);
  2. dry-run their public boards;
  3. keep those that pass.

  If a class can't reach 4, it stays U.

## 7. What users see
The same rule for every airport, pilots included:
1. **The airport's class applies** under §5a: the class text below.
2. **Otherwise U.**

Sample airports' own results feed their class and are published in `docs/validation/`. They don't change that airport's label. This also removes r2's "failed check" case: Heathrow's checks, made under the earlier curated identity rule, stay on record as evidence only.

Per-method labels stay: an inferred row is always labelled inferred, and a method that failed its own figures is shown as experimental, as the design already requires.
- **Class S, D or A with a validated class:** for example, "Receivers here see aircraft on the ground well. Checked at similar airports: about X% of movements found, Y% false." Inferred movements are still labelled per row.
- **Class U:** "Not enough evidence yet about coverage here", with the list shown as experimental, as today.
- The coverage text in the movements list already exists. This proposal adds the class and its figures and replaces the blanket "experimental" caption.

## 8. CF-012 impact
A traffic-rate signal needs **all** of these:
1. **Movement accuracy:** the airport's class applies (§7), with class S or D. Class A and U airports get `unknown`. This replaces "airport passed P5".
2. **Current-window completeness, unchanged** (plan §3): at least 90% of the current window watched, with no gap over 5 minutes. A class or a validation never substitutes for it.
3. **Baseline comparability, unchanged** (plan §3): the baseline uses the same movement definition and source type, or a validated adjustment. Class validation says nothing about the baseline.

## 9. Changes this implies
- **Detector:** count gap-inferred movements separately (a sub-basis on inferred), and keep the failed-poll count per window. Both are small.
- **A coverage-measures store** per (provider, airport):
  - **Contents:** hourly count buckets for 8 days, counts only, with no aircraft identifiers, so it doesn't extend the 6-hour retention of callsigns and hex codes.
  - **Write path:** inside the existing compare-and-set write, so a replayed poll changes nothing, and a measure can't diverge from the movements it counts.
  - **Failed polls:** counted in the same atomic write as `record_failure`, including repeated failures while no window is open.
  - **Initialisation:** existing airports start empty (U) and fill by watching; there's no back-fill from the 6-hour state.
  - **Expiry:** a key TTL of 8 days.
- **Conversion tracking:** the detector keeps a small per-aircraft "seen in the low gate" marker within the existing aircraft state (15-minute TTL), and counts the gate entries and the conversions into the hourly buckets.
- **API:** `/movements` gains a `confidence` block (class, measures, class figures, basis); `validation` is **kept**, with the same shape (`observed`, `inferred`, `airport`), now **derived from the class**:
  - `observed` and `inferred` come from the class's per-method results;
  - `airport` is `validated` when the class applies under §5a, otherwise `experimental`.
  
  No schema break, so existing clients and contract fixtures keep working. A method that failed, or couldn't be assessed in the class, stays `experimental`.
- **Docs:** D-014 amendment; plan v1.2 (P5 per class, with pilot airports where an automated source exists); design §9 per-source protocols.

## 10. Owner decisions
**Decided 2026-11-16:**
1. **Principle adopted:** class validation plus measured coverage replaces per-airport P5 (plan v1.2).
2. **No special status for any airport:** pilots are rated by class, and board checks only feed classes (§2, §7).
3. **Sample size:** 4 airports per class (2 calibration, 2 held out), 3 busy hours each.
4. **No curated data:** identity by plain flight number with any prefix, else a unique aircraft-type match, else unidentified (§5). This replaces the IATA→ICAO table and the JFK alias proposal.

**Still open:**
5. **ATC-callsign airports (critique finding 2).** Choose one:
   - **(a) U until tested (recommended):** callsign mix is a class bound, so such airports are U, including EGLL.
   - **(b) Test the assumption:** add a test that detection accuracy doesn't depend on callsign format. Within sample airports, compare rule-2-matched (ATC-callsign) flights with numbered ones over all 12 hours per class. Lift the bound only if they agree within 5 points. Start with (a).
   - **(c) Accept the assumption untested,** and say so in the class text.
   
   The 80% bar for choosing sample airports stays either way: below it, identity can't be measured reliably.
6. **Wording** of the user-facing class text (§7).
7. **Approval of r3 as a whole,** then the plan v1.2 text and the D-014 amendment.

## 11. Risks
- **The class assumption may not hold.** Accuracy may depend on more than measured coverage (runway layout, traffic mix). §5's agreement test detects this, and a failing class stays U.
- **Sample bias:** airports with automatable boards are mostly large Western hubs. Classes D and A may be hard to fill, and stay U until they are.
- **Measures can drift** (receivers come and go). The rolling window and the U fallback keep claims current.
- **Cost:** more recorded busy hours at more airports, though unattended once sources pass their dry runs.

## 12. Revision history
- **r1** (`cc8471a`): first draft.
- **r2:** CORMORANT critique of r1 (`~/codex-reviews/ClearFlight-API-confidence-proposal-r1-critique-20261116T085328Z.md`, Codex, read-only). 5 findings, **5 confirmed, 0 refuted**:
  1. *High, accuracy transfer untested, and a blind spot for movements never seen:* added conversion measures (§3) and a held-out airport per class (§5).
  2. *High, no freshness or invalidation contract:* added §5a, with read-time rules and class validity by provider and rule version.
  3. *High, CF-012 dropped the current-window and baseline gates:* §8 keeps both explicitly.
  4. *Medium, the measure store couldn't be rebuilt from the retained state:* §9 specifies counts-only hourly buckets in the same atomic write, failed-poll counting, initialisation and an 8-day TTL.
  5. *Medium, "board-checked" would label a failed check as validated:* §7 adds a precedence (passed, failed, class, U); Heathrow's failed check is shown as such.
- Still for the owner (§10), plus one raised by the critique: the regional-operator matching rule for JFK, fixed before any fresh JFK recording.
- **r3:** owner answers 2026-11-16:
  - **Principle adopted.**
  - **No special status for pilot airports** ("Is it not inconsistent to retain the checks for the pilot airports while the rest go off classes?"): §2, §7 and §8 now use one rule for all airports.
  - **4 airports per class.**
  - **No curated data** ("we need a solution that will cover all airports without curating data"): §5's identity rules drop the IATA→ICAO table and the aliases. The plain-number rule was measured before adoption on the three recorded hours: 0 ambiguous of 163, and 12 of 12 cross-prefix matches correct.
  - **Sample criteria added.** Identity coverage of at least 80% excludes EGLL (41%); KJFK (92%) qualifies.
  - **Not yet critiqued:** r3 changes the r2 design materially (sample criteria, identity rules, label precedence), so it gets a scoped critique before approval.
- **r4:** scoped CORMORANT critique of r3 (`~/codex-reviews/ClearFlight-API-confidence-proposal-r3-critique-*.md`, Codex, read-only). 3 High + 1 Medium, **4 confirmed, 0 refuted**:
  1. *High, "unidentified" could hide spurious detections:* zero candidates now counts as false; a sample passes only on **worst-case false** ≤5%.
  2. *High, the 80% filter left transfer untested for ATC-callsign traffic:* the callsign mix becomes a class bound (such airports are U), with owner decision 5 on lifting it.
  3. *High, unique-but-wrong matches unmeasured, and the rule order unspecified:* a 3-hour-shift coincidence check (≤1%), and an explicit order (numbered first, closest time; type-unique on the remainder).
  4. *Medium, retiring `validation` broke the labels and the contract:* the field is kept, same shape, derived from the class, so no schema break.
- **Critique budget:** two rounds (r1 full, r3 scoped), both well within CORMORANT's caps. No further critique before approval; the implementation gets its normal code reviews.
