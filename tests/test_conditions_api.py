import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest
import redis
import requests
from fastapi.testclient import TestClient

from app.main import app
from app.services import aviationstack, cache, metar, unrecognised_weather, weatherstack
from app.services.metar import (
    MetarRateLimited,
    MetarTimeout,
    MetarUpstreamError,
    RateLimiter,
    select_observation,
)

"""
Test suite for GET /v1/airports/{code}/conditions, /health and legacy cache keys
"""

FIXTURES = Path(__file__).parent / "testfiles" / "awc"


@pytest.fixture
def client():
    return TestClient(app)


def records(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def observation(name, station, age_minutes=20):
    """A fixture observation re-dated to age_minutes ago."""
    now = datetime.now(timezone.utc)
    obs = select_observation(records(name), station, now)
    return obs.model_copy(
        update={"observed_at": now - timedelta(minutes=age_minutes), "fetched_at": now}
    )


def get_conditions(client, code, result=None, error=None):
    with mock.patch(
        "app.api.conditions.get_latest_observation",
        return_value=result,
        side_effect=error,
    ) as lookup:
        response = client.get(f"/v1/airports/{code}/conditions")
    return response, lookup


@pytest.mark.describe("Conditions endpoint: current observations")
class TestCurrent:
    @pytest.mark.it("returns airport, observation, score and status")
    def test_current(self, client):
        obs = observation("pilots_latest", "EGLL", age_minutes=35)
        with mock.patch("app.api.conditions.utc_now", return_value=obs.fetched_at):
            response, lookup = get_conditions(client, "lhr", obs)
        assert response.status_code == 200
        lookup.assert_called_once_with("EGLL")
        body = response.json()
        assert body["airport"] == {
            "code": "EGLL",
            "icao": "EGLL",
            "iata": "LHR",
            "name": "London Heathrow Airport",
            "city": "London",
            "country": "United Kingdom",
            "country_code": "GB",
            "timezone": "Europe/London",
        }
        assert body["data_status"] == "current"
        assert body["unavailable_reason"] is None
        assert body["observation"]["age_minutes"] == 35
        assert body["observation"]["source"] == "Aviation Weather Center"
        assert body["observation"]["raw_text"].startswith("METAR EGLL")
        assert body["last_observed_at"] == body["observation"]["observed_at"]
        assert body["conditions"]["score"] == 8
        assert body["conditions"]["level"] == "severe"
        assert [f["name"] for f in body["conditions"]["factors"]] == [
            "wind",
            "visibility",
            "ceiling",
            "weather",
        ]
        assert "not a forecast" in body["conditions"]["disclaimer"]

    @pytest.mark.it("scores the recorded fixtures as expected")
    @pytest.mark.parametrize(
        "code, fixture, station, score, level",
        [
            ("KIX", "pilots_latest", "RJBB", 5, "moderate"),
            ("JFK", "pilots_latest", "KJFK", 2, "low"),
            ("EGKK", "egkk_obscured_fog", "EGKK", 10, "severe"),
            ("PANC", "panc_10plus_gust_rain", "PANC", 6, "high"),
            ("ZBAA", "zbaa_mps_gust", "ZBAA", 4, "moderate"),
            ("LEMD", "lemd_vrb_cavok", "LEMD", 0, "low"),
            ("DNMM", "dnmm_garbled", "DNMM", 0, "low"),
        ],
    )
    def test_fixture_scores(self, client, code, fixture, station, score, level):
        response, _ = get_conditions(client, code, observation(fixture, station))
        conditions = response.json()["conditions"]
        assert (conditions["score"], conditions["level"]) == (score, level)


@pytest.mark.describe("Conditions endpoint: freshness")
class TestFreshness:
    @pytest.mark.it("shows a stale observation without a score")
    def test_stale(self, client):
        response, _ = get_conditions(
            client, "EGLL", observation("pilots_latest", "EGLL", age_minutes=120)
        )
        body = response.json()
        assert body["data_status"] == "stale"
        assert body["observation"]["visibility_m"] == 1304
        assert (body["conditions"]["score"], body["conditions"]["level"]) == (
            None,
            "unknown",
        )

    @pytest.mark.it("returns no values for an expired observation, only its time")
    def test_expired(self, client):
        obs = observation("pilots_latest", "EGLL", age_minutes=200)
        response, _ = get_conditions(client, "EGLL", obs)
        body = response.json()
        assert response.status_code == 200
        assert body["data_status"] == "unavailable"
        assert body["unavailable_reason"] == "observation_too_old"
        assert body["observation"] is None
        assert datetime.fromisoformat(body["last_observed_at"]) == obs.observed_at
        assert body["conditions"]["score"] is None

    @pytest.mark.it("follows configured freshness thresholds, one clock per request")
    @pytest.mark.parametrize(
        "age, status, scored",
        [(29, "current", True), (31, "stale", False), (61, "unavailable", False)],
    )
    def test_configured_thresholds(self, client, monkeypatch, age, status, scored):
        monkeypatch.setattr(metar.settings, "METAR_CURRENT_MAX_MINUTES", 30)
        monkeypatch.setattr(metar.settings, "METAR_STALE_MAX_MINUTES", 60)
        obs = observation("pilots_latest", "KJFK", age_minutes=age)
        body = get_conditions(client, "KJFK", obs)[0].json()
        assert body["data_status"] == status
        assert (body["conditions"]["score"] is not None) == scored

    @pytest.mark.it("switches status exactly at the thresholds, with age rounded up")
    @pytest.mark.parametrize(
        "age, status, shown_age",
        [
            (timedelta(minutes=90), "current", 90),
            (timedelta(minutes=90, seconds=1), "stale", 91),
            (timedelta(minutes=90, seconds=24), "stale", 91),
            (timedelta(minutes=180), "stale", 180),
            (timedelta(minutes=180, seconds=1), "unavailable", None),
        ],
    )
    def test_exact_boundaries(self, client, age, status, shown_age):
        obs = observation("pilots_latest", "KJFK")
        now = obs.observed_at + age
        with mock.patch("app.api.conditions.utc_now", return_value=now):
            body = get_conditions(client, "KJFK", obs)[0].json()
        assert body["data_status"] == status
        observation_body = body["observation"] or {}
        assert observation_body.get("age_minutes") == shown_age
        assert (body["conditions"]["score"] is not None) == (status == "current")

    @pytest.mark.it("reports age 0 for an observation slightly in the future")
    def test_future_age(self, client):
        obs = observation("pilots_latest", "KJFK", age_minutes=-5)
        body = get_conditions(client, "KJFK", obs)[0].json()
        assert (body["data_status"], body["observation"]["age_minutes"]) == (
            "current",
            0,
        )


@pytest.mark.describe("Conditions endpoint: unavailable data")
class TestUnavailable:
    @pytest.mark.it("returns 200 'no_report' when the station has no report")
    def test_no_report(self, client):
        response, _ = get_conditions(client, "RJBB", None)
        body = response.json()
        assert response.status_code == 200
        assert (body["data_status"], body["unavailable_reason"]) == (
            "unavailable",
            "no_report",
        )
        assert body["observation"] is None and body["last_observed_at"] is None
        assert body["airport"]["code"] == "RJBB"

    @pytest.mark.it("returns 200 'no_metar_station' for an airport without ICAO")
    def test_no_station(self, client):
        response, lookup = get_conditions(client, "AAI")
        body = response.json()
        assert response.status_code == 200
        assert body["unavailable_reason"] == "no_metar_station"
        assert body["airport"]["icao"] is None and body["airport"]["code"] == "AAI"
        lookup.assert_not_called()


@pytest.mark.describe("Conditions endpoint: errors")
class TestErrors:
    @pytest.mark.it("returns 400 for a badly formed code")
    @pytest.mark.parametrize(
        "code", ["XX", "EGLLX", "L1R", "EG-L", "%20", "ſfo", "ıCAO"]
    )
    def test_invalid_code(self, client, code):
        response, lookup = get_conditions(client, code)
        assert response.status_code == 400
        assert response.json()["reason"] == "invalid_code"
        lookup.assert_not_called()

    @pytest.mark.it("returns 404 for an unknown airport")
    @pytest.mark.parametrize("code", ["ZZZ", "ZZZZ"])
    def test_not_found(self, client, code):
        response, _ = get_conditions(client, code)
        assert response.status_code == 404
        assert response.json() == {
            "detail": f"No airport with code {code}",
            "reason": "airport_not_found",
        }

    @pytest.mark.it("maps provider failures to 502, 503 and 504")
    @pytest.mark.parametrize(
        "error, status, reason",
        [
            (MetarTimeout("timeout"), 504, "provider_timeout"),
            (MetarUpstreamError("http_500"), 502, "provider_error"),
            (MetarUpstreamError("invalid_json"), 502, "provider_error"),
        ],
    )
    def test_provider_errors(self, client, error, status, reason):
        response, _ = get_conditions(client, "EGLL", error=error)
        assert response.status_code == status
        assert response.json()["reason"] == reason
        assert "access_key" not in response.text

    @pytest.mark.it("returns 503 with Retry-After when the budget is used up")
    @pytest.mark.parametrize("retry_after, header", [(0.2, "1"), (12.3, "13")])
    def test_rate_limited(self, client, retry_after, header):
        response, _ = get_conditions(
            client, "EGLL", error=MetarRateLimited(retry_after)
        )
        assert response.status_code == 503
        assert response.headers["Retry-After"] == header
        assert response.json()["reason"] == "rate_limited"


class FakeRedis:
    """In-memory stand-in for the Redis client."""

    def __init__(self):
        self.data = {}
        self.hashes = {}

    def get(self, key):
        return self.data.get(key)

    def setex(self, key, ttl, value):
        self.data[key] = value

    def eval(self, script, numkeys, *args):
        # Emulates unrecognised_weather.RECORD_SCRIPT (atomic in real Redis)
        assert "HINCRBY" in script and numkeys == 3
        seen_key, counts_key, examples_key, _ttl, group, example = args
        if seen_key in self.data:
            return 0
        self.data[seen_key] = 1
        self.hincrby(counts_key, group, 1)
        self.hset(examples_key, group, example)
        return 1

    def hincrby(self, key, field, amount):
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = str(int(bucket.get(field, 0)) + amount)

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))


