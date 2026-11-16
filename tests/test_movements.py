import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import cache, positions_service
from app.services import movements as mv
from app.services.metar import MetarUpstreamError
from app.services.positions import Area, FeedResult, Target, distance_nm
from app.services.positions_providers import AdsbLol, ProviderDisabled, QuotaExhausted

"""
Test suite for movement detection (CF-011 design r3 §3-§5): recorded tracks
from the 2026-11-15 probes, then synthetic tracks for each rule.
"""

FIXTURES = Path(__file__).parent / "testfiles" / "movements"
UTC = timezone.utc
T0 = datetime(2026, 11, 15, 7, 0, tzinfo=UTC)

# A synthetic airport at the origin with a neighbour 5 nm east (Northolt-like).
HOME = mv.Place("HOME", 0.0, 0.0)
EAST = mv.Place("EAST", 0.0, 5 / 60)
CTX = mv.AirportContext("HOME", 0.0, 0.0, 100, (HOME, EAST))


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def nm_east(nm: float) -> float:
    return nm / 60  # longitude degrees at the equator


def target(
    id="abc123",
    lon_nm=0.5,
    state="ground",
    alt=None,
    vr=None,
    category="A3",
    callsign="TST1",
):
    on_ground = state == "ground"
    altitude = None if on_ground or state == "unknown" else alt
    return Target(
        id=id,
        callsign=callsign,
        latitude=0.0,
        longitude=nm_east(lon_nm),
        altitude_ft=altitude,
        on_ground=on_ground,
        ground_speed_kt=None,
        track_deg=None,
        vertical_rate_fpm=vr,
        category=category,
        kind="aircraft",
        position_at=T0,
        distance_nm=abs(lon_nm),
    )


def poll(minutes: float, *targets, stale_s: float = 0, dropped: int = 0) -> FeedResult:
    t = at(minutes)
    return FeedResult(
        provider="adsblol",
        access="keyless",
        observed_at=t - timedelta(seconds=stale_s),
        fetched_at=t,
        targets=list(targets),
        dropped=dropped,
    )


def run(*polls, ctx=CTX, state=None):
    state = state or mv.empty_state()
    for p in polls:
        state = (
            mv.record_failure(state, p)
            if isinstance(p, str)
            else mv.detect(state, p, ctx)
        )
    return state


def kinds(state):
    return [(m["kind"], m["method"]) for m in state["movements"]]


@pytest.mark.describe("Recorded tracks (CF-011 probes, 2026-11-15)")
class TestRecorded:
    def replay(self, name, code):
        data = json.loads((FIXTURES / f"{name}_15min.json").read_text())
        ctx = mv.context_for(code)
        area = Area(ctx.latitude, ctx.longitude, 25.0)
        state = mv.empty_state()
        for p in data["polls"]:
            fetched = datetime.strptime(p["fetched_at"], "%Y%m%dT%H%M%S").replace(
                tzinfo=UTC
            )
            state = mv.detect(state, AdsbLol.parse(p["body"], area, fetched), ctx)
        counts = {}
        for m in state["movements"]:
            counts[(m["kind"], m["method"])] = (
                counts.get((m["kind"], m["method"]), 0) + 1
            )
        return state, counts

    @pytest.mark.it("KJFK: observed departures and arrivals with surface coverage")
    def test_kjfk(self):
        state, counts = self.replay("kjfk", "KJFK")
        assert counts == {("departure", "observed"): 10, ("arrival", "observed"): 5}
        assert mv.coverage_mode(state)[0] == "surface"

    @pytest.mark.it("WSSS: no ground fixes, so inferred movements only")
    def test_wsss(self):
        state, counts = self.replay("wsss", "WSSS")
        assert counts == {("departure", "inferred"): 7, ("arrival", "inferred"): 5}
        assert mv.coverage_mode(state)[0] == "airborne_only"

    @pytest.mark.it(
        "RKSI: mixed, one movement per aircraft; no transition across a missed poll"
    )
    def test_rksi(self):
        # Six aircraft vanish for a poll or more between their ground and air
        # fixes: not consecutive (not observed), but inferred across the gap
        # (spec §3, 2026-11-16).
        state, counts = self.replay("rksi", "RKSI")
        assert counts == {
            ("departure", "inferred"): 3,
            ("arrival", "observed"): 1,
            ("arrival", "inferred"): 9,
        }
        ids = [m["id"] for m in state["movements"]]
        assert len(ids) == len(set(ids))


