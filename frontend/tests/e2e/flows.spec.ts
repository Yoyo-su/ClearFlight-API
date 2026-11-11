import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// The API is mocked from tests/fixtures (recorded from the real backend), and
// the clock is fixed at the fixtures' fetch time.
const NOW = new Date("2026-10-30T07:55:00Z");

function load(name: string) {
  return JSON.parse(readFileSync(new URL(`../fixtures/${name}.json`, import.meta.url), "utf8")) as {
    status: number;
    headers: Record<string, string>;
    body: unknown;
  };
}

// Map layers and tiles (CF-010): never reach the real providers in tests.
const MAP_DEFAULTS = { aircraft: "aircraft-egll-available", nearby: "nearby-egll-available", radar: "radar-disabled" };
const OFFLINE_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#eef2f6" } }],
};

async function mockApi(
  page: Page,
  conditions: Record<string, string>,
  searches: Record<string, string> = {},
  forecasts: Record<string, string> = {},
  map: { aircraft: string; nearby: string; radar: string } = MAP_DEFAULTS,
) {
  await page.route("https://tiles.openfreemap.org/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(OFFLINE_STYLE) }),
  );
  await page.route("https://tilecache.rainviewer.com/**", (route) => route.fulfill({ status: 204, body: "" }));
  await page.route("**/v1/map/radar", async (route) => {
    const f = load(map.radar);
    await route.fulfill({ status: f.status, contentType: "application/json", body: JSON.stringify(f.body) });
  });
  await page.route("**/v1/airports/**", async (route) => {
    const url = new URL(route.request().url());
    const code = decodeURIComponent(url.pathname.split("/")[3] ?? "");
    let name: string | undefined;
    if (url.pathname === "/v1/airports/search") name = searches[url.searchParams.get("q") ?? ""];
    else if (url.pathname.endsWith("/forecast")) name = forecasts[code] ?? "forecast-rjbb-no-forecast";
    else if (url.pathname.endsWith("/aircraft")) name = map.aircraft;
    else if (url.pathname.endsWith("/nearby-conditions")) name = map.nearby;
    else name = conditions[code];
    if (!name) return route.fulfill({ status: 500, body: "unexpected request" });
    const f = load(name);
    await route.fulfill({ status: f.status, headers: f.headers, contentType: "application/json", body: JSON.stringify(f.body) });
  });
}

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(NOW);
});

test("search, open an airport and read its conditions", async ({ page }) => {
  await mockApi(page, { EGLL: "conditions-egll-severe" }, { lon: "search-lon" });
  await page.goto("/");
  await expectAccessible(page);
  await page.getByLabel("Airport name, city or code").fill("lon");
  await expect(page.getByText(/airports found/)).toBeVisible();
  await expectAccessible(page);
  await page.getByRole("link", { name: /London Heathrow Airport/ }).click();
  await expect(page).toHaveURL(/\/airport\/EGLL$/);
  await expect(page.getByRole("heading", { level: 1, name: "London Heathrow Airport" })).toBeVisible();
  await expect(page.getByText("Severe", { exact: true })).toBeVisible();
  await expect(page.getByText("Observed 35 min ago · 07:20 UTC")).toBeVisible();
  // The zone label: a name when the browser has one ("GMT (UTC+0)"), else
  // the offset. Playwright's headless Chromium ships without zone names.
  await expect(page.getByText(/· ((GMT|Greenwich Mean Time) \(UTC\+0\)|UTC\+0)$/)).toBeVisible();
  await expect(page.getByText(/does not predict delays, cancellations or flight safety/).first()).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
});

test("a shared link with an IATA code opens the canonical page", async ({ page }) => {
  await mockApi(page, { LHR: "conditions-egll-severe" });
  await page.goto("/airport/lhr");
  await expect(page.getByRole("heading", { level: 1, name: "London Heathrow Airport" })).toBeVisible();
  await expect(page).toHaveURL(/\/airport\/EGLL$/);
  await expect(page).toHaveTitle("London Heathrow Airport (EGLL) – ClearFlight");
});

