import { readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { validate, type Schema } from "../../src/api/schema";
import {
  AirportSearchResponseSchema,
  ConditionsResponseSchema,
  ErrorResponseSchema,
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
