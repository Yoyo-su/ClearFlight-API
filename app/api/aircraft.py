import math
from dataclasses import asdict
from datetime import timedelta

from app.api.conditions import call_provider, resolve_airport, utc_now
from app.core.config import settings
from app.services import positions_service
from app.services.positions import Area, assess, visible
from app.services.positions_providers import ProviderDisabled, QuotaExhausted

DISCLAIMER = (
    "Live positions from volunteer receiver networks. Coverage is incomplete and "
    "positions can be delayed; not for navigation or safety use."
)


def aircraft_query(code: str) -> dict:
    """Live aircraft near an airport (CF-009 design r3 §7).

    Raises:
        ConditionsError: 400 invalid code, 404 unknown airport, 502/503/504
            for provider failures (incl. 502 provider_auth_failed).

    Returns:
        dict: the AircraftResponse fields.
    """
    airport, airport_data = resolve_airport(code)
    area = Area(airport.latitude, airport.longitude, settings.POSITIONS_RADIUS_NM)
    base = {"airport": airport_data, "area": asdict(area)}
    if not (math.isfinite(airport.latitude) and math.isfinite(airport.longitude)):
        return empty(base, "unavailable", "no_location")
    try:
        result, evidence, provider = call_provider(
            positions_service.get_positions, airport.code, area
        )
    except ProviderDisabled:
        return empty(base, "unavailable", "provider_disabled")
    except QuotaExhausted as e:
        return empty(base, "quota_exhausted", e.reason, retry_at=e.retry_at)
    except positions_service.Busy:
        return empty(base, "coverage_unknown", "busy")

    now = utc_now()  # one clock for expiry and state
    shown = visible(result, now, settings.POSITIONS_MAX_AGE_S)
    status, reason = assess(shown, now, settings.POSITIONS_MAX_AGE_S, evidence)
    max_age = timedelta(seconds=settings.POSITIONS_MAX_AGE_S)
    return {
        **base,
        "source": {
            "provider": provider.name,
            "name": provider.display,
            "attribution_url": provider.attribution_url,
            "access": provider.access,
            "privacy_filter": provider.privacy_filter,
        },
        "observed_at": shown.observed_at,
        "fetched_at": shown.fetched_at,
        "aircraft": [
            {**asdict(t), "expires_at": t.position_at + max_age} for t in shown.targets
        ],
        "withheld": shown.withheld,
        "excluded": shown.excluded,
        "dropped": shown.dropped,
        "data_status": status,
        "unavailable_reason": reason,
        "retry_at": None,
        "disclaimer": DISCLAIMER,
    }


def empty(base: dict, status: str, reason: str, retry_at=None) -> dict:
    return {
        **base,
        "source": None,
        "observed_at": None,
        "fetched_at": None,
        "aircraft": [],
        "withheld": 0,
        "excluded": 0,
        "dropped": 0,
        "data_status": status,
        "unavailable_reason": reason,
        "retry_at": retry_at,
        "disclaimer": DISCLAIMER,
    }
