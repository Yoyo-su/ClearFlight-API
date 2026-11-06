# ClearFlight API reference

The backend is a FastAPI app (`app/main.py`). Interactive OpenAPI docs are served at `/docs` when it runs (http://localhost:8000/docs locally). The response models are in `app/api/models.py`. The contract decisions are D-005 to D-009 in [DECISIONS.md](DECISIONS.md).

## GET /health
Liveness check: `{"status": "ok"}` (`GET /` returns the same).

## GET /v1/airports/{code}/conditions
Observed weather conditions at an airport, from the latest METAR report. `code` is an IATA (3 letters) or ICAO (4 characters) code, in any case.

example: `/v1/airports/LHR/conditions`. This illustrative, abridged response is based on a recorded report with 1.3 km visibility in mist and overcast at 200 ft:
```json
{
  "airport": {"code": "EGLL", "icao": "EGLL", "iata": "LHR", "name": "London Heathrow Airport",
              "city": "London", "country": "United Kingdom", "country_code": "GB",
              "timezone": "Europe/London"},
  "observation": {"source": "Aviation Weather Center", "station": "EGLL",
                  "observed_at": "2026-10-30T07:20:00Z", "fetched_at": "2026-10-30T07:55:02Z",
                  "age_minutes": 35, "raw_text": "METAR EGLL 300720Z 07004KT ... BR OVC002 10/10 Q1029",
                  "wind_speed_kt": 4, "visibility_m": 1304, "sky_condition": "clouds",
                  "ceiling_ft": 200, "weather_phenomena": ["BR"], "...": "..."},
  "conditions": {"version": "0.1", "score": 8, "level": "severe",
                 "factors": [{"name": "visibility", "value": 1304, "unit": "m", "score": 8,
                              "detail": "1.3 km"}, "..."],
                 "explanation": "Observed conditions index 8/10 (severe), mainly from visibility of 1.3 km and a cloud ceiling at 200 ft.",
                 "disclaimer": "Experimental index of the weather reported at the airport. It is not a forecast and does not predict delays, cancellations or flight safety."},
  "data_status": "current",
  "unavailable_reason": null,
  "last_observed_at": "2026-10-30T07:20:00Z",
  "current_until": "2026-10-30T08:50:00Z",
  "stale_until": "2026-10-30T10:20:00Z"
}
```
**`data_status`:**
- `current`: observed within `METAR_CURRENT_MAX_MINUTES` (90). Scored if the inputs are adequate.
- `stale`: observed within `METAR_STALE_MAX_MINUTES` (180). The observation is shown, but not scored.
- `unavailable` (`200`, never `404` for a known airport), with `observation: null` and an `unavailable_reason`:
  - `no_metar_station`: the airport has no ICAO code;
  - `no_report`: the station has no current report;
  - `observation_too_old`: older than the stale limit; `last_observed_at` gives its time.

**`current_until` / `stale_until`** (D-008): when the observation stops being current (it loses its score) and when it expires (its values should no longer be shown). The backend computes them from its configured thresholds, so a client keeping a response on screen can age it without knowing the thresholds. They're `null` when there's no observation.

**Conditions index v0.1 (D-007):** an experimental 0–10 severity of the *observed* conditions; higher is more severe. It is not a forecast and does not predict delays, cancellations or flight safety. The index is the highest of four components:

| Score | Wind (kt, higher of speed and gust) | Visibility | Ceiling (lowest BKN/OVC) |
|---|---|---|---|
| 0 | < 10 | ≥ 8 km | none, or > 3000 ft |
| 2 | 10–19 | | |
| 3 | | 4.8–8 km | 1000–3000 ft |
| 4 | 20–29 | | |
| 6 | 30–39 | 1.6–4.8 km | 500–999 ft |
| 8 | 40–49 | 0.8–1.6 km | 200–499 ft |
| 10 | ≥ 50 | < 800 m | < 200 ft |

Visibility arrives from the provider in statute miles rounded to 0.01. Band comparisons allow 10 m for that rounding, so a reported 8000 m (sent as 4.97 SM = 7998 m) scores 0. When the provider's "6+" comes from a metric `9999` or `CAVOK` report, it is reported as 10,000 m, "at least"; any other "6+" stays at 6 statute miles, "at least".

- **Reported weather:**
  - thunderstorm 8 (heavy 10);
  - hail, squall, funnel cloud, volcanic ash, dust or sandstorm 10;
  - freezing rain or drizzle 8;
  - snow, ice pellets or snow pellets 3 / 5 / 8 (light / moderate / heavy);
  - rain, drizzle, showers, snow grains, ice crystals or unknown precipitation 1 / 3 / 5;
  - blowing snow, sand or dust 3;
  - mist, haze, fog and smoke 0 (visibility covers them);
  - weather "in the vicinity" (VC) is capped at 5;
  - an unrecognised code makes the weather factor unknown (see below). It is named in the factor detail and recorded for later scoring.
- **Levels:** low 0–2, moderate 3–5, high 6–7, severe 8–10, or `unknown`.
- **When there's no score:** a score needs a `current` observation with known wind speed, visibility, ceiling and weather. Otherwise the level is `unknown` and the explanation names what's missing or couldn't be interpreted. The one exception: if the known components already reach 10, the score is 10, because the missing one can't change it. Examples are dense fog with the sky obscured, or a gust of 50 kt or more when the sustained speed is missing.
- **Unrecognised weather codes** are logged and counted in Redis, once per observation, with the last example report. List them with `docker compose exec clearflightapi python scripts/unrecognised_weather.py` so the scoring table can be extended.

**Errors** (body `{"detail": "...", "reason": "..."}`):
- `400` `invalid_code`;
- `404` `airport_not_found`;
- `502` `provider_error`;
- `503` `rate_limited`, with `Retry-After` (the server's own METAR request budget is used up);
- `504` `provider_timeout`.

`429` (a per-client rate limit, plan §4) isn't implemented yet; the server-wide METAR budget returns `503`.

**Known limitations (v0.1):**
- The index bands are heuristic and not yet validated with travellers (CF-007).
- A garbled report whose wind, visibility and cloud fields still parse is scored normally; the provider's quality flags aren't used.
- The METAR request budget is per server process.
- A provider timeout can make a lookup take up to about 21 s.

## GET /v1/airports/search
Searches the local airport catalogue (OurAirports data, no provider call) by IATA or ICAO code, name or city. Matching ignores case and accents.

Parameters: `q` (2–64 characters, required), `limit` (1–25, default 10).

example: `/v1/airports/search?q=heathrow` returns
```json
{
  "query": "heathrow",
  "count": 1,
  "results": [
    {
      "code": "EGLL", "icao": "EGLL", "iata": "LHR",
      "name": "London Heathrow Airport", "city": "London",
      "country": "United Kingdom", "country_code": "GB",
      "type": "large_airport", "timezone": "Europe/London",
      "latitude": 51.470748, "longitude": -0.459909
    }
  ]
}
```
- Results are ordered: exact IATA/ICAO code first; then airports with scheduled airline service before those without; within each group, name or city starting with `q`, then a word starting with `q`, then any other match; then larger airports, then by name.
- `code` is the ICAO code, or the IATA code when the airport has no ICAO code. `icao`, `iata`, `city`, `country` and `timezone` can be `null`.
- `timezone` is an IANA zone ID. A few remote airports have none (`null`); the API never substitutes a fixed offset.
- No match returns `200` with an empty `results` list. A missing, too short or too long `q`, or an invalid `limit`, returns `400`.

The catalogue covers large, medium and small airports with an IATA or ICAO code (about 11,000). It is a committed snapshot in `app/data/airports.csv`; see [Updating the airport catalogue](DEVELOPMENT.md#updating-the-airport-catalogue).

## GET /airport (deprecated)
Legacy prototype route: airport metadata and weather from AviationStack and WeatherStack. Replaced by `/v1/airports/{code}/conditions`; it will be removed in CF-006, before public deployment. It currently fails against the AviationStack trial, which returns each airport twice.

example: `/airport/KJFK` or `/airport/JFK`