@pytest.mark.describe("Observed movements")
class TestObserved:
    @pytest.mark.it(
        "ground then airborne at consecutive polls is a departure, attributed at the ground fix"
    )
    def test_departure(self):
        state = run(
            poll(0, target()), poll(0.5, target(state="air", alt=300, lon_nm=1.5))
        )
        assert kinds(state) == [("departure", "observed")]
        m = state["movements"][0]
        assert (m["time_from"], m["time_to"]) == (
            at(0).isoformat(),
            at(0.5).isoformat(),
        )
        assert m["distance_nm"] == 0.5  # the ground fix, not the airborne one

    @pytest.mark.it(
        "airborne then ground is an arrival, attributed at the first ground fix"
    )
    def test_arrival(self):
        state = run(
            poll(0, target(state="air", alt=200, lon_nm=2)),
            poll(0.5, target(lon_nm=0.3)),
        )
        assert kinds(state) == [("arrival", "observed")]
        assert state["movements"][0]["distance_nm"] == 0.3

    @pytest.mark.it("a gap over 90 s between the fixes is no movement")
    def test_gap(self):
        state = run(poll(0, target()), poll(2, target(state="air", alt=300)))
        assert kinds(state) == []

    @pytest.mark.it(
        "an unknown fix (no altitude) neither completes nor breaks a transition"
    )
    def test_unknown(self):
        assert kinds(run(poll(0, target()), poll(0.5, target(state="unknown")))) == []
        state = run(
            poll(0, target()),
            poll(0.5, target(state="unknown")),
            poll(1, target(state="air", alt=400)),
        )
        assert kinds(state) == [("departure", "observed")]

    @pytest.mark.it("a failed poll between the fixes ends the window: no movement")
    def test_failed_poll(self):
        state = run(
            poll(0, target()), "provider_error", poll(0.5, target(state="air", alt=300))
        )
        assert kinds(state) == []
        assert state["windows"][0]["ended_by"] == "provider_error"

    @pytest.mark.it("a stale provider answer is a failed poll")
    def test_unusable(self):
        # Newer than the last poll, but its data is 70 s older than its fetch.
        state = run(
            poll(0, target()), poll(1.5, target(state="air", alt=300), stale_s=70)
        )
        assert kinds(state) == [] and state["windows"][0]["ended_by"] == "unusable"

    @pytest.mark.it(
        "a replayed data time is a no-op: state unchanged, the next transition still found"
    )
    def test_replay_noop(self):
        state = run(poll(0), poll(0.5, target()))
        before = json.dumps(state, sort_keys=True)
        state = mv.detect(state, poll(0.5, target(state="air", alt=300)), CTX)
        assert json.dumps(state, sort_keys=True) == before
        state = run(poll(1, target(state="air", alt=300)), state=state)
        assert kinds(state) == [("departure", "observed")]

    @pytest.mark.it(
        "an aircraft absent between its fixes is inferred, never observed (§3 gap rule)"
    )
    def test_absent_between(self):
        state = run(poll(0, target()), poll(0.5), poll(1, target(state="air", alt=300)))
        assert kinds(state) == [("departure", "inferred")]
        m = state["movements"][0]
        assert (m["time_from"], m["time_to"], m["distance_nm"]) == (
            at(0).isoformat(),
            at(1).isoformat(),
            0.5,
        )

    @pytest.mark.it("infers an arrival across a gap, attributed at the ground fix")
    def test_gap_arrival(self):
        state = run(
            poll(0, target(state="air", alt=300, lon_nm=2)),
            poll(0.5),
            poll(1, target(lon_nm=0.4)),
        )
        assert kinds(state) == [("arrival", "inferred")]
        assert state["movements"][0]["distance_nm"] == 0.4

    @pytest.mark.it("allows up to 120 s across the gap, not more")
    def test_gap_limit(self):
        assert (
            kinds(
                run(
                    poll(0, target()),
                    poll(0.5),
                    poll(1),
                    poll(1.5),
                    poll(2),
                    poll(2.5, target(state="air", alt=300)),  # 150 s
                )
            )
            == []
        )
        exactly = run(
            poll(0, target()),
            poll(0.5),
            poll(1),
            poll(1.5),
            poll(2, target(state="air", alt=300)),
        )
        assert kinds(exactly) == [("departure", "inferred")]  # 120 s is allowed
        state = run(
            poll(0, target()),
            poll(0.5),
            poll(1),
            poll(1.5, target(state="air", alt=300)),
        )
        assert kinds(state) == [("departure", "inferred")]

    @pytest.mark.it("infers nothing across a failed poll (the window ended)")
    def test_gap_failed_poll(self):
        assert (
            kinds(
                run(
                    poll(0, target()),
                    "provider_error",
                    poll(0.5, target(state="air", alt=300)),
                )
            )
            == []
        )

    @pytest.mark.it(
        "drops a gap movement whose ground fix isn't attributed to the airport"
    )
    def test_gap_attribution(self):
        state = run(
            poll(0, target(lon_nm=4.6)),
            poll(0.5),
            poll(1, target(state="air", alt=300, lon_nm=0.5)),
        )
        assert kinds(state) == []

    @pytest.mark.it("an answer with only dropped rows is unusable")
    def test_all_dropped(self):
        state = run(poll(0, dropped=4))
        assert state["windows"] == [] and state["window"] is None

    @pytest.mark.it(
        "attributes to the nearest airport, drops ambiguous or distant fixes (V2)"
    )
    @pytest.mark.parametrize(
        "ground_nm, expected",
        [
            (0.5, 1),
            (4.6, 0),
            (2.3, 0),  # HOME 2.3 nm, EAST 2.7 nm: within 1 nm, ambiguous
            (-4.5, 0),
        ],  # home; nearer EAST; ambiguous; >4 nm
    )
    def test_attribution(self, ground_nm, expected):
        state = run(
            poll(0, target(lon_nm=ground_nm)),
            poll(0.5, target(state="air", alt=300, lon_nm=ground_nm)),
        )
        assert len(state["movements"]) == expected

    @pytest.mark.it(
        "attributes by the ground fix even when the climb-out passes nearer a neighbour"
    )
    def test_ground_fix_decides(self):
        state = run(
            poll(0, target(lon_nm=0.5)),
            poll(0.5, target(state="air", alt=300, lon_nm=4.6)),
        )
        assert kinds(state) == [("departure", "observed")]

    @pytest.mark.it("ignores helicopters (V6)")
    def test_helicopter(self):
        state = run(
            poll(0, target(category="A7")),
            poll(0.5, target(state="air", alt=300, category="A7")),
        )
        assert kinds(state) == []

    @pytest.mark.it("records one departure per aircraft per 10 minutes")
    def test_dedupe(self):
        state = run(
            poll(0, target()),
            poll(0.5, target(state="air", alt=300)),
            poll(1, target(state="air", alt=200, lon_nm=0.4)),
            poll(1.5, target()),
            poll(2, target(state="air", alt=300)),
        )
        assert kinds(state) == [("departure", "observed"), ("arrival", "observed")]


