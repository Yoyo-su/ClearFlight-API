import itertools
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fakeredis
import pytest
import redis
import requests
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.main import app
from app.services import cache, positions_service
from app.services.credit_budget import BudgetExhausted, DailyBudget, Lock, SlotBusy
from app.services.metar import MetarTimeout, MetarUpstreamError
from app.services.positions import (
    Area,
    Collector,
    FeedResult,
    Target,
    assess,
    clean_callsign,
    classify,
    distance_nm,
    visible,
)
from app.services.positions_providers import (
    AdsbLol,
    OpenSky,
    ProviderDisabled,
    QuotaExhausted,
)

"""
Test suite for live positions (CF-009 design r3): parsers, area maths,
classification, expiry and states, the credit budget and lock, the service
(cache, single-flight, gate, fail closed) and GET /v1/airports/{code}/aircraft.
"""

FIXTURES = Path(__file__).parent / "testfiles"
PILOTS = {
    "egll": (51.4706, -0.4619),
    "kjfk": (40.6398, -73.7789),
    "rjbb": (34.4273, 135.244),
}
UTC = timezone.utc


def adsblol(name):
    return json.loads((FIXTURES / "adsblol" / f"point_{name}.json").read_text())


def opensky(name):
    return json.loads((FIXTURES / "opensky" / f"states_{name}.json").read_text())


def area(name):
    lat, lon = PILOTS[name]
    return Area(lat, lon, 25)


def parse_opensky(name, max_age=60):
    body = opensky(name)
    collector = Collector(
        area(name), max_age, datetime.fromtimestamp(body["time"], UTC)
    )
    for state in body["states"] or []:
        collector.add(OpenSky.row(state))
    return collector.result("opensky", "anonymous", datetime.now(UTC))


def target(**changes):
    base = dict(
        id="abc123",
        callsign="BAW1",
        latitude=51.5,
        longitude=-0.4,
        altitude_ft=3000,
        on_ground=False,
        ground_speed_kt=180,
        track_deg=270,
        vertical_rate_fpm=-700,
        category="A3",
        kind="aircraft",
        position_at=datetime(2026, 11, 10, 0, 50, tzinfo=UTC),
        distance_nm=2.0,
    )
    return Target(**{**base, **changes})


def feed(targets=(), **changes):
    base = dict(
        provider="adsblol",
        access="keyless",
        observed_at=datetime(2026, 11, 10, 0, 50, 5, tzinfo=UTC),
        fetched_at=datetime(2026, 11, 10, 0, 50, 5, tzinfo=UTC),
        targets=list(targets),
    )
    return FeedResult(**{**base, **changes})


@pytest.fixture
def fake_redis():
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    with mock.patch.object(cache, "redis_client", client):
        yield client


@pytest.fixture(autouse=True)
def fresh_providers():
    positions_service._providers.clear()
    yield
    positions_service._providers.clear()


@pytest.mark.describe("Provider parsers on recorded responses")
class TestParsers:
    @pytest.mark.it(
        "adsb.lol: shows aircraft, excludes surface vehicles and towers, withholds LADD/PIA"
    )
    @pytest.mark.parametrize(
        "name, shown, withheld, excluded, airborne",
        [("egll", 4, 0, 8, 1), ("kjfk", 99, 7, 0, 39), ("rjbb", 23, 0, 0, 12)],
    )
    def test_adsblol(self, name, shown, withheld, excluded, airborne):
        result = AdsbLol.parse(adsblol(name), area(name), datetime.now(UTC))
        assert (
            len(result.targets),
            result.withheld,
            result.excluded,
            result.dropped,
        ) == (
            shown,
            withheld,
            excluded,
            0,
        )
        assert result.airborne == airborne
        assert [t.distance_nm for t in result.targets] == sorted(
            t.distance_nm for t in result.targets
        )
        ids = {t.id for t in result.targets}
        ladd = {
            ac["hex"] for ac in adsblol(name)["ac"] if (ac.get("dbFlags") or 0) & 12
        }
        assert not ids & ladd

    @pytest.mark.it("adsb.lol: converts fields and cleans placeholder callsigns")
    def test_adsblol_fields(self):
        result = AdsbLol.parse(adsblol("egll"), area("egll"), datetime.now(UTC))
        ryanair = next(t for t in result.targets if t.callsign == "RYR4AU")
        assert (
            ryanair.altitude_ft,
            ryanair.ground_speed_kt,
            ryanair.category,
            ryanair.kind,
        ) == (
            36900,
            464,
            "A3",
            "aircraft",
        )
        parked = [t for t in result.targets if t.on_ground]
        assert parked and all(t.altitude_ft is None for t in parked)
        assert all(t.callsign is None for t in parked)  # @@@@@@@@
        assert result.observed_at == datetime.fromtimestamp(1794271833.5, UTC)

    @pytest.mark.it(
        "OpenSky: converts units, drops positions over 60 s old, can't classify"
    )
    @pytest.mark.parametrize(
        "name, shown, dropped", [("egll", 5, 1), ("kjfk", 97, 16), ("rjbb", 19, 3)]
    )
    def test_opensky(self, name, shown, dropped):
        result = parse_opensky(name)
        assert (
            len(result.targets),
            result.dropped,
            result.excluded,
            result.withheld,
        ) == (
            shown,
            dropped,
            0,
            0,
        )
        delta = opensky("kjfk")["states"][0]
        row = OpenSky.row(delta)
        assert row["altitude_ft"] == round(6035.04 * 3.28084)
        assert row["ground_speed_kt"] == round(183.61 * 1.943844)
        assert row["vertical_rate_fpm"] == round(-8.13 * 196.8504)
        assert row["callsign"] == "DAL671"

    @pytest.mark.it("OpenSky: maps emitter categories, surface ones are excluded")
    def test_opensky_categories(self):
        state = list(opensky("kjfk")["states"][0])
        assert OpenSky.row(state[:17] + [4])["category"] == "A3"
        assert OpenSky.row(state[:17] + [0])["category"] is None
        assert classify(OpenSky.row(state[:17] + [17])["category"]) == "surface"

    @pytest.mark.it("drops rows with invalid identity, position or time")
    @pytest.mark.parametrize(
        "change",
        [
            {"hex": "zzz"},
            {"lat": None},
            {"lon": 200},
            {"seen_pos": None},
            {"lat": True},
        ],
    )
    def test_invalid_rows(self, change):
        ac = dict(adsblol("rjbb")["ac"][0], **change)
        assert AdsbLol.row(ac, datetime.now(UTC)) is None
        body = {"ac": [ac], "now": 1794271840001}
        result = AdsbLol.parse(body, area("rjbb"), datetime.now(UTC))
        assert (result.targets, result.dropped) == ([], 1)

    @pytest.mark.it("rejects a malformed provider body")
    @pytest.mark.parametrize(
        "body", [[], {"ac": None, "now": 1}, {"ac": []}, {"ac": [], "now": "x"}]
    )
    def test_bad_body(self, body):
        with pytest.raises(MetarUpstreamError):
            AdsbLol.parse(body, area("rjbb"), datetime.now(UTC))

    @pytest.mark.it("cleans callsigns")
    @pytest.mark.parametrize(
        "raw, clean",
        [
            ("BAW123  ", "BAW123"),
            ("@@@@@@@@", None),
            ("", None),
            (None, None),
            ("LEADER 7", None),
        ],
    )
    def test_callsign(self, raw, clean):
        assert clean_callsign(raw) == clean


