import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest
import requests

from app.services import metar
from app.services.metar import (
    NO_REPORT,
    MetarRateLimited,
    MetarTimeout,
    MetarUpstreamError,
    Observation,
    RateLimiter,
    age_minutes,
    freshness,
    get_latest_observation,
    select_observation,
)

"""
Test suite for the Aviation Weather Center METAR adapter
"""

FIXTURES = Path(__file__).parent / "testfiles" / "awc"
FETCHED_AT = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def observe(name, station):
    return select_observation(fixture(name), station, FETCHED_AT)


def record(**fields):
    base = {
        "icaoId": "EGLL",
        "obsTime": 1793344800,  # 2026-10-30 07:20 UTC
        "metarType": "METAR",
        "rawOb": "METAR EGLL 300720Z ...",
        "temp": 10,
        "dewp": 9,
        "wdir": 70,
        "wspd": 4,
        "visib": 6.0,
        "altim": 1029,
        "cover": "BKN",
        "clouds": [{"cover": "BKN", "base": 1200}],
    }
    base.update(fields)
    return base


def response(status=200, body=None, headers=None):
    resp = mock.Mock(status_code=status, headers=headers or {})
    if isinstance(body, Exception):
        resp.json.side_effect = body
    else:
        resp.json.return_value = body
    return resp


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """Fresh rate limiter, no real sleeping, no real Redis."""
    monkeypatch.setattr(metar, "rate_limiter", RateLimiter(100))
    monkeypatch.setattr(metar.time, "sleep", mock.Mock())
    monkeypatch.setattr(metar, "check_cache", mock.Mock(return_value=None))
    monkeypatch.setattr(metar, "cache_response", mock.Mock())


@pytest.fixture
def get():
    with mock.patch.object(metar.requests, "get") as get:
        yield get


@pytest.mark.describe("METAR normalisation of recorded AWC responses")
class TestRecordedFixtures:
    @pytest.mark.it("normalises the pilot stations")
    def test_pilots(self):
        egll = observe("pilots_latest", "EGLL")
        assert egll.observed_at == datetime(2026, 10, 30, 7, 20, tzinfo=timezone.utc)
        assert egll.fetched_at == FETCHED_AT
        assert egll.source == "Aviation Weather Center"
        assert (egll.temperature_c, egll.dewpoint_c) == (10, 10)
        assert (egll.wind_direction_deg, egll.wind_speed_kt) == (70, 4)
        assert (egll.visibility_m, egll.visibility_at_least) == (1304, False)
        assert (egll.sky_condition, egll.ceiling_ft) == ("clouds", 200)
        assert egll.pressure_hpa == 1029
        assert egll.weather_phenomena == ["BR"]
        assert egll.raw_text.startswith("METAR EGLL 300720Z")

        rjbb = observe("pilots_latest", "RJBB")
        assert rjbb.ceiling_ft == 3000  # lowest BKN, below FEW/SCT layers
        assert [layer.cover for layer in rjbb.cloud_layers] == ["FEW", "SCT", "BKN"]
        assert rjbb.weather_phenomena == ["+SHRA", "BR"]

    @pytest.mark.it("uses obsTime, not reportTime, as observed_at")
    def test_observed_at_from_obs_time(self):
        kjfk = observe("pilots_latest", "KJFK")
        # reportTime in the fixture is 07:00Z; the observation was at 06:51Z
        assert kjfk.observed_at == datetime(2026, 10, 30, 6, 51, tzinfo=timezone.utc)
        assert kjfk.ceiling_ft is None  # FEW only: no ceiling
        assert kjfk.pressure_hpa == 1018  # A3006 reported in hPa by AWC

    @pytest.mark.it("reads '10+' and '6+' visibility as a lower bound")
    def test_visibility_lower_bound(self):
        panc = observe("panc_10plus_gust_rain", "PANC")
        assert (panc.visibility_m, panc.visibility_at_least) == (16093, True)
        lemd = observe("lemd_vrb_cavok", "LEMD")
        assert (lemd.visibility_m, lemd.visibility_at_least) == (9656, True)

    @pytest.mark.it("keeps gusts and AWC's knot conversion for MPS stations")
    def test_gusts(self):
        zbaa = observe("zbaa_mps_gust", "ZBAA")
        assert (zbaa.wind_speed_kt, zbaa.wind_gust_kt) == (16, 27)
        assert (zbaa.sky_condition, zbaa.cloud_layers) == ("cavok", [])

    @pytest.mark.it("marks variable wind without a direction")
    def test_variable_wind(self):
        lemd = observe("lemd_vrb_cavok", "LEMD")
        assert (lemd.wind_variable, lemd.wind_direction_deg) == (True, None)

    @pytest.mark.it("reports an obscured sky (VV///) with an unknown ceiling")
    def test_obscured(self):
        egkk = observe("egkk_obscured_fog", "EGKK")
        assert (egkk.sky_condition, egkk.ceiling_ft) == ("obscured", None)
        assert egkk.visibility_m == 145
        assert egkk.weather_phenomena == ["FG"]

    @pytest.mark.it("reads an automated 'no cloud detected' SPECI as clear")
    def test_auto_ncd(self):
        yssy = observe("yssy_auto_ncd_speci", "YSSY")
        assert (yssy.report_type, yssy.sky_condition) == ("SPECI", "clear")

    @pytest.mark.it("keeps a garbled report's valid fields and nulls the missing ones")
    def test_garbled(self):
        dnmm = observe("dnmm_garbled", "DNMM")
        assert dnmm.pressure_hpa is None
        assert dnmm.temperature_c == 25
        assert "CHECK TEXT" in dnmm.raw_text