def awc_response(status=200, body=None):
    resp = mock.Mock(status_code=status, headers={})
    resp.json.return_value = body
    return resp


def fresh_records(station="KJFK", age_minutes=20):
    obs_time = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return [
        {**r, "obsTime": int(obs_time.timestamp())}
        for r in records("pilots_latest")
        if r["icaoId"] == station
    ]


@pytest.mark.describe("Conditions endpoint through the real METAR adapter")
class TestComposed:
    @pytest.fixture(autouse=True)
    def adapter(self, monkeypatch):
        monkeypatch.setattr(metar, "rate_limiter", RateLimiter(10))
        monkeypatch.setattr(metar.time, "sleep", mock.Mock())
        self.redis = FakeRedis()
        monkeypatch.setattr(cache, "redis_client", self.redis)
        with mock.patch.object(metar.requests, "get") as get:
            self.get = get
            yield

    @pytest.mark.it("caches the observation and serves the next request from cache")
    def test_cache_hit(self, client):
        self.get.return_value = awc_response(body=fresh_records())
        first = client.get("/v1/airports/JFK/conditions").json()
        second = client.get("/v1/airports/KJFK/conditions").json()
        assert self.get.call_count == 1
        assert "metar:v1:KJFK" in self.redis.data
        assert first["observation"]["fetched_at"] == second["observation"]["fetched_at"]
        assert second["data_status"] == "current"

    @pytest.mark.it("falls back to the provider when Redis is down")
    def test_redis_down(self, client, monkeypatch):
        down = mock.Mock()
        down.get.side_effect = redis.ConnectionError("down")
        down.setex.side_effect = redis.ConnectionError("down")
        monkeypatch.setattr(cache, "redis_client", down)
        self.get.return_value = awc_response(body=fresh_records())
        response = client.get("/v1/airports/KJFK/conditions")
        assert response.status_code == 200
        assert response.json()["data_status"] == "current"

    @pytest.mark.it("returns 503 with Retry-After once the budget is used up")
    def test_budget_exhausted(self, client, monkeypatch):
        monkeypatch.setattr(metar, "rate_limiter", RateLimiter(1))
        self.get.return_value = awc_response(status=204)
        assert client.get("/v1/airports/EGLL/conditions").status_code == 200
        response = client.get("/v1/airports/KJFK/conditions")
        assert response.status_code == 503
        assert int(response.headers["Retry-After"]) >= 1

    @pytest.mark.it("returns 'no_report' on 204 and caches it")
    def test_no_content(self, client):
        self.get.return_value = awc_response(status=204)
        body = client.get("/v1/airports/EGLL/conditions").json()
        assert body["unavailable_reason"] == "no_report"
        client.get("/v1/airports/EGLL/conditions")
        assert self.get.call_count == 1

    @pytest.mark.it("returns 504 after repeated provider timeouts")
    def test_timeout(self, client):
        self.get.side_effect = requests.Timeout()
        response = client.get("/v1/airports/EGLL/conditions")
        assert response.status_code == 504
        assert self.get.call_count == 2