@pytest.mark.describe("Area maths")
class TestArea:
    @pytest.mark.it("measures great-circle distance in nautical miles")
    def test_distance(self):
        assert distance_nm(51.4706, -0.4619, 51.1481, -0.1903) == pytest.approx(
            21.6, abs=0.3
        )
        assert distance_nm(0, 0, 1, 0) == pytest.approx(60.04, abs=0.05)

    @pytest.mark.it("covers the circle with one box, under 25 sq deg")
    def test_box(self):
        ((lamin, lomin, lamax, lomax),) = Area(51.4706, -0.4619, 25).boxes()
        assert lamax - lamin == pytest.approx(25 / 30)
        assert (lamax - lamin) * (lomax - lomin) < 25

    @pytest.mark.it("splits a box at the antimeridian")
    @pytest.mark.parametrize("lon", [179.9, -179.9])
    def test_antimeridian(self, lon):
        boxes = Area(51.47, lon, 25).boxes()
        assert len(boxes) == 2
        assert all(-180 <= b[1] < b[3] <= 180 for b in boxes)

    @pytest.mark.it("handles the poles without dividing by zero")
    def test_pole(self):
        boxes = Area(89.9, 10, 25).boxes()
        assert boxes == [(89.4833333333333, -180.0, 90.0, 180.0)] or len(boxes) == 1

    @pytest.mark.it("ignores rows in the box but outside the circle")
    def test_box_corner(self):
        a = Area(51.4706, -0.4619, 25)
        ((lamin, lomin, _, _),) = a.boxes()
        collector = Collector(a, 60, datetime(2026, 11, 10, tzinfo=UTC))
        row = dict(
            id="abc123", callsign=None, latitude=lamin + 0.01, longitude=lomin + 0.01, altitude_ft=1000,
            on_ground=False, ground_speed_kt=None, track_deg=None, vertical_rate_fpm=None,
            category=None, position_at=datetime(2026, 11, 10, tzinfo=UTC),
        )  # fmt: skip
        collector.add(row)
        result = collector.result(
            "opensky", "anonymous", datetime(2026, 11, 10, tzinfo=UTC)
        )
        assert (result.targets, result.dropped, result.airborne) == ([], 0, 0)


@pytest.mark.describe("Expiry and states (spec §3-§4)")
class TestStates:
    NOW = datetime(2026, 11, 10, 0, 50, 30, tzinfo=UTC)

    @pytest.mark.it("drops each position at its own expiry, at every read")
    def test_expiry(self):
        old = target(id="aaaaaa", position_at=self.NOW - timedelta(seconds=59))
        new = target(id="bbbbbb", position_at=self.NOW - timedelta(seconds=5))
        result = feed([old, new])
        assert [t.id for t in visible(result, self.NOW, 60).targets] == [
            "aaaaaa",
            "bbbbbb",
        ]
        later = visible(result, self.NOW + timedelta(seconds=1), 60)
        assert ([t.id for t in later.targets], later.dropped) == (["bbbbbb"], 1)

    @pytest.mark.it("reports available, including when only withheld aircraft remain")
    def test_available(self):
        assert assess(feed([target()]), self.NOW, 60, False) == ("available", None)
        assert assess(feed(withheld=2), self.NOW, 60, False) == ("available", None)

    @pytest.mark.it("never turns unusable or expired data into no aircraft")
    def test_unusable(self):
        result = feed([target(position_at=self.NOW - timedelta(seconds=61))])
        shown = visible(result, self.NOW, 60)
        assert assess(shown, self.NOW, 60, True) == (
            "coverage_unknown",
            "unusable_data",
        )
        assert assess(feed(dropped=3), self.NOW, 60, True) == (
            "coverage_unknown",
            "unusable_data",
        )

    @pytest.mark.it("needs a fresh feed and coverage evidence for no aircraft (C6)")
    def test_no_aircraft(self):
        assert assess(feed(), self.NOW, 60, True) == ("no_aircraft", None)
        assert assess(feed(), self.NOW, 60, False) == (
            "coverage_unknown",
            "no_coverage_evidence",
        )
        stale = feed(observed_at=self.NOW - timedelta(seconds=61))
        assert assess(stale, self.NOW, 60, True) == ("coverage_unknown", "stale_feed")

    @pytest.mark.it("counts surface vehicles as excluded, not as traffic or coverage")
    def test_surface_only(self):
        result = AdsbLol.parse(
            {
                "ac": [a for a in adsblol("egll")["ac"] if a.get("category") == "C2"],
                "now": 1794271833500,
            },
            area("egll"),
            datetime.now(UTC),
        )
        assert (result.targets, result.excluded, result.airborne) == ([], 6, 0)
        now = datetime.fromtimestamp(1794271840, UTC)
        assert assess(result, now, 60, True) == ("no_aircraft", None)
        assert assess(result, now, 60, False)[0] == "coverage_unknown"

    @pytest.mark.it("round-trips a feed result through the cache format")
    def test_round_trip(self):
        result = feed([target()], withheld=1, excluded=2, dropped=3, airborne=1)
        assert FeedResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result