@pytest.mark.describe("METAR field validation")
class TestFieldValidation:
    def normalise(self, **fields):
        return select_observation([record(**fields)], "EGLL", FETCHED_AT)

    @pytest.mark.it("turns missing fields into None, never defaults")
    def test_missing_fields(self):
        obs = select_observation(
            [{"icaoId": "EGLL", "obsTime": 1793344800}], "EGLL", FETCHED_AT
        )
        assert obs.temperature_c is None and obs.wind_speed_kt is None
        assert obs.visibility_m is None and obs.visibility_at_least is False
        assert (obs.sky_condition, obs.cloud_layers, obs.ceiling_ft) == (
            "unknown",
            [],
            None,
        )
        assert obs.pressure_hpa is None and obs.weather_phenomena == []
        assert obs.raw_text is None and obs.report_type is None

    @pytest.mark.it("rejects out-of-range, non-finite, bool and string numbers")
    @pytest.mark.parametrize(
        "field, value, attribute",
        [
            ("temp", 61, "temperature_c"),
            ("dewp", -91, "dewpoint_c"),
            ("temp", math.nan, "temperature_c"),
            ("temp", True, "temperature_c"),
            ("temp", "10", "temperature_c"),
            ("wdir", 361, "wind_direction_deg"),
            ("wspd", -1, "wind_speed_kt"),
            ("wspd", 251, "wind_speed_kt"),
            ("wspd", math.inf, "wind_speed_kt"),
            ("visib", -0.5, "visibility_m"),
            ("visib", "lots", "visibility_m"),
            ("visib", "-1+", "visibility_m"),
            ("altim", 849, "pressure_hpa"),
            ("altim", 1101, "pressure_hpa"),
        ],
    )
    def test_invalid_values(self, field, value, attribute):
        assert getattr(self.normalise(**{field: value}), attribute) is None

    @pytest.mark.it("drops a gust that is below the wind speed or out of range")
    @pytest.mark.parametrize("gust", [3, 301, -5])
    def test_invalid_gust(self, gust):
        assert self.normalise(wspd=4, wgst=gust).wind_gust_kt is None

    @pytest.mark.it("keeps a gust when the wind speed is unknown")
    def test_gust_without_speed(self):
        assert self.normalise(wspd=None, wgst=20).wind_gust_kt == 20

    @pytest.mark.it("treats a BKN/OVC layer with an unknown base as an unknown ceiling")
    @pytest.mark.parametrize("bad_base", [None, -1, "low"])
    @pytest.mark.parametrize("cover", ["BKN", "CLR", "CAVOK"])
    def test_unknown_ceiling_base(self, bad_base, cover):
        obs = self.normalise(
            cover=cover,
            clouds=[
                {"cover": "FEW", "base": 1500},
                {"cover": "BKN", "base": 5000},
                {"cover": "OVC", "base": bad_base},
            ],
        )
        assert (obs.sky_condition, obs.ceiling_ft) == ("unknown", None)
        assert [layer.base_ft for layer in obs.cloud_layers] == [1500, 5000]

    @pytest.mark.it("keeps 'obscured' when a layer base is also unknown")
    def test_obscured_with_unknown_base(self):
        obs = self.normalise(cover="OVX", clouds=[{"cover": "OVC", "base": None}])
        assert (obs.sky_condition, obs.ceiling_ft) == ("obscured", None)

    @pytest.mark.it("keeps 'clouds' when only a FEW/SCT layer has an unknown base")
    def test_unknown_few_base(self):
        obs = self.normalise(
            cover="BKN",
            clouds=[{"cover": "SCT", "base": None}, {"cover": "BKN", "base": 3000}],
        )
        assert (obs.sky_condition, obs.ceiling_ft) == ("clouds", 3000)

    @pytest.mark.it("rejects integers too large to convert")
    def test_huge_integer(self):
        obs = self.normalise(temp=10**400, wspd=10**400, obsTime=1793344800)
        assert (obs.temperature_c, obs.wind_speed_kt) == (None, None)
        assert select_observation([record(obsTime=10**400)], "EGLL", FETCHED_AT) is None

    @pytest.mark.it("ignores non-string cover values")
    def test_non_string_cover(self):
        obs = self.normalise(cover=[], clouds=[{"cover": [], "base": 100}])
        assert (obs.sky_condition, obs.cloud_layers) == ("unknown", [])
        assert obs.temperature_c == 10

    @pytest.mark.it("nulls a visibility too large to convert")
    def test_visibility_overflow(self):
        assert self.normalise(visib=1e308).visibility_m is None

    @pytest.mark.it("drops cloud layers with invalid bases or covers")
    def test_invalid_layers(self):
        obs = self.normalise(
            cover="BKN",
            clouds=[
                {"cover": "BKN", "base": -100},
                {"cover": "OVC", "base": "low"},
                {"cover": "XYZ", "base": 500},
                "BKN012",
            ],
        )
        assert (obs.sky_condition, obs.cloud_layers, obs.ceiling_ft) == (
            "unknown",
            [],
            None,
        )

    @pytest.mark.it("ignores a clouds value that isn't a list")
    def test_clouds_not_list(self):
        assert self.normalise(cover="CLR", clouds=None).sky_condition == "clear"

    @pytest.mark.it("ignores non-string text fields")
    def test_non_string_text(self):
        obs = self.normalise(rawOb=123, metarType=["METAR"], wxString=5)
        assert (obs.raw_text, obs.report_type, obs.weather_phenomena) == (
            None,
            None,
            [],
        )


