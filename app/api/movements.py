import redis

from app.api.conditions import resolve_airport, utc_now
from app.services import cache, movements, positions_service
from app.services.positions_providers import ProviderDisabled

DISCLAIMER = (
    "Detected from volunteer receiver data while this page was open. May be "
    "incomplete; not an official departures board."
)
MAX_LISTED = 100  # V4

# P5 results per airport (CF-011 §9), set from docs/validation/ once checked.
# Until then every airport and method is "experimental".
VALIDATION: dict[str, dict[str, str]] = {}


def validation_for(code: str) -> dict:
    known = VALIDATION.get(code, {})
    return {
        key: known.get(key, "experimental")
        for key in ("observed", "inferred", "airport")
    }


def movements_query(code: str) -> dict:
    """Recent observed movements for an airport (CF-011 design r3 §5).

    Reads the movement store only; no provider call.

    Raises:
        ConditionsError: 400 invalid code, 404 unknown airport.
    """
    airport, airport_data = resolve_airport(code)
    base = {
        "airport": airport_data,
        "source": None,
        "movements": [],
        "watched": [],
        "coverage_mode": "unknown",
        "coverage_reason": "not_enough_watching",
        "validation": validation_for(airport.code),
        "disclaimer": DISCLAIMER,
    }
    try:
        provider = positions_service.get_provider()
    except ProviderDisabled:
        return {
            **base,
            "data_status": "unavailable",
            "unavailable_reason": "not_watched",
        }
    source = {
        "provider": provider.name,
        "name": provider.display,
        "attribution_url": provider.attribution_url,
        "access": provider.access,
        "privacy_filter": provider.privacy_filter,
    }
    try:
        state = movements.read(
            cache.redis_client, provider.name, airport.code, utc_now()
        )
    except redis.RedisError:
        return {
            **base,
            "source": source,
            "data_status": "unavailable",
            "unavailable_reason": "store_unavailable",
        }
    if state is None:
        return {
            **base,
            "source": source,
            "data_status": "unavailable",
            "unavailable_reason": "not_watched",
        }
    watched = [dict(w) for w in state["windows"]]
    if state.get("window"):
        watched.append(
            {
                "from": state["window"]["from"],
                "to": state["window"]["to"],
                "ended_by": None,
            }
        )
    mode, reason = movements.coverage_mode(state)
    listed = sorted(state["movements"], key=lambda m: m["time_to"], reverse=True)[
        :MAX_LISTED
    ]
    return {
        **base,
        "source": source,
        "movements": listed,
        "watched": watched,
        "coverage_mode": mode,
        "coverage_reason": reason,
        "data_status": "available",
        "unavailable_reason": None,
    }
