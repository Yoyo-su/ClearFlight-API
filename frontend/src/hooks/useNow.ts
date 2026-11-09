import { useEffect, useState } from "react";

/**
 * The current time. It updates every `intervalMs`, when the tab becomes
 * visible, just after each future deadline in `deadlines` (epoch ms), so
 * boundaries such as current_until take effect on time rather than at the
 * next tick, and whenever `refreshKey` changes (e.g. new data arrived).
 */
export function useNow(intervalMs: number, deadlines: readonly (number | null)[] = [], refreshKey?: unknown): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const tick = () => setNow(new Date());
    const timer = window.setInterval(tick, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") tick();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs]);

  useEffect(() => {
    const timer = window.setTimeout(() => setNow(new Date()), 0);
    return () => window.clearTimeout(timer);
  }, [refreshKey]);

  // A timer for every future deadline, not just the soonest, so a later one
  // never depends on a re-render happening in between.
  const key = [...new Set(deadlines.filter((d): d is number => d !== null && d >= now.getTime()))]
    .sort((a, b) => a - b)
    .join(",");
  useEffect(() => {
    if (!key) return;
    const timers = key.split(",").map((deadline) =>
      window.setTimeout(() => setNow(new Date()), Math.max(0, Number(deadline) - Date.now()) + 1),
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [key]);

  return now;
}
