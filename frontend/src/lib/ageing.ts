import type { Conditions, ConditionsResponse } from "../api/types";

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
