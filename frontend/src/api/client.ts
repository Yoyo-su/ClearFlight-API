import { validate, type Schema } from "./schema";
import {
  AirportSearchResponseSchema,
  ConditionsResponseSchema,
  type AirportSearchResponse,
  type ConditionsResponse,
  type ErrorResponse,
} from "./types";

// Empty means same origin (the Vite dev proxy, or a same-origin deployment).
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

// Longer than the API's worst case (two provider attempts plus backoff), so a
// hung connection ends as a network failure instead of loading forever.
export const REQUEST_TIMEOUT_MS = 25_000;

export type ApiResult<T> =
  | { kind: "ok"; data: T }
  | { kind: "error"; status: number; reason: string; detail: string; retryAfter: number | null }
  | { kind: "network" };

/** Our own cancellation (navigation, a newer request); callers ignore it. */
export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function getJson<T>(path: string, schema: Schema<T>, signal: AbortSignal): Promise<ApiResult<T>> {
  const combined = AbortSignal.any([signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { signal: combined, headers: { Accept: "application/json" } });
  } catch {
    if (signal.aborted) throw new DOMException("aborted", "AbortError");
    return { kind: "network" }; // includes the timeout
  }
  let body: unknown = null;
  let parsed = true;
  try {
    body = await response.json();
  } catch {
    if (signal.aborted) throw new DOMException("aborted", "AbortError");
    parsed = false;
  }
  if (response.ok) {
    if (parsed) {
      try {
        return { kind: "ok", data: validate(schema, body) };
      } catch {
        // fall through: a 200 that doesn't match the contract is a failure
      }
    }
    return { kind: "error", status: response.status, reason: "invalid_response", detail: "", retryAfter: null };
  }
  const error = (body ?? {}) as Partial<ErrorResponse>;
  const retryAfter = Number(response.headers.get("Retry-After"));
  return {
    kind: "error",
    status: response.status,
    reason: typeof error.reason === "string" ? error.reason : "unknown",
    detail: typeof error.detail === "string" ? error.detail : "",
    retryAfter: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
  };
}

export function fetchConditions(code: string, signal: AbortSignal): Promise<ApiResult<ConditionsResponse>> {
  return getJson(`/v1/airports/${encodeURIComponent(code)}/conditions`, ConditionsResponseSchema, signal);
}

export function searchAirports(query: string, signal: AbortSignal): Promise<ApiResult<AirportSearchResponse>> {
  return getJson(`/v1/airports/search?q=${encodeURIComponent(query)}&limit=10`, AirportSearchResponseSchema, signal);
}
