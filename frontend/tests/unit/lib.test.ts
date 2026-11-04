import { describe, expect, it } from "vitest";

import type { ConditionsResponse, Observation } from "../../src/api/types";
import { conditionsFor, STALE_EXPLANATION, viewAt } from "../../src/lib/ageing";
import { isValidTimeZone, readClock } from "../../src/lib/clock";
import {
  describeWeather,
  formatAgo,
  formatCeiling,
  formatCloud,
  formatDuration,
  formatGusts,
  formatHeight,
  formatPressure,
  formatTemperature,
  formatUtcTime,
  formatVisibility,
  formatWeather,
  formatWind,
  minutesSince,
} from "../../src/lib/format";
import { clearRecent, loadRecent, MAX_RECENT, rememberAirport } from "../../src/lib/recent";
import { fixture } from "./helpers";

const obs = (fields: Partial<Observation>): Observation => ({
  ...(fixture("conditions-egll-severe").body as ConditionsResponse).observation!,
  ...fields,
});

describe("unit formatting (both systems, metric first)", () => {
  it("formats temperature", () => {
    expect(formatTemperature(10)).toBe("10 °C (50 °F)");
    expect(formatTemperature(13.9)).toBe("13.9 °C (57 °F)");
    expect(formatTemperature(-6)).toBe("-6 °C (21 °F)");
    expect(formatTemperature(null)).toBe("Not reported");
  });

  it("formats wind direction, speed, calm and variable", () => {
    expect(formatWind(obs({ wind_direction_deg: 70, wind_speed_kt: 4 }))).toBe("From 070° at 4 kt (7 km/h)");
    expect(formatWind(obs({ wind_speed_kt: 0 }))).toBe("Calm");
    expect(formatWind(obs({ wind_variable: true, wind_direction_deg: null, wind_speed_kt: 2 }))).toBe(
      "Variable at 2 kt (4 km/h)",
    );
    expect(formatWind(obs({ wind_direction_deg: null, wind_speed_kt: 9 }))).toBe(
      "9 kt (17 km/h), direction not reported",
    );
    expect(formatWind(obs({ wind_speed_kt: null }))).toBe("Not reported");
    expect(formatGusts(33)).toBe("33 kt (61 km/h)");
    expect(formatGusts(null)).toBe("None reported");
  });

  it("formats visibility, including 'or more'", () => {
    expect(formatVisibility(1304, false)).toBe("1.3 km (0.8 mi)");
    expect(formatVisibility(145, false)).toBe("145 m (0.1 mi)");
    expect(formatVisibility(16093, true)).toBe("16.1 km or more (10 mi or more)");
    expect(formatVisibility(null, false)).toBe("Not reported");
  });

  it("formats cloud, ceiling and heights", () => {
    expect(formatHeight(200)).toBe("200 ft (60 m)");
    expect(formatHeight(25000)).toBe("25,000 ft (7,620 m)");
    const clouds = obs({
      sky_condition: "clouds",
      cloud_layers: [
        { cover: "FEW", base_ft: 1500 },
        { cover: "BKN", base_ft: 3000 },
      ],
      ceiling_ft: 3000,
    });
    expect(formatCloud(clouds)).toBe("Few clouds at 1,500 ft, Broken cloud at 3,000 ft");
    expect(formatCeiling(clouds)).toBe("3,000 ft (910 m)");
    expect(formatCeiling(obs({ sky_condition: "clouds", ceiling_ft: null }))).toBe("No ceiling");
    expect(formatCloud(obs({ sky_condition: "clear", cloud_layers: [] }))).toBe("No cloud detected");
    expect(formatCloud(obs({ sky_condition: "cavok", cloud_layers: [] }))).toBe("CAVOK: no significant cloud");
    expect(formatCloud(obs({ sky_condition: "obscured", cloud_layers: [] }))).toBe(
      "Sky obscured; height not reported",
    );
    expect(formatCeiling(obs({ sky_condition: "obscured" }))).toBe("Not reported");
    expect(formatCloud(obs({ sky_condition: "unknown", cloud_layers: [] }))).toBe("Not reported");
    expect(formatCloud(obs({ sky_condition: "clouds", cloud_layers: [] }))).toBe("Not reported");
    expect(formatCloud(obs({ sky_condition: "clouds", cloud_layers: [{ cover: "XYZ", base_ft: 100 }] }))).toBe(
      "XYZ at 100 ft",
    );
  });

  it("formats pressure", () => {
    expect(formatPressure(1029)).toBe("1,029 hPa");
    expect(formatPressure(1000.4)).toBe("1,000.4 hPa");
    expect(formatPressure(null)).toBe("Not reported");
  });
});

