import type {
  AircraftPosition,
  AircraftResponse,
  Conditions,
  ConditionsResponse,
  ForecastHour,
  ForecastResponse,
  NearbyStation,
  RadarResponse,
} from "../api/types";

// Data kept on screen ages (spec §4, D11). The API's current_until and
// stale_until come from the backend's thresholds (the single freshness
// authority); the page applies them as time passes, including while
// refreshes fail or the tab was in the background.

export type View = "current" | "stale" | "too-old" | "no-report" | "no-station";

export function viewAt(data: ConditionsResponse, now: Date): View {
  if (data.data_status === "unavailable") {
    if (data.unavailable_reason === "no_metar_station") return "no-station";
    if (data.unavailable_reason === "observation_too_old") return "too-old";
    return "no-report";
  }
  // Inclusive like the backend (metar.freshness): exactly at current_until the
  // report is still current; it becomes stale just after.
  const t = now.getTime();
  if (data.stale_until && t > Date.parse(data.stale_until)) return "too-old";
  if (data.data_status === "stale") return "stale";
  if (data.current_until && t > Date.parse(data.current_until)) return "stale";
  return "current";
}

export const STALE_EXPLANATION =
  "No score: the latest observation is too old to score; its values are shown with their age.";

/** The conditions to show: a score is withdrawn once the data is stale. */
export function conditionsFor(data: ConditionsResponse, view: View): Conditions {
  if (view !== "stale" || data.conditions.score === null) return data.conditions;
  return { ...data.conditions, score: null, level: "unknown", explanation: STALE_EXPLANATION };
}

// Forecasts age too (CF-008 spec §5): an hour leaves the screen once it has
// ended, and the whole forecast is withdrawn at valid_to, including while
// refreshes fail or the tab was in the background.

export type ForecastView =
  | { kind: "hours"; hours: ForecastHour[] }
  | { kind: "expired" }
  | { kind: "outdated" } // every downloaded hour has passed, but the TAF is still valid
  | { kind: "no-forecast" }
  | { kind: "no-station" };

export function forecastViewAt(data: ForecastResponse, now: Date): ForecastView {
  if (data.unavailable_reason === "no_metar_station") return { kind: "no-station" };
  if (data.unavailable_reason === "no_forecast") return { kind: "no-forecast" };
  const t = now.getTime();
  if (data.unavailable_reason === "forecast_expired" || !data.forecast || t >= Date.parse(data.forecast.valid_to)) {
    return { kind: "expired" };
  }
  const hours = data.hours.filter((hour) => Date.parse(hour.end) > t);
  return hours.length > 0 ? { kind: "hours", hours } : { kind: "outdated" };
}

// Map layers age too (CF-010 §3-§5): every position at its own expires_at,
// every state claim at its own deadline, stations by their freshness times
// and the radar frame by its current_until, whether or not refreshes work.

const CLAIM_MS = 60_000; // no_aircraft / coverage_unknown hold for 60 s (CF-009 §7)

export type AircraftView =
  | { kind: "aircraft"; aircraft: AircraftPosition[] }
  | { kind: "no-aircraft" }
  | { kind: "coverage-unknown"; reason: string | null }
  | { kind: "limit"; retryAt: string | null }
  | { kind: "disabled" }
  | { kind: "unavailable"; reason: string | null }
  | { kind: "outdated" }; // the claim or every position has expired

export function aircraftViewAt(data: AircraftResponse, now: Date): AircraftView {
  const t = now.getTime();
  const claimHolds = data.observed_at !== null && t < Date.parse(data.observed_at) + CLAIM_MS;
  switch (data.data_status) {
    case "available": {
      const aircraft = data.aircraft.filter((a) => t < Date.parse(a.expires_at));
      if (aircraft.length > 0) return { kind: "aircraft", aircraft };
      // Only withheld aircraft, or every position has expired.
      return data.aircraft.length === 0 && claimHolds ? { kind: "aircraft", aircraft: [] } : { kind: "outdated" };
    }
    case "no_aircraft":
      return claimHolds ? { kind: "no-aircraft" } : { kind: "outdated" };
    case "coverage_unknown":
      // Claims without a feed time (e.g. "busy") hold until the next refresh.
      return data.observed_at === null || claimHolds ? { kind: "coverage-unknown", reason: data.unavailable_reason } : { kind: "outdated" };
    case "quota_exhausted":
      return data.retry_at === null || t < Date.parse(data.retry_at)
        ? { kind: "limit", retryAt: data.retry_at }
        : { kind: "outdated" };
    default:
      return data.unavailable_reason === "provider_disabled"
        ? { kind: "disabled" }
        : { kind: "unavailable", reason: data.unavailable_reason };
  }
}

export type StationView = NearbyStation & { view: "current" | "stale" };

/** Stations that may still be shown, with their status now (D-007/D-008). */
export function stationsAt(stations: NearbyStation[], now: Date): StationView[] {
  const t = now.getTime();
  return stations
    .filter((s) => t <= Date.parse(s.stale_until))
    .map((s) => ({
      ...s,
      view: s.data_status === "stale" || t > Date.parse(s.current_until) ? ("stale" as const) : ("current" as const),
    }));
}

/** The radar frame to show now, if any. */
export function radarFrameAt(data: RadarResponse | null, now: Date): RadarResponse["frame"] {
  const frame = data?.frame ?? null;
  return frame && now.getTime() < Date.parse(frame.current_until) ? frame : null;
}