@pytest.mark.describe("Credit budget and lock (Lua, atomic)")
class TestBudget:
    def budget(self, client, budget=3, start=1794268800):
        clock = itertools.count(start)  # a new second per call: no slot clash
        return DailyBudget(client, "opensky", budget, clock=lambda: next(clock))

    @pytest.mark.it(
        "reserves until the daily budget is used, then is exhausted until midnight"
    )
    def test_reserve(self, fake_redis):
        b = self.budget(fake_redis)
        assert [b.reserve(), b.reserve(), b.reserve()] == [1, 2, 3]
        with pytest.raises(BudgetExhausted) as e:
            b.reserve()
        assert e.value.retry_at == datetime(2026, 11, 11, tzinfo=UTC)

    @pytest.mark.it("allows one call per second (the per-second slot)")
    def test_slot(self, fake_redis):
        b = DailyBudget(fake_redis, "opensky", 10, clock=lambda: 1794268800.2)
        b.reserve()
        with pytest.raises(SlotBusy):
            b.reserve()

    @pytest.mark.it(
        "treats a counter lost mid-day as exhausted, but starts fresh on a new day"
    )
    def test_counter_loss(self, fake_redis):
        b = DailyBudget(fake_redis, "opensky", 10, clock=lambda: 1794268800 + 3600)
        b.reserve()
        fake_redis.delete("budget:opensky:2026-11-10")
        with pytest.raises(BudgetExhausted):
            DailyBudget(
                fake_redis, "opensky", 10, clock=lambda: 1794268800 + 3601
            ).reserve()
        assert (
            DailyBudget(
                fake_redis, "opensky", 10, clock=lambda: 1794268800 + 86400
            ).reserve()
            == 1
        )

    @pytest.mark.it(
        "reconciles from the provider raise-only, never erasing reservations"
    )
    def test_raise_only(self, fake_redis):
        b = self.budget(fake_redis, budget=100)
        for _ in range(5):
            b.reserve()
        b.raise_to(3)  # a late, lower header
        assert b.used() == 5
        b.raise_to(40)
        assert b.used() == 40

    @pytest.mark.it("never exceeds the budget under concurrency")
    def test_concurrency(self, fake_redis):
        clock = itertools.count(1794268800)
        lock = threading.Lock()

        def tick():
            with lock:
                return next(clock)

        b = DailyBudget(fake_redis, "opensky", 7, clock=tick)
        results = []

        def worker():
            try:
                results.append(b.reserve())
            except BudgetExhausted:
                results.append("exhausted")

        threads = [threading.Thread(target=worker) for _ in range(20)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert sorted(r for r in results if r != "exhausted") == list(range(1, 8))
        assert results.count("exhausted") == 13

    @pytest.mark.it("raises Redis errors instead of treating them as a miss")
    def test_redis_error(self):
        broken = mock.Mock()
        broken.eval.side_effect = redis.ConnectionError("down")
        with pytest.raises(redis.RedisError):
            DailyBudget(broken, "opensky", 10).reserve()

    @pytest.mark.it("releases a lock only for its owner")
    def test_lock(self, fake_redis):
        first = Lock(fake_redis, "positions:lock", 30)
        second = Lock(fake_redis, "positions:lock", 30)
        assert first.acquire() and not second.acquire()
        second.release()
        assert fake_redis.get("positions:lock") == first.token
        first.release()
        assert fake_redis.get("positions:lock") is None
        assert 0 < fake_redis.pttl("positions:lock") or second.acquire()


class FakeResponse:
    """A streamed requests response; an Exception body gives invalid JSON."""

    def __init__(self, status=200, body=None, headers=None, chunks=None):
        self.status_code = status
        self.headers = headers or {}
        if chunks is not None:
            self.chunks = chunks
        elif isinstance(body, Exception):
            self.chunks = [b"not json"]
        else:
            self.chunks = [json.dumps(body).encode()] if body is not None else []
        self.closed = False

        self.raw = self  # requests' raw urllib3 response

    def read1(self, amt=None, decode_content=None):
        if not hasattr(self, "_iter"):
            self._iter = iter(self.chunks)
        return next(self._iter, b"")

    def close(self):
        self.closed = True
        self.__dict__.pop("_iter", None)  # the same fake may answer again


@pytest.fixture
def opensky_settings():
    with mock.patch.multiple(
        settings,
        POSITIONS_PROVIDER="opensky",
        OPENSKY_EDUCATIONAL_USE=True,
        OPENSKY_CLIENT_ID=SecretStr("client-id-123"),
        OPENSKY_CLIENT_SECRET=SecretStr("very-secret-value"),
        OPENSKY_DAILY_CREDIT_BUDGET=None,
    ):
        yield


def states_body(name="rjbb"):
    return opensky(name)


@pytest.mark.describe("OpenSky adapter: credits, OAuth and retries")
class TestOpenSky:
    def adapter(self, client):
        clock = itertools.count(1794268800)
        return OpenSky(client, clock=lambda: next(clock))

    def deadline(self):
        return time.monotonic() + 20

    @pytest.mark.it("reserves a credit before each call and reconciles from the header")
    def test_reserve_and_reconcile(self, fake_redis, opensky_settings):
        adapter = self.adapter(fake_redis)
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        states = FakeResponse(
            body=states_body(), headers={"x-rate-limit-remaining": "3990"}
        )
        with mock.patch("requests.post", return_value=token) as post, mock.patch(
            "requests.get", return_value=states
        ) as get:
            result = adapter.fetch(area("rjbb"), self.deadline())
            adapter.fetch(area("rjbb"), self.deadline())
        assert post.call_count == 1  # the token is cached
        assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
        # The header raised the counter to 10 (4000 - 3990) after the first
        # call; the second call reserved one more. Raise-only never lowers it.
        assert adapter.budget.used() == 11
        assert (adapter.access, adapter.budget.budget) == ("account", 3600)
        assert len(result.targets) == 19

    @pytest.mark.it("charges a retry after a 5xx and gives up after one retry")
    def test_retry_charged(self, fake_redis, opensky_settings):
        adapter = self.adapter(fake_redis)
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        with mock.patch("requests.post", return_value=token), mock.patch(
            "requests.get", return_value=FakeResponse(503)
        ) as get, mock.patch("time.sleep"):
            with pytest.raises(MetarUpstreamError, match="http_503"):
                adapter.fetch(area("rjbb"), self.deadline())
        assert get.call_count == 2 and adapter.budget.used() == 2

    @pytest.mark.it("turns a 429 into quota_exhausted and stops calling for the day")
    def test_429(self, fake_redis, opensky_settings):
        adapter = self.adapter(fake_redis)
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        limited = FakeResponse(429, headers={"x-rate-limit-retry-after-seconds": "120"})
        with mock.patch("requests.post", return_value=token), mock.patch(
            "requests.get", return_value=limited
        ) as get:
            with pytest.raises(QuotaExhausted) as e:
                adapter.fetch(area("rjbb"), self.deadline())
            assert 110 < (e.value.retry_at - datetime.now(UTC)).total_seconds() <= 120
            with pytest.raises(QuotaExhausted):
                adapter.fetch(area("rjbb"), self.deadline())
        assert get.call_count == 1

    @pytest.mark.it(
        "refreshes the token once on a 401, then fails as provider_auth_failed"
    )
    def test_401(self, fake_redis, opensky_settings):
        adapter = self.adapter(fake_redis)
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        with mock.patch("requests.post", return_value=token) as post, mock.patch(
            "requests.get", return_value=FakeResponse(401)
        ) as get:
            with pytest.raises(MetarUpstreamError) as e:
                adapter.fetch(area("rjbb"), self.deadline())
        assert e.value.reason == "provider_auth_failed"
        assert (post.call_count, get.call_count, adapter.budget.used()) == (2, 2, 2)

    @pytest.mark.it(
        "makes no states call when the token request fails, and leaks no secret"
    )
    @pytest.mark.parametrize(
        "token",
        [
            FakeResponse(
                401,
                body={"error": "invalid_client", "client_secret": "very-secret-value"},
            ),
            FakeResponse(200, body={"token_type": "bearer"}),
            FakeResponse(200, body=ValueError("not json")),
            requests.ConnectionError("down"),
        ],
    )
    def test_token_failure(self, fake_redis, opensky_settings, token, caplog):
        adapter = self.adapter(fake_redis)
        post = (
            mock.Mock(side_effect=token)
            if isinstance(token, Exception)
            else mock.Mock(return_value=token)
        )
        with mock.patch("requests.post", post), mock.patch("requests.get") as get:
            with caplog.at_level(logging.DEBUG), pytest.raises(MetarUpstreamError) as e:
                adapter.fetch(area("rjbb"), self.deadline())
        assert e.value.reason == "provider_auth_failed"
        assert not get.called
        assert "very-secret-value" not in str(e.value) + caplog.text
        assert "client-id-123" not in str(e.value) + caplog.text

    @pytest.mark.it(
        "runs anonymously with the smaller budget when no credentials are set"
    )
    def test_anonymous(self, fake_redis):
        with mock.patch.multiple(
            settings, OPENSKY_CLIENT_ID=None, OPENSKY_CLIENT_SECRET=None
        ):
            adapter = OpenSky(fake_redis)
        assert (
            adapter.access,
            adapter.budget.budget,
            adapter.bearer(time.monotonic() + 20),
        ) == (
            "anonymous",
            360,
            {},
        )

    @pytest.mark.it("refuses incomplete credentials")
    def test_partial_credentials(self, fake_redis):
        with mock.patch.multiple(
            settings, OPENSKY_CLIENT_ID=SecretStr("x"), OPENSKY_CLIENT_SECRET=None
        ):
            with pytest.raises(ProviderDisabled):
                OpenSky(fake_redis)

    @pytest.mark.it("queries both halves of an antimeridian box, each charged")
    def test_antimeridian(self, fake_redis, opensky_settings):
        adapter = self.adapter(fake_redis)
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        empty = FakeResponse(body={"time": 1794271833, "states": None})
        with mock.patch("requests.post", return_value=token), mock.patch(
            "requests.get", return_value=empty
        ) as get:
            adapter.fetch(Area(51.0, 179.9, 25), self.deadline())
        assert get.call_count == 2 and adapter.budget.used() == 2


@pytest.fixture
def adsblol_settings():
    with mock.patch.multiple(settings, POSITIONS_PROVIDER="adsblol"):
        yield


@pytest.mark.describe("Positions service: gate, cache, single-flight, fail closed")
class TestService:
    @pytest.mark.it("blocks OpenSky without the educational-use flag (licence gate)")
    def test_gate(self, fake_redis):
        with mock.patch.multiple(
            settings, POSITIONS_PROVIDER="opensky", OPENSKY_EDUCATIONAL_USE=False
        ):
            with pytest.raises(ProviderDisabled):
                positions_service.get_provider()

    @pytest.mark.it("fetches once, caches for 30 s and records coverage evidence")
    def test_cache(self, fake_redis, adsblol_settings):
        recorded = datetime.fromtimestamp(1794271841, UTC)  # the fixture's fetch time
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), recorded)
        provider = positions_service.get_provider()
        with mock.patch.object(provider, "fetch", return_value=result) as fetch:
            first = positions_service.get_positions("RJBB", area("rjbb"))
            second = positions_service.get_positions("RJBB", area("rjbb"))
        assert fetch.call_count == 1
        assert first[0] == second[0] == result and second[1] is True
        assert 0 < fake_redis.ttl("positions:v1:adsblol:RJBB") <= 30
        assert fake_redis.exists("positions:coverage:adsblol:RJBB")

    @pytest.mark.it(
        "keys by canonical airport code, so IATA-only airports don't collide"
    )
    def test_keys(self):
        assert (
            positions_service.keys("adsblol", "AAI")[2]
            != positions_service.keys("adsblol", "BBI")[2]
        )

    @pytest.mark.it("lets concurrent misses share one fetch")
    def test_single_flight(self, fake_redis, adsblol_settings):
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), datetime.now(UTC))
        provider = positions_service.get_provider()
        started = threading.Event()

        def slow_fetch(*args):
            started.set()
            time.sleep(0.6)
            return result

        outcomes = []
        with mock.patch.object(
            provider, "fetch", side_effect=slow_fetch
        ) as fetch, mock.patch.object(positions_service, "WAIT_POLL_S", 0.05):
            threads = [
                threading.Thread(
                    target=lambda: outcomes.append(
                        positions_service.get_positions("RJBB", area("rjbb"))[0]
                    )
                )
                for _ in range(5)
            ]
            [t.start() for t in threads]
            [t.join() for t in threads]
        assert fetch.call_count == 1
        assert outcomes == [result] * 5

    @pytest.mark.it(
        "returns busy rather than fetching when another fetch doesn't finish"
    )
    def test_busy(self, fake_redis, adsblol_settings):
        fake_redis.set("positions:v1:adsblol:RJBB:lock", "someone-else", px=30000)
        provider = positions_service.get_provider()
        with mock.patch.object(provider, "fetch") as fetch, mock.patch.multiple(
            settings, POSITIONS_DEADLINE_S=0.3
        ), mock.patch.object(positions_service, "WAIT_POLL_S", 0.05):
            with pytest.raises(positions_service.Busy):
                positions_service.get_positions("RJBB", area("rjbb"))
        assert not fetch.called

    @pytest.mark.it(
        "fails closed for OpenSky when Redis is down, but still serves adsb.lol"
    )
    def test_redis_down(self, opensky_settings):
        broken = mock.Mock()
        broken.get.side_effect = redis.ConnectionError("down")
        with mock.patch.object(cache, "redis_client", broken), mock.patch(
            "requests.get"
        ) as get:
            with pytest.raises(QuotaExhausted) as e:
                positions_service.get_positions("RJBB", area("rjbb"))
        assert e.value.reason == "budget_unavailable" and not get.called

        positions_service._providers.clear()
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), datetime.now(UTC))
        with mock.patch.object(cache, "redis_client", broken), mock.patch.multiple(
            settings, POSITIONS_PROVIDER="adsblol"
        ):
            provider = positions_service.get_provider()
            with mock.patch.object(provider, "fetch", return_value=result):
                got, evidence, _ = positions_service.get_positions("RJBB", area("rjbb"))
        assert got == result and evidence is False


