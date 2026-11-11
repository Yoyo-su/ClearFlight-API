from app.api.conditions import call_provider, utc_now
from app.services.metar import MetarUpstreamError
from app.services.radar import ATTRIBUTION, ATTRIBUTION_URL, RadarDisabled, get_radar


def radar_query() -> dict:
    """The latest radar frame, or why there is none (CF-010 design r3 §5).

    Raises:
        ConditionsError: 502/503/504 for provider failures.
    """
    base = {"attribution": ATTRIBUTION, "attribution_url": ATTRIBUTION_URL}
    try:
        frame = call_provider(lambda: own_reasons(get_radar, utc_now()))
    except RadarDisabled:
        return {**base, "enabled": False, "data_status": "unavailable",
                "unavailable_reason": "provider_disabled", "frame": None}  # fmt: skip
    except Unavailable as e:
        return {**base, "enabled": True, "data_status": "unavailable",
                "unavailable_reason": e.reason, "frame": None}  # fmt: skip
    return {**base, "enabled": True, "data_status": "available",
            "unavailable_reason": None, "frame": frame}  # fmt: skip


class Unavailable(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def own_reasons(fetch, now):
    """Invalid or empty indexes are states (200), not provider errors."""
    try:
        return fetch(now)
    except MetarUpstreamError as e:
        if e.reason in ("invalid_index", "no_frames"):
            raise Unavailable(e.reason)
        raise