describe("weather wording", () => {
  it.each([
    ["BR", "Mist (BR)"],
    ["+SHRA", "Heavy rain showers (+SHRA)"],
    ["-RA", "Light rain (-RA)"],
    ["TSRA", "Thunderstorm with rain (TSRA)"],
    ["TS", "Thunderstorm (TS)"],
    ["VCTS", "Thunderstorm in the vicinity (VCTS)"],
    ["VCSH", "Showers in the vicinity (VCSH)"],
    ["-FZDZ", "Light freezing drizzle (-FZDZ)"],
    ["BLSN", "Blowing snow (BLSN)"],
    ["RASN", "Rain and snow (RASN)"],
    ["XYZ", "XYZ (not recognised)"],
    ["FZ", "FZ (not recognised)"],
  ])("describes %s", (group, words) => {
    expect(describeWeather(group)).toBe(words);
  });

  it("lists groups or says none", () => {
    expect(formatWeather(["+SHRA", "BR"])).toBe("Heavy rain showers (+SHRA), Mist (BR)");
    expect(formatWeather([])).toBe("None reported");
  });
});

describe("times and ages", () => {
  const now = new Date("2026-10-30T07:55:00Z");
  it("formats UTC times", () => {
    expect(formatUtcTime("2026-10-30T07:20:00Z")).toBe("07:20 UTC");
  });
  it("counts minutes, rounding up, never negative", () => {
    expect(minutesSince("2026-10-30T07:20:00Z", now)).toBe(35);
    expect(minutesSince("2026-10-30T07:19:30Z", now)).toBe(36);
    expect(minutesSince("2026-10-30T08:00:00Z", now)).toBe(0);
  });
  it("formats durations and ages", () => {
    expect(formatDuration(35)).toBe("35 min");
    expect(formatDuration(125)).toBe("2 h 5 min");
    expect(formatDuration(240)).toBe("4 h");
    expect(formatAgo("2026-10-30T05:50:00Z", now)).toBe("2 h 5 min ago");
    expect(formatAgo("2026-10-30T07:55:00Z", now)).toBe("just now");
  });
});

describe("local clock with DST (IANA zones)", () => {
  it.each([
    // London: BST ends 25 Oct 2026 01:00 UTC
    ["Europe/London", "2026-10-25T00:59:00Z", "01:59", "BST (UTC+1)"],
    ["Europe/London", "2026-10-25T01:00:00Z", "01:00", "GMT (UTC+0)"],
    // New York: EDT ends 1 Nov 2026 06:00 UTC
    ["America/New_York", "2026-11-01T05:59:00Z", "01:59", "EDT (UTC−4)"],
    ["America/New_York", "2026-11-01T06:00:00Z", "01:00", "EST (UTC−5)"],
    // Tokyo: no DST
    ["Asia/Tokyo", "2026-07-15T12:00:00Z", "21:00", "UTC+9"],
    // India: half-hour offset
    ["Asia/Kolkata", "2026-07-15T12:00:00Z", "17:30", "UTC+5:30"],
  ])("%s at %s reads %s %s", (zone, iso, time, label) => {
    const reading = readClock(zone, new Date(iso));
    expect(reading.time).toBe(time);
    expect(reading.zone).toBe(label);
  });

  it("shows UTC with its date", () => {
    const reading = readClock("UTC", new Date("2026-11-02T08:20:00Z"));
    expect(reading).toMatchObject({ time: "08:20", date: "Mon 2 Nov" });
  });

  it("validates time zones", () => {
    expect(isValidTimeZone("Europe/London")).toBe(true);
    expect(isValidTimeZone("Mars/Base")).toBe(false);
  });
});

