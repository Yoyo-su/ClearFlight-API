import logging
import math
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

import requests
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from .cache import cache_response, check_cache

"""
METAR observations from the Aviation Weather Center (AWC) data API.

Observations are normalised into Observation; missing or implausible values
become None and are never inferred. Freshness is computed when read, never
stored. Provider failures raise MetarError subclasses so callers can map them
to HTTP statuses (D-006).
"""

logger = logging.getLogger(__name__)

AWC_METAR_URL = "https://aviationweather.gov/api/data/metar"
SOURCE = "Aviation Weather Center"
STATION_PATTERN = re.compile(r"[A-Z0-9]{4}")

MAX_ATTEMPTS = 2
BACKOFF_SECONDS = 0.5
BACKOFF_JITTER_SECONDS = 0.25
MAX_RETRY_AFTER_SECONDS = 2.0
FUTURE_TOLERANCE = timedelta(minutes=10)
METRES_PER_STATUTE_MILE = 1609.344

CLEAR_COVERS = {"CLR", "SKC", "NCD", "NSC"}
LAYER_COVERS = {"FEW", "SCT", "BKN", "OVC"}
CEILING_COVERS = {"BKN", "OVC"}
NO_REPORT = {"no_report": True}  # cached when the provider has no usable report


class MetarError(Exception):
    """Base error for METAR lookups; reason is machine-readable."""

    def __init__(self, reason: str, message: str | None = None):
        self.reason = reason
        super().__init__(message or reason)


class MetarTimeout(MetarError):
    """The provider did not respond in time, after retrying."""


class MetarUpstreamError(MetarError):
    """The provider failed or returned an unusable response."""


class MetarRateLimited(MetarError):
    """The local provider request budget is used up."""

    def __init__(self, retry_after_s: float):
        self.retry_after_s = retry_after_s
        super().__init__(
            "rate_limited",
            f"METAR request budget exhausted; retry in {retry_after_s:.0f}s",
        )


class CloudLayer(BaseModel):
    cover: str
    base_ft: int


class Observation(BaseModel):
    source: Literal["Aviation Weather Center"] = SOURCE
    station: str
    report_type: str | None
    observed_at: datetime
    fetched_at: datetime
    raw_text: str | None
    temperature_c: float | None
    dewpoint_c: float | None
    wind_direction_deg: int | None
    wind_variable: bool
    wind_speed_kt: int | None
    wind_gust_kt: int | None
    visibility_m: int | None
    visibility_at_least: bool
    sky_condition: Literal["clear", "cavok", "clouds", "obscured", "unknown"]
    cloud_layers: list[CloudLayer]
    ceiling_ft: int | None
    pressure_hpa: float | None
    weather_phenomena: list[str]


class RateLimiter:
    """Thread-safe token bucket allowing per_minute requests per minute."""

    def __init__(self, per_minute: int, clock=time.monotonic):
        self.capacity = float(per_minute)
        self.rate_per_second = per_minute / 60
        self.tokens = self.capacity
        self.clock = clock
        self.updated = clock()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        """Take one token.

        Raises:
            MetarRateLimited: when no token is available.
        """
        with self.lock:
            now = self.clock()
            elapsed = now - self.updated
            self.tokens = min(
                self.capacity, self.tokens + elapsed * self.rate_per_second
            )
            self.updated = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            raise MetarRateLimited((1 - self.tokens) / self.rate_per_second)


rate_limiter = RateLimiter(settings.METAR_RATE_LIMIT_PER_MINUTE)


def get_latest_observation(icao: str) -> Observation | None:
    """Return the latest METAR observation for a station, using the cache.

    Args:
        icao (str): 4-character ICAO station identifier.

    Raises:
        ValueError: if icao isn't 4 letters or digits.
        MetarTimeout, MetarUpstreamError, MetarRateLimited: provider failures.

    Returns:
        Observation or None: None when the provider has no usable report.
    """
    station = icao.strip().upper()
    if not STATION_PATTERN.fullmatch(station):
        raise ValueError("Station must be a 4-character ICAO code")

    cache_key = f"metar:v1:{station}"
    cached = check_cache(cache_key)
    if cached == NO_REPORT:
        return None
    if cached is not None:
        try:
            return Observation.model_validate(cached)
        except ValidationError:
            logger.warning("Ignoring invalid cached METAR for %s", station)

    records = fetch_metar_records(station)
    fetched_at = datetime.now(timezone.utc)
    observation = select_observation(records, station, fetched_at)
    if observation is None:
        # Cache "no report" only when the provider said so (204 or an empty
        # list), not when a response had records but none were usable.
        if not records:
            cache_response(cache_key, NO_REPORT, settings.METAR_NO_DATA_CACHE_TTL)
    else:
        cache_response(
            cache_key, observation.model_dump(mode="json"), settings.METAR_CACHE_TTL
        )
    return observation


