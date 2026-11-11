import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import redis

from app.core.config import settings
from app.services import cache
from app.services.credit_budget import Lock
from app.services.metar import MetarRateLimited, MetarUpstreamError, RateLimiter
from app.services.positions_http import get

"""
RainViewer radar frames for the map (CF-010 design r3 §5; owner decision M4).

RainViewer allows personal/educational use only, so the layer exists only
with RAINVIEWER_EDUCATIONAL_USE=true. The index is a trust boundary: only the
expected tile host and path shapes ever reach the browser.
"""

logger = logging.getLogger(__name__)

INDEX_URL = "https://api.rainviewer.com/public/weather-maps.json"
TILE_HOST = "https://tilecache.rainviewer.com"
PATH_PATTERN = re.compile(r"/v2/radar/[A-Za-z0-9]+")
CACHE_KEY = "radar:v1:index"
FAILED_KEY = "radar:v1:failed"
LOCK_KEY = "radar:v1:lock"
CACHE_TTL = 300  # seconds
FAILURE_TTL = 60  # an outage costs at most one fetch a minute per process
KEPT_REASONS = {"invalid_index", "no_frames"}  # reasons that are 200 states
MAX_FRAME_AGE = timedelta(hours=3)
FRAME_VALID_FOR = timedelta(minutes=20)
ATTRIBUTION = "Radar © RainViewer"
ATTRIBUTION_URL = "https://www.rainviewer.com"
DEADLINE_S = 15.0
WAIT_POLL_S = 0.2

rate_limiter = RateLimiter(6)  # index fetches per minute, per process


class RadarDisabled(Exception):
    """The licence gate is off."""


def latest_frame(index, now: datetime) -> dict:
    """The newest valid frame from a RainViewer index.

    Raises:
        MetarUpstreamError: "invalid_index" or "no_frames".
    """
    if not isinstance(index, dict) or index.get("host") != TILE_HOST:
        raise MetarUpstreamError("invalid_index", "unexpected host")
    radar = index.get("radar")
    past = radar.get("past") if isinstance(radar, dict) else None
    if not isinstance(past, list):
        raise MetarUpstreamError("invalid_index", "no frame list")
    frames = []
    for frame in past:
        if not isinstance(frame, dict):
            raise MetarUpstreamError("invalid_index", "bad frame")
        when, path = frame.get("time"), frame.get("path")
        if (
            isinstance(when, bool)
            or not isinstance(when, int)
            or not isinstance(path, str)
        ):
            raise MetarUpstreamError("invalid_index", "bad frame")
        if not PATH_PATTERN.fullmatch(path):
            raise MetarUpstreamError("invalid_index", "unexpected path")
        try:
            at = datetime.fromtimestamp(when, timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise MetarUpstreamError("invalid_index", "bad time")
        if not (now - MAX_FRAME_AGE <= at <= now + timedelta(minutes=5)):
            continue  # implausible or too old
        frames.append((at, path))
    if not frames:
        raise MetarUpstreamError("no_frames")
    at, path = max(frames)
    return {
        "time": at,
        "tile_url": f"{TILE_HOST}{path}/256/{{z}}/{{x}}/{{y}}/2/1_0.png",
        "current_until": at + FRAME_VALID_FOR,
    }


def get_radar(now: datetime | None = None) -> dict:
    """The latest radar frame (cached index; single-flight; negative cache).

    Raises:
        RadarDisabled: the licence gate is off (nothing is fetched).
        MetarUpstreamError ("invalid_index", "no_frames", transport), MetarTimeout,
        MetarRateLimited.
    """
    if not settings.RAINVIEWER_EDUCATIONAL_USE:
        raise RadarDisabled()
    now = now or datetime.now(timezone.utc)
    client = cache.redis_client
    try:
        index = cached_index(client)
        if index is None:
            index = fetch_shared(client, now)
    except redis.RedisError as e:
        logger.warning(
            "Redis unavailable for radar; fetching uncached: %s", type(e).__name__
        )
        index = fetch_index()
    return latest_frame(index, now)


def cached_index(client):
    failed = client.get(FAILED_KEY)
    if failed is not None:
        # The same failure, with the same reason, for every caller in the
        # back-off window (an invalid index stays a 200 state, not a 502).
        reason = failed if failed in KEPT_REASONS else "provider_error"
        raise MetarUpstreamError(reason, "recent radar failure")
    raw = client.get(CACHE_KEY)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def fetch_shared(client, now: datetime):
    """Fetch the index once for all concurrent callers (CF-009 lock)."""
    lock = Lock(client, LOCK_KEY, int(DEADLINE_S) + 10)
    if not lock.acquire():
        end = time.monotonic() + DEADLINE_S
        while time.monotonic() < end:
            time.sleep(WAIT_POLL_S)
            index = cached_index(client)
            if index is not None:
                return index
        raise MetarUpstreamError("provider_error", "radar busy")
    try:
        # Another caller may have finished (or failed) between our miss and lock.
        index = cached_index(client)
        if index is not None:
            return index
        try:
            index = fetch_index()
        except MetarRateLimited:
            raise  # our own cap: RainViewer wasn't contacted
        except MetarUpstreamError as e:
            client.set(FAILED_KEY, e.reason, ex=FAILURE_TTL)  # back off a minute
            raise
        except Exception:
            client.set(FAILED_KEY, "provider_error", ex=FAILURE_TTL)
            raise
        try:
            latest_frame(index, now)  # validate before caching (spec §5)
        except MetarUpstreamError as e:
            # A bad index takes the 60 s failure path, not the 5 min cache.
            client.set(FAILED_KEY, e.reason, ex=FAILURE_TTL)
            raise
        client.set(CACHE_KEY, json.dumps(index), ex=CACHE_TTL)
        return index
    finally:
        try:
            lock.release()
        except redis.RedisError:
            pass


def fetch_index():
    rate_limiter.acquire()  # MetarRateLimited when over the cap
    reply = get(INDEX_URL, time.monotonic() + DEADLINE_S)
    if reply.status_code != 200:
        raise MetarUpstreamError(f"http_{reply.status_code}")
    try:
        return reply.json()
    except ValueError:
        raise MetarUpstreamError("invalid_index", "not json")
