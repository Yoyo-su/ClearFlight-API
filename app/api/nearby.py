from datetime import timedelta

from app.api.conditions import call_provider, resolve_airport, utc_now
from app.core.config import settings
from app.services import conditions as index
from app.services.metar import freshness
from app.services.nearby import get_nearby
from app.services.positions import Area

NEARBY_RADIUS_NM = 50.0  # owner decision M3
SOURCE = "NOAA Aviation Weather Center (METAR)"


def nearby_query(code: str) -> dict:
    """Observed conditions at stations within 50 nm (CF-010 design r3 §4).

    Raises:
        ConditionsError: 400/404, and 502/503/504 for provider failures.
    """
    airport, airport_data = resolve_airport(code)
    area = Area(airport.latitude, airport.longitude, NEARBY_RADIUS_NM)
    result = call_provider(get_nearby, airport.code, area, airport.icao)
    now = utc_now()  # one clock for every station's status and score
    stations = []
    for s in result["stations"]:
        obs = s["observation"]
        status = freshness(obs.observed_at, now)
        if status == "expired":
            continue  # too old to show at all (D-007)
        stations.append(
            {
                "station": s["station"],
                "name": s["name"],
                "latitude": s["latitude"],
                "longitude": s["longitude"],
                "distance_nm": s["distance_nm"],
                "observed_at": obs.observed_at,
                "current_until": obs.observed_at
                + timedelta(minutes=settings.METAR_CURRENT_MAX_MINUTES),
                "stale_until": obs.observed_at
                + timedelta(minutes=settings.METAR_STALE_MAX_MINUTES),
                "data_status": status,
                "conditions": index.evaluate(obs, status),
            }
        )
    reason = None
    if not stations:
        reason = (
            "no_stations"
            if result["records"] == 0 or not result["dropped"]
            else "unusable_data"
        )
    return {
        "airport": airport_data,
        "area": {
            "latitude": area.latitude,
            "longitude": area.longitude,
            "radius_nm": area.radius_nm,
        },
        "stations": stations,
        "complete": result["complete"],
        "dropped": result["dropped"],
        "fetched_at": result["fetched_at"],
        "data_status": "available" if stations else "unavailable",
        "unavailable_reason": reason,
        "source": SOURCE,
    }
