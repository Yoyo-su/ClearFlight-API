from app.api.conditions import call_provider, resolve_airport, utc_now
from app.services import taf


def forecast_query(code: str) -> dict:
    """Build the forecast outlook for an airport (CF-008 spec §4).

    Raises:
        ConditionsError: 400 invalid code, 404 unknown airport, 502/503/504
            for provider failures, incl. 502 invalid_forecast (D-006).

    Returns:
        dict: airport, forecast (source, station, issued_at, valid_from,
            valid_to, raw_text), hours, data_status, unavailable_reason and
            disclaimer.
    """
    airport, airport_data = resolve_airport(code)
    if airport.icao is None:
        return unavailable(airport_data, "no_metar_station")
    record = call_provider(taf.get_latest_forecast, airport.icao)
    if record is None:
        return unavailable(airport_data, "no_forecast")
    meta, periods = call_provider(taf.parse_taf, record, airport.icao)
    now = utc_now()
    if now >= meta["valid_to"]:
        return unavailable(airport_data, "forecast_expired", meta)
    return {
        "airport": airport_data,
        "forecast": meta,
        "hours": taf.hourly_outlook(meta, periods, now),
        "data_status": "available",
        "unavailable_reason": None,
        "disclaimer": taf.index.FORECAST_DISCLAIMER,
    }


def unavailable(airport_data: dict, reason: str, meta: dict | None = None) -> dict:
    return {
        "airport": airport_data,
        "forecast": meta,
        "hours": [],
        "data_status": "unavailable",
        "unavailable_reason": reason,
        "disclaimer": taf.index.FORECAST_DISCLAIMER,
    }
