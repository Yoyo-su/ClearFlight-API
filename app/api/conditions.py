import math
import re
from datetime import datetime, timezone

from fastapi import HTTPException

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


def conditions_query(code: str) -> dict:
    """Build the conditions response for an airport (IATA or ICAO code).

    Raises:
        ConditionsError: 400 invalid code, 404 unknown airport, 502/503/504
            for METAR provider failures (D-006).

    Returns:
        dict: airport, observation, conditions, data_status,
            unavailable_reason and last_observed_at (D-007).
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

    if airport.icao is None:
        return unavailable(airport_data, "no_metar_station")
    try:
        observation = get_latest_observation(airport.icao)
    except MetarTimeout:
        raise ConditionsError(504, "provider_timeout", "The weather provider timed out")
    except MetarUpstreamError as e:
        raise ConditionsError(
            502, "provider_error", f"The weather provider failed ({e.reason})"
        )
    except MetarRateLimited as e:
        raise ConditionsError(
            503,
            "rate_limited",
            "Weather requests are temporarily limited; try again shortly",
            headers={"Retry-After": str(max(1, math.ceil(e.retry_after_s)))},
        )
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
    }