@pytest.fixture
def client():
    return TestClient(app)


def get_aircraft(
    client, code, result=None, evidence=True, error=None, now=None, provider=None
):
    provider = provider or AdsbLol()
    with mock.patch(
        "app.api.aircraft.positions_service.get_positions",
        return_value=(result, evidence, provider),
        side_effect=error,
    ), mock.patch("app.api.aircraft.utc_now", return_value=now or datetime.now(UTC)):
        return client.get(f"/v1/airports/{code}/aircraft")


@pytest.mark.describe("Aircraft endpoint")
class TestEndpoint:
    @pytest.mark.it(
        "returns positions with source, attribution and per-position expiry"
    )
    def test_available(self, client):
        result = AdsbLol.parse(adsblol("kjfk"), area("kjfk"), datetime.now(UTC))
        now = result.observed_at + timedelta(seconds=1)
        body = get_aircraft(client, "jfk", result, now=now).json()
        assert body["data_status"] == "available"
        assert body["area"]["radius_nm"] == 25.0
        assert body["area"]["latitude"] == pytest.approx(40.6398, abs=0.01)
        assert body["source"]["name"] == "adsb.lol (ODbL 1.0)"
        assert body["source"]["privacy_filter"] == "applied"
        assert body["withheld"] == 7 and len(body["aircraft"]) == 99
        first = body["aircraft"][0]
        assert set(first) == {
            "id", "callsign", "latitude", "longitude", "altitude_ft", "on_ground", "ground_speed_kt",
            "track_deg", "vertical_rate_fpm", "category", "kind", "position_at", "expires_at", "distance_nm",
        }  # fmt: skip
        assert "registration" not in json.dumps(body) and '"t"' not in json.dumps(body)
        assert "safety" in body["disclaimer"]

    @pytest.mark.it(
        "withdraws positions as they expire, then reports the feed as stale"
    )
    def test_expiry(self, client):
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), datetime.now(UTC))
        later = result.observed_at + timedelta(seconds=61)
        body = get_aircraft(client, "RJBB", result, now=later).json()
        assert (body["aircraft"], body["data_status"], body["unavailable_reason"]) == (
            [],
            "coverage_unknown",
            "stale_feed",
        )

    @pytest.mark.it("reports the gate, quota and busy states")
    @pytest.mark.parametrize(
        "error, status, reason",
        [
            (
                ProviderDisabled("educational_use_not_enabled"),
                "unavailable",
                "provider_disabled",
            ),
            (
                QuotaExhausted("daily_budget", datetime(2026, 11, 11, tzinfo=UTC)),
                "quota_exhausted",
                "daily_budget",
            ),
            (
                QuotaExhausted("budget_unavailable", None),
                "quota_exhausted",
                "budget_unavailable",
            ),
            (positions_service.Busy(), "coverage_unknown", "busy"),
        ],
    )
    def test_states(self, client, error, status, reason):
        response = get_aircraft(client, "RJBB", error=error)
        body = response.json()
        assert response.status_code == 200
        assert (body["data_status"], body["unavailable_reason"], body["aircraft"]) == (
            status,
            reason,
            [],
        )
        if reason == "daily_budget":
            assert body["retry_at"] == "2026-11-11T00:00:00Z"

    @pytest.mark.it("maps provider failures like the other endpoints")
    @pytest.mark.parametrize(
        "error, status, reason",
        [
            (MetarTimeout("timeout"), 504, "provider_timeout"),
            (MetarUpstreamError("http_500"), 502, "provider_error"),
            (
                MetarUpstreamError("provider_auth_failed", "token request failed"),
                502,
                "provider_auth_failed",
            ),
        ],
    )
    def test_errors(self, client, error, status, reason):
        response = get_aircraft(client, "RJBB", error=error)
        assert (response.status_code, response.json()["reason"]) == (status, reason)

    @pytest.mark.it("rejects bad and unknown codes")
    def test_codes(self, client):
        assert get_aircraft(client, "L!").status_code == 400
        assert get_aircraft(client, "QQQ").status_code == 404

    @pytest.mark.it("says no aircraft only with coverage evidence")
    def test_no_aircraft(self, client):
        empty = AdsbLol.parse(
            {"ac": [], "now": 1794271840001}, area("rjbb"), datetime.now(UTC)
        )
        now = empty.observed_at + timedelta(seconds=5)
        assert (
            get_aircraft(client, "RJBB", empty, True, now=now).json()["data_status"]
            == "no_aircraft"
        )
        body = get_aircraft(client, "RJBB", empty, False, now=now).json()
        assert (body["data_status"], body["unavailable_reason"]) == (
            "coverage_unknown",
            "no_coverage_evidence",
        )