test("the whole flow works with the keyboard alone", async ({ page }) => {
  await mockApi(page, { KJFK: "conditions-kjfk-low" }, { jfk: "search-jfk" });
  await page.goto("/");
  await page.keyboard.press("Tab"); // wordmark
  await page.keyboard.press("Tab"); // search field
  await expect(page.getByLabel("Airport name, city or code")).toBeFocused();
  await page.keyboard.type("jfk");
  await expect(page.getByText(/airports? found/)).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/airport\/KJFK$/);
  await expect(page.getByText("Low", { exact: true })).toBeVisible();
});

const STATES: [string, string, RegExp][] = [
  ["conditions-kjfk-low", "KJFK", /Observed conditions index 2\/10 \(low\)/],
  ["conditions-rjbb-moderate", "RJBB", /Observed conditions index 5\/10 \(moderate\)/],
  ["conditions-panc-high", "PANC", /Observed conditions index 6\/10 \(high\)/],
  ["conditions-egkk-fog", "EGKK", /Observed conditions index 10\/10 \(severe\)/],
  ["conditions-egll-unknown", "EGLL", /No score: the visibility wasn't reported/],
  ["conditions-egll-stale", "EGLL", /so it isn’t scored/],
  ["conditions-egll-too-old", "EGLL", /is too old to show/],
  ["conditions-rjbb-no-report", "RJBB", /hasn’t published a report recently/],
  ["conditions-aai-no-station", "AAI", /doesn’t have a weather station/],
  ["error-400-invalid-code", "XX", /isn’t an airport code/],
  ["error-404-not-found", "ZZZ", /couldn’t find an airport/],
  ["error-502-provider", "EGLL", /weather service didn’t respond/],
  ["error-503-busy", "EGLL", /Trying again automatically in \d+ s/],
  ["error-504-timeout", "EGLL", /weather service didn’t respond/],
];

for (const [name, code, text] of STATES) {
  test(`state: ${name}`, async ({ page }) => {
    await mockApi(page, { [code]: name });
    await page.goto(`/airport/${code}`);
    await expect(page.getByText(text).first()).toBeVisible();
    await expectAccessible(page);
    await expectNoHorizontalScroll(page);
  });
}

test("manual refresh has a cooldown", async ({ page }) => {
  await mockApi(page, { EGLL: "conditions-egll-severe" });
  await page.goto("/airport/EGLL");
  const refresh = page.getByRole("button", { name: "Refresh", exact: true });
  await refresh.click();
  await expect(page.getByText("Checked just now")).toBeVisible();
  await expect(refresh).toBeDisabled();
});

test("recently viewed airports appear on the home page", async ({ page }) => {
  await mockApi(page, { EGLL: "conditions-egll-severe" });
  await page.goto("/airport/EGLL");
  await expect(page.getByRole("heading", { level: 1, name: "London Heathrow Airport" })).toBeVisible();
  await page.getByRole("link", { name: "ClearFlight" }).click();
  await expect(page.getByRole("heading", { name: "Recently viewed" })).toBeVisible();
  await expect(page.getByRole("link", { name: "London Heathrow Airport · LHR" })).toBeVisible();
  await expectAccessible(page);
});

test("unknown paths show a not-found page", async ({ page }) => {
  await page.goto("/nowhere");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expectAccessible(page);
});

test("the forecast outlook is labelled, distinct from observed, and accessible (CF-008)", async ({ page }) => {
  await mockApi(page, { EGLL: "conditions-egll-severe" }, {}, { EGLL: "forecast-lfpg-possible" });
  await page.goto("/airport/EGLL");
  const forecast = page.getByRole("region", { name: "Forecast (next 12 hours)" });
  await expect(forecast.getByRole("listitem")).toHaveCount(12);
  await expect(forecast.getByText("Forecast conditions index · not observed weather")).toBeVisible();
  const first = forecast.getByRole("button").first();
  await expect(first).toContainText("Up to 10 / 10");
  // Outlined (dashed) forecast cells; the observed index keeps its filled chip.
  const border = await forecast.locator(".forecast-hour").first().evaluate((el) => getComputedStyle(el).borderStyle);
  expect(border).toBe("dashed");
  await expect(forecast.locator("[class*='level-chip']")).toHaveCount(0);
  await first.click();
  await expect(page.getByRole("region", { name: /Forecast details 07:00–08:00/ })).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
});

function countRequests(page: Page, part: string) {
  const seen = { count: 0 };
  page.on("request", (request) => {
    if (request.url().includes(part)) seen.count += 1;
  });
  return seen;
}

test("the live map loads on scroll, lists the same data and is accessible (CF-010)", async ({ page }) => {
  // A real WebGL map rendered in software plus axe: slower than other flows.
  test.slow();
  await mockApi(page, { EGLL: "conditions-egll-severe" });
  const aircraftRequests = countRequests(page, "/aircraft");
  await page.goto("/airport/EGLL");
  await expect(page.getByRole("heading", { level: 1, name: "London Heathrow Airport" })).toBeVisible();
  const map = page.getByRole("region", { name: "Live map" });
  await page.waitForTimeout(500);
  const beforeScroll = aircraftRequests.count;
  await map.scrollIntoViewIfNeeded();
  await expect(map.getByRole("status").first()).toContainText("aircraft within 25 nm");
  expect(aircraftRequests.count).toBeGreaterThan(beforeScroll);
  // The real map must render (headless Chromium has WebGL2); a silent fallback
  // once hid a broken worker, so the fallback has its own test below.
  await expect(map.locator(".map-canvas canvas.maplibregl-canvas")).toBeVisible();
  await expect(map.locator(".map-label-airport")).toHaveText("EGLL · 8 Severe (observed)");
  await expect(map.locator(".map-failed")).toHaveCount(0);
  const aircraftTable = page.getByRole("table", { name: /Aircraft within 25 nm/ });
  await expect(aircraftTable.getByRole("row")).not.toHaveCount(1);
  await expect(page.getByRole("table", { name: /Observed weather at nearby airports/ }).getByText("EGWU")).toBeVisible();
  await expect(map.getByText(/Map tiles from OpenFreeMap/)).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
});

test("the live map makes no requests while the tab is hidden (CF-010)", async ({ page }) => {
  // A real WebGL map rendered in software plus axe: slower than other flows.
  test.slow();
  await mockApi(page, { EGLL: "conditions-egll-severe" });
  const aircraftRequests = countRequests(page, "/aircraft");
  await page.goto("/airport/EGLL");
  await page.getByRole("region", { name: "Live map" }).scrollIntoViewIfNeeded();
  await expect.poll(() => aircraftRequests.count).toBeGreaterThan(0);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const hiddenAt = aircraftRequests.count;
  await page.clock.runFor(95_000); // three refresh periods
  expect(aircraftRequests.count).toBe(hiddenAt);
});

test("the radar toggle appears only when enabled, and is off by default (CF-010)", async ({ page }) => {
  // A real WebGL map rendered in software plus axe: slower than other flows.
  test.slow();
  await mockApi(page, { EGLL: "conditions-egll-severe" }, {}, {}, { ...MAP_DEFAULTS, radar: "radar-available" });
  const radarTiles = countRequests(page, "tilecache.rainviewer.com");
  await page.goto("/airport/EGLL");
  const map = page.getByRole("region", { name: "Live map" });
  await map.scrollIntoViewIfNeeded();
  const toggle = map.getByRole("checkbox", { name: /Radar \(observed\)/ });
  await expect(toggle).not.toBeChecked();
  await page.waitForTimeout(500);
  expect(radarTiles.count).toBe(0); // nothing from RainViewer until turned on
  await toggle.check();
  await expect(map.getByText(/coarse at this zoom/)).toBeVisible();
  await expectAccessible(page);
});

test("when the map can't load, the list still carries the data (CF-010)", async ({ page }) => {
  // A real WebGL map rendered in software plus axe: slower than other flows.
  test.slow();
  await mockApi(page, { EGLL: "conditions-egll-severe" });
  await page.route("https://tiles.openfreemap.org/**", (route) => route.fulfill({ status: 503, body: "" }));
  await page.goto("/airport/EGLL");
  const map = page.getByRole("region", { name: "Live map" });
  await map.scrollIntoViewIfNeeded();
  await expect(map.getByText("The map couldn't load. The list below has the same information.")).toBeVisible();
  await expect(page.getByRole("table", { name: /Aircraft within 25 nm/ }).getByRole("row")).not.toHaveCount(1);
  await expectAccessible(page);
});
