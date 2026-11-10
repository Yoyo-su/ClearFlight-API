import json
import logging
import time

import redis

from app.core.config import settings
from app.services import cache
from app.services.credit_budget import Lock
from app.services.positions import Area, FeedResult
from app.services.positions_providers import (
    AdsbLol,
    OpenSky,
    ProviderDisabled,
    QuotaExhausted,
)

"""
Live positions for an airport: the licence gate, the shared cache,
single-flight and coverage evidence (CF-009 design r3 §4-§6).

No background collection (P6): a request fetches only when the shared cache
is empty, and concurrent requests for the same airport wait for that fetch.
"""

logger = logging.getLogger(__name__)

WAIT_POLL_S = 0.25


class Busy(Exception):
    """Another request is fetching this airport and didn't finish in time."""


_providers: dict[str, object] = {}


def get_provider():
    """The configured provider, after the licence gate (spec §6).

    Raises:
        ProviderDisabled: OpenSky without the educational-use flag, or with
            incomplete credentials.
    """
    name = settings.POSITIONS_PROVIDER
    if name == "opensky" and not settings.OPENSKY_EDUCATIONAL_USE:
        raise ProviderDisabled("educational_use_not_enabled")
    if name not in _providers:
        _providers[name] = (
            AdsbLol() if name == "adsblol" else OpenSky(cache.redis_client)
        )
    return _providers[name]


def keys(provider: str, code: str) -> tuple[str, str, str]:
    """Cache, lock and coverage keys; always the canonical airport code."""
    base = f"positions:v1:{provider}:{code}"
    return base, f"{base}:lock", f"positions:coverage:{provider}:{code}"


def get_positions(code: str, area: Area) -> tuple[FeedResult, bool, object]:
    """The latest feed result for an airport, fetching only on a cache miss.

    Returns:
        tuple: (FeedResult, coverage evidence seen in the last 24 h, provider).

    Raises:
        ProviderDisabled, QuotaExhausted, Busy, and the provider's typed errors
        (MetarTimeout, MetarUpstreamError, MetarRateLimited).
    """
    provider = get_provider()
    cache_key, lock_key, coverage_key = keys(provider.name, code)
    client = cache.redis_client
    try:
        cached = client.get(cache_key)
    except redis.RedisError as e:
        if provider.needs_budget:  # a hard quota: fail closed
            raise QuotaExhausted("budget_unavailable", None) from e
        logger.warning("Redis unavailable; fetching positions without cache: %s", e)
        return provider.fetch(area, deadline()), False, provider
    if cached is not None:
        return (
            FeedResult.from_dict(json.loads(cached)),
            has_evidence(client, coverage_key),
            provider,
        )

    lock = Lock(client, lock_key, settings.POSITIONS_LOCK_LEASE_S)
    try:
        acquired = lock.acquire()
    except redis.RedisError as e:
        if provider.needs_budget:
            raise QuotaExhausted("budget_unavailable", None) from e
        return provider.fetch(area, deadline()), False, provider
    if not acquired:
        return wait_for(client, cache_key), has_evidence(client, coverage_key), provider
    try:
        result = provider.fetch(area, deadline())
        store(client, cache_key, coverage_key, result)
    finally:
        try:
            lock.release()
        except redis.RedisError:
            pass  # the lease expires by itself
    return result, has_evidence(client, coverage_key), provider


def deadline() -> float:
    return time.monotonic() + settings.POSITIONS_DEADLINE_S


def store(client, cache_key: str, coverage_key: str, result: FeedResult) -> None:
    try:
        client.set(
            cache_key, json.dumps(result.to_dict()), ex=settings.POSITIONS_CACHE_TTL
        )
        if result.airborne:
            client.set(coverage_key, 1, ex=settings.POSITIONS_COVERAGE_TTL)
    except redis.RedisError as e:
        logger.warning("Couldn't cache positions: %s", e)


def has_evidence(client, coverage_key: str) -> bool:
    try:
        return bool(client.exists(coverage_key))
    except redis.RedisError:
        return False  # no evidence: never claim "no aircraft"


def wait_for(client, cache_key: str) -> FeedResult:
    """Wait for another request's fetch, up to the operation deadline."""
    end = time.monotonic() + settings.POSITIONS_DEADLINE_S
    while time.monotonic() < end:
        time.sleep(WAIT_POLL_S)
        try:
            cached = client.get(cache_key)
        except redis.RedisError:
            break
        if cached is not None:
            return FeedResult.from_dict(json.loads(cached))
    raise Busy()