@pytest.mark.describe("Capturing unrecognised weather groups")
class TestUnrecognisedCapture:
    @pytest.fixture
    def fake_redis(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "redis_client", fake)
        return fake

    def odd_observation(self):
        return observation("pilots_latest", "EGLL").model_copy(
            update={"weather_phenomena": ["XYZ", "-RA", "QQ"]}
        )

    @pytest.mark.it("counts each group once per observation, keeping an example")
    def test_counts_once(self, client, fake_redis):
        obs = self.odd_observation()
        for _ in range(3):
            body = get_conditions(client, "EGLL", obs)[0].json()
        assert body["conditions"]["level"] == "unknown"
        rows = unrecognised_weather.summary()
        assert [(r["group"], r["count"]) for r in rows] == [("QQ", 1), ("XYZ", 1)]
        assert rows[0]["example"]["station"] == "EGLL"
        assert rows[0]["example"]["raw_text"].startswith("METAR EGLL")

    @pytest.mark.it("counts a group again for a new observation")
    def test_new_observation(self, client, fake_redis):
        first = self.odd_observation()
        later = first.model_copy(
            update={"observed_at": first.observed_at + timedelta(minutes=5)}
        )
        get_conditions(client, "EGLL", first)
        get_conditions(client, "EGLL", later)
        counts = {r["group"]: r["count"] for r in unrecognised_weather.summary()}
        assert counts == {"QQ": 2, "XYZ": 2}

    @pytest.mark.it("doesn't record anything for recognised weather")
    def test_recognised(self, client, fake_redis):
        get_conditions(client, "EGLL", observation("pilots_latest", "EGLL"))
        assert unrecognised_weather.summary() == []

    @pytest.mark.it("counts the observation once Redis recovers from a failure")
    def test_failure_then_recovery(self, fake_redis, monkeypatch):
        obs = self.odd_observation()
        real_eval = fake_redis.eval
        monkeypatch.setattr(
            fake_redis, "eval", mock.Mock(side_effect=redis.ConnectionError("down"))
        )
        unrecognised_weather.record(obs, ["XYZ"])
        assert unrecognised_weather.summary() == []
        monkeypatch.setattr(fake_redis, "eval", real_eval)
        unrecognised_weather.record(obs, ["XYZ"])
        assert [(r["group"], r["count"]) for r in unrecognised_weather.summary()] == [
            ("XYZ", 1)
        ]

    @pytest.mark.it("sends one atomic script with the marker, count and example")
    def test_atomic_script(self, monkeypatch):
        client = mock.Mock()
        monkeypatch.setattr(cache, "redis_client", client)
        obs = self.odd_observation()
        unrecognised_weather.record(obs, ["XYZ"])
        script, numkeys, seen_key, counts_key, examples_key, ttl, group, example = (
            client.eval.call_args[0]
        )
        assert script == unrecognised_weather.RECORD_SCRIPT and numkeys == 3
        assert seen_key.endswith(f"EGLL:{obs.observed_at.isoformat()}:XYZ")
        assert (counts_key, examples_key) == (
            unrecognised_weather.COUNTS_KEY,
            unrecognised_weather.EXAMPLES_KEY,
        )
        assert (ttl, group) == (unrecognised_weather.SEEN_TTL, "XYZ")
        assert json.loads(example)["station"] == "EGLL"

    @pytest.mark.it("still answers when Redis is down")
    def test_redis_down(self, client, monkeypatch):
        down = mock.Mock()
        down.eval.side_effect = redis.ConnectionError("down")
        monkeypatch.setattr(cache, "redis_client", down)
        response, _ = get_conditions(client, "EGLL", self.odd_observation())
        assert response.status_code == 200

    @pytest.mark.it("lists recorded groups with the script")
    def test_script(self, fake_redis, capsys):
        import importlib.util

        path = (
            Path(__file__).resolve().parent.parent
            / "scripts"
            / "unrecognised_weather.py"
        )
        spec = importlib.util.spec_from_file_location(
            "unrecognised_weather_script", path
        )
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        assert script.main() == 0
        assert "No unrecognised weather groups recorded." in capsys.readouterr().out
        unrecognised_weather.record(self.odd_observation(), ["XYZ"])
        script.main()
        output = capsys.readouterr().out
        assert output.startswith("XYZ: 1 observation(s); last at EGLL")