@pytest.mark.describe("adsb.lol adapter: HTTP, retries and the local cap")
class TestAdsbLolFetch:
    def deadline(self):
        return time.monotonic() + 20

    @pytest.mark.it("queries the point endpoint with the radius and parses the answer")
    def test_fetch(self):
        with mock.patch(
            "requests.get", return_value=FakeResponse(body=adsblol("rjbb"))
        ) as get:
            result = AdsbLol().fetch(area("rjbb"), self.deadline())
        assert (
            get.call_args.args[0] == "https://api.adsb.lol/v2/point/34.4273/135.2440/25"
        )
        assert get.call_args.kwargs["timeout"] <= settings.PROVIDER_TIMEOUT
        assert len(result.targets) == 23 and result.access == "keyless"

    @pytest.mark.it("retries once after a timeout or 5xx, then raises")
    @pytest.mark.parametrize(
        "replies, error",
        [
            ([requests.Timeout(), requests.Timeout()], MetarTimeout),
            ([FakeResponse(502), FakeResponse(502)], MetarUpstreamError),
            (
                [requests.ConnectionError(), requests.ConnectionError()],
                MetarUpstreamError,
            ),
        ],
    )
    def test_retry_then_fail(self, replies, error):
        with mock.patch("requests.get", side_effect=replies) as get, mock.patch(
            "time.sleep"
        ):
            with pytest.raises(error):
                AdsbLol().fetch(area("rjbb"), self.deadline())
        assert get.call_count == 2

    @pytest.mark.it("recovers when the retry succeeds")
    def test_retry_succeeds(self):
        replies = [requests.Timeout(), FakeResponse(body=adsblol("rjbb"))]
        with mock.patch("requests.get", side_effect=replies), mock.patch("time.sleep"):
            assert len(AdsbLol().fetch(area("rjbb"), self.deadline()).targets) == 23

    @pytest.mark.it("doesn't retry a 429 or a bad body")
    @pytest.mark.parametrize(
        "reply",
        [FakeResponse(429), FakeResponse(body=ValueError("x")), FakeResponse(404)],
    )
    def test_no_retry(self, reply):
        with mock.patch("requests.get", return_value=reply) as get:
            with pytest.raises(MetarUpstreamError):
                AdsbLol().fetch(area("rjbb"), self.deadline())
        assert get.call_count == 1

    @pytest.mark.it("stops at the local rate cap without calling")
    def test_cap(self):
        with mock.patch.multiple(settings, ADSBLOL_RATE_LIMIT_PER_MINUTE=1):
            adapter = AdsbLol()
        with mock.patch(
            "requests.get", return_value=FakeResponse(body=adsblol("rjbb"))
        ) as get:
            adapter.fetch(area("rjbb"), self.deadline())
            with pytest.raises(Exception) as e:
                adapter.fetch(area("rjbb"), self.deadline())
        assert type(e.value).__name__ == "MetarRateLimited" and get.call_count == 1

    @pytest.mark.it("doesn't start an attempt with under 2 s left")
    def test_deadline(self):
        with mock.patch("requests.get") as get:
            with pytest.raises(MetarTimeout):
                AdsbLol().fetch(area("rjbb"), time.monotonic() + 1)
        assert not get.called


@pytest.mark.describe("Settings")
class TestSettings:
    @pytest.mark.it(
        "treats empty OpenSky credentials (as Compose passes them) as unset"
    )
    def test_empty_credentials(self):
        from app.core.config import Settings

        loaded = Settings(
            OPENSKY_CLIENT_ID="",
            OPENSKY_CLIENT_SECRET="  ",
            OPENSKY_DAILY_CREDIT_BUDGET="",
        )
        assert (
            loaded.OPENSKY_CLIENT_ID,
            loaded.OPENSKY_CLIENT_SECRET,
            loaded.OPENSKY_DAILY_CREDIT_BUDGET,
        ) == (
            None,
            None,
            None,
        )


