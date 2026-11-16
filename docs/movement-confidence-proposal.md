# Proposal: movement confidence by coverage class (draft r1, for owner decision)

**Status:** draft, 2026-11-16. If approved, this amends D-014 and plan v1.1 §7 / §11 P5 (a plan v1.2 increment), and sets CF-012's eligibility rule.
**Context:** CF-011 shipped with every airport labelled `experimental`, because P5 is defined per pilot airport against that airport's own board ([validation](validation/)). That can't scale to the 11,318 catalogue airports, and most of them publish no usable board.

## 1. Problem
- **Per-airport board checks don't scale.** Of the three pilot airports, only Heathrow and JFK can be checked automatically. Kansai blocks automated access, and Japan's open-data platform (ODPT) has no Kansai airport dataset (§6).
- **"Experimental" everywhere is honest but uninformative.** It can't tell an airport where receivers see every take-off from one where they see none.
- **CF-012 needs an eligibility rule.** It is currently "airport passed P5", which would leave traffic-rate signals unavailable almost everywhere.

## 2. Principle
Movement detection accuracy depends mainly on **what the receivers see at that airport** (ground coverage, low-altitude dropouts, provider reliability, nearby airfields), not on the airport's name. So:
1. **Validate the method once per coverage class**, at sample airports whose boards can be checked automatically.
2. **Measure every airport's coverage continuously** from the detector's own data (no board needed) and place it in a class.
3. **An airport inherits its class's validated accuracy** only while its own measurements stay inside the class bounds and it has been watched enough. Otherwise it is `unknown`.
4. **"Validated" stays reserved** for an airport actually checked against its own board.

The assumption in point 1 is itself tested: each class is validated at **two or more** airports, and their figures must agree (§5). If they don't, the class model is wrong for that class, and the class isn't used.

## 3. Coverage measures (per airport, from the detector's own data)
All are already counted or derivable from state the detector keeps. Each is computed over a rolling window (proposal: the last 7 days of watched time, at least 60 watched minutes).

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
- **Samples:** at least 2 airports per class, each with an automatable ground-truth source that passed a dry run (identity, access, time type, coverage; SHRIKE S23). At least 3 busy hours per airport, on different days.
- **Protocol:** design §9 as amended (identity by flight number, then airline + aircraft type; per-source time-type tolerances). It is fixed per source before recording.
- **Pass:** each sample airport meets P5 (≥90% found, ≤5% false) on its combined hours. The two airports' found rates are within 5 points of each other, which tests the class assumption.
- **Re-validation:** yearly, or when the detector's rules change (a new rule version).

## 6. Ground-truth sources: dry runs (2026-11-16)
- **Heathrow (S):** automated. The board feed has runway times and aircraft types, and was used twice.
- **JFK (S):** automated. The public flight tracker, driven by time window, returns complete departure and arrival lists (1,089 arrival rows for 12:00–18:00 on 2026-11-15). Its times are gate times, so recordings must run to the hour's end plus 45 min. A regional-operator alias rule is needed (EDV, RPA and others flying partner flight numbers). The earlier "no arrivals board" finding was my error: an unsorted list judged by its first and last rows. It is corrected in the [JFK validation note](validation/2026-11-15-kjfk-p5.md).
- **Kansai (D):** **no automated source.** The airport site blocks automated access. ODPT's catalogue has no Kansai airport or operator dataset (searches for 関西, kansai and KIX return none; none of its 138 organisations is Kansai's). Its JAL and ANA airline feeds need registration and would cover only those airlines' flights, about 3–4 of the 31 board movements in the RJBB hour. So class D needs **other sample airports** with automatable boards.
- **Still to find:** two class-D and two class-A sample airports with automatable sources. Method: measure coverage at candidate busy airports cheaply first (the adsb.lol probes used for CF-011), then dry-run their boards.

## 7. What users see
- **A board-checked airport:** "Validated at this airport: found X%, false Y% (date)."
- **Class S, D or A with a validated class:** for example, "Receivers here see aircraft on the ground well. Checked at similar airports: about X% of movements found, Y% false." Inferred movements are still labelled per row.
- **Class U:** "Not enough evidence yet about coverage here", with the list shown as experimental, as today.
- The coverage text in the movements list already exists. This proposal adds the class and its figures and replaces the blanket "experimental" caption.

## 8. CF-012 impact
Traffic-rate signals are eligible at an airport in a **validated class (S or D)**, with the airport's own coverage inside the class bounds and enough watched minutes. Class A and U airports get no traffic-rate signal, only `unknown`. This replaces "airport passed P5" and follows the plan's existing rule that uncertain data shows as unknown.

## 9. Changes this implies
- **Detector:** count gap-inferred movements separately (a sub-basis on inferred), and keep the failed-poll count per window. Both are small.
- **A coverage-measures store** per airport, with a rolling window, updated with each fresh poll (the same write path as movements).
- **API:** `/movements` gains a `confidence` block (class, measures, class figures, basis); `validation` keeps per-airport board results.
- **Docs:** D-014 amendment; plan v1.2 (P5 per class, with pilot airports where an automated source exists); design §9 per-source protocols.

## 10. Owner decisions needed
1. **Adopt the principle** (§2): class validation plus measured coverage, replacing per-airport P5 for the full app.
2. **Pilot airports:** keep P5 per pilot airport where an automated source exists (EGLL, KJFK), and let Kansai inherit class D once validated elsewhere. Or drop per-airport P5 entirely.
3. **Validation size:** 2 airports per class, 3 busy hours each (§5), or a different size.
4. **Wording** of the user-facing class text (§7).

## 11. Risks
- **The class assumption may not hold.** Accuracy may depend on more than measured coverage (runway layout, traffic mix). §5's agreement test detects this, and a failing class stays U.
- **Sample bias:** airports with automatable boards are mostly large Western hubs. Classes D and A may be hard to fill, and stay U until they are.
- **Measures can drift** (receivers come and go). The rolling window and the U fallback keep claims current.
- **Cost:** more recorded busy hours at more airports, though unattended once sources pass their dry runs.