@pytest.mark.describe("Inferred movements (V1, V3)")
class TestInferred:
    def climbing(self, **kw):
        return target(**{"state": "air", "alt": 900, "vr": 1500, "lon_nm": 1.0, **kw})

    @pytest.mark.it("first seen low, close and climbing is an inferred departure")
    def test_departure(self):
        state = run(poll(0), poll(0.5, self.climbing()))
        assert kinds(state) == [("departure", "inferred")]

    @pytest.mark.it("is never inferred on the first poll of a window")
    def test_window_edge(self):
        assert kinds(run(poll(0, self.climbing()))) == []
        assert kinds(run(poll(0), "busy", poll(0.5, self.climbing()))) == []

    @pytest.mark.it("needs low, close, climbing and a known field elevation")
    @pytest.mark.parametrize(
        "change",
        [
            {"alt": 1700},
            {"lon_nm": 2.5},
            {"vr": 100},
            {"vr": None},
        ],  # 1600 AGL; >2 nm; slow; no rate
    )
    def test_guards(self, change):
        assert kinds(run(poll(0), poll(0.5, self.climbing(**change)))) == []
        no_elevation = mv.AirportContext("HOME", 0.0, 0.0, None, (HOME, EAST))
        assert kinds(run(poll(0), poll(0.5, self.climbing()), ctx=no_elevation)) == []

    @pytest.mark.it(
        "last seen low and descending, then absent for 2 polls, is an inferred arrival"
    )
    def test_arrival(self):
        descending = target(state="air", alt=400, vr=-700, lon_nm=1.2)
        state = run(poll(0, descending), poll(0.5), poll(1))
        assert kinds(state) == [("arrival", "inferred")]
        assert state["movements"][0]["time_to"] == at(1).isoformat()

    @pytest.mark.it(
        "needs 2 consecutive absent polls: an unknown-altitude fix in between resets it"
    )
    def test_arrival_unknown_resets(self):
        descending = target(state="air", alt=400, vr=-700, lon_nm=1.2)
        state = run(
            poll(0, descending), poll(0.5), poll(1, target(state="unknown")), poll(1.5)
        )
        assert kinds(state) == []

    @pytest.mark.it("isn't confirmed if the window ends before 2 absent polls")
    def test_arrival_window_end(self):
        descending = target(state="air", alt=400, vr=-700, lon_nm=1.2)
        assert (
            kinds(run(poll(0, descending), poll(0.5), "quota_exhausted", poll(1))) == []
        )

    @pytest.mark.it(
        "is withdrawn when the aircraft reappears airborne within 10 minutes (go-around)"
    )
    def test_withdrawn(self):
        descending = target(state="air", alt=400, vr=-700, lon_nm=1.2)
        state = run(poll(0, descending), poll(0.5), poll(1))
        assert kinds(state) == [("arrival", "inferred")]
        state = run(
            poll(1.5, target(state="air", alt=1200, vr=1800, lon_nm=1.5)), state=state
        )
        assert ("arrival", "inferred") not in kinds(state)

    @pytest.mark.it(
        "isn't inferred when the aircraft had an observed movement within 10 minutes"
    )
    def test_after_observed(self):
        state = run(
            poll(0, target()),
            poll(0.5, target(state="air", alt=300, vr=1500)),
            poll(1, target(state="air", alt=600, vr=-700, lon_nm=1)),
            poll(1.5),
            poll(2),
        )
        assert kinds(state) == [("departure", "observed")]


