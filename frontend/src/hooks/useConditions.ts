import { useCallback, useEffect, useRef, useState } from "react";

import { fetchConditions, isAbort, type ApiResult } from "../api/client";
import type { ConditionsResponse } from "../api/types";

// Loads and refreshes one airport's conditions (spec §4, §8):
// - every request, retry and timer belongs to the airport on screen; changing
//   airport or leaving aborts them, and a late response is ignored;
// - auto-refresh every 5 minutes while the tab is visible, and when it becomes
//   visible again after that long (D4);
// - manual refresh with a 60 s cooldown (D4);
// - a failed refresh keeps the last good data;
// - a 503 is retried once, automatically, after its Retry-After.

export const AUTO_REFRESH_MS = 5 * 60 * 1000;
export const COOLDOWN_MS = 60 * 1000;
export const SLOW_MS = 10 * 1000;
const DEFAULT_RETRY_S = 5;

export type Failure = Exclude<ApiResult<ConditionsResponse>, { kind: "ok" }>;

export interface ConditionsState {
  owner: string; // the airport code this state belongs to
  data: ConditionsResponse | null;
  failure: Failure | null; // only when there's no data to show
  loading: boolean;
  slow: boolean;
  refreshFailed: boolean; // the last refresh failed; data is the last good one
  cooldownUntil: number; // epoch ms; manual refresh disabled until then
  retryAt: number | null; // epoch ms of the automatic retry after a 503
}

const EMPTY: ConditionsState = {
  owner: "",
  data: null,
  failure: null,
  loading: true,
  slow: false,
  refreshFailed: false,
  cooldownUntil: 0,
  retryAt: null,
};

type Mode = "initial" | "refresh" | "retry";

export function useConditions(code: string) {
  const [state, setState] = useState<ConditionsState>({ ...EMPTY, owner: code });
  const runRef = useRef<(mode: Mode) => void>(() => {});
  const lastFetchRef = useRef(0);
  const cooldownRef = useRef(0);

  useEffect(() => {
    let disposed = false;
    let requestId = 0;
    let controller: AbortController | null = null;
    let retried = false; // the 503 auto-retry for the current request chain was used
    let retryTimer: number | null = null;
    const timers = new Set<number>();
    const later = (fn: () => void, ms: number) => {
      const timer = window.setTimeout(() => {
        timers.delete(timer);
        fn();
      }, ms);
      timers.add(timer);
      return timer;
    };

    async function run(mode: Mode) {
      controller?.abort();
      controller = new AbortController();
      const id = ++requestId;
      // A newer request supersedes any pending 503 retry.
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
        timers.delete(retryTimer);
        retryTimer = null;
      }
      if (mode !== "retry") retried = false;
      if (mode === "initial") {
        cooldownRef.current = 0;
        setState({ ...EMPTY, owner: code });
        later(() => {
          if (!disposed && id === requestId) setState((s) => (s.loading ? { ...s, slow: true } : s));
        }, SLOW_MS);
      }
      let result: ApiResult<ConditionsResponse>;
      try {
        result = await fetchConditions(code, controller.signal);
      } catch (error) {
        if (isAbort(error)) return;
        result = { kind: "network" };
      }
      if (disposed || id !== requestId) return; // a newer request or another airport owns the page
      lastFetchRef.current = Date.now();
      if (result.kind === "ok") {
        const data = result.data;
        setState((s) => ({ ...s, data, failure: null, loading: false, slow: false, refreshFailed: false, retryAt: null }));
        return;
      }
      const failure = result;
      const busy = failure.kind === "error" && failure.status === 503;
      const retryAt = busy && !retried ? Date.now() + (failure.retryAfter ?? DEFAULT_RETRY_S) * 1000 : null;
      setState((s) =>
        s.data
          ? { ...s, loading: false, slow: false, refreshFailed: true, retryAt }
          : { ...s, failure, loading: false, slow: false, retryAt },
      );
      if (retryAt !== null) {
        retried = true;
        retryTimer = later(() => {
          retryTimer = null;
          if (!disposed && id === requestId) void run("retry"); // still the latest request
        }, retryAt - Date.now());
      }
    }

    runRef.current = (mode) => void run(mode);
    void run("initial");

    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void run("refresh");
    }, AUTO_REFRESH_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible" && Date.now() - lastFetchRef.current >= AUTO_REFRESH_MS) {
        void run("refresh");
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      disposed = true;
      controller?.abort();
      timers.forEach((timer) => window.clearTimeout(timer));
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
      runRef.current = () => {};
    };
  }, [code]);

  /** Manual refresh: at most once a minute (D4). */
  const refresh = useCallback(() => {
    const now = Date.now();
    if (now < cooldownRef.current) return;
    cooldownRef.current = now + COOLDOWN_MS;
    setState((s) => ({ ...s, cooldownUntil: cooldownRef.current }));
    runRef.current("refresh");
  }, []);

  /** Retry after a failure with nothing on screen (no cooldown). */
  const retry = useCallback(() => runRef.current("initial"), []);

  // Until the effect has reset for a new airport, never expose the previous
  // airport's data (it could otherwise be shown or used to rewrite the URL).
  const current = state.owner === code ? state : { ...EMPTY, owner: code };
  return { state: current, refresh, retry };
}
