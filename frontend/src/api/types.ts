import { arr, bool, datetime, literal, nullable, num, obj, oneOf, refine, str, type Infer } from "./schema";

// The v1 API (app/api/models.py; D-007, D-008), as runtime schemas with the
// TypeScript types derived from them. Recorded responses in tests/fixtures
// are validated against these schemas (tests/unit/contract.test.ts), and the
// backend test tests/test_frontend_fixtures.py checks the same fixtures
// against the Pydantic models.

const airportFields = {
  code: str,
  icao: nullable(str),
  iata: nullable(str),
  name: str,
  city: nullable(str),
  country: nullable(str),
  country_code: str,
  timezone: nullable(str),
};

export const AirportSchema = obj(airportFields);
export const AirportResultSchema = obj({ ...airportFields, type: str, latitude: num, longitude: num });
export const AirportSearchResponseSchema = obj({ query: str, count: num, results: arr(AirportResultSchema) });

export const SkyConditionSchema = literal("clear", "cavok", "clouds", "obscured", "unknown");
export const CloudLayerSchema = obj({ cover: str, base_ft: num });

export const ObservationSchema = obj({
  source: str,
  station: str,
  report_type: nullable(str),
  observed_at: datetime,
  fetched_at: datetime,
  age_minutes: num,
  raw_text: nullable(str),
  temperature_c: nullable(num),
  dewpoint_c: nullable(num),
  wind_direction_deg: nullable(num),
  wind_variable: bool,
  wind_speed_kt: nullable(num),
  wind_gust_kt: nullable(num),
  visibility_m: nullable(num),
  visibility_at_least: bool,
  sky_condition: SkyConditionSchema,
  ceiling_ft: nullable(num),
  cloud_layers: arr(CloudLayerSchema),
  pressure_hpa: nullable(num),
  weather_phenomena: arr(str),
});

export const LevelSchema = literal("low", "moderate", "high", "severe", "unknown");
export const FactorSchema = obj({
  name: literal("wind", "visibility", "ceiling", "weather"),
  value: nullable(oneOf(num, arr(str))),
  unit: nullable(str),
  score: nullable(num),
  detail: str,
});
export const ConditionsSchema = obj({
  version: str,
  score: nullable(num),
  level: LevelSchema,
  factors: arr(FactorSchema),
  explanation: str,
  disclaimer: str,
});

const conditionsResponseFields = obj({
  airport: AirportSchema,
  observation: nullable(ObservationSchema),
  conditions: ConditionsSchema,
  data_status: literal("current", "stale", "unavailable"),
  unavailable_reason: nullable(literal("no_metar_station", "no_report", "observation_too_old")),
  last_observed_at: nullable(datetime),
  current_until: nullable(datetime),
  stale_until: nullable(datetime),
});

// Cross-field rules the ageing rule depends on (D11): a current or stale
// response carries its observation and both eligibility times; an
// unavailable one carries no observation.
export const ConditionsResponseSchema = refine(conditionsResponseFields, (r) => {
  if (r.data_status === "unavailable") {
    if (r.observation !== null) return "unavailable response has an observation";
    if (r.unavailable_reason === null) return "unavailable response has no reason";
    return null;
  }
  if (r.observation === null) return `${r.data_status} response has no observation`;
  if (r.current_until === null || r.stale_until === null) return `${r.data_status} response lacks current_until/stale_until`;
  if (r.unavailable_reason !== null) return `${r.data_status} response has an unavailable_reason`;
  return null;
});

export const ErrorResponseSchema = obj({ detail: str, reason: str });

// CF-008 forecast outlook (docs/cf-008-design.md §4).
export const ForecastSummarySchema = obj({
  source: str,
  station: str,
  issued_at: datetime,
  valid_from: datetime,
  valid_to: datetime,
  raw_text: str,
});
const ForecastPossibleSchema = obj({
  label: str,
  probability: nullable(num),
  temporary: bool,
  conditions: ConditionsSchema,
});
export const ForecastHourSchema = refine(
  obj({
    start: datetime,
    end: datetime,
    status: literal("forecast", "not_yet_valid", "unknown"),
    prevailing: nullable(obj({ conditions: ConditionsSchema, changing: bool })),
    possible: arr(ForecastPossibleSchema),
  }),
  (h) => {
    if (Date.parse(h.end) <= Date.parse(h.start)) return "hour ends before it starts";
    if (h.status === "not_yet_valid") return h.prevailing === null ? null : "not-yet-valid hour has a forecast";
    return h.prevailing === null ? `${h.status} hour has no prevailing conditions` : null;
  },
);
const forecastResponseFields = obj({
  airport: AirportSchema,
  forecast: nullable(ForecastSummarySchema),
  hours: arr(ForecastHourSchema),
  data_status: literal("available", "unavailable"),
  unavailable_reason: nullable(literal("no_metar_station", "no_forecast", "forecast_expired")),
  disclaimer: str,
});

// Cross-field rules the on-screen ageing depends on: an available forecast
// carries its summary (valid_to) and hours; an unavailable one has no hours.
export const ForecastResponseSchema = refine(forecastResponseFields, (r) => {
  if (r.data_status === "unavailable") {
    if (r.hours.length > 0) return "unavailable forecast has hours";
    if (r.unavailable_reason === null) return "unavailable forecast has no reason";
    return null;
  }
  if (r.forecast === null) return "available forecast has no summary";
  if (r.unavailable_reason !== null) return "available forecast has an unavailable_reason";
  return null;
});

