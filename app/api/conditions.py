import math
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.core.config import settings
from app.services import conditions as index
from app.services import unrecognised_weather
from app.services.airport_catalogue import get_catalogue
from app.services.metar import (
    MetarRateLimited,
    MetarTimeout,
    MetarUpstreamError,
    age_minutes,
    freshness,
    get_latest_observation,
)

CODE_PATTERN = re.compile(r"[A-Z]{3}|[A-Z0-9]{4}")


class ConditionsError(HTTPException):
    """An HTTP error with a machine-readable reason (body: detail + reason)."""

    def __init__(self, status_code: int, reason: str, detail: str, headers=None):
        self.reason = reason
        super().__init__(status_code=status_code, detail=detail, headers=headers)


def resolve_airport(code: str):
    """Validate a code and find the airport; shared by the v1 airport routes.

    Raises:
        ConditionsError: 400 for a badly formed code, 404 for an unknown airport.

    Returns:
        tuple: (Airport, its public fields for responses).
    """
    normalised = code.strip().upper()
    if not code.isascii() or not CODE_PATTERN.fullmatch(normalised):
        raise ConditionsError(
            400, "invalid_code", "code must be a 3-letter IATA or 4-character ICAO code"
        )
    airport = get_catalogue().get(normalised)
    if airport is None:
        raise ConditionsError(
            404, "airport_not_found", f"No airport with code {normalised}"
        )
    airport_data = {
        key: value
        for key, value in airport.to_dict().items()
        if key not in ("type", "latitude", "longitude")
    }
    return airport, airport_data


def call_provider(fetch, *args):
    """Call a weather-provider function, mapping its errors to HTTP (D-006)."""
    try:
        return fetch(*args)
    except MetarTimeout:
        raise ConditionsError(504, "provider_timeout", "The weather provider timed out")
    except MetarUpstreamError as e:
        reason = (
            "invalid_forecast" if e.reason == "invalid_forecast" else "provider_error"
        )
        raise ConditionsError(502, reason, f"The weather provider failed ({e.reason})")
    except MetarRateLimited as e:
        raise ConditionsError(
            503,
            "rate_limited",
            "Weather requests are temporarily limited; try again shortly",
            headers={"Retry-After": str(max(1, math.ceil(e.retry_after_s)))},
        )


def conditions_query(code: str) -> dict:
    """Build the conditions response for an airport (IATA or ICAO code).

    Raises:
        ConditionsError: 400 invalid code, 404 unknown airport, 502/503/504
            for METAR provider failures (D-006).

    Returns:
        dict: airport, observation, conditions, data_status,
            unavailable_reason, last_observed_at, and current_until and
            stale_until (when the observation stops being current and
            expires, from the configured thresholds; D-007, D-008).
    """
    airport, airport_data = resolve_airport(code)
    if airport.icao is None:
        return unavailable(airport_data, "no_metar_station")
    observation = call_provider(get_latest_observation, airport.icao)
    if observation is None:
        return unavailable(airport_data, "no_report")

    now = utc_now()  # one clock for age, status and score
    status = freshness(observation.observed_at, now)
    if status == "expired":
        return unavailable(airport_data, "observation_too_old", observation.observed_at)
    groups = index.unrecognised_groups(observation.weather_phenomena)
    if groups:
        unrecognised_weather.record(observation, groups)
    return {
        "airport": airport_data,
        "observation": {
            **observation.model_dump(),
            # Rounded up, so a displayed age never looks fresher than its status
            "age_minutes": max(0, math.ceil(age_minutes(observation.observed_at, now))),
        },
        "conditions": index.evaluate(observation, status),
        "data_status": status,
        "unavailable_reason": None,
        "last_observed_at": observation.observed_at,
        "current_until": observation.observed_at
        + timedelta(minutes=settings.METAR_CURRENT_MAX_MINUTES),
        "stale_until": observation.observed_at
        + timedelta(minutes=settings.METAR_STALE_MAX_MINUTES),
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def unavailable(airport_data: dict, reason: str, last_observed_at=None) -> dict:
    return {
        "airport": airport_data,
        "observation": None,
        "conditions": index.evaluate(None, "unavailable", reason),
        "data_status": "unavailable",
        "unavailable_reason": reason,
        "last_observed_at": last_observed_at,
        "current_until": None,
        "stale_until": None,
    }
