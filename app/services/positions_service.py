import json
import logging
import time
from datetime import datetime

import redis

from app.core.config import settings
from app.services import cache
from app.services.credit_budget import Lock
from app.services.metar import MetarRateLimited, MetarTimeout, MetarUpstreamError
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
        cached = read_cached(client, cache_key)
        lock = Lock(client, lock_key, settings.POSITIONS_LOCK_LEASE_S)
        acquired = cached is None and lock.acquire()
    except redis.RedisError as e:
        if provider.needs_budget:  # a hard quota: fail closed
            raise QuotaExhausted("budget_unavailable", None) from e
        logger.warning("Redis unavailable; fetching positions without cache: %s", e)
        return provider.fetch(area, deadline()), False, provider
    if cached is not None:
        return cached, has_evidence(client, coverage_key), provider
    if not acquired:
        return (
            wait_for(client, cache_key, lock_key),
            has_evidence(client, coverage_key),
            provider,
        )
    try:
        # Another request may have filled the cache between our read and lock.
        try:
            cached = read_cached(client, cache_key)
        except redis.RedisError:
            cached = None
        if cached is not None:
            return cached, has_evidence(client, coverage_key), provider
        result = provider.fetch(area, deadline())
        store(client, cache_key, coverage_key, result)  # before releasing the lock
    except redis.RedisError as e:
        # Redis failed mid-fetch (reserving credits): fail closed (spec §5).
        failure = QuotaExhausted("budget_unavailable", None)
        publish_failure(client, cache_key, failure, lock.token)
        raise failure from e
    except FAILURES as e:
        publish_failure(client, cache_key, e, lock.token)
        raise
    finally:
        try:
            lock.release()
        except redis.RedisError:
            pass  # the lease expires by itself
    return result, has_evidence(client, coverage_key), provider


FAILURES = (QuotaExhausted, MetarTimeout, MetarUpstreamError, MetarRateLimited)
FAILURE_TTL_MS = 5000


def read_cached(client, cache_key: str) -> FeedResult | None:
    """The cached result; a corrupt entry is treated as a miss."""
    raw = client.get(cache_key)
    if raw is None:
        return None
    try:
        return FeedResult.from_dict(json.loads(raw)).validate()
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        logger.warning(
            "Ignoring corrupt cached positions %s: %s", cache_key, type(e).__name__
        )
        return None


def publish_failure(client, cache_key: str, error: Exception, owner: str) -> None:
    """Tell this fetch's waiting requests why it failed, for a few seconds.

    The record names the lock owner, so waiters of a later fetch ignore it.
    """
    record = {
        "kind": type(error).__name__,
        "reason": getattr(error, "reason", ""),
        "owner": owner,
    }
    if isinstance(error, QuotaExhausted) and error.retry_at:
        record["retry_at"] = error.retry_at.isoformat()
    if isinstance(error, MetarRateLimited):
        record["retry_after_s"] = error.retry_after_s
    try:
        client.set(f"{cache_key}:failed", json.dumps(record), px=FAILURE_TTL_MS)
    except redis.RedisError:
        pass


def failure_from(record: dict) -> Exception:
    kind, reason = record.get("kind"), record.get("reason") or "provider_error"
    if kind == "QuotaExhausted":
        retry_at = record.get("retry_at")
        return QuotaExhausted(
            reason, datetime.fromisoformat(retry_at) if retry_at else None
        )
    if kind == "MetarRateLimited":
        return MetarRateLimited(float(record.get("retry_after_s") or 5))
    if kind == "MetarTimeout":
        return MetarTimeout(reason)
    return MetarUpstreamError(reason)


def deadline() -> float:
    return time.monotonic() + settings.POSITIONS_DEADLINE_S


def store(client, cache_key: str, coverage_key: str, result: FeedResult) -> None:
    try:
        client.set(
            cache_key, json.dumps(result.to_dict()), ex=settings.POSITIONS_CACHE_TTL
        )
        # Only a fresh feed is evidence of coverage (C6).
        lag = abs((result.fetched_at - result.observed_at).total_seconds())
        if result.airborne and lag <= settings.POSITIONS_MAX_AGE_S:
            client.set(coverage_key, 1, ex=settings.POSITIONS_COVERAGE_TTL)
    except redis.RedisError as e:
        logger.warning("Couldn't cache positions: %s", e)


def has_evidence(client, coverage_key: str) -> bool:
    try:
        return bool(client.exists(coverage_key))
    except redis.RedisError:
        return False  # no evidence: never claim "no aircraft"


def wait_for(client, cache_key: str, lock_key: str) -> FeedResult:
    """Wait for another request's fetch, up to the operation deadline.

    Re-raises that fetch's failure when it publishes one, and stops waiting as
    soon as its lock is gone without a result.
    """
    end = time.monotonic() + settings.POSITIONS_DEADLINE_S
    try:
        owner = client.get(lock_key)  # the fetch we are waiting for
    except redis.RedisError:
        raise Busy()
    while time.monotonic() < end:
        time.sleep(WAIT_POLL_S)
        try:
            cached = read_cached(client, cache_key)
            if cached is not None:
                return cached
            failed = client.get(f"{cache_key}:failed")
            record = json.loads(failed) if failed is not None else None
            if (
                record is not None
                and owner is not None
                and record.get("owner") == owner
            ):
                raise failure_from(record)
            if client.get(lock_key) != owner:
                break  # that fetch ended without a result for us
        except (redis.RedisError, ValueError):
            break
    raise Busy()