@pytest.mark.describe("Windows, retention and coverage")
class TestWindowsCoverage:
    @pytest.mark.it("joins usable polls within 90 s into a window and ends it at a gap")
    def test_windows(self):
        state = run(poll(0), poll(0.5), poll(1), poll(5), poll(5.5))
        assert state["windows"] == [
            {"from": at(0).isoformat(), "to": at(1).isoformat(), "ended_by": "gap"}
        ]
        assert state["window"]["from"] == at(5).isoformat()

    @pytest.mark.it("drops movements and windows older than 6 hours")
    def test_retention(self):
        state = run(poll(0, target()), poll(0.5, target(state="air", alt=300)))
        state = run(poll(6 * 60 + 1), state=state)
        assert state["movements"] == []

    @pytest.mark.it("reports coverage modes, never a claim of no coverage")
    def test_modes(self):
        assert mv.coverage_mode(run(poll(0))) == ("unknown", "not_enough_watching")
        quiet = run(*[poll(i / 2) for i in range(12)])
        assert mv.coverage_mode(quiet) == ("unknown", "no_recent_data")
        high = run(
            *[
                poll(i / 2, target(state="air", alt=9000, vr=0, lon_nm=1))
                for i in range(12)
            ]
        )
        assert mv.coverage_mode(high) == ("unknown", "no_low_traffic_seen")
        low = run(
            *[
                poll(
                    i / 2, target(id=f"a{i:05x}", state="air", alt=500, vr=0, lon_nm=1)
                )
                for i in range(12)
            ]
        )
        assert mv.coverage_mode(low) == ("airborne_only", None)
        ground = run(*[poll(i / 2, target(id=f"g{i:05x}")) for i in range(12)])
        assert mv.coverage_mode(ground) == ("surface", None)
        # One ground fix is evidence against airborne_only, though not enough for surface.
        mixed = [
            poll(i / 2, target(id=f"a{i:05x}", state="air", alt=500, vr=0, lon_nm=1))
            for i in range(11)
        ]
        mixed = run(*mixed, poll(5.5, target(id="g00001")))
        assert mv.coverage_mode(mixed) == ("unknown", "not_enough_watching")


