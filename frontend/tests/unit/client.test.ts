import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchConditions, searchAirports } from "../../src/api/client";
import { fixture, fixtureFetch, response } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API client", () => {
  it("returns data for a 200 and encodes the code", async () => {
    const fetch = fixtureFetch(() => fixture("conditions-egll-severe"));
    vi.stubGlobal("fetch", fetch);
    const result = await fetchConditions("EG/LL", new AbortController().signal);
    expect(result.kind).toBe("ok");
    expect(fetch.mock.calls[0]![0]).toBe("/v1/airports/EG%2FLL/conditions");
  });

  it("returns status, reason and Retry-After for an error", async () => {
    vi.stubGlobal("fetch", fixtureFetch(() => fixture("error-503-busy")));
    const result = await fetchConditions("EGLL", new AbortController().signal);
    expect(result).toEqual({
      kind: "error",
      status: 503,
      reason: "rate_limited",
      detail: "Weather requests are temporarily limited; try again shortly",
      retryAfter: 13,
    });
  });

  it("copes with an error that isn't JSON or has no Retry-After", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })));
    const result = await fetchConditions("EGLL", new AbortController().signal);
    expect(result).toEqual({ kind: "error", status: 502, reason: "unknown", detail: "", retryAfter: null });
  });

  it("reports a network failure", async () => {
    vi.stubGlobal("fetch", fixtureFetch(() => "network"));
    expect(await fetchConditions("EGLL", new AbortController().signal)).toEqual({ kind: "network" });
  });

  it("rethrows an abort so callers can ignore it", async () => {
    vi.stubGlobal("fetch", fixtureFetch(() => fixture("conditions-egll-severe")));
    const controller = new AbortController();
    controller.abort();
    await expect(fetchConditions("EGLL", controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  });

  it("rethrows our own abort while reading the body", async () => {
    const controller = new AbortController();
    const reply = response(fixture("conditions-egll-severe"));
    vi.spyOn(reply, "json").mockImplementation(async () => {
      controller.abort();
      throw new DOMException("aborted", "AbortError");
    });
    vi.stubGlobal("fetch", vi.fn(async () => reply));
    await expect(fetchConditions("EGLL", controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  });

  it.each([
    ["invalid JSON", "{not json"],
    ["an empty object", "{}"],
    ["a field of the wrong type", JSON.stringify({ ...(fixture("conditions-egll-severe").body as object), current_until: 5 })],
    ["an unexpected field", JSON.stringify({ ...(fixture("conditions-egll-severe").body as object), extra: 1 })],
  ])("treats a 200 with %s as a failure", async (_, body) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    expect(await fetchConditions("EGLL", new AbortController().signal)).toEqual({
      kind: "error",
      status: 200,
      reason: "invalid_response",
      detail: "",
      retryAfter: null,
    });
  });

  it("treats a request timeout as a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new DOMException("timed out", "TimeoutError");
      }),
    );
    expect(await fetchConditions("EGLL", new AbortController().signal)).toEqual({ kind: "network" });
  });

  it("searches with a limit and an encoded query", async () => {
    const fetch = fixtureFetch(() => fixture("search-lon"));
    vi.stubGlobal("fetch", fetch);
    const result = await searchAirports("São Paulo", new AbortController().signal);
    expect(result.kind).toBe("ok");
    expect(fetch.mock.calls[0]![0]).toBe("/v1/airports/search?q=S%C3%A3o%20Paulo&limit=10");
  });
});