describe("ageing of data kept on screen (D11)", () => {
  const severe = fixture("conditions-egll-severe").body as ConditionsResponse;
  // observed 07:20, current_until 08:50, stale_until 10:20
  it("moves from current to stale to too old at the API's times", () => {
    // Inclusive like the backend: exactly at a boundary the earlier state holds.
    expect(viewAt(severe, new Date("2026-10-30T08:50:00.000Z"))).toBe("current");
    expect(viewAt(severe, new Date("2026-10-30T08:50:00.001Z"))).toBe("stale");
    expect(viewAt(severe, new Date("2026-10-30T10:20:00.000Z"))).toBe("stale");
    expect(viewAt(severe, new Date("2026-10-30T10:20:00.001Z"))).toBe("too-old");
  });

  it("keeps the API's own stale and unavailable states", () => {
    const stale = fixture("conditions-egll-stale").body as ConditionsResponse;
    expect(viewAt(stale, new Date("2026-10-30T07:55:00Z"))).toBe("stale");
    expect(viewAt(stale, new Date("2026-10-30T08:50:00.001Z"))).toBe("too-old");
    const now = new Date("2026-10-30T07:55:00Z");
    expect(viewAt(fixture("conditions-rjbb-no-report").body as ConditionsResponse, now)).toBe("no-report");
    expect(viewAt(fixture("conditions-aai-no-station").body as ConditionsResponse, now)).toBe("no-station");
    expect(viewAt(fixture("conditions-egll-too-old").body as ConditionsResponse, now)).toBe("too-old");
  });

  it("withdraws the score once stale, and only then", () => {
    expect(conditionsFor(severe, "current")).toBe(severe.conditions);
    const stale = conditionsFor(severe, "stale");
    expect(stale).toMatchObject({ score: null, level: "unknown", explanation: STALE_EXPLANATION });
    expect(stale.factors).toEqual(severe.conditions.factors);
    const unknown = fixture("conditions-egll-unknown").body as ConditionsResponse;
    expect(conditionsFor(unknown, "stale")).toBe(unknown.conditions);
  });
});

describe("recently viewed (browser only)", () => {
  const heathrow = { code: "EGLL", iata: "LHR", name: "London Heathrow Airport" };
  it("remembers, de-duplicates, orders newest first and caps the list", () => {
    rememberAirport(heathrow);
    rememberAirport({ code: "KJFK", iata: "JFK", name: "JFK" });
    rememberAirport(heathrow);
    expect(loadRecent().map((a) => a.code)).toEqual(["EGLL", "KJFK"]);
    for (let i = 0; i < 10; i++) rememberAirport({ code: `T${i}00`, iata: null, name: `Test ${i}` });
    expect(loadRecent()).toHaveLength(MAX_RECENT);
  });

  it("clears", () => {
    rememberAirport(heathrow);
    clearRecent();
    expect(loadRecent()).toEqual([]);
  });

  it("ignores corrupt or foreign data", () => {
    window.localStorage.setItem("clearflight.recentAirports", "{not json");
    expect(loadRecent()).toEqual([]);
    window.localStorage.setItem("clearflight.recentAirports", JSON.stringify([{ code: 1 }, heathrow, "x"]));
    expect(loadRecent()).toEqual([heathrow]);
    window.localStorage.setItem("clearflight.recentAirports", JSON.stringify({ a: 1 }));
    expect(loadRecent()).toEqual([]);
  });

  it("works when storage is blocked", () => {
    const original = Object.getOwnPropertyDescriptor(window, "localStorage")!;
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("blocked", "SecurityError");
      },
    });
    try {
      expect(loadRecent()).toEqual([]);
      expect(rememberAirport(heathrow)).toEqual([heathrow]);
      expect(() => clearRecent()).not.toThrow();
    } finally {
      Object.defineProperty(window, "localStorage", original);
    }
  });
});
