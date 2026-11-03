import { readFileSync } from "node:fs";
import { join } from "node:path";
import { vi } from "vitest";

export interface Fixture {
  status: number;
  headers: Record<string, string>;
  body: unknown;
}

const FIXTURES = join(__dirname, "..", "fixtures");

/** A recorded API response from tests/fixtures (see scripts/record_frontend_fixtures.py). */
export function fixture(name: string): Fixture {
  return JSON.parse(readFileSync(join(FIXTURES, `${name}.json`), "utf8")) as Fixture;
}

export function response(f: Fixture): Response {
  return new Response(JSON.stringify(f.body), {
    status: f.status,
    headers: { "Content-Type": "application/json", ...f.headers },
  });
}

/** A fetch whose replies the test controls, one request at a time. */
export function controlledFetch() {
  const pending: { url: string; resolve: (r: Response) => void; reject: (e: unknown) => void; signal?: AbortSignal | null }[] = [];
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    return new Promise<Response>((resolve, reject) => {
      const entry = { url: String(input), resolve, reject, signal: init?.signal };
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      pending.push(entry);
    });
  });
  return { fn, pending };
}

/** A fetch that answers each URL with the fixture `route(url)` returns. */
export function fixtureFetch(route: (url: string) => Fixture | "network") {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");
    const result = route(String(input));
    if (result === "network") throw new TypeError("Failed to fetch");
    return response(result);
  });
}