def fetch_metar_records(station: str) -> list:
    """Request the latest METAR records for a station from AWC.

    Retries once after a short backoff on timeouts, connection errors, 429 and
    5xx. Every attempt uses a token from the rate limiter.

    Returns:
        list: the JSON records; empty when AWC has no report (HTTP 204).
    """
    error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            rate_limiter.acquire()
        except MetarRateLimited as limited:
            raise limited from error
        delay = BACKOFF_SECONDS + random.uniform(0, BACKOFF_JITTER_SECONDS)
        try:
            response = requests.get(
                AWC_METAR_URL,
                params={"ids": station, "format": "json"},
                headers={"User-Agent": settings.METAR_USER_AGENT},
                timeout=settings.PROVIDER_TIMEOUT,
            )
        except requests.Timeout:
            error = MetarTimeout("timeout")
        except requests.RequestException as e:
            error = MetarUpstreamError("connection_error", type(e).__name__)
        else:
            status = response.status_code
            if status == 204:
                return []
            if status == 429 or status >= 500:
                error = MetarUpstreamError(f"http_{status}")
                if status == 429:
                    delay = retry_after_seconds(response, delay)
            elif status != 200:
                raise MetarUpstreamError(f"http_{status}")
            else:
                try:
                    data = response.json()
                except ValueError:
                    raise MetarUpstreamError("invalid_json")
                if not isinstance(data, list):
                    raise MetarUpstreamError("unexpected_payload")
                return data
        logger.warning("METAR request for %s failed: %s", station, error.reason)
        if attempt < MAX_ATTEMPTS:
            time.sleep(delay)
    raise error


def retry_after_seconds(response, default: float) -> float:
    """Read a Retry-After header in seconds, capped at MAX_RETRY_AFTER_SECONDS."""
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return default
    if not math.isfinite(seconds):
        return default
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)


def select_observation(
    records: list, station: str, fetched_at: datetime
) -> Observation | None:
    """Normalise the station's newest valid record.

    Records for other stations, without a valid obsTime, or more than
    FUTURE_TOLERANCE ahead of fetched_at are ignored.
    """
    candidates = []
    for record in records:
        if not isinstance(record, dict) or record.get("icaoId") != station:
            continue
        obs_time = number(record.get("obsTime"), 0, math.inf, "obsTime")
        if obs_time is None:
            continue
        try:
            observed_at = datetime.fromtimestamp(obs_time, timezone.utc)
        except (OverflowError, OSError, ValueError):
            logger.warning("Ignoring invalid METAR obsTime: %r", obs_time)
            continue
        if observed_at > fetched_at + FUTURE_TOLERANCE:
            logger.warning("Ignoring METAR for %s dated in the future", station)
            continue
        candidates.append((observed_at, record))
    if not candidates:
        return None
    observed_at, record = max(candidates, key=lambda c: c[0])
    return normalise_record(record, station, observed_at, fetched_at)


def number(value, low: float, high: float, field: str) -> float | None:
    """Return value if it is a finite number within [low, high], else None."""
    if value is None:
        return None
    try:
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)  # OverflowError for huge JSON integers
            and low <= value <= high
        )
    except OverflowError:
        valid = False
    if not valid:
        logger.warning("Ignoring invalid METAR %s: %.40r", field, value)
        return None
    return value


def whole(value: float | None) -> int | None:
    return None if value is None else round(value)


def parse_visibility(value) -> tuple[float | None, bool]:
    """Return (statute miles, at_least) from AWC's visib, e.g. 4.35 or "10+"."""
    at_least = False
    if isinstance(value, str):
        text = value.strip()
        at_least = text.endswith("+")
        try:
            value = float(text.rstrip("+"))
        except ValueError:
            logger.warning("Ignoring invalid METAR visib: %r", text)
            return None, False
    miles = number(value, 0, math.inf, "visib")
    return miles, at_least and miles is not None


