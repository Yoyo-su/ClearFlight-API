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

export type Airport = Infer<typeof AirportSchema>;
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