@pytest.mark.describe("METAR record selection")
class TestRecordSelection:
    @pytest.mark.it("picks the newest record for the station only")
    def test_newest_for_station(self):
        records = [
            record(obsTime=1793343000, temp=8),
            record(obsTime=1793344800, temp=10),
            record(icaoId="EGKK", obsTime=1793345000, temp=5),
            "not a record",
        ]
        assert select_observation(records, "EGLL", FETCHED_AT).temperature_c == 10

    @pytest.mark.it("skips records without a valid obsTime or dated in the future")
    def test_invalid_times(self):
        future = int((FETCHED_AT + timedelta(minutes=11)).timestamp())
        near = int((FETCHED_AT + timedelta(minutes=9)).timestamp())
        assert select_observation([record(obsTime=None)], "EGLL", FETCHED_AT) is None
        assert select_observation([record(obsTime="x")], "EGLL", FETCHED_AT) is None
        assert select_observation([record(obsTime=future)], "EGLL", FETCHED_AT) is None
        assert select_observation([record(obsTime=near)], "EGLL", FETCHED_AT)

    @pytest.mark.it("skips an obsTime too large to convert, keeping other records")
    @pytest.mark.parametrize("obs_time", [1e12, 1e20, 1e300])
    def test_unconvertible_obs_time(self, obs_time):
        records = [record(obsTime=obs_time), record(temp=12)]
        assert select_observation(records, "EGLL", FETCHED_AT).temperature_c == 12
        assert (
            select_observation([record(obsTime=obs_time)], "EGLL", FETCHED_AT) is None
        )

    @pytest.mark.it("returns None when there are no records")
    def test_empty(self):
        assert select_observation([], "EGLL", FETCHED_AT) is None