@pytest.mark.describe("Review round 1 fixes")
class TestReviewRound1:
    NOW = datetime(2026, 11, 10, 0, 50, 30, tzinfo=UTC)

    def deadline(self):
        return time.monotonic() + 20

    @pytest.mark.it("reports a stale withheld-only feed as stale, not available")
    def test_stale_withheld(self):
        stale = feed(withheld=3, observed_at=self.NOW - timedelta(seconds=90))
        assert assess(stale, self.NOW, 60, True) == ("coverage_unknown", "stale_feed")
        fresh = feed(withheld=3, observed_at=self.NOW - timedelta(seconds=5))
        assert assess(fresh, self.NOW, 60, True) == ("available", None)

    @pytest.mark.it("withholds aircraft whose privacy flags can't be read")
    @pytest.mark.parametrize("flags", ["8", 8.0, None, True])
    def test_unreadable_flags(self, flags):
        ac = dict(adsblol("rjbb")["ac"][0], dbFlags=flags)
        result = AdsbLol.parse(
            {"ac": [ac], "now": 1794271840001}, area("rjbb"), datetime.now(UTC)
        )
        assert (result.targets, result.withheld) == ([], 1)

    @pytest.mark.it(
        "stops reading a body that outlives the deadline, and caps its size"
    )
    def test_bounded_read(self):
        def slow():
            yield b'{"ac": ['
            time.sleep(0.3)
            yield b"]}"

        from app.services import positions_providers
        from app.services.positions_providers import get

        reply = FakeResponse(chunks=slow())
        with mock.patch("requests.get", return_value=reply), mock.patch.object(
            positions_providers, "MIN_ATTEMPT_S", 0.05
        ):
            with pytest.raises(MetarTimeout):
                get("https://example.invalid", time.monotonic() + 0.2)
        # The request's own thread closes the response once its read ends.
        end = time.monotonic() + 2
        while not reply.closed and time.monotonic() < end:
            time.sleep(0.01)
        assert reply.closed
        big = FakeResponse(chunks=[b"x" * 5_000_000, b"x" * 5_000_000])
        with mock.patch("requests.get", return_value=big):
            with pytest.raises(MetarUpstreamError, match="response_too_large"):
                get("https://example.invalid", self.deadline())

    @pytest.mark.it("fetches the token before reserving the per-second slot")
    def test_token_before_slot(self, fake_redis, opensky_settings):
        adapter = OpenSky(fake_redis)
        order = []
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        states = FakeResponse(body=states_body())

        def post(*args, **kwargs):
            order.append("token")
            return token

        real_reserve = adapter.budget.reserve

        def reserve(cost=1):
            order.append("reserve")
            return real_reserve(cost)

        with mock.patch("requests.post", side_effect=post), mock.patch(
            "requests.get", return_value=states
        ), mock.patch.object(adapter.budget, "reserve", side_effect=reserve):
            adapter.fetch(area("rjbb"), self.deadline())
        assert order == ["token", "reserve"]

    @pytest.mark.it("makes at most two states calls, whatever mix of 5xx and 401")
    @pytest.mark.parametrize(
        "replies",
        [
            [FakeResponse(500), FakeResponse(401), FakeResponse(body=states_body())],
            [FakeResponse(401), FakeResponse(500), FakeResponse(body=states_body())],
            [requests.Timeout(), FakeResponse(401), FakeResponse(body=states_body())],
        ],
    )
    def test_call_limit(self, fake_redis, opensky_settings, replies):
        clock = itertools.count(1794268800)
        adapter = OpenSky(fake_redis, clock=lambda: next(clock))
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        with mock.patch("requests.post", return_value=token), mock.patch(
            "requests.get", side_effect=replies
        ) as get, mock.patch("time.sleep"):
            with pytest.raises((MetarUpstreamError, MetarTimeout)):
                adapter.fetch(area("rjbb"), self.deadline())
        assert get.call_count == 2 and adapter.budget.used() == 2

    @pytest.mark.it(
        "reports a slow token server as a timeout (504), not bad credentials"
    )
    def test_token_timeout(self, fake_redis, opensky_settings, client):
        adapter = OpenSky(fake_redis)
        with mock.patch("requests.post", side_effect=requests.Timeout()), mock.patch(
            "requests.get"
        ) as get:
            with pytest.raises(MetarTimeout):
                adapter.fetch(area("rjbb"), self.deadline())
        assert not get.called and adapter.budget.used() is None  # no credit spent

    @pytest.mark.it("refuses an invalid credit budget")
    @pytest.mark.parametrize("budget", [0, -5, 4001])
    def test_invalid_budget(self, fake_redis, opensky_settings, budget):
        with mock.patch.multiple(settings, OPENSKY_DAILY_CREDIT_BUDGET=budget):
            with pytest.raises(ProviderDisabled):
                OpenSky(fake_redis)

    @pytest.mark.it("keeps fetched data when reconciliation can't reach Redis")
    def test_reconcile_failure(self, fake_redis, opensky_settings):
        clock = itertools.count(1794268800)
        adapter = OpenSky(fake_redis, clock=lambda: next(clock))
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        states = FakeResponse(
            body=states_body(), headers={"x-rate-limit-remaining": "3990"}
        )
        with mock.patch("requests.post", return_value=token), mock.patch(
            "requests.get", return_value=states
        ), mock.patch.object(
            adapter.budget, "raise_to", side_effect=redis.ConnectionError("down")
        ):
            assert len(adapter.fetch(area("rjbb"), self.deadline()).targets) == 19

    @pytest.mark.it(
        "answers budget_unavailable (200), not 500, when Redis fails mid-fetch"
    )
    def test_redis_mid_fetch(self, fake_redis, opensky_settings, client):
        provider = positions_service.get_provider()
        with mock.patch.object(
            provider.budget, "reserve", side_effect=redis.ConnectionError("down")
        ), mock.patch(
            "requests.post",
            return_value=FakeResponse(body={"access_token": "tok", "expires_in": 1800}),
        ), mock.patch(
            "requests.get"
        ) as get:
            response = client.get("/v1/airports/KIX/aircraft")
        body = response.json()
        assert response.status_code == 200
        assert (body["data_status"], body["unavailable_reason"]) == (
            "quota_exhausted",
            "budget_unavailable",
        )
        assert not get.called

    @pytest.mark.it("re-checks the cache after taking the lock")
    def test_recheck(self, fake_redis, adsblol_settings):
        recorded = datetime.fromtimestamp(1794271841, UTC)
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), recorded)
        provider = positions_service.get_provider()
        real_acquire = Lock.acquire

        def acquire(lock):
            fake_redis.set(
                "positions:v1:adsblol:RJBB", json.dumps(result.to_dict()), ex=30
            )
            return real_acquire(lock)

        with mock.patch.object(Lock, "acquire", acquire), mock.patch.object(
            provider, "fetch"
        ) as fetch:
            got, _, _ = positions_service.get_positions("RJBB", area("rjbb"))
        assert got == result and not fetch.called

    @pytest.mark.it(
        "tells waiting requests why the fetch failed, without waiting it out"
    )
    def test_waiters_learn_failure(self, fake_redis, adsblol_settings):
        provider = positions_service.get_provider()
        started = threading.Event()

        def failing(*args):
            started.set()
            time.sleep(0.3)
            raise MetarUpstreamError("http_502")

        errors = []

        def call():
            try:
                positions_service.get_positions("RJBB", area("rjbb"))
            except Exception as e:
                errors.append(type(e).__name__ + ":" + getattr(e, "reason", ""))

        with mock.patch.object(
            provider, "fetch", side_effect=failing
        ), mock.patch.object(positions_service, "WAIT_POLL_S", 0.05):
            begin = time.monotonic()
            threads = [threading.Thread(target=call) for _ in range(4)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        assert errors == ["MetarUpstreamError:http_502"] * 4
        assert time.monotonic() - begin < 5

    @pytest.mark.it("treats a corrupt cache entry as a miss")
    def test_corrupt_cache(self, fake_redis, adsblol_settings):
        fake_redis.set("positions:v1:adsblol:RJBB", "{not json", ex=30)
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), datetime.now(UTC))
        provider = positions_service.get_provider()
        with mock.patch.object(provider, "fetch", return_value=result) as fetch:
            assert positions_service.get_positions("RJBB", area("rjbb"))[0] == result
        assert fetch.called

    @pytest.mark.it("doesn't record coverage evidence from a stale feed")
    def test_stale_evidence(self, fake_redis, adsblol_settings):
        result = AdsbLol.parse(
            adsblol("rjbb"), area("rjbb"), datetime.now(UTC)
        )  # recorded long ago
        provider = positions_service.get_provider()
        with mock.patch.object(provider, "fetch", return_value=result):
            positions_service.get_positions("RJBB", area("rjbb"))
        assert not fake_redis.exists("positions:coverage:adsblol:RJBB")


