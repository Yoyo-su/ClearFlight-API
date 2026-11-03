import { defineConfig, devices } from "@playwright/test";

// End-to-end flows on desktop and mobile against the built app, with the API
// mocked from tests/fixtures (spec §10). Run with `npm run e2e`.
export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: "npm run build && npm run preview -- --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    // Always a fresh build and server: reusing a running preview could test a
    // stale build (a likely cause of an earlier unreproducible failure).
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
