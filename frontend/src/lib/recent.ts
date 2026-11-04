// "Recently viewed" airports (D5): kept only in this browser, never sent to the
// server. Storage can be missing or blocked (private windows), so every access
// is guarded and the page works without it.

export interface RecentAirport {
  code: string;
  iata: string | null;
  name: string;
}

const KEY = "clearflight.recentAirports";
export const MAX_RECENT = 5;

function isRecent(value: unknown): value is RecentAirport {
  const item = value as RecentAirport;
  return (
    typeof item === "object" &&
    item !== null &&
    typeof item.code === "string" &&
    typeof item.name === "string" &&
    (item.iata === null || typeof item.iata === "string")
  );
}

export function loadRecent(): RecentAirport[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isRecent).slice(0, MAX_RECENT) : [];
  } catch {
    return [];
  }
}

export function rememberAirport(airport: RecentAirport): RecentAirport[] {
  const next = [airport, ...loadRecent().filter((a) => a.code !== airport.code)].slice(0, MAX_RECENT);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Storage blocked or full: the list just isn't remembered.
  }
  return next;
}

export function clearRecent(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Nothing stored, or storage blocked.
  }
}
