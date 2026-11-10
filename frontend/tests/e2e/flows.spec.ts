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

async function mockApi(
  page: Page,
  conditions: Record<string, string>,
  searches: Record<string, string> = {},
  forecasts: Record<string, string> = {},
) {
  await page.route("**/v1/airports/**", async (route) => {
    const url = new URL(route.request().url());
    const code = decodeURIComponent(url.pathname.split("/")[3] ?? "");
    let name: string | undefined;
    if (url.pathname === "/v1/airports/search") name = searches[url.searchParams.get("q") ?? ""];
    else if (url.pathname.endsWith("/forecast")) name = forecasts[code] ?? "forecast-rjbb-no-forecast";
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
  const refresh = page.getByRole("button", { name: "Refresh" });
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
