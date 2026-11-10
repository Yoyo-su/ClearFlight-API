import logging
import math
import random
import threading
import time
from datetime import datetime, timedelta, timezone

import redis

from app.core.config import settings
from app.services.credit_budget import BudgetExhausted, DailyBudget, SlotBusy
from app.services.metar import (
    MetarRateLimited,
    MetarTimeout,
    MetarUpstreamError,
    RateLimiter,
)
from app.services.positions_http import MIN_ATTEMPT_S, Reply, get, post
from app.services.positions import (
    FEET_PER_METRE,
    FPM_PER_MPS,
    ID_PATTERN,
    KNOTS_PER_MPS,
    Area,
    Collector,
    FeedResult,
    clean_callsign,
    finite,
    whole,
)

"""
Live position providers behind one interface (CF-009 design r3 §2, §5, §6):

    provider.fetch(area, deadline) -> FeedResult

adsb.lol is keyless (ODbL); OpenSky is for development/educational use only
(P4) and spends daily credits, reserved before every call. Errors reuse the
weather adapter's typed errors, so the API maps them the same way (D-006).
"""

logger = logging.getLogger(__name__)

MAX_STATES_CALLS = 2  # per box, retries and 401 refreshes together
BACKOFF_S = 0.5

# OpenSky emitter categories (state vector index 17) as ADS-B categories.
OPENSKY_CATEGORIES = {
    2: "A1", 3: "A2", 4: "A3", 5: "A4", 6: "A5", 7: "A6", 8: "A7",
    9: "B1", 10: "B2", 11: "B3", 12: "B4", 14: "B6", 15: "B7",
    16: "C1", 17: "C2", 18: "C3", 19: "C4", 20: "C5",
}  # fmt: skip


class QuotaExhausted(Exception):
    """A provider budget is used up or can't be checked (fail closed)."""

    def __init__(self, reason: str, retry_at: datetime | None):
        self.reason = reason  # "daily_budget" | "budget_unavailable"
        self.retry_at = retry_at
        super().__init__(reason)


class ProviderDisabled(Exception):
    """The licence gate or configuration doesn't allow this provider."""


def remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def utc(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, timezone.utc)


def json_body(response: Reply):
    try:
        return response.json()
    except ValueError:
        raise MetarUpstreamError("invalid_json")


def retryable(error: Exception) -> bool:
    return isinstance(error, MetarTimeout) or (
        isinstance(error, MetarUpstreamError)
        and (error.reason == "connection_error" or error.reason.startswith("http_5"))
    )


class AdsbLol:
    name = "adsblol"
    display = "adsb.lol (ODbL 1.0)"
    attribution_url = "https://adsb.lol"
    access = "keyless"
    privacy_filter = "applied"
    needs_budget = False
    URL = "https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{radius}"

    def __init__(self):
        self.limiter = RateLimiter(settings.ADSBLOL_RATE_LIMIT_PER_MINUTE)

    def fetch(self, area: Area, deadline: float) -> FeedResult:
        url = self.URL.format(
            lat=area.latitude,
            lon=area.longitude,
            radius=min(250, math.ceil(area.radius_nm)),
        )
        error = None
        for attempt in range(2):
            try:
                self.limiter.acquire()
            except MetarRateLimited as limited:
                raise limited from error
            try:
                response = get(url, deadline)
                if response.status_code == 429:
                    raise MetarUpstreamError("http_429")
                if response.status_code != 200:
                    raise MetarUpstreamError(f"http_{response.status_code}")
                return self.parse(json_body(response), area, utc(time.time()))
            except (MetarTimeout, MetarUpstreamError) as e:
                error = e
                if (
                    attempt == 1
                    or not retryable(e)
                    or remaining(deadline) < MIN_ATTEMPT_S + BACKOFF_S
                ):
                    raise
                time.sleep(BACKOFF_S + random.uniform(0, 0.25))
        raise error  # pragma: no cover

    @staticmethod
    def parse(body, area: Area, fetched_at: datetime) -> FeedResult:
        if not isinstance(body, dict) or not isinstance(body.get("ac"), list):
            raise MetarUpstreamError("invalid_response", "no aircraft list")
        now_ms = finite(body.get("now"), 0, 4102444800000)
        if now_ms is None:
            raise MetarUpstreamError("invalid_response", "no data time")
        observed_at = utc(now_ms / 1000)
        collector = Collector(area, settings.POSITIONS_MAX_AGE_S, observed_at)
        for ac in body["ac"]:
            if not isinstance(ac, dict):
                collector.add(None)
                continue
            flags = ac.get("dbFlags", 0)
            if not isinstance(flags, int) or isinstance(flags, bool):
                flags = 12  # unreadable privacy flags: withhold (fail closed)
            collector.add(
                AdsbLol.row(ac, observed_at),
                withheld=bool(flags & 12),  # PIA (4) or LADD (8)
                type_code=ac.get("t") if isinstance(ac.get("t"), str) else None,
            )
        return collector.result(AdsbLol.name, AdsbLol.access, fetched_at)

    @staticmethod
    def row(ac: dict, observed_at: datetime) -> dict | None:
        ident = ac.get("hex")
        lat = finite(ac.get("lat"), -90, 90)
        lon = finite(ac.get("lon"), -180, 180)
        seen = finite(ac.get("seen_pos"), 0, 86400)
        if not isinstance(ident, str) or not ID_PATTERN.fullmatch(ident.lower()):
            return None
        if lat is None or lon is None or seen is None:
            return None
        alt = ac.get("alt_baro")
        on_ground = alt == "ground"
        altitude = None
        if not on_ground:
            altitude = finite(alt, -2000, 60000)
            if altitude is None:
                altitude = finite(ac.get("alt_geom"), -2000, 60000)
        rate = finite(ac.get("baro_rate"), -20000, 20000)
        if rate is None:
            rate = finite(ac.get("geom_rate"), -20000, 20000)
        category = ac.get("category") if isinstance(ac.get("category"), str) else None
        return {
            "id": ident.lower(),
            "callsign": clean_callsign(ac.get("flight")),
            "latitude": lat,
            "longitude": lon,
            "altitude_ft": whole(altitude),
            "on_ground": on_ground,
            "ground_speed_kt": whole(finite(ac.get("gs"), 0, 1000)),
            "track_deg": whole(finite(ac.get("track"), 0, 360)),
            "vertical_rate_fpm": whole(rate),
            "category": category,
            "position_at": observed_at - timedelta(seconds=seen),
        }