@pytest.mark.describe("Review round 2 fixes")
class TestReviewRound2:
    def deadline(self):
        return time.monotonic() + 20

    @pytest.mark.it("cuts off a provider that trickles bytes, at the deadline")
    def test_trickle(self):
        from app.services import positions_providers
        from app.services.positions_providers import get

        def trickle():
            while True:
                time.sleep(0.01)  # each read returns quickly, so no socket timeout
                yield b" "

        reply = FakeResponse(chunks=trickle())
        begin = time.monotonic()
        with mock.patch("requests.get", return_value=reply), mock.patch.object(
            positions_providers, "MIN_ATTEMPT_S", 0.05
        ):
            with pytest.raises(MetarTimeout):
                get("https://example.invalid", time.monotonic() + 0.2)
        assert time.monotonic() - begin < 0.4

    @pytest.mark.it("caches the result before releasing the lock")
    def test_store_before_release(self, fake_redis, adsblol_settings):
        recorded = datetime.fromtimestamp(1794271841, UTC)
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), recorded)
        provider = positions_service.get_provider()
        seen = []
        real_release = Lock.release

        def release(lock):
            seen.append(fake_redis.exists("positions:v1:adsblol:RJBB"))
            return real_release(lock)

        with mock.patch.object(Lock, "release", release), mock.patch.object(
            provider, "fetch", return_value=result
        ):
            positions_service.get_positions("RJBB", area("rjbb"))
        assert seen == [1]

    @pytest.mark.it("ignores a failure record from an earlier fetch")
    def test_old_failure(self, fake_redis, adsblol_settings):
        recorded = datetime.fromtimestamp(1794271841, UTC)
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), recorded)
        fake_redis.set(
            "positions:v1:adsblol:RJBB:failed",
            json.dumps(
                {
                    "kind": "MetarUpstreamError",
                    "reason": "http_502",
                    "owner": "old-owner",
                }
            ),
            px=5000,
        )
        fake_redis.set("positions:v1:adsblol:RJBB:lock", "new-owner", px=30000)

        def finish():
            time.sleep(0.2)
            fake_redis.set(
                "positions:v1:adsblol:RJBB", json.dumps(result.to_dict()), ex=30
            )
            fake_redis.delete("positions:v1:adsblol:RJBB:lock")

        worker = threading.Thread(target=finish)
        worker.start()
        with mock.patch.object(positions_service, "WAIT_POLL_S", 0.05):
            got, _, _ = positions_service.get_positions("RJBB", area("rjbb"))
        worker.join()
        assert got == result

    @pytest.mark.it("treats a cache entry with naive timestamps or bad types as a miss")
    @pytest.mark.parametrize(
        "change",
        [
            lambda d: d.update(observed_at="2026-11-10T00:50:05"),
            lambda d: d.update(withheld="3"),
            lambda d: d["targets"][0].update(position_at="2026-11-10T00:50:00"),
            lambda d: d["targets"][0].update(kind="surface"),
        ],
    )
    def test_invalid_cache_values(self, fake_redis, adsblol_settings, change):
        recorded = datetime.fromtimestamp(1794271841, UTC)
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), recorded)
        data = result.to_dict()
        change(data)
        fake_redis.set("positions:v1:adsblol:RJBB", json.dumps(data), ex=30)
        provider = positions_service.get_provider()
        with mock.patch.object(provider, "fetch", return_value=result) as fetch:
            assert positions_service.get_positions("RJBB", area("rjbb"))[0] == result
        assert fetch.called

    @pytest.mark.it("rejects an OpenSky answer without a states field")
    def test_missing_states(self, fake_redis, opensky_settings):
        clock = itertools.count(1794268800)
        adapter = OpenSky(fake_redis, clock=lambda: next(clock))
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        with mock.patch("requests.post", return_value=token), mock.patch(
            "requests.get", return_value=FakeResponse(body={"time": 1794271833})
        ):
            with pytest.raises(MetarUpstreamError) as e:
                adapter.fetch(area("rjbb"), self.deadline())
        assert e.value.reason == "invalid_response"

    @pytest.mark.it(
        "requests at most two tokens per operation, across antimeridian halves"
    )
    def test_token_limit_across_halves(self, fake_redis, opensky_settings):
        clock = itertools.count(1794268800)
        adapter = OpenSky(fake_redis, clock=lambda: next(clock))
        token = FakeResponse(body={"access_token": "tok", "expires_in": 1800})
        ok = FakeResponse(body={"time": 1794271833, "states": None})
        replies = [FakeResponse(401), ok, FakeResponse(401), ok]
        with mock.patch("requests.post", return_value=token) as post, mock.patch(
            "requests.get", side_effect=replies
        ):
            with pytest.raises(MetarUpstreamError) as e:
                adapter.fetch(Area(51.0, 179.9, 25), self.deadline())
        assert e.value.reason == "provider_auth_failed" and post.call_count == 2


@pytest.mark.describe("Review round 3 fixes")
class TestReviewRound3:
    def deadline(self):
        return time.monotonic() + 20

    def body(self):
        return json.dumps(adsblol("rjbb")).encode()

    @pytest.mark.it("asks for uncompressed responses and reads raw bytes")
    def test_identity(self):
        from app.services.positions_providers import get

        reply = FakeResponse(chunks=[self.body()])
        with mock.patch("requests.get", return_value=reply) as call:
            assert (
                get("https://example.invalid", self.deadline()).json()["now"]
                == 1794271840001
            )
        assert call.call_args.kwargs["headers"]["Accept-Encoding"] == "identity"

    @pytest.mark.it(
        "decodes gzip or deflate itself, step by step, when a server compresses anyway"
    )
    @pytest.mark.parametrize("encoding", ["gzip", "deflate"])
    def test_decodes(self, encoding):
        import zlib

        from app.services.positions_providers import get

        compressor = zlib.compressobj(wbits=31 if encoding == "gzip" else 15)
        data = compressor.compress(self.body()) + compressor.flush()
        pieces = [
            bytes(piece) for piece in itertools.batched(data, 7)
        ]  # many small reads
        reply = FakeResponse(chunks=pieces, headers={"Content-Encoding": encoding})
        with mock.patch("requests.get", return_value=reply):
            assert (
                get("https://example.invalid", self.deadline()).json()["now"]
                == 1794271840001
            )

    @pytest.mark.it("rejects unknown encodings and caps a decompression bomb")
    def test_encoding_limits(self):
        import zlib

        from app.services.positions_providers import get

        brotli = FakeResponse(chunks=[b"x"], headers={"Content-Encoding": "br"})
        with mock.patch("requests.get", return_value=brotli):
            with pytest.raises(MetarUpstreamError) as e:
                get("https://example.invalid", self.deadline())
        assert e.value.reason == "unsupported_encoding"
        bomb = zlib.compress(b"\0" * 20_000_000)  # about 20 kB in, 20 MB out
        reply = FakeResponse(chunks=[bomb], headers={"Content-Encoding": "deflate"})
        with mock.patch("requests.get", return_value=reply):
            with pytest.raises(MetarUpstreamError) as e:
                get("https://example.invalid", self.deadline())
        assert e.value.reason == "response_too_large"

    @pytest.mark.it("maps raw urllib3 read errors to typed errors")
    @pytest.mark.parametrize(
        "error, kind", [("timeout", MetarTimeout), ("protocol", MetarUpstreamError)]
    )
    def test_urllib3_errors(self, error, kind):
        import urllib3

        from app.services.positions_providers import get

        raised = (
            urllib3.exceptions.ReadTimeoutError(
                None, "https://example.invalid", "read timed out"
            )
            if error == "timeout"
            else urllib3.exceptions.ProtocolError("truncated")
        )
        reply = FakeResponse(chunks=[])
        reply.read1 = mock.Mock(side_effect=raised)
        with mock.patch("requests.get", return_value=reply):
            with pytest.raises(kind):
                get("https://example.invalid", self.deadline())
        assert reply.closed

    @pytest.mark.it("treats a cached target with a bad optional field as a miss")
    @pytest.mark.parametrize(
        "field, value",
        [
            ("altitude_ft", "invalid"),
            ("ground_speed_kt", 1.5),
            ("callsign", 7),
            ("category", ["A3"]),
            ("id", "zz"),
        ],
    )
    def test_cached_target_fields(self, fake_redis, adsblol_settings, field, value):
        recorded = datetime.fromtimestamp(1794271841, UTC)
        result = AdsbLol.parse(adsblol("rjbb"), area("rjbb"), recorded)
        data = result.to_dict()
        data["targets"][0][field] = value
        fake_redis.set("positions:v1:adsblol:RJBB", json.dumps(data), ex=30)
        provider = positions_service.get_provider()
        with mock.patch.object(provider, "fetch", return_value=result) as fetch:
            assert positions_service.get_positions("RJBB", area("rjbb"))[0] == result
        assert fetch.called


