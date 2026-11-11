import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fakeredis
import pytest
import redis
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import cache, nearby, radar
from app.services.metar import MetarRateLimited, MetarTimeout, MetarUpstreamError
from app.services.positions import Area

"""
Test suite for the CF-010 map layers (design r3 §4-§5):
GET /v1/airports/{code}/nearby-conditions and GET /v1/map/radar.
"""

FIXTURES = Path(__file__).parent / "testfiles"
UTC = timezone.utc
EGLL = Area(51.4706, -0.4619, 50)


def bbox_records():
    return json.loads((FIXTURES / "awc" / "metar_bbox_egll.json").read_text())


def fetched_time():
    """A clock just after the recorded observations."""
    latest = max(r["obsTime"] for r in bbox_records())
    return datetime.fromtimestamp(latest, UTC) + timedelta(minutes=5)


def rainviewer_index(**changes):
    now = int(datetime(2026, 11, 11, 12, 30, tzinfo=UTC).timestamp())
    index = {
        "version": "2.0",
        "generated": now,
        "host": "https://tilecache.rainviewer.com",
        "radar": {
            "past": [
                {"time": now - 600 * i, "path": f"/v2/radar/abc{i}"}
                for i in range(3, -1, -1)
            ],
            "nowcast": [],
        },
    }
    index.update(changes)
    return index


NOW = datetime(2026, 11, 11, 12, 35, tzinfo=UTC)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def fresh_radar_cap():
    """The radar rate cap is per process; each test starts with a full one."""
    from app.services.metar import RateLimiter

    with mock.patch.object(radar, "rate_limiter", RateLimiter(6)):
        yield


@pytest.fixture
def fake_redis():
    server = fakeredis.FakeStrictRedis(decode_responses=True)
    with mock.patch.object(cache, "redis_client", server):
        yield server


@pytest.mark.describe("Nearby stations: parsing (spec §4)")
class TestNearbyParse:
    @pytest.mark.it("keeps stations within 50 nm, sorted, excluding the airport itself")
    def test_parse(self):
        result = nearby.parse_nearby(bbox_records(), EGLL, "EGLL", fetched_time())
        stations = [s["station"] for s in result["stations"]]
        assert "EGLL" not in stations and len(stations) >= 10
        distances = [s["distance_nm"] for s in result["stations"]]
        assert distances == sorted(distances) and max(distances) <= 50
        assert result["complete"] and result["dropped"] == 0

    @pytest.mark.it("drops records with bad stations or coordinates, and counts them")
    @pytest.mark.parametrize(
        "change",
        [{"lat": None}, {"lon": 999}, {"icaoId": "X"}, {"lat": "51"}, {"icaoId": None}],
    )
    def test_invalid(self, change):
        records = bbox_records()
        records[0] = {**records[0], **change}
        result = nearby.parse_nearby(records, EGLL, None, fetched_time())
        assert result["dropped"] == 1

    @pytest.mark.it("keeps one entry per station, the latest observation")
    def test_dedupe(self):
        records = bbox_records()
        first = next(r for r in records if r["icaoId"] != "EGLL")
        older = {**first, "obsTime": first["obsTime"] - 3600, "rawOb": "older"}
        result = nearby.parse_nearby(records + [older], EGLL, None, fetched_time())
        same = [s for s in result["stations"] if s["station"] == first["icaoId"]]
        assert len(same) == 1 and same[0]["observation"].raw_text != "older"

    @pytest.mark.it("marks a capped answer (400 records) as incomplete")
    def test_cap(self):
        records = (bbox_records() * 20)[:400]
        assert (
            nearby.parse_nearby(records, EGLL, None, fetched_time())["complete"]
            is False
        )

    @pytest.mark.it("builds the AWC bbox from the area")
    def test_bbox(self):
        (box,) = nearby.bboxes(EGLL)
        lat0, lon0, lat1, lon1 = map(float, box.split(","))
        assert lat0 < 51.47 < lat1 and lon0 < -0.46 < lon1
        assert lat1 - lat0 == pytest.approx(100 / 60, abs=0.01)


