import logging
import re
from datetime import datetime, timezone

from app.services.cache import cache_response, check_cache
from app.services.metar import (
    AWC_METAR_URL,
    Observation,
    fetch_metar_records,
    freshness,
    number,
    select_observation,
)
from app.services.positions import Area, distance_nm

"""
Observed conditions at reporting stations near an airport (CF-010 design r3
§4): one AWC METAR bounding-box query per airport, validated, de-duplicated
and filtered by true distance. Freshness is applied at read time by the API.
"""

logger = logging.getLogger(__name__)

AWC_RESULT_CAP = 400  # AWC returns at most this many records per request
NEARBY_CACHE_TTL = 600  # seconds
STALE_ANSWER_TTL = 60  # D-007: an answer that is stale as a whole recovers fast
NO_STATIONS_TTL = 300
STATION_PATTERN = re.compile(r"[A-Z0-9]{4}")


def bbox(area: Area) -> str:
    """AWC bbox parameter: lat0,lon0,lat1,lon1 (one box; split at ±180)."""
    lamin, lomin, lamax, lomax = area.boxes()[0]
    return f"{lamin:.4f},{lomin:.4f},{lamax:.4f},{lomax:.4f}"


def get_nearby(code: str, area: Area, exclude: str | None) -> dict:
    """Nearby stations' latest observations for an airport, using the cache.

    Returns:
        dict: {stations: [station dicts], complete, dropped, fetched_at,
            records}; records == 0 means AWC had no stations in the area.

    Raises:
        MetarTimeout, MetarUpstreamError, MetarRateLimited: provider failures.
    """
    cache_key = f"nearby:v1:{code}"
    cached = check_cache(cache_key)
    if isinstance(cached, dict) and "stations" in cached:
        try:
            return revive(cached)
        except (ValueError, KeyError, TypeError):
            logger.warning("Ignoring invalid cached nearby result for %s", code)
    fetched_at = datetime.now(timezone.utc)
    records = fetch_metar_records(code, AWC_METAR_URL, {"bbox": bbox(area)})
    result = parse_nearby(records, area, exclude, fetched_at)
    cache_response(cache_key, serialise(result), ttl_for(result, fetched_at))
    return result


def parse_nearby(
    records: list, area: Area, exclude: str | None, fetched_at: datetime
) -> dict:
    """Validate, de-duplicate and distance-filter AWC records (spec §4)."""
    by_station: dict[str, list] = {}
    places: dict[str, tuple[float, float, str | None]] = {}
    dropped = 0
    for record in records if isinstance(records, list) else []:
        station = record.get("icaoId") if isinstance(record, dict) else None
        lat = (
            number(record.get("lat"), -90, 90, "lat")
            if isinstance(record, dict)
            else None
        )
        lon = (
            number(record.get("lon"), -180, 180, "lon")
            if isinstance(record, dict)
            else None
        )
        if (
            not isinstance(station, str)
            or not STATION_PATTERN.fullmatch(station)
            or lat is None
            or lon is None
        ):
            dropped += 1
            continue
        by_station.setdefault(station, []).append(record)
        name = record.get("name") if isinstance(record.get("name"), str) else None
        places[station] = (lat, lon, name)
    stations = []
    for station, group in by_station.items():
        if station == exclude:
            continue  # the airport itself comes from /conditions (spec §4)
        lat, lon, name = places[station]
        dist = distance_nm(area.latitude, area.longitude, lat, lon)
        if dist > area.radius_nm:
            continue
        observation = select_observation(group, station, fetched_at)
        if observation is None:
            dropped += 1
            continue
        stations.append(
            {
                "station": station,
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "distance_nm": round(dist, 1),
                "observation": observation,
            }
        )
    stations.sort(key=lambda s: s["distance_nm"])
    return {
        "stations": stations,
        "complete": (
            len(records) < AWC_RESULT_CAP if isinstance(records, list) else False
        ),
        "dropped": dropped,
        "fetched_at": fetched_at,
        "records": len(records) if isinstance(records, list) else 0,
    }


def ttl_for(result: dict, fetched_at: datetime) -> int:
    if result["records"] == 0:
        return NO_STATIONS_TTL
    stations = result["stations"]
    if stations and all(
        freshness(s["observation"].observed_at, fetched_at) != "current"
        for s in stations
    ):
        return STALE_ANSWER_TTL  # likely a stale CDN answer (D-007)
    return NEARBY_CACHE_TTL


def serialise(result: dict) -> dict:
    return {
        **result,
        "fetched_at": result["fetched_at"].isoformat(),
        "stations": [
            {**s, "observation": s["observation"].model_dump(mode="json")}
            for s in result["stations"]
        ],
    }


def revive(data: dict) -> dict:
    return {
        **data,
        "fetched_at": datetime.fromisoformat(data["fetched_at"]),
        "stations": [
            {**s, "observation": Observation.model_validate(s["observation"])}
            for s in data["stations"]
        ],
    }
