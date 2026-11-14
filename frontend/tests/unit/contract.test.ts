import { readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { validate, type Schema } from "../../src/api/schema";
import {
  AirportSearchResponseSchema,
  ConditionsResponseSchema,
  ErrorResponseSchema,
  ForecastResponseSchema,
  AircraftResponseSchema,
  NearbyConditionsResponseSchema,
  RadarResponseSchema,
} from "../../src/api/types";
import { fixture } from "./helpers";

// Contract (spec §10, D-008): every recorded response must match the runtime
// schema the TypeScript types are derived from: field names, value types,
// nullability and allowed values. The backend test
// tests/test_frontend_fixtures.py checks the same fixtures against the
// Pydantic models, so models, fixtures and frontend types can't drift apart.

const names = readdirSync(join(__dirname, "..", "fixtures"))
  .filter((file) => file.endsWith(".json"))
  .map((file) => file.replace(/\.json$/, ""));

function schemaFor(name: string, status: number): Schema<unknown> {
  if (name.startsWith("search-")) return AirportSearchResponseSchema;
  if (name.startsWith("forecast-")) return ForecastResponseSchema;
  if (status === 200 && name.startsWith("aircraft-")) return AircraftResponseSchema;
  if (status === 200 && name.startsWith("nearby-")) return NearbyConditionsResponseSchema;
  if (status === 200 && name.startsWith("radar-")) return RadarResponseSchema;
  return status === 200 ? ConditionsResponseSchema : ErrorResponseSchema;
}

describe("recorded API responses match the frontend schema exactly", () => {
  it("has fixtures to check", () => {
    expect(names.length).toBeGreaterThanOrEqual(15);
  });

  it.each(names)("%s", (name) => {
    const { status, body } = fixture(name);
    expect(() => validate(schemaFor(name, status), body, name)).not.toThrow();
  });
});

describe("the schema rejects contract changes", () => {
  const good = fixture("conditions-egll-severe").body as Record<string, unknown>;
  const observation = good.observation as Record<string, unknown>;

  it.each([
    ["a changed value type", { ...good, current_until: 5 }, "current_until: expected ISO timestamp"],
    ["a null where not allowed", { ...good, data_status: null }, "data_status: expected current | stale | unavailable"],
    ["an unknown enum value", { ...good, data_status: "fresh" }, "data_status: expected"],
    ["an unexpected field", { ...good, extra: true }, "extra: unexpected field"],
    ["a missing field", Object.fromEntries(Object.entries(good).filter(([key]) => key !== "stale_until")), "stale_until: missing field"],
    [
      "a nested type change",
      { ...good, observation: { ...observation, wind_speed_kt: "4" } },
      "observation.wind_speed_kt: expected number",
    ],
    [
      "a bad array item",
      { ...good, observation: { ...observation, weather_phenomena: [1] } },
      "observation.weather_phenomena[0]: expected string",
    ],
    ["current without eligibility times", { ...good, current_until: null, stale_until: null }, "lacks current_until/stale_until"],
    ["current without an observation", { ...good, observation: null }, "current response has no observation"],
    ["current with an unavailable reason", { ...good, unavailable_reason: "no_report" }, "has an unavailable_reason"],
    [
      "unavailable with an observation",
      { ...good, data_status: "unavailable", unavailable_reason: "no_report" },
      "unavailable response has an observation",
    ],
    [
      "unavailable without a reason",
      { ...(fixture("conditions-rjbb-no-report").body as object), unavailable_reason: null },
      "unavailable response has no reason",
    ],
  ])("rejects %s", (_, body, message) => {
    expect(() => validate(ConditionsResponseSchema, body)).toThrow(message);
  });
});

describe("the forecast schema rejects contract changes", () => {
  const good = fixture("forecast-egll-fog").body as Record<string, unknown>;
  const hour = (good.hours as Record<string, unknown>[])[0] as Record<string, unknown>;

  it.each([
    ["available without a summary", { ...good, forecast: null }, "available forecast has no summary"],
    ["available with a reason", { ...good, unavailable_reason: "no_forecast" }, "has an unavailable_reason"],
    ["unavailable with hours", { ...good, data_status: "unavailable", unavailable_reason: "no_forecast" }, "unavailable forecast has hours"],
    [
      "an unavailable forecast without a reason",
      { ...(fixture("forecast-rjbb-no-forecast").body as object), unavailable_reason: null },
      "unavailable forecast has no reason",
    ],
    ["an unknown hour status", { ...good, hours: [{ ...hour, status: "observed" }] }, "hours[0].status: expected"],
    ["a forecast hour without conditions", { ...good, hours: [{ ...hour, prevailing: null }] }, "forecast hour has no prevailing"],
    [
      "a not-yet-valid hour with conditions",
      { ...good, hours: [{ ...hour, status: "not_yet_valid" }] },
      "not-yet-valid hour has a forecast",
    ],
    ["an hour that ends before it starts", { ...good, hours: [{ ...hour, end: hour.start }] }, "hour ends before it starts"],
  ])("rejects %s", (_, body, message) => {
    expect(() => validate(ForecastResponseSchema, body)).toThrow(message);
  });
});

describe("the map-layer schemas reject contract changes", () => {
  it("rejects radar tiles from any other host", () => {
    const body = fixture("radar-available").body as { frame: Record<string, unknown> };
    const evil = { ...body, frame: { ...body.frame, tile_url: "https://evil.example/{z}/{x}/{y}.png" } };
    expect(() => validate(RadarResponseSchema, evil)).toThrow("unexpected radar tile host");
  });

  it("rejects a no_aircraft answer without a feed time", () => {
    const body = fixture("aircraft-rjbb-no-aircraft").body as Record<string, unknown>;
    expect(() => validate(AircraftResponseSchema, { ...body, observed_at: null })).toThrow("lacks observed_at");
  });

  it("rejects an aircraft without its expiry time", () => {
    const body = fixture("aircraft-egll-available").body as { aircraft: Record<string, unknown>[] };
    const first = { ...body.aircraft[0]! };
    delete first.expires_at;
    expect(() => validate(AircraftResponseSchema, { ...body, aircraft: [first] })).toThrow("expires_at: missing field");
  });
});