@pytest.mark.describe("METAR freshness")
class TestFreshness:
    @pytest.mark.it("classifies age with the 90/180 minute pilot thresholds")
    @pytest.mark.parametrize(
        "minutes, expected",
        [
            (-5, "current"),
            (0, "current"),
            (90, "current"),
            (90.01, "stale"),
            (180, "stale"),
            (180.01, "expired"),
            (600, "expired"),
        ],
    )
    def test_thresholds(self, minutes, expected):
        observed_at = FETCHED_AT - timedelta(minutes=minutes)
        assert freshness(observed_at, FETCHED_AT) == expected

    @pytest.mark.it("follows configured thresholds")
    def test_configured(self, monkeypatch):
        monkeypatch.setattr(metar.settings, "METAR_CURRENT_MAX_MINUTES", 30)
        assert freshness(FETCHED_AT - timedelta(minutes=45), FETCHED_AT) == "stale"

    @pytest.mark.it("computes age against the current time by default")
    def test_age_default_now(self):
        observed_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert 29.9 < age_minutes(observed_at) < 30.1
        assert freshness(observed_at) == "current"


@pytest.mark.describe("METAR provider requests")
class TestProviderRequests:
    @pytest.mark.it("requests the station with a User-Agent and timeout")
    def test_request(self, get):
        get.return_value = response(body=fixture("pilots_latest"))
        obs = get_latest_observation(" egll ")
        assert obs.station == "EGLL"
        get.assert_called_once_with(
            metar.AWC_METAR_URL,
            params={"ids": "EGLL", "format": "json"},
            headers={"User-Agent": metar.settings.METAR_USER_AGENT},
            timeout=metar.settings.PROVIDER_TIMEOUT,
        )

    @pytest.mark.it("rejects an invalid station code without calling AWC")
    @pytest.mark.parametrize("code", ["LHR", "EGLLX", "EG-L", ""])
    def test_invalid_station(self, get, code):
        with pytest.raises(ValueError):
            get_latest_observation(code)
        get.assert_not_called()

    @pytest.mark.it("returns None and caches 'no report' on HTTP 204")
    def test_no_content(self, get):
        get.return_value = response(status=204)
        assert get_latest_observation("ZZZZ") is None
        metar.cache_response.assert_called_once_with(
            "metar:v1:ZZZZ", NO_REPORT, metar.settings.METAR_NO_DATA_CACHE_TTL
        )

    @pytest.mark.it("returns None without caching when no record is usable")
    def test_no_usable_record(self, get):
        get.return_value = response(body=[record(icaoId="EGKK")])
        assert get_latest_observation("EGLL") is None
        metar.cache_response.assert_not_called()

    @pytest.mark.it("caches 'no report' for an empty list")
    def test_empty_list(self, get):
        get.return_value = response(body=[])
        assert get_latest_observation("EGLL") is None
        metar.cache_response.assert_called_once_with(
            "metar:v1:EGLL", NO_REPORT, metar.settings.METAR_NO_DATA_CACHE_TTL
        )

    @pytest.mark.it("retries once after a timeout, then succeeds")
    def test_retry_timeout_then_success(self, get):
        get.side_effect = [
            requests.Timeout(),
            response(body=fixture("pilots_latest")),
        ]
        assert get_latest_observation("KJFK").station == "KJFK"
        assert get.call_count == 2
        metar.time.sleep.assert_called_once()
        assert 0.5 <= metar.time.sleep.call_args[0][0] <= 0.75

    @pytest.mark.it("raises MetarTimeout after repeated timeouts")
    def test_repeated_timeout(self, get):
        get.side_effect = requests.Timeout()
        with pytest.raises(MetarTimeout) as error:
            get_latest_observation("EGLL")
        assert error.value.reason == "timeout"
        assert get.call_count == 2
        metar.cache_response.assert_not_called()

    @pytest.mark.it("raises MetarUpstreamError after repeated connection errors")
    def test_connection_error(self, get):
        get.side_effect = requests.ConnectionError()
        with pytest.raises(MetarUpstreamError) as error:
            get_latest_observation("EGLL")
        assert error.value.reason == "connection_error"

    @pytest.mark.it("retries 5xx and reports the status if it persists")
    def test_server_error(self, get):
        get.return_value = response(status=503)
        with pytest.raises(MetarUpstreamError) as error:
            get_latest_observation("EGLL")
        assert error.value.reason == "http_503"
        assert get.call_count == 2

    @pytest.mark.it("honours Retry-After on 429, capped at 2 seconds")
    @pytest.mark.parametrize("header, expected", [("1", 1.0), ("30", 2.0)])
    def test_too_many_requests(self, get, header, expected):
        get.side_effect = [
            response(status=429, headers={"Retry-After": header}),
            response(body=fixture("pilots_latest")),
        ]
        get_latest_observation("EGLL")
        metar.time.sleep.assert_called_once_with(expected)

    @pytest.mark.it("falls back to the normal backoff for an unreadable Retry-After")
    @pytest.mark.parametrize("header", ["soon", "nan", "inf"])
    def test_bad_retry_after(self, get, header):
        get.side_effect = [
            response(status=429, headers={"Retry-After": header}),
            response(body=fixture("pilots_latest")),
        ]
        get_latest_observation("EGLL")
        assert 0.5 <= metar.time.sleep.call_args[0][0] <= 0.75

    @pytest.mark.it("doesn't retry other 4xx responses")
    def test_client_error(self, get):
        get.return_value = response(status=400, body={"status": "error"})
        with pytest.raises(MetarUpstreamError) as error:
            get_latest_observation("EGLL")
        assert error.value.reason == "http_400"
        assert get.call_count == 1

    @pytest.mark.it("rejects invalid JSON and non-list payloads without caching")
    @pytest.mark.parametrize(
        "body, reason",
        [(ValueError("bad"), "invalid_json"), ({"data": []}, "unexpected_payload")],
    )
    def test_bad_payload(self, get, body, reason):
        get.return_value = response(body=body)
        with pytest.raises(MetarUpstreamError) as error:
            get_latest_observation("EGLL")
        assert error.value.reason == reason
        metar.cache_response.assert_not_called()