// CF-009/CF-010 map layers (docs/cf-009-design.md §7, cf-010-design.md §3-§5).
const AreaSchema = obj({ latitude: num, longitude: num, radius_nm: num });

export const AircraftPositionSchema = obj({
  id: str,
  callsign: nullable(str),
  latitude: num,
  longitude: num,
  altitude_ft: nullable(num),
  on_ground: bool,
  ground_speed_kt: nullable(num),
  track_deg: nullable(num),
  vertical_rate_fpm: nullable(num),
  category: nullable(str),
  kind: literal("aircraft", "unclassified"),
  position_at: datetime,
  expires_at: datetime,
  distance_nm: num,
});

const aircraftResponseFields = obj({
  airport: AirportSchema,
  area: AreaSchema,
  source: nullable(
    obj({
      provider: literal("adsblol", "opensky"),
      name: str,
      attribution_url: str,
      access: literal("keyless", "anonymous", "account"),
      privacy_filter: literal("applied", "unavailable"),
    }),
  ),
  observed_at: nullable(datetime),
  fetched_at: nullable(datetime),
  aircraft: arr(AircraftPositionSchema),
  withheld: num,
  excluded: num,
  dropped: num,
  data_status: literal("available", "no_aircraft", "coverage_unknown", "quota_exhausted", "unavailable"),
  unavailable_reason: nullable(
    literal(
      "no_location",
      "provider_disabled",
      "no_coverage_evidence",
      "stale_feed",
      "busy",
      "unusable_data",
      "daily_budget",
      "budget_unavailable",
    ),
  ),
  retry_at: nullable(datetime),
  disclaimer: str,
});

// The expiry rules depend on these: a feed answer carries its data time.
export const AircraftResponseSchema = refine(aircraftResponseFields, (r) => {
  const fed = r.data_status === "available" || r.data_status === "no_aircraft";
  if (fed && (r.observed_at === null || r.source === null)) return `${r.data_status} response lacks observed_at/source`;
  if (r.data_status === "no_aircraft" && r.aircraft.length > 0) return "no_aircraft response has aircraft";
  return null;
});

export const NearbyStationSchema = obj({
  station: str,
  name: nullable(str),
  latitude: num,
  longitude: num,
  distance_nm: num,
  observed_at: datetime,
  current_until: datetime,
  stale_until: datetime,
  data_status: literal("current", "stale"),
  conditions: ConditionsSchema,
});

export const NearbyConditionsResponseSchema = obj({
  airport: AirportSchema,
  area: AreaSchema,
  stations: arr(NearbyStationSchema),
  complete: bool,
  dropped: num,
  fetched_at: nullable(datetime),
  data_status: literal("available", "unavailable"),
  unavailable_reason: nullable(literal("no_stations", "unusable_data")),
  source: str,
});

export const RadarResponseSchema = refine(
  obj({
    enabled: bool,
    data_status: literal("available", "unavailable"),
    unavailable_reason: nullable(literal("provider_disabled", "invalid_index", "no_frames")),
    frame: nullable(obj({ time: datetime, tile_url: str, current_until: datetime })),
    attribution: str,
    attribution_url: str,
  }),
  (r) => {
    if (r.frame && !r.frame.tile_url.startsWith("https://tilecache.rainviewer.com/")) return "unexpected radar tile host";
    if (r.data_status === "available" && r.frame === null) return "available radar has no frame";
    return null;
  },
);

export type Airport = Infer<typeof AirportSchema>;
export type AircraftPosition = Infer<typeof AircraftPositionSchema>;
export type AircraftResponse = Infer<typeof AircraftResponseSchema>;
export type NearbyStation = Infer<typeof NearbyStationSchema>;
export type NearbyConditionsResponse = Infer<typeof NearbyConditionsResponseSchema>;
export type RadarResponse = Infer<typeof RadarResponseSchema>;
export type AirportResult = Infer<typeof AirportResultSchema>;
export type AirportSearchResponse = Infer<typeof AirportSearchResponseSchema>;
export type SkyCondition = Infer<typeof SkyConditionSchema>;
export type CloudLayer = Infer<typeof CloudLayerSchema>;
export type Observation = Infer<typeof ObservationSchema>;
export type Level = Infer<typeof LevelSchema>;
export type Factor = Infer<typeof FactorSchema>;
export type FactorName = Factor["name"];
export type Conditions = Infer<typeof ConditionsSchema>;
export type ConditionsResponse = Infer<typeof ConditionsResponseSchema>;
export type DataStatus = ConditionsResponse["data_status"];
export type UnavailableReason = NonNullable<ConditionsResponse["unavailable_reason"]>;
export type ErrorResponse = Infer<typeof ErrorResponseSchema>;
export type ForecastSummary = Infer<typeof ForecastSummarySchema>;
export type ForecastHour = Infer<typeof ForecastHourSchema>;
export type ForecastPossible = ForecastHour["possible"][number];
export type ForecastResponse = Infer<typeof ForecastResponseSchema>;