@pytest.fixture
def fake_redis():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.mark.describe("Store: exactly once, failures and partial loss (spec §5)")
class TestStore:
    @pytest.fixture(autouse=True)
    def home_context(self):
        with mock.patch.object(mv, "context_for", return_value=CTX):
            yield

    @pytest.mark.it("applies each poll once; replaying the same data time is a no-op")
    def test_once(self, fake_redis):
        mv.observe(fake_redis, "adsblol", "HOME", poll(0, target()))
        mv.observe(
            fake_redis, "adsblol", "HOME", poll(0.5, target(state="air", alt=300))
        )
        mv.observe(
            fake_redis, "adsblol", "HOME", poll(0.5, target(state="air", alt=300))
        )
        state = mv.read(fake_redis, "adsblol", "HOME", at(1))
        assert kinds(state) == [("departure", "observed")]
        assert fake_redis.get("movements:v1:adsblol:HOME:last") == at(0.5).isoformat()

    @pytest.mark.it(
        "refuses a write whose expected last poll is out of date (concurrency)"
    )
    def test_cas(self, fake_redis):
        state, last = mv.load(fake_redis, "adsblol", "HOME")
        mv.observe(fake_redis, "adsblol", "HOME", poll(0, target()))
        assert (
            mv.save(
                fake_redis, "adsblol", "HOME", mv.detect(state, poll(0.2), CTX), last
            )
            is False
        )

    @pytest.mark.it("treats a lost or out-of-step key as a window break")
    def test_partial_loss(self, fake_redis):
        mv.observe(fake_redis, "adsblol", "HOME", poll(0, target()))
        fake_redis.delete("movements:v1:adsblol:HOME:last")
        mv.observe(
            fake_redis, "adsblol", "HOME", poll(0.5, target(state="air", alt=300))
        )
        state = mv.read(fake_redis, "adsblol", "HOME", at(1))
        assert kinds(state) == [] and state["windows"][0]["ended_by"] == "state_lost"

    @pytest.mark.it("records a failed poll, ending the window")
    def test_failed_poll(self, fake_redis):
        mv.observe(fake_redis, "adsblol", "HOME", poll(0, target()))
        mv.record_failed_poll(fake_redis, "adsblol", "HOME", "quota_exhausted")
        mv.observe(
            fake_redis, "adsblol", "HOME", poll(0.5, target(state="air", alt=300))
        )
        state = mv.read(fake_redis, "adsblol", "HOME", at(1))
        assert (
            kinds(state) == [] and state["windows"][0]["ended_by"] == "quota_exhausted"
        )

    @pytest.mark.it(
        "never raises: a detector failure is logged and recorded as a failed poll"
    )
    def test_never_raises(self, fake_redis):
        mv.observe(fake_redis, "adsblol", "HOME", poll(0, target()))
        with mock.patch.object(mv, "detect", side_effect=ValueError("boom")):
            mv.observe(
                fake_redis, "adsblol", "HOME", poll(0.5, target(state="air", alt=300))
            )
        state = mv.read(fake_redis, "adsblol", "HOME", at(1))
        assert state["windows"][-1]["ended_by"] == "detector_error"

    @pytest.mark.it(
        "applies a replay without writing; a later transition is still found"
    )
    def test_replay_store(self, fake_redis):
        mv.observe(fake_redis, "adsblol", "HOME", poll(0))
        mv.observe(fake_redis, "adsblol", "HOME", poll(0.5, target()))
        before = fake_redis.get("movements:v1:adsblol:HOME")
        mv.observe(
            fake_redis, "adsblol", "HOME", poll(0.5, target(state="air", alt=300))
        )
        assert fake_redis.get("movements:v1:adsblol:HOME") == before
        mv.observe(fake_redis, "adsblol", "HOME", poll(1, target(state="air", alt=300)))
        assert kinds(mv.read(fake_redis, "adsblol", "HOME", at(1.2))) == [
            ("departure", "observed")
        ]

    @pytest.mark.it("closes an open window at read time once nobody is watching")
    def test_read_closes_window(self, fake_redis):
        mv.observe(fake_redis, "adsblol", "HOME", poll(0))
        mv.observe(fake_redis, "adsblol", "HOME", poll(0.5))
        assert mv.read(fake_redis, "adsblol", "HOME", at(1))["window"] is not None
        state = mv.read(fake_redis, "adsblol", "HOME", at(3))
        assert state["window"] is None
        assert state["windows"] == [
            {"from": at(0).isoformat(), "to": at(0.5).isoformat(), "ended_by": "gap"}
        ]
        assert mv.read(fake_redis, "adsblol", "HOME", at(7 * 60))["windows"] == []

    @pytest.mark.it("expires state with a TTL and filters retention at read time")
    def test_ttl(self, fake_redis):
        mv.observe(fake_redis, "adsblol", "HOME", poll(0, target()))
        assert 0 < fake_redis.ttl("movements:v1:adsblol:HOME") <= mv.STATE_TTL_S
        mv.observe(
            fake_redis, "adsblol", "HOME", poll(0.5, target(state="air", alt=300))
        )
        assert mv.read(fake_redis, "adsblol", "HOME", at(7 * 60))["movements"] == []