class OpenSky:
    name = "opensky"
    display = "OpenSky Network (educational use)"
    attribution_url = "https://opensky-network.org"
    privacy_filter = "unavailable"
    needs_budget = True
    URL = "https://opensky-network.org/api/states/all"
    ACCOUNT_LIMIT = 4000
    ANONYMOUS_LIMIT = 400

    def __init__(self, redis_client, clock=time.time):
        client_id = settings.OPENSKY_CLIENT_ID
        secret = settings.OPENSKY_CLIENT_SECRET
        if (client_id is None) != (secret is None):
            raise ProviderDisabled("credentials_incomplete")
        self.credentials = (
            None
            if client_id is None
            else (client_id.get_secret_value(), secret.get_secret_value())
        )
        self.access = "anonymous" if self.credentials is None else "account"
        self.limit = (
            self.ANONYMOUS_LIMIT if self.credentials is None else self.ACCOUNT_LIMIT
        )
        budget = settings.OPENSKY_DAILY_CREDIT_BUDGET
        if budget is None:
            budget = int(self.limit * 0.9)
        elif not 1 <= budget <= self.limit:
            raise ProviderDisabled("invalid_budget")
        self.budget = DailyBudget(redis_client, "opensky", budget, clock)
        self.token: tuple[str, float] | None = None  # (token, monotonic expiry)
        self.token_lock = threading.Lock()

    # -- OAuth2 client credentials (spec §6) --------------------------------
    def bearer(self, deadline: float, refresh: bool = False) -> dict:
        if self.credentials is None:
            return {}
        if not self.token_lock.acquire(
            timeout=max(0.0, remaining(deadline) - MIN_ATTEMPT_S)
        ):
            raise MetarTimeout("deadline")
        try:
            if refresh:
                self.token = None
            if self.token is None or time.monotonic() >= self.token[1]:
                self.token = self.request_token(deadline)
            return {"Authorization": f"Bearer {self.token[0]}"}
        finally:
            self.token_lock.release()

    def request_token(self, deadline: float) -> tuple[str, float]:
        client_id, secret = self.credentials
        try:
            response = post(
                settings.OPENSKY_TOKEN_URL,
                deadline,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": secret,
                },
            )
            body = response.json() if response.status_code == 200 else None
        except MetarTimeout:
            raise MetarTimeout("token_timeout")  # a slow server isn't bad credentials
        except (MetarUpstreamError, ValueError):
            body = None
        token = body.get("access_token") if isinstance(body, dict) else None
        expires = (
            finite(body.get("expires_in"), 61, 86400)
            if isinstance(body, dict)
            else None
        )
        if not isinstance(token, str) or not token or expires is None:
            # Never include the response, which could echo credentials.
            raise MetarUpstreamError("provider_auth_failed", "token request failed")
        return token, time.monotonic() + expires - 60

    # -- Budget --------------------------------------------------------------
    def reserve(self, deadline: float) -> None:
        while True:
            try:
                self.budget.reserve(1)
                return
            except SlotBusy:
                wait = 1.0 - (time.time() % 1.0) + 0.01
                if remaining(deadline) < MIN_ATTEMPT_S + wait:
                    raise MetarTimeout("deadline")
                time.sleep(wait)
            except BudgetExhausted as e:
                raise QuotaExhausted(e.reason, e.retry_at)

    def reconcile(self, response: Reply) -> None:
        header = response.headers.get("x-rate-limit-remaining", "")
        if header.isdigit():
            try:
                self.budget.raise_to(max(0, self.limit - int(header)))
            except redis.RedisError as e:  # the reservation already counted
                logger.warning(
                    "Couldn't reconcile OpenSky credits: %s", type(e).__name__
                )

    def exhausted(self, response: Reply) -> QuotaExhausted:
        try:
            self.budget.raise_to(self.budget.budget)
        except redis.RedisError as e:
            logger.warning("Couldn't record OpenSky exhaustion: %s", type(e).__name__)
        retry = response.headers.get("x-rate-limit-retry-after-seconds", "")
        now = datetime.now(timezone.utc)
        if retry.isdigit():
            retry_at = now + timedelta(seconds=int(retry))
        else:
            retry_at = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        return QuotaExhausted("daily_budget", retry_at)

    # -- Fetch -----------------------------------------------------------------
    def fetch(self, area: Area, deadline: float) -> FeedResult:
        fetched_at = utc(time.time())
        operation = {"refreshed": False}  # one token refresh per operation
        bodies = [self.query(box, deadline, operation) for box in area.boxes()]
        times = [finite(b.get("time"), 0, 4102444800) for b in bodies]
        if any(t is None for t in times):
            raise MetarUpstreamError("invalid_response", "no data time")
        observed_at = utc(min(times))
        collector = Collector(area, settings.POSITIONS_MAX_AGE_S, observed_at)
        seen = set()
        for body in bodies:
            for state in body.get("states") or []:
                row = self.row(state)
                if row is not None:
                    if row["id"] in seen:
                        continue
                    seen.add(row["id"])
                collector.add(row)
        return collector.result(self.name, self.access, fetched_at)

    def query(self, box, deadline: float, operation: dict) -> dict:
        lamin, lomin, lamax, lomax = box
        params = {
            "lamin": round(lamin, 4), "lomin": round(lomin, 4),
            "lamax": round(lamax, 4), "lomax": round(lomax, 4), "extended": 1,
        }  # fmt: skip
        calls = 0
        while True:
            # The token first, so the per-second slot is used only by the call
            # it was reserved for (design r3 §5).
            headers = self.bearer(deadline)
            self.reserve(deadline)  # every call, retries included
            calls += 1
            last = calls >= MAX_STATES_CALLS  # one shared limit (design r3 §6)
            try:
                response = get(self.URL, deadline, params=params, headers=headers)
            except (MetarTimeout, MetarUpstreamError) as e:
                if (
                    last
                    or not retryable(e)
                    or remaining(deadline) < MIN_ATTEMPT_S + BACKOFF_S
                ):
                    raise
                time.sleep(BACKOFF_S + random.uniform(0, 0.25))
                continue
            self.reconcile(response)
            status = response.status_code
            if status == 401:
                if self.credentials is None or operation["refreshed"] or last:
                    raise MetarUpstreamError(
                        "provider_auth_failed", "states call rejected"
                    )
                operation["refreshed"] = True  # one refresh, then one more call
                self.bearer(deadline, refresh=True)
                continue
            if status == 429:
                raise self.exhausted(response)
            if (
                status >= 500
                and not last
                and remaining(deadline) >= MIN_ATTEMPT_S + BACKOFF_S
            ):
                time.sleep(BACKOFF_S + random.uniform(0, 0.25))
                continue
            if status != 200:
                raise MetarUpstreamError(f"http_{status}")
            body = json_body(response)
            # "states" must be present: null means empty, absent is invalid.
            if not isinstance(body, dict) or "states" not in body:
                raise MetarUpstreamError("invalid_response", "no states field")
            if not isinstance(body["states"], (list, type(None))):
                raise MetarUpstreamError("invalid_response", "bad states")
            return body

    @staticmethod
    def row(state) -> dict | None:
        if not isinstance(state, list) or len(state) < 17:
            return None
        ident = state[0]
        when = finite(state[3], 0, 4102444800)
        lon = finite(state[5], -180, 180)
        lat = finite(state[6], -90, 90)
        if not isinstance(ident, str) or not ID_PATTERN.fullmatch(ident.lower()):
            return None
        if when is None or lat is None or lon is None or not isinstance(state[8], bool):
            return None
        on_ground = state[8]
        altitude = None
        if not on_ground:
            metres = finite(state[7], -700, 20000)
            if metres is None:
                metres = finite(state[13], -700, 20000)
            altitude = None if metres is None else metres * FEET_PER_METRE
        speed = finite(state[9], 0, 600)
        rate = finite(state[11], -100, 100)
        category = state[17] if len(state) > 17 else None
        return {
            "id": ident.lower(),
            "callsign": clean_callsign(state[1]),
            "latitude": lat,
            "longitude": lon,
            "altitude_ft": whole(altitude),
            "on_ground": on_ground,
            "ground_speed_kt": whole(None if speed is None else speed * KNOTS_PER_MPS),
            "track_deg": whole(finite(state[10], 0, 360)),
            "vertical_rate_fpm": whole(None if rate is None else rate * FPM_PER_MPS),
            "category": (
                OPENSKY_CATEGORIES.get(category) if isinstance(category, int) else None
            ),
            "position_at": utc(when),
        }
