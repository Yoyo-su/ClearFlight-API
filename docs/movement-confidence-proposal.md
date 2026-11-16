# Proposal: movement confidence by coverage class (draft r2, for owner decision)

**Status:** draft r2, 2026-11-16, revised after a CORMORANT critique of r1 (Codex: 3 High, 2 Medium, all confirmed; §12). If approved, this amends D-014 and plan v1.1 §7 / §11 P5 (a plan v1.2 increment), and sets CF-012's eligibility rule.
**Context:** CF-011 shipped with every airport labelled `experimental`, because P5 is defined per pilot airport against that airport's own board ([validation](validation/)). That can't scale to the 11,318 catalogue airports, and most of them publish no usable board.

## 1. Problem
- **Per-airport board checks don't scale.** Of the three pilot airports, only Heathrow and JFK can be checked automatically. Kansai blocks automated access, and Japan's open-data platform (ODPT) has no Kansai airport dataset (§6).
- **"Experimental" everywhere is honest but uninformative.** It can't tell an airport where receivers see every take-off from one where they see none.
- **CF-012 needs an eligibility rule.** It is currently "airport passed P5", which would leave traffic-rate signals unavailable almost everywhere.

## 2. Principle
Movement detection accuracy depends mainly on **what the receivers see at that airport** (ground coverage, low-altitude dropouts, provider reliability, nearby airfields), not on the airport's name. So:
1. **Validate the method once per coverage class**, at sample airports whose boards can be checked automatically.
2. **Measure every airport's coverage continuously** from the detector's own data (no board needed) and place it in a class.
3. **An airport inherits its class's validated accuracy** only while its own **current** measurements stay inside the class bounds and it has been watched enough (§5a). Otherwise it is `unknown`.
4. **"Validated" stays reserved** for an airport whose own board check **passed** and hasn't expired (§7).

The assumption in point 1 is itself tested, **on airports not used to set the class** (§5): thresholds come from two sample airports, and a third, held-out airport classified only by its measures must also meet P5. If it doesn't, the class isn't used.

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
- **Samples:** **3 airports per class**, each with an automatable ground-truth source that passed a dry run (identity, access, time type, coverage; SHRIKE S23). At least 3 busy hours per airport, on different days.
- **Calibration and transfer test:** class bounds, including the conversion thresholds, are set from 2 calibration airports. The third airport is **held out**. It is classified by its measures alone, and it must meet P5 on its own hours. Only then is the class validated. If the held-out airport misses, the class isn't used (U), whatever the calibration airports scored.
- **Protocol:** design §9 as amended (identity by flight number, then airline + aircraft type; per-source time-type tolerances). It is fixed per source before recording.
- **Pass:** every sample airport meets P5 (≥90% found, ≤5% false) on its combined hours.
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
- **Heathrow (S):** automated. The board feed has runway times and aircraft types, and was used twice.
- **JFK (S):** automated. The public flight tracker, driven by time window, returns complete departure and arrival lists (1,089 arrival rows for 12:00–18:00 on 2026-11-15). Its times are gate times, so recordings must run to the hour's end plus 45 min. A regional-operator alias rule is needed (EDV, RPA and others flying partner flight numbers). The earlier "no arrivals board" finding was my error: an unsorted list judged by its first and last rows. It is corrected in the [JFK validation note](validation/2026-11-15-kjfk-p5.md).
- **Kansai (D):** **no automated source.** The airport site blocks automated access. ODPT's catalogue has no Kansai airport or operator dataset (searches for 関西, kansai and KIX return none; none of its 138 organisations is Kansai's). Its JAL and ANA airline feeds need registration and would cover only those airlines' flights, about 3–4 of the 31 board movements in the RJBB hour. So class D needs **other sample airports** with automatable boards.
- **Still to find:** two class-D and two class-A sample airports with automatable sources. Method: measure coverage at candidate busy airports cheaply first (the adsb.lol probes used for CF-011), then dry-run their boards.

## 7. What users see
**Precedence**, first match wins:
1. **This airport's board check passed** and is current (§5 validity): "Validated at this airport: found X%, false Y% (date)."
2. **This airport's board check failed** and is current: "Checked at this airport: below our accuracy bar (found X%, false Y%, date)." No class figures are inherited: the airport's own evidence beats its class. This is Heathrow today.
3. **A class applies** under §5a: the class text below.
4. **Otherwise U.**

Per-method labels stay: an inferred row is always labelled inferred, and a method that failed its own figures is shown as experimental, as the design already requires.
- **Class S, D or A with a validated class:** for example, "Receivers here see aircraft on the ground well. Checked at similar airports: about X% of movements found, Y% false." Inferred movements are still labelled per row.
- **Class U:** "Not enough evidence yet about coverage here", with the list shown as experimental, as today.
- The coverage text in the movements list already exists. This proposal adds the class and its figures and replaces the blanket "experimental" caption.

## 8. CF-012 impact
A traffic-rate signal needs **all** of these:
1. **Movement accuracy:** the airport is validated (§7 rule 1), or its class applies (rule 3), with class S or D. Class A, U, and airports whose own check failed (rule 2) get `unknown`. This replaces "airport passed P5".
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
- **API:** `/movements` gains a `confidence` block (class, measures, class figures, basis); `validation` keeps per-airport board results.
- **Docs:** D-014 amendment; plan v1.2 (P5 per class, with pilot airports where an automated source exists); design §9 per-source protocols.

## 10. Owner decisions needed
1. **Adopt the principle** (§2): class validation plus measured coverage, replacing per-airport P5 for the full app.
2. **Pilot airports:** keep P5 per pilot airport where an automated source exists (EGLL, KJFK), and let Kansai inherit class D once validated elsewhere. Or drop per-airport P5 entirely.
3. **Validation size:** 3 airports per class (2 calibration, 1 held out), 3 busy hours each (§5), or a different size.
4. **Wording** of the user-facing class text (§7).
5. **JFK regional operators:** adopt an alias rule (EDV, RPA, SKW, ENY, JIA, ASH, GJS, PDT flying partner flight numbers), fixed before any fresh JFK hour.

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