@pytest.mark.describe("Nearby stations: cache (spec §4, D-007)")
class TestNearbyCache:
    def run(self, records, fake_redis, now=None):
        with mock.patch(
            "app.services.nearby.fetch_metar_records", return_value=records
        ) as fetch, mock.patch("app.services.nearby.datetime") as clock:
            clock.now.return_value = now or fetched_time()
            clock.fromisoformat = datetime.fromisoformat
            result = nearby.get_nearby("EGLL", EGLL, "EGLL")
        return result, fetch

    @pytest.mark.it("queries AWC with a bbox once and caches for 10 minutes")
    def test_cache(self, fake_redis):
        result, fetch = self.run(bbox_records(), fake_redis)
        assert fetch.call_args.args[2] == {"bbox": nearby.bboxes(EGLL)[0]}
        assert 590 < fake_redis.ttl("nearby:v1:EGLL") <= 600
        again, fetch = self.run(bbox_records(), fake_redis)
        assert not fetch.called
        assert [s["station"] for s in again["stations"]] == [
            s["station"] for s in result["stations"]
        ]

    @pytest.mark.it("caches an answer that is stale as a whole for only 60 s")
    def test_all_stale(self, fake_redis):
        self.run(bbox_records(), fake_redis, now=fetched_time() + timedelta(hours=2))
        assert 0 < fake_redis.ttl("nearby:v1:EGLL") <= 60

    @pytest.mark.it("caches an empty answer for 5 minutes")
    def test_empty(self, fake_redis):
        result, _ = self.run([], fake_redis)
        assert result["records"] == 0 and 290 < fake_redis.ttl("nearby:v1:EGLL") <= 300


def get_nearby(client, code, result=None, error=None, now=None):
    with mock.patch(
        "app.api.nearby.get_nearby", return_value=result, side_effect=error
    ), mock.patch("app.api.nearby.utc_now", return_value=now or fetched_time()):
        return client.get(f"/v1/airports/{code}/nearby-conditions")


@pytest.mark.describe("Nearby conditions endpoint")
class TestNearbyEndpoint:
    def result(self, records=None, now=None):
        return nearby.parse_nearby(
            bbox_records() if records is None else records,
            EGLL,
            "EGLL",
            now or fetched_time(),
        )

    @pytest.mark.it("returns scored current stations with freshness times")
    def test_available(self, client):
        body = get_nearby(client, "lhr", self.result()).json()
        assert body["data_status"] == "available" and body["complete"]
        first = body["stations"][0]
        assert first["data_status"] == "current"
        assert first["conditions"]["explanation"].startswith(
            ("Observed conditions index", "No score")
        )
        assert first["current_until"] < first["stale_until"]
        assert body["source"].startswith("NOAA")

    @pytest.mark.it("shows stale stations unscored and drops expired ones")
    def test_ageing(self, client):
        stale = get_nearby(
            client, "LHR", self.result(), now=fetched_time() + timedelta(minutes=100)
        ).json()
        assert {s["data_status"] for s in stale["stations"]} == {"stale"}
        assert all(s["conditions"]["score"] is None for s in stale["stations"])
        gone = get_nearby(
            client, "LHR", self.result(), now=fetched_time() + timedelta(hours=4)
        ).json()
        assert (gone["stations"], gone["data_status"], gone["unavailable_reason"]) == (
            [],
            "unavailable",
            "reports_too_old",
        )

    @pytest.mark.it("distinguishes no stations from unusable data")
    def test_empty_states(self, client):
        empty = get_nearby(client, "LHR", self.result([])).json()
        assert empty["unavailable_reason"] == "no_stations"
        bad = [{**r, "lat": None} for r in bbox_records()]
        unusable = get_nearby(client, "LHR", self.result(bad)).json()
        assert (unusable["unavailable_reason"], unusable["dropped"]) == (
            "unusable_data",
            len(bad),
        )

    @pytest.mark.it("maps provider failures and bad codes")
    @pytest.mark.parametrize(
        "error, status",
        [
            (MetarTimeout("timeout"), 504),
            (MetarUpstreamError("http_500"), 502),
            (MetarRateLimited(3), 503),
        ],
    )
    def test_errors(self, client, error, status):
        assert get_nearby(client, "LHR", error=error).status_code == status
        assert get_nearby(client, "L!").status_code == 400
        assert get_nearby(client, "QQQ").status_code == 404