@pytest.mark.describe("METAR caching")
class TestCaching:
    @pytest.mark.it("caches the normalised observation for METAR_CACHE_TTL")
    def test_cache_store(self, get):
        get.return_value = response(body=fixture("pilots_latest"))
        obs = get_latest_observation("EGLL")
        metar.check_cache.assert_called_once_with("metar:v1:EGLL")
        metar.cache_response.assert_called_once_with(
            "metar:v1:EGLL",
            obs.model_dump(mode="json"),
            metar.settings.METAR_CACHE_TTL,
        )

    @pytest.mark.it("serves a cached observation without calling AWC")
    def test_cache_hit(self, get):
        cached = observe("pilots_latest", "EGLL").model_dump(mode="json")
        metar.check_cache.return_value = cached
        obs = get_latest_observation("EGLL")
        assert obs == Observation.model_validate(cached)
        assert obs.fetched_at == FETCHED_AT  # original fetch time is kept
        get.assert_not_called()

    @pytest.mark.it("serves a cached 'no report' without calling AWC")
    def test_cached_no_report(self, get):
        metar.check_cache.return_value = dict(NO_REPORT)
        assert get_latest_observation("ZZZZ") is None
        get.assert_not_called()

    @pytest.mark.it("refetches when the cached value has an invalid schema")
    def test_invalid_cached_schema(self, get):
        metar.check_cache.return_value = {"station": "EGLL"}
        get.return_value = response(body=fixture("pilots_latest"))
        assert get_latest_observation("EGLL").station == "EGLL"
        get.assert_called_once()

    @pytest.mark.it("does not use a rate-limit token for a cache hit")
    def test_cache_hit_no_token(self, get, monkeypatch):
        monkeypatch.setattr(metar, "rate_limiter", RateLimiter(1))
        metar.rate_limiter.acquire()
        metar.check_cache.return_value = observe("pilots_latest", "EGLL").model_dump(
            mode="json"
        )
        assert get_latest_observation("EGLL")