@pytest.mark.describe("Context")
class TestContext:
    @pytest.mark.it(
        "includes the airport and its catalogue neighbours within 10 nm (EGLL: Northolt)"
    )
    def test_neighbours(self):
        ctx = mv.context_for("EGLL")
        codes = {p.code for p in ctx.neighbours}
        assert {"EGLL", "EGWU"} <= codes and ctx.elevation_ft == 83
        assert all(
            distance_nm(ctx.latitude, ctx.longitude, p.latitude, p.longitude) <= 10
            for p in ctx.neighbours
        )


LHR = (51.470748, -0.459909)


def lhr_target(state, alt=None, id="abc123"):
    return Target(
        id=id, callsign="BAW1", latitude=LHR[0], longitude=LHR[1], altitude_ft=alt,
        on_ground=state == "ground", ground_speed_kt=None, track_deg=None, vertical_rate_fpm=None,
        category="A3", kind="aircraft", position_at=T0, distance_nm=0.0,
    )  # fmt: skip


def get_movements(client, code, redis_client, now):
    with mock.patch.object(cache, "redis_client", redis_client), mock.patch(
        "app.api.movements.utc_now", return_value=now
    ):
        return client.get(f"/v1/airports/{code}/movements")


@pytest.mark.describe("Movements endpoint")
class TestEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def watched(self, fake_redis):
        mv.observe(fake_redis, "adsblol", "EGLL", poll(0, lhr_target("ground")))
        mv.observe(fake_redis, "adsblol", "EGLL", poll(0.5, lhr_target("air", 300)))
        return fake_redis

    @pytest.mark.it("returns movements newest first, watched windows and validation")
    def test_available(self, client, watched):
        body = get_movements(client, "lhr", watched, at(1)).json()
        assert body["data_status"] == "available"
        assert [(m["kind"], m["method"], m["callsign"]) for m in body["movements"]] == [
            ("departure", "observed", "BAW1")
        ]
        assert body["watched"] == [
            {
                "from": "2026-11-15T07:00:00Z",
                "to": "2026-11-15T07:00:30Z",
                "ended_by": None,
            }
        ]
        assert body["validation"] == {
            "observed": "experimental",
            "inferred": "experimental",
            "airport": "experimental",
        }
        assert body["source"]["name"] == "adsb.lol (ODbL 1.0)"
        assert "not an official departures board" in body["disclaimer"]

    @pytest.mark.it("never lists movements older than 6 hours")
    def test_retention(self, client, watched):
        assert (
            get_movements(client, "LHR", watched, at(6 * 60 + 2)).json()["movements"]
            == []
        )

    @pytest.mark.it("lists at most 100, newest first")
    def test_cap(self, client, fake_redis):
        state = mv.empty_state()
        state["last_poll"] = at(0).isoformat()
        state["movements"] = [
            {"kind": "arrival", "method": "observed", "id": f"{i:06x}", "callsign": None,
             "time_from": at(i / 10).isoformat(), "time_to": at(i / 10).isoformat(), "distance_nm": 1.0}
            for i in range(150)
        ]  # fmt: skip
        fake_redis.set("movements:v1:adsblol:EGLL", json.dumps(state))
        fake_redis.set("movements:v1:adsblol:EGLL:last", state["last_poll"])
        listed = get_movements(client, "LHR", fake_redis, at(20)).json()["movements"]
        assert len(listed) == 100 and listed[0]["time_to"] > listed[-1]["time_to"]

    @pytest.mark.it("says not watched when nobody has viewed the airport")
    def test_not_watched(self, client, fake_redis):
        body = get_movements(client, "LHR", fake_redis, at(1)).json()
        assert (body["data_status"], body["unavailable_reason"], body["movements"]) == (
            "unavailable",
            "not_watched",
            [],
        )

    @pytest.mark.it("says the store is unavailable when Redis fails")
    def test_store_down(self, client):
        broken = mock.Mock()
        broken.get.side_effect = __import__("redis").ConnectionError("down")
        body = get_movements(client, "LHR", broken, at(1)).json()
        assert body["unavailable_reason"] == "store_unavailable"

    @pytest.mark.it("reports a validated airport from the P5 results")
    def test_validation(self, client, watched):
        with mock.patch.dict(
            "app.api.movements.VALIDATION",
            {"EGLL": {"observed": "validated", "airport": "validated"}},
        ):
            body = get_movements(client, "LHR", watched, at(1)).json()
        assert body["validation"] == {
            "observed": "validated",
            "inferred": "experimental",
            "airport": "validated",
        }

    @pytest.mark.it("rejects bad and unknown codes")
    def test_codes(self, client, fake_redis):
        assert get_movements(client, "L!", fake_redis, at(1)).status_code == 400
        assert get_movements(client, "QQQ", fake_redis, at(1)).status_code == 404


