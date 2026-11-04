import { useCallback, useEffect, useState } from "react";

import { isAbort, searchAirports } from "../api/client";
import type { AirportResult } from "../api/types";

// Search as you type (D3): 2+ characters, 250 ms after the last keystroke;
// a newer query aborts the previous request.

export const MIN_QUERY = 2;
export const DEBOUNCE_MS = 250;

export type SearchState =
  | { status: "idle" }
  | { status: "loading"; query: string }
  | { status: "done"; query: string; results: AirportResult[] }
  | { status: "error"; query: string };

export function useSearch(query: string) {
  const [state, setState] = useState<SearchState>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);
  const term = query.trim();

  useEffect(() => {
    if (term.length < MIN_QUERY) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const result = await searchAirports(term, controller.signal);
        if (result.kind === "ok") setState({ status: "done", query: term, results: result.data.results });
        else setState({ status: "error", query: term });
      } catch (error) {
        if (!isAbort(error)) setState({ status: "error", query: term });
      }
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [term, attempt]);

  const retry = useCallback(() => {
    setState({ status: "idle" });
    setAttempt((n) => n + 1);
  }, []);
  // Derived: too short is idle; a result for an older query (or none yet)
  // shows as loading until this query's answer arrives.
  let shown: SearchState;
  if (term.length < MIN_QUERY) shown = { status: "idle" };
  else if (state.status !== "idle" && state.status !== "loading" && state.query === term) shown = state;
  else shown = { status: "loading", query: term };
  return { state: shown, retry };
}