@pytest.mark.describe("METAR rate limiting")
class TestRateLimiter:
    @pytest.mark.it("allows the configured number of requests, then refills")
    def test_bucket(self):
        now = [0.0]
        limiter = RateLimiter(2, clock=lambda: now[0])
        limiter.acquire()
        limiter.acquire()
        with pytest.raises(MetarRateLimited) as error:
            limiter.acquire()
        assert error.value.reason == "rate_limited"
        assert error.value.retry_after_s == pytest.approx(30)
        now[0] = 30
        limiter.acquire()

    @pytest.mark.it("counts each retry attempt against the budget")
    def test_retries_use_tokens(self, get, monkeypatch):
        monkeypatch.setattr(metar, "rate_limiter", RateLimiter(1))
        get.side_effect = requests.Timeout()
        with pytest.raises(MetarRateLimited):
            get_latest_observation("EGLL")
        assert get.call_count == 1

    @pytest.mark.it("keeps the first failure as the cause when the retry is blocked")
    def test_blocked_retry_keeps_cause(self, get, monkeypatch):
        monkeypatch.setattr(metar, "rate_limiter", RateLimiter(1))
        get.side_effect = requests.Timeout()
        with pytest.raises(MetarRateLimited) as error:
            get_latest_observation("EGLL")
        assert isinstance(error.value.__cause__, MetarTimeout)

    @pytest.mark.it("raises MetarRateLimited before calling AWC when exhausted")
    def test_exhausted(self, get, monkeypatch):
        monkeypatch.setattr(metar, "rate_limiter", RateLimiter(1))
        metar.rate_limiter.acquire()
        with pytest.raises(MetarRateLimited):
            get_latest_observation("EGLL")
        get.assert_not_called()


@pytest.mark.describe("METAR settings")
class TestSettings:
    @pytest.mark.it("reads METAR settings from the environment")
    def test_env(self, monkeypatch):
        from app.core.config import Settings

        values = {
            "METAR_USER_AGENT": "test-agent",
            "METAR_CACHE_TTL": "900",
            "METAR_NO_DATA_CACHE_TTL": "120",
            "METAR_RATE_LIMIT_PER_MINUTE": "12",
            "METAR_CURRENT_MAX_MINUTES": "60",
            "METAR_STALE_MAX_MINUTES": "120",
        }
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        config = Settings()
        for name, value in values.items():
            assert str(getattr(config, name)) == value


@pytest.mark.describe("METAR lookups when Redis is down")
class TestRedisOutage:
    @pytest.mark.it("falls back to the provider when Redis fails")
    def test_redis_down(self, get, monkeypatch):
        import redis

        from app.services import cache

        monkeypatch.setattr(metar, "check_cache", cache.check_cache)
        monkeypatch.setattr(metar, "cache_response", cache.cache_response)
        down = mock.Mock()
        down.get.side_effect = redis.ConnectionError("down")
        down.setex.side_effect = redis.ConnectionError("down")
        monkeypatch.setattr(cache, "redis_client", down)
        get.return_value = response(body=fixture("pilots_latest"))
        assert get_latest_observation("EGLL").station == "EGLL"
        get.assert_called_once()