@pytest.mark.describe("Radar index validation (trust boundary, spec §5)")
class TestRadarValidation:
    @pytest.mark.it("returns the latest frame on RainViewer's tile host only")
    def test_latest(self):
        frame = radar.latest_frame(rainviewer_index(), NOW)
        assert frame["time"] == datetime(2026, 11, 11, 12, 30, tzinfo=UTC)
        assert (
            frame["tile_url"]
            == "https://tilecache.rainviewer.com/v2/radar/abc0/256/{z}/{x}/{y}/2/1_0.png"
        )
        assert frame["current_until"] == frame["time"] + timedelta(minutes=20)

    @pytest.mark.it("rejects an unexpected host, path or frame")
    @pytest.mark.parametrize(
        "index",
        [
            rainviewer_index(host="https://evil.example"),
            rainviewer_index(host="http://tilecache.rainviewer.com"),
            rainviewer_index(
                radar={"past": [{"time": 1794400200, "path": "/v2/radar/../../x"}]}
            ),
            rainviewer_index(
                radar={"past": [{"time": 1794400200, "path": "//evil.example/a"}]}
            ),
            rainviewer_index(
                radar={"past": [{"time": "1794400200", "path": "/v2/radar/a"}]}
            ),
            rainviewer_index(radar={"past": "nope"}),
            [],
        ],
    )
    def test_invalid(self, index):
        with pytest.raises(MetarUpstreamError) as e:
            radar.latest_frame(index, NOW)
        assert e.value.reason == "invalid_index"

    @pytest.mark.it("reports no frames when every frame is too old or empty")
    @pytest.mark.parametrize("past", [[], [{"time": 1000, "path": "/v2/radar/old"}]])
    def test_no_frames(self, past):
        with pytest.raises(MetarUpstreamError) as e:
            radar.latest_frame(rainviewer_index(radar={"past": past}), NOW)
        assert e.value.reason == "no_frames"


class Reply:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.body = body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.fixture
def radar_on():
    with mock.patch.multiple(settings, RAINVIEWER_EDUCATIONAL_USE=True):
        yield


@pytest.mark.describe("Radar service: gate, cache, budget (spec §5)")
class TestRadarService:
    @pytest.mark.it("fetches nothing when the licence gate is off")
    def test_gate(self, fake_redis):
        with mock.patch("app.services.radar.get") as get:
            with pytest.raises(radar.RadarDisabled):
                radar.get_radar(NOW)
        assert not get.called

    @pytest.mark.it("caches the index for 5 minutes")
    def test_cache(self, fake_redis, radar_on):
        with mock.patch(
            "app.services.radar.get", return_value=Reply(body=rainviewer_index())
        ) as get:
            radar.get_radar(NOW)
            radar.get_radar(NOW)
        assert get.call_count == 1 and 290 < fake_redis.ttl(radar.CACHE_KEY) <= 300

    @pytest.mark.it("backs off for 60 s after a failure")
    def test_negative_cache(self, fake_redis, radar_on):
        with mock.patch("app.services.radar.get", return_value=Reply(503)) as get:
            with pytest.raises(MetarUpstreamError):
                radar.get_radar(NOW)
            with pytest.raises(MetarUpstreamError):
                radar.get_radar(NOW)
        assert get.call_count == 1 and 0 < fake_redis.ttl(radar.FAILED_KEY) <= 60

    @pytest.mark.it("doesn't back off when only our own rate cap was hit")
    def test_own_cap(self, fake_redis, radar_on):
        with mock.patch.object(
            radar.rate_limiter, "acquire", side_effect=MetarRateLimited(5)
        ):
            with pytest.raises(MetarRateLimited):
                radar.get_radar(NOW)
        assert not fake_redis.exists(radar.FAILED_KEY)

    @pytest.mark.it("lets concurrent misses share one index fetch")
    def test_single_flight(self, fake_redis, radar_on):
        def slow(*args, **kwargs):
            time.sleep(0.4)
            return Reply(body=rainviewer_index())

        results = []
        with mock.patch(
            "app.services.radar.get", side_effect=slow
        ) as get, mock.patch.object(radar, "WAIT_POLL_S", 0.05):
            threads = [
                threading.Thread(target=lambda: results.append(radar.get_radar(NOW)))
                for _ in range(5)
            ]
            [t.start() for t in threads]
            [t.join() for t in threads]
        assert get.call_count == 1 and len(results) == 5

    @pytest.mark.it("still works, capped and uncached, without Redis")
    def test_no_redis(self, radar_on):
        broken = mock.Mock()
        broken.get.side_effect = redis.ConnectionError("down")
        with mock.patch.object(cache, "redis_client", broken), mock.patch(
            "app.services.radar.get", return_value=Reply(body=rainviewer_index())
        ):
            assert radar.get_radar(NOW)["time"].minute == 30