class LocalServer:
    """A raw HTTP server on 127.0.0.1 that sends scripted bytes (no network)."""

    def __init__(self, script):
        import socket as socketlib

        self.script = script
        self.sock = socketlib.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}/"
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        conn, _ = self.sock.accept()
        try:
            conn.recv(65536)  # the request
            self.script(conn, self.stop)
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self.stop.set()
        self.sock.close()


def respond(body: bytes, headers: dict):
    def script(conn, stop):
        head = (
            "HTTP/1.1 200 OK\r\n"
            + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
            + "\r\n"
        )
        conn.sendall(head.encode() + body)

    return script


@pytest.mark.describe("Round 4: the deadline against a real HTTP server")
class TestRealServer:
    @pytest.fixture
    def short(self):
        from app.services import positions_providers

        with mock.patch.object(
            positions_providers, "MIN_ATTEMPT_S", 0.05
        ), mock.patch.multiple(settings, PROVIDER_TIMEOUT=1.0):
            yield

    @pytest.mark.it("cuts off trickled chunk framing at the deadline")
    def test_trickled_framing(self, short):
        from app.services.positions_providers import get

        def trickle(conn, stop):
            conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1")
            while not stop.is_set():
                conn.sendall(b";")  # a chunk extension that never ends
                time.sleep(0.05)  # well under the 1 s socket timeout

        server = LocalServer(trickle)
        begin = time.monotonic()
        try:
            with pytest.raises(MetarTimeout):
                get(server.url, time.monotonic() + 0.5)
        finally:
            server.close()
        assert time.monotonic() - begin < 1.0

    @pytest.mark.it("reads a normal chunked body")
    def test_chunked(self, short):
        from app.services.positions_providers import get

        body = b'{"now": 1}'
        chunked = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
        server = LocalServer(respond(chunked, {"Transfer-Encoding": "chunked"}))
        try:
            assert get(server.url, time.monotonic() + 5).json() == {"now": 1}
        finally:
            server.close()

    @pytest.mark.it("decodes every member of a multi-member gzip body")
    def test_multi_member_gzip(self, short):
        import gzip

        from app.services.positions_providers import get

        body = gzip.compress(b'{"a":') + gzip.compress(b"1}")
        server = LocalServer(
            respond(body, {"Content-Encoding": "gzip", "Content-Length": len(body)})
        )
        try:
            assert get(server.url, time.monotonic() + 5).json() == {"a": 1}
        finally:
            server.close()

    @pytest.mark.it("rejects a truncated compressed body")
    @pytest.mark.parametrize("encoding", ["gzip", "deflate"])
    def test_truncated(self, short, encoding):
        import gzip
        import zlib

        from app.services.positions_providers import get

        full = (
            gzip.compress(b'{"a": 1}')
            if encoding == "gzip"
            else zlib.compress(b'{"a": 1}')
        )
        body = full[:-4]  # drop the trailer (checksum)
        server = LocalServer(
            respond(body, {"Content-Encoding": encoding, "Content-Length": len(body)})
        )
        try:
            with pytest.raises(MetarUpstreamError) as e:
                get(server.url, time.monotonic() + 5)
        finally:
            server.close()
        assert e.value.reason == "invalid_response"


@pytest.mark.describe("Round 5: the whole request is bounded (real HTTP server)")
class TestWholeRequestBounded:
    @pytest.fixture
    def short(self):
        from app.services import positions_providers

        with mock.patch.object(
            positions_providers, "MIN_ATTEMPT_S", 0.05
        ), mock.patch.multiple(settings, PROVIDER_TIMEOUT=1.0):
            yield

    def trickle(self, head: bytes, drip: bytes):
        def script(conn, stop):
            conn.sendall(head)
            while not stop.is_set():
                conn.sendall(drip)
                time.sleep(0.05)  # well under the 1 s socket timeout

        return script

    @pytest.mark.it("cuts off trickled headers at the deadline")
    def test_trickled_headers(self, short):
        from app.services.positions_providers import get

        server = LocalServer(self.trickle(b"HTTP/1.1 200 OK\r\nX-Slow: ", b"a"))
        begin = time.monotonic()
        try:
            with pytest.raises(MetarTimeout):
                get(server.url, time.monotonic() + 0.5)
        finally:
            server.close()
        assert time.monotonic() - begin < 1.0

    @pytest.mark.it("times out without blocking on a Connection: close response")
    def test_connection_close(self, short):
        from app.services.positions_providers import get

        head = b"HTTP/1.1 200 OK\r\nConnection: close\r\nTransfer-Encoding: chunked\r\n\r\n1"
        server = LocalServer(self.trickle(head, b";"))
        begin = time.monotonic()
        try:
            with pytest.raises(MetarTimeout):
                get(server.url, time.monotonic() + 0.5)
            assert time.monotonic() - begin < 1.0  # the caller never waited on close
        finally:
            server.close()

    @pytest.mark.it("doesn't follow redirects (each would be another provider call)")
    def test_no_redirect(self, short):
        from app.services.positions_providers import get

        redirect = LocalServer(
            lambda conn, stop: conn.sendall(
                b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:9/x\r\n"
                b"Content-Length: 0\r\n\r\n"
            )
        )
        try:
            reply = get(redirect.url, time.monotonic() + 5)
        finally:
            redirect.close()
        assert reply.status_code == 302  # returned, not followed

    @pytest.mark.it(
        "fails fast without contacting the provider when every request slot is busy"
    )
    def test_saturated(self, short):
        from app.services import positions_providers
        from app.services.positions_providers import get

        full = threading.BoundedSemaphore(1)
        full.acquire()
        with mock.patch.object(positions_providers, "IN_FLIGHT", full), mock.patch(
            "requests.get"
        ) as call:
            begin = time.monotonic()
            with pytest.raises(MetarTimeout) as e:
                get("https://example.invalid", time.monotonic() + 0.3)
        assert e.value.reason == "requests_busy" and not call.called
        assert time.monotonic() - begin < 0.5
