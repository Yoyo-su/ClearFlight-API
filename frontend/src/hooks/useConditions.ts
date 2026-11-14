import { useCallback, useEffect, useRef, useState } from "react";

import { fetchConditions, fetchForecast, isAbort, type ApiResult } from "../api/client";
import type { ConditionsResponse, ForecastResponse } from "../api/types";

// Loads and refreshes one airport's data, its conditions or its forecast
// (spec §4, §8; CF-008 §5):
// - every request, retry and timer belongs to the airport on screen; changing
//   airport or leaving aborts them, and a late response is ignored;
// - auto-refresh every 5 minutes while the tab is visible, and when it becomes
//   visible again after that long (D4);
// - manual refresh with a 60 s cooldown (D4);
// - a failed refresh keeps the last good data;
// - a 503 is retried once, automatically, after its Retry-After.
//
// Gated use (CF-010 §3, the map layers): with an `active` option, nothing is
// requested unless the tab is visible AND active is true. That covers the
// first load, interval refreshes, resume, manual refresh and the 503 retry.
// Work that falls due while inactive is deferred, not sent, and runs on
// becoming active again if still due.

export const AUTO_REFRESH_MS = 5 * 60 * 1000;
export const COOLDOWN_MS = 60 * 1000;
export const SLOW_MS = 10 * 1000;
const DEFAULT_RETRY_S = 5;

export type Failure = Exclude<ApiResult<unknown>, { kind: "ok" }>;
type Fetcher<T> = (code: string, signal: AbortSignal) => Promise<ApiResult<T>>;

export interface PolledState<T> {
  owner: string; // the airport code this state belongs to
  data: T | null;
  failure: Failure | null; // only when there's no data to show
  loading: boolean;
  slow: boolean;
  refreshFailed: boolean; // the last refresh failed; data is the last good one
  cooldownUntil: number; // epoch ms; manual refresh disabled until then
  retryAt: number | null; // epoch ms of the automatic retry after a 503
}

export type ConditionsState = PolledState<ConditionsResponse>;
export type ForecastState = PolledState<ForecastResponse>;

const EMPTY: PolledState<never> = {
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

export interface PollOptions {
  /** Gate every request on this (and tab visibility); omit for always-on. */
  active?: boolean;
  refreshMs?: number;
  cooldownMs?: number;
}

const PRIORITY: Record<Mode, number> = { refresh: 0, retry: 1, initial: 2 };

export function useConditions(code: string) {
  return useAirportData(code, fetchConditions);
}

export function useForecast(code: string) {
  return useAirportData(code, fetchForecast);
}

/** `fetcher` must be stable (a module-level function). */
export function useAirportData<T>(code: string, fetcher: Fetcher<T>, options: PollOptions = {}) {
  const gated = options.active !== undefined;
  const refreshMs = options.refreshMs ?? AUTO_REFRESH_MS;
  const cooldownMs = options.cooldownMs ?? COOLDOWN_MS;
  const [state, setState] = useState<PolledState<T>>({ ...EMPTY, owner: code });
  const runRef = useRef<(mode: Mode) => void>(() => {});
  const resumeRef = useRef<() => void>(() => {});
  const activeRef = useRef(options.active ?? true);
  const lastFetchRef = useRef(0);
  const cooldownRef = useRef(0);

  // The map section reports when it is on screen; resume deferred work then.
  useEffect(() => {
    activeRef.current = options.active ?? true;
    if (activeRef.current) resumeRef.current();
  }, [options.active]);

  useEffect(() => {
    let disposed = false;
    let requestId = 0;
    let controller: AbortController | null = null;
    let retried = false; // the 503 auto-retry for the current request chain was used
    let retryTimer: number | null = null;
    let pending: Mode | null = null; // work that fell due while inactive
    const timers = new Set<number>();
    const canRun = () => !gated || (activeRef.current && document.visibilityState === "visible");
    /** The one gate every request goes through. */
    const request = (mode: Mode) => {
      if (!canRun()) {
        if (pending === null || PRIORITY[mode] > PRIORITY[pending]) pending = mode;
        return;
      }
      pending = null;
      void run(mode);
    };
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
      let result: ApiResult<T>;
      try {
        result = await fetcher(code, controller.signal);
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
          if (!disposed && id === requestId) request("retry"); // still the latest request
        }, retryAt - Date.now());
      }
    }

    runRef.current = request;
    resumeRef.current = () => {
      if (pending !== null) request(pending);
      else if (Date.now() - lastFetchRef.current >= refreshMs) request("refresh");
    };
    lastFetchRef.current = 0;
    request("initial");

    const interval = window.setInterval(() => {
      // Interval refreshes aren't deferred: resuming refreshes if data is old.
      if (document.visibilityState === "visible" && canRun()) void run("refresh");
    }, refreshMs);
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (pending !== null) request(pending);
      else if (Date.now() - lastFetchRef.current >= refreshMs) request("refresh");
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
  }, [code, fetcher, gated, refreshMs]);

  /** Manual refresh: at most once a minute (D4). */
  const refresh = useCallback(() => {
    const now = Date.now();
    if (now < cooldownRef.current) return;
    cooldownRef.current = now + cooldownMs;
    setState((s) => ({ ...s, cooldownUntil: cooldownRef.current }));
    runRef.current("refresh");
  }, [cooldownMs]);

  /** Retry after a failure with nothing on screen (no cooldown). */
  const retry = useCallback(() => runRef.current("initial"), []);

  // Until the effect has reset for a new airport, never expose the previous
  // airport's data (it could otherwise be shown or used to rewrite the URL).
  const current = state.owner === code ? state : { ...EMPTY, owner: code };
  return { state: current, refresh, retry };
}