@pytest.mark.describe("Health check")
class TestHealth:
    @pytest.mark.it("GET /health returns ok")
    def test_health(self, client):
        response = client.get("/health")
        assert (response.status_code, response.json()) == (200, {"status": "ok"})


@pytest.mark.describe("Legacy provider cache keys exclude access keys")
class TestLegacyCacheKeys:
    def airport_key(self, code, api_key):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"data": [{"airport_name": "x"}]}
        with mock.patch.object(
            aviationstack, "check_cache", return_value=None
        ), mock.patch.object(aviationstack, "cache_response"), mock.patch.object(
            aviationstack.requests, "get", return_value=response
        ), mock.patch.object(
            aviationstack, "get_cache_key", wraps=cache.get_cache_key
        ) as key:
            aviationstack.get_airport_info(code, as_api_key=api_key)
        return key.call_args[0][0], cache.get_cache_key(key.call_args[0][0])

    def weather_key(self, api_key, lat="51.47", lon="-0.45"):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"current": {}}
        with mock.patch.object(
            weatherstack, "check_cache", return_value=None
        ), mock.patch.object(weatherstack, "cache_response"), mock.patch.object(
            weatherstack.requests, "get", return_value=response
        ), mock.patch.object(
            weatherstack, "get_cache_key", wraps=cache.get_cache_key
        ) as key:
            weatherstack.get_current_weather_info(lat, lon, ws_api_key=api_key)
        return key.call_args[0][0], cache.get_cache_key(key.call_args[0][0])

    @pytest.mark.it("AviationStack hashes a key-free string")
    def test_aviationstack(self):
        hashed_input, key_a = self.airport_key("JFK", "secret-a")
        _, key_b = self.airport_key("JFK", "secret-b")
        _, key_other = self.airport_key("KJFK", "secret-a")
        assert hashed_input == "aviationstack:airports:iata_code=JFK"
        assert "secret" not in hashed_input
        assert key_a == key_b != key_other

    @pytest.mark.it("WeatherStack hashes a key-free string")
    def test_weatherstack(self):
        hashed_input, key_a = self.weather_key("secret-a")
        _, key_b = self.weather_key("secret-b")
        _, key_other = self.weather_key("secret-a", lat="34.43")
        assert hashed_input == "weatherstack:current:query=51.47,-0.45"
        assert "secret" not in hashed_input
        assert key_a == key_b != key_other