def parse_sky(cover, clouds) -> tuple[str, list[CloudLayer], int | None]:
    """Return (sky_condition, cloud layers, ceiling in feet)."""
    layers = []
    ceiling_unknown = False  # a BKN/OVC layer whose base is missing or invalid
    for layer in clouds if isinstance(clouds, list) else []:
        if not isinstance(layer, dict) or not isinstance(layer.get("cover"), str):
            continue
        if layer["cover"] not in LAYER_COVERS:
            continue
        base = number(layer.get("base"), 0, 100000, "cloud base")
        if base is not None:
            layers.append(CloudLayer(cover=layer["cover"], base_ft=round(base)))
        elif layer["cover"] in CEILING_COVERS:
            ceiling_unknown = True
    ceilings = [layer.base_ft for layer in layers if layer.cover in CEILING_COVERS]
    ceiling = min(ceilings) if ceilings else None
    if not isinstance(cover, str):
        cover = None
    if cover == "OVX":
        condition = "obscured"
    elif ceiling_unknown:
        # The ceiling could be at the unknown base, so it isn't knowable,
        # whatever the top-level cover says.
        condition, ceiling = "unknown", None
    elif cover == "CAVOK":
        condition = "cavok"
    elif cover in CLEAR_COVERS:
        condition = "clear"
    elif layers:
        condition = "clouds"
    else:
        condition = "unknown"
    return condition, layers, ceiling


def normalise_record(
    record: dict, station: str, observed_at: datetime, fetched_at: datetime
) -> Observation:
    """Map an AWC METAR record to an Observation (units: °C, kt, m, ft, hPa)."""
    wind_direction = record.get("wdir")
    wind_variable = wind_direction == "VRB"
    wind_speed = number(record.get("wspd"), 0, 250, "wspd")
    wind_gust = number(record.get("wgst"), 0, 300, "wgst")
    if wind_gust is not None and wind_speed is not None and wind_gust < wind_speed:
        logger.warning("Ignoring METAR gust below wind speed for %s", station)
        wind_gust = None
    miles, at_least = parse_visibility(record.get("visib"))
    sky_condition, layers, ceiling = parse_sky(
        record.get("cover"), record.get("clouds")
    )
    weather = record.get("wxString")
    report_type = record.get("metarType")
    raw_text = record.get("rawOb")
    return Observation(
        station=station,
        report_type=report_type if isinstance(report_type, str) else None,
        observed_at=observed_at,
        fetched_at=fetched_at,
        raw_text=raw_text if isinstance(raw_text, str) else None,
        temperature_c=number(record.get("temp"), -90, 60, "temp"),
        dewpoint_c=number(record.get("dewp"), -90, 60, "dewp"),
        wind_direction_deg=(
            None if wind_variable else whole(number(wind_direction, 0, 360, "wdir"))
        ),
        wind_variable=wind_variable,
        wind_speed_kt=whole(wind_speed),
        wind_gust_kt=whole(wind_gust),
        visibility_m=whole(
            None
            if miles is None
            else number(miles * METRES_PER_STATUTE_MILE, 0, math.inf, "visib")
        ),
        visibility_at_least=at_least,
        sky_condition=sky_condition,
        cloud_layers=layers,
        ceiling_ft=ceiling,
        pressure_hpa=number(record.get("altim"), 850, 1100, "altim"),
        weather_phenomena=weather.split() if isinstance(weather, str) else [],
    )


def age_minutes(observed_at: datetime, now: datetime | None = None) -> float:
    """Minutes between the observation and now (negative if slightly ahead)."""
    now = now or datetime.now(timezone.utc)
    return (now - observed_at).total_seconds() / 60


def freshness(
    observed_at: datetime, now: datetime | None = None
) -> Literal["current", "stale", "expired"]:
    """Classify an observation's age with the pilot thresholds (plan §3)."""
    age = age_minutes(observed_at, now)
    if age <= settings.METAR_CURRENT_MAX_MINUTES:
        return "current"
    if age <= settings.METAR_STALE_MAX_MINUTES:
        return "stale"
    return "expired"
