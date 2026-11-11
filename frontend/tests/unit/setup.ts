import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no IntersectionObserver. By default nothing is ever on screen, so
// the live map stays idle in page tests; tests/unit/map.test.tsx installs a
// controllable one.
class NeverIntersecting {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}
if (typeof globalThis.IntersectionObserver === "undefined") {
  globalThis.IntersectionObserver = NeverIntersecting as unknown as typeof IntersectionObserver;
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});