@pytest.mark.describe("Positions hook: once per fresh fetch, failures recorded")
class TestHook:
    @pytest.fixture(autouse=True)
    def fresh(self):
        positions_service._providers.clear()
        yield
        positions_service._providers.clear()

    def area(self):
        return Area(LHR[0], LHR[1], 25.0)

    @pytest.mark.it(
        "runs detection once per fresh fetch, before the cache is published, never on a cache hit"
    )
    def test_once(self, fake_redis):
        provider = positions_service.get_provider()
        order = []
        result = poll(0, lhr_target("ground"))
        with mock.patch.object(cache, "redis_client", fake_redis), mock.patch.object(
            provider, "fetch", return_value=result
        ), mock.patch.object(
            mv, "observe", side_effect=lambda *a: order.append("observe")
        ), mock.patch.object(
            positions_service, "store", side_effect=lambda *a: order.append("store")
        ):
            positions_service.get_positions("EGLL", self.area())
        assert order == ["observe", "store"]
        fake_redis.set("positions:v1:adsblol:EGLL", json.dumps(result.to_dict()))
        with mock.patch.object(cache, "redis_client", fake_redis), mock.patch.object(
            mv, "observe"
        ) as observe:
            positions_service.get_positions("EGLL", self.area())
        assert not observe.called

    @pytest.mark.it("records a failed fetch as a failed poll with its reason")
    @pytest.mark.parametrize(
        "error, reason",
        [
            (QuotaExhausted("daily_budget", None), "quota_exhausted"),
            (MetarUpstreamError("requests_busy"), "busy"),
            (MetarUpstreamError("http_502"), "provider_error"),
        ],
    )
    def test_failure(self, fake_redis, error, reason):
        provider = positions_service.get_provider()
        with mock.patch.object(cache, "redis_client", fake_redis), mock.patch.object(
            provider, "fetch", side_effect=error
        ), mock.patch.object(mv, "record_failed_poll") as record:
            with pytest.raises(type(error)):
                positions_service.get_positions("EGLL", self.area())
        record.assert_called_once_with(fake_redis, "adsblol", "EGLL", reason)

    @pytest.mark.it("records nothing when the provider is disabled (no poll happened)")
    def test_disabled(self, fake_redis):
        with mock.patch.object(
            positions_service, "get_provider", side_effect=ProviderDisabled("x")
        ), mock.patch.object(mv, "record_failed_poll") as record:
            with pytest.raises(ProviderDisabled):
                positions_service.get_positions("EGLL", self.area())
        assert not record.called

    @pytest.mark.it("records an unexpected provider failure as a failed poll too")
    def test_unexpected_failure(self, fake_redis):
        provider = positions_service.get_provider()
        with mock.patch.object(cache, "redis_client", fake_redis), mock.patch.object(
            provider, "fetch", side_effect=KeyError("bad row")
        ), mock.patch.object(mv, "record_failed_poll") as record:
            with pytest.raises(KeyError):
                positions_service.get_positions("EGLL", self.area())
        record.assert_called_once_with(fake_redis, "adsblol", "EGLL", "provider_error")