@pytest.mark.describe("Radar endpoint")
class TestRadarEndpoint:
    def call(self, client, reply=None, error=None):
        with mock.patch(
            "app.services.radar.get", return_value=reply, side_effect=error
        ), mock.patch("app.api.radar.utc_now", return_value=NOW):
            return client.get("/v1/map/radar")

    @pytest.mark.it("says provider_disabled when the gate is off")
    def test_disabled(self, client, fake_redis):
        body = self.call(client).json()
        assert (
            body["enabled"],
            body["data_status"],
            body["unavailable_reason"],
            body["frame"],
        ) == (
            False,
            "unavailable",
            "provider_disabled",
            None,
        )

    @pytest.mark.it("returns the latest frame with attribution")
    def test_available(self, client, fake_redis, radar_on):
        body = self.call(client, Reply(body=rainviewer_index())).json()
        assert body["data_status"] == "available" and body["enabled"]
        assert body["frame"]["tile_url"].startswith(
            "https://tilecache.rainviewer.com/v2/radar/"
        )
        assert body["attribution"] == "Radar © RainViewer"

    @pytest.mark.it("reports an invalid index or no frames as states, not errors")
    @pytest.mark.parametrize(
        "index, reason",
        [
            (rainviewer_index(host="https://evil.example"), "invalid_index"),
            (rainviewer_index(radar={"past": []}), "no_frames"),
        ],
    )
    def test_states(self, client, fake_redis, radar_on, index, reason):
        response = self.call(client, Reply(body=index))
        assert response.status_code == 200
        assert (response.json()["enabled"], response.json()["unavailable_reason"]) == (
            True,
            reason,
        )

    @pytest.mark.it("maps provider failures to 502/504")
    @pytest.mark.parametrize(
        "error, status",
        [
            (MetarTimeout("deadline"), 504),
            (MetarUpstreamError("connection_error"), 502),
        ],
    )
    def test_errors(self, client, fake_redis, radar_on, error, status):
        assert self.call(client, error=error).status_code == status


@pytest.mark.describe("Review round 1 fixes (CF-010)")
class TestReviewRound1:
    @pytest.mark.it("queries both sides of the date line and merges them")
    def test_date_line(self, fake_redis):
        labasa = Area(-16.4667, 179.34, 50)  # NFNL; Matei (NFNM) is across ±180
        east = {
            "icaoId": "NFNM",
            "lat": -16.69,
            "lon": -179.88,
            "name": "Matei",
            "obsTime": 1794268800,
        }
        west = {
            "icaoId": "NFNS",
            "lat": -16.80,
            "lon": 179.34,
            "name": "Savusavu",
            "obsTime": 1794268800,
        }
        replies = [[west], [east]]
        with mock.patch(
            "app.services.nearby.fetch_metar_records",
            side_effect=lambda *a: replies.pop(0),
        ) as fetch:
            result = nearby.get_nearby("NFNL", labasa, "NFNL")
        assert fetch.call_count == 2
        assert {s["station"] for s in result["stations"]} >= {
            "NFNS"
        }  # the parsed ones within 50 nm
        assert len(nearby.bboxes(labasa)) == 2

    @pytest.mark.it(
        "marks the answer incomplete when either date-line query hits the cap"
    )
    def test_date_line_cap(self, fake_redis):
        labasa = Area(-16.4667, 179.34, 50)
        capped = [{"icaoId": "XXXX", "lat": 0, "lon": 0, "obsTime": 1}] * 400
        replies = [capped, []]
        with mock.patch(
            "app.services.nearby.fetch_metar_records",
            side_effect=lambda *a: replies.pop(0),
        ):
            assert nearby.get_nearby("NFNL", labasa, "NFNL")["complete"] is False

    @pytest.mark.it(
        "says reports_too_old, not no_stations, when every report has expired"
    )
    def test_reports_too_old(self, client):
        result = nearby.parse_nearby(bbox_records(), EGLL, "EGLL", fetched_time())
        body = get_nearby(
            client, "LHR", result, now=fetched_time() + timedelta(hours=4)
        ).json()
        assert (body["data_status"], body["unavailable_reason"]) == (
            "unavailable",
            "reports_too_old",
        )

    @pytest.mark.it("re-checks the radar cache after taking the lock")
    def test_radar_recheck(self, fake_redis, radar_on):
        real_acquire = radar.Lock.acquire

        def acquire(lock):
            fake_redis.set(radar.CACHE_KEY, json.dumps(rainviewer_index()), ex=300)
            return real_acquire(lock)

        with mock.patch.object(radar.Lock, "acquire", acquire), mock.patch(
            "app.services.radar.get"
        ) as get:
            assert radar.get_radar(NOW)["time"].minute == 30
        assert not get.called

    @pytest.mark.it(
        "keeps an invalid index a 200 state for every caller in the back-off"
    )
    def test_radar_reason_kept(self, client, fake_redis, radar_on):
        with mock.patch(
            "app.services.radar.get", return_value=Reply(body=ValueError("not json"))
        ), mock.patch("app.api.radar.utc_now", return_value=NOW):
            first = client.get("/v1/map/radar")
            second = client.get("/v1/map/radar")
        assert [r.status_code for r in (first, second)] == [200, 200]
        assert [r.json()["unavailable_reason"] for r in (first, second)] == [
            "invalid_index",
            "invalid_index",
        ]
