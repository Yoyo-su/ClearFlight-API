import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import taf
from app.services.metar import MetarRateLimited, MetarTimeout, MetarUpstreamError

"""
Test suite for the TAF forecast outlook (CF-008 design spec r3) and
GET /v1/airports/{code}/forecast
"""

FIXTURES = Path(__file__).parent / "testfiles" / "awc"
# The recorded TAFs were issued around 2300Z on 8 Nov 2026, valid 09/00Z-10/06Z.
NOW = datetime(2026, 11, 9, 7, 30, tzinfo=timezone.utc)


def utc(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


def record(name, station):
    rows = json.loads((FIXTURES / f"{name}.json").read_text())
    return next(r for r in rows if r["icaoId"] == station)


def outlook(name, station, now=NOW):
    meta, periods = taf.parse_taf(record(name, station), station)
    return taf.hourly_outlook(meta, periods, now)


def scores(hours):
    return [h["prevailing"]["conditions"]["score"] for h in hours]


def possible(hour):
    return [(p["label"], p["conditions"]["score"]) for p in hour["possible"]]


@pytest.mark.describe("TAF parsing: raw groups and field presence")
class TestParse:
    @pytest.mark.it("splits the raw TAF into change groups, PROB30 TEMPO as one")
    def test_raw_groups(self):
        groups = taf.raw_groups(record("taf_pilots", "EGLL")["rawTAF"])
        assert [(c, p) for c, p, _ in groups] == [
            (None, None),
            ("TEMPO", 30),
            ("BECMG", None),
            ("BECMG", None),
            ("TEMPO", 30),
            ("TEMPO", 30),
            ("TEMPO", 30),
        ]

    @pytest.mark.it("reads FM groups and PROB40 without TEMPO")
    def test_fm_and_prob(self):
        kjfk = taf.raw_groups(record("taf_pilots", "KJFK")["rawTAF"])
        assert [c for c, _, _ in kjfk] == [None, "FM", "FM", "FM"]
        egkk = taf.raw_groups(record("taf_egkk_tempo_prob", "EGKK")["rawTAF"])
        assert ("PROB", 40) in [(c, p) for c, p, _ in egkk]

    @pytest.mark.it(
        "inherits elements a TEMPO group omits, including AWC's empty visibility"
    )
    def test_omitted_inherits(self):
        _, periods = taf.parse_taf(record("taf_pilots", "EGLL"), "EGLL")
        cloud_only = periods[4]  # PROB30 TEMPO 0912/0919 BKN010, visib ""
        assert cloud_only.change == "TEMPO"
        assert cloud_only.elements["visibility"] is taf.OMITTED
        assert cloud_only.elements["sky"] == {
            "sky_condition": "clouds",
            "ceiling_ft": 1000,
        }

    @pytest.mark.it(
        "treats a stated but unreadable element as unknown, never inherited"
    )
    def test_stated_unusable_is_unknown(self):
        rec = record("taf_pilots", "EGLL")
        rec["fcsts"][1]["clouds"][0]["base"] = None  # the raw TEMPO group states BKN005
        _, periods = taf.parse_taf(rec, "EGLL")
        assert periods[1].elements["sky"] is taf.UNKNOWN
        state = taf.EMPTY_STATE.with_elements(periods[0].elements).with_elements(
            periods[1].elements
        )
        assert state.sky_condition == "unknown"  # not the base's "obscured"
        kjfk = record("taf_pilots", "KJFK")
        kjfk["fcsts"][1]["visib"] = "nonsense"  # the raw FM group states P6SM
        _, periods = taf.parse_taf(kjfk, "KJFK")
        assert periods[1].elements["visibility"] is taf.UNKNOWN

    @pytest.mark.it(
        "reads base VV/// as obscured, metric visibility exactly, and NSW as no weather"
    )
    def test_values(self):
        _, periods = taf.parse_taf(record("taf_pilots", "EGLL"), "EGLL")
        base = periods[0].elements
        assert base["sky"] == {"sky_condition": "obscured", "ceiling_ft": None}
        assert base["visibility"] == {"visibility_m": 150, "visibility_at_least": False}
        assert periods[2].elements["weather"] == {"weather_phenomena": ()}  # NSW

    @pytest.mark.it("reads P6SM as 6 SM or more and 9999 as 10 km or more")
    def test_visibility_or_more(self):
        _, kjfk = taf.parse_taf(record("taf_pilots", "KJFK"), "KJFK")
        assert kjfk[0].elements["visibility"] == {
            "visibility_m": 9656,
            "visibility_at_least": True,
        }
        _, rjbb = taf.parse_taf(record("taf_pilots", "RJBB"), "RJBB")
        assert rjbb[0].elements["visibility"] == {
            "visibility_m": 10000,
            "visibility_at_least": True,
        }

    @pytest.mark.it(
        "treats a base or FM group without weather as no significant weather"
    )
    def test_base_without_weather(self):
        _, periods = taf.parse_taf(record("taf_pilots", "KJFK"), "KJFK")
        assert all(p.elements["weather"] == {"weather_phenomena": ()} for p in periods)

    @pytest.mark.it("makes the wind unknown when a stated gust can't be read")
    @pytest.mark.parametrize("wgst", [None, 999, 10])
    def test_unreadable_gust(self, wgst):
        rec = record("taf_pilots", "KJFK")
        rec["rawTAF"] = rec["rawTAF"].replace("26014KT", "26014G55KT", 1)
        rec["fcsts"][0]["wgst"] = wgst
        _, periods = taf.parse_taf(rec, "KJFK")
        assert periods[0].elements["wind"] is taf.UNKNOWN
        rec["fcsts"][0]["wgst"] = 55
        _, periods = taf.parse_taf(rec, "KJFK")
        assert periods[0].elements["wind"]["wind_gust_kt"] == 55

    @pytest.mark.it("reads a vertical visibility with a height as a ceiling")
    def test_vertical_visibility(self):
        _, periods = taf.parse_taf(record("taf_eham_variants", "EHAM"), "EHAM")
        skies = [
            p.elements["sky"] for p in periods if isinstance(p.elements["sky"], dict)
        ]
        assert {"sky_condition": "clouds", "ceiling_ft": 100} in skies

    @pytest.mark.it(
        "makes every period unknown when raw and decoded groups don't align"
    )
    def test_misaligned(self):
        rec = record("taf_pilots", "EGLL")
        rec["fcsts"][2]["fcstChange"] = "TEMPO"  # the raw group says BECMG
        _, periods = taf.parse_taf(rec, "EGLL")
        assert all(v is taf.UNKNOWN for p in periods for v in p.elements.values())
        meta, periods = taf.parse_taf(rec, "EGLL")
        hours = taf.hourly_outlook(meta, periods, NOW)
        assert all(h["prevailing"]["conditions"]["score"] is None for h in hours)


@pytest.mark.describe("TAF validation (trust boundary)")
class TestValidation:
    @pytest.mark.it(
        "rejects a station mismatch, a missing base and periods outside validity"
    )
    @pytest.mark.parametrize(
        "change",
        [
            lambda r: r.update(icaoId="EGKK"),
            lambda r: r["fcsts"].pop(0),
            lambda r: r["fcsts"][3].update(timeTo=r["validTimeTo"] + 3600),
            lambda r: r["fcsts"][1].update(timeFrom=r["fcsts"][1]["timeTo"]),
            lambda r: r.update(validTimeTo=r["validTimeFrom"]),
            lambda r: r.update(fcsts=[]),
            lambda r: r.update(rawTAF=None),
            lambda r: r.update(issueTime="yesterday"),
        ],
    )
    def test_invalid(self, change):
        rec = record("taf_pilots", "EGLL")
        change(rec)
        with pytest.raises(MetarUpstreamError) as e:
            taf.parse_taf(rec, "EGLL")
        assert e.value.reason == "invalid_forecast"

    @pytest.mark.it("allows a transition that completes after its decoded period ends")
    def test_becoming_after_end(self):
        _, periods = taf.parse_taf(record("taf_pilots", "EGLL"), "EGLL")
        assert periods[2].becoming > periods[2].end

    @pytest.mark.it("selects the station's most recent TAF")
    def test_select(self):
        old = dict(
            record("taf_pilots", "EGLL"),
            mostRecent=0,
            issueTime="2026-11-08T17:00:00.000Z",
        )
        new = record("taf_pilots", "EGLL")
        other = record("taf_pilots", "KJFK")
        assert taf.select_taf([old, other, new], "EGLL") is new
        with pytest.raises(MetarUpstreamError):
            taf.select_taf([other], "EGLL")

    @pytest.mark.it(
        "treats an unknown change type as unknown rather than rejecting the TAF"
    )
    def test_unknown_change(self):
        rec = record("taf_kord_fm_groups", "KORD")
        rec["fcsts"][1]["fcstChange"] = "INTER"  # no matching raw group
        meta, periods = taf.parse_taf(rec, "KORD")
        hours = taf.hourly_outlook(meta, periods, NOW)
        assert scores(hours) == [None] * 12


@pytest.mark.describe("Hourly outlook")
class TestOutlook:
    @pytest.mark.it("gives 12 hourly cells from the current hour")
    def test_hours(self):
        hours = outlook("taf_pilots", "RJBB")
        assert len(hours) == 12
        assert hours[0]["start"] == utc(9, 7) and hours[-1]["end"] == utc(9, 19)
        assert scores(hours) == [2] * 12  # wind 11 kt

    @pytest.mark.it("switches state at FM times")
    def test_fm(self):
        assert scores(outlook("taf_pilots", "KJFK")) == [2] * 5 + [4] * 7

    @pytest.mark.it(
        "scores the worst candidate across overlapping BECMG transitions (F3)"
    )
    def test_overlapping_becmg(self):
        hours = outlook("taf_pilots", "EGLL")
        # Fog (10) until BECMG 0908/0912 completes; 0911/0913 overlaps it.
        assert scores(hours) == [10, 10, 10, 10, 10, 2, 2, 2, 2, 2, 2, 2]
        assert [h["prevailing"]["changing"] for h in hours[:7]] == [
            False,
            True,
            True,
            True,
            True,
            True,
            False,
        ]
        at_11 = taf.candidates_at(
            taf.parse_taf(record("taf_pilots", "EGLL"), "EGLL")[1], utc(9, 11, 30)
        )
        # Fog base, BECMG-1, and BECMG-2 applied to each of those two.
        assert len(at_11) == 4
        assert max(taf.index.evaluate_forecast(c)["score"] for c in at_11) == 10

    @pytest.mark.it("shows TEMPO and PROB states only when they could be worse")
    def test_possible(self):
        lfpg = outlook("taf_lfpg_becmg", "LFPG")
        assert scores(lfpg)[0] == 0
        assert possible(lfpg[0]) == [
            ("40% chance, temporarily", 6),
            ("30% chance, temporarily", 10),
        ]
        egll = outlook("taf_pilots", "EGLL")
        assert possible(egll[0]) == []  # prevailing is already 10
        assert possible(egll[5]) == [("30% chance, temporarily", 3)]
        eham = outlook("taf_eham_variants", "EHAM")
        assert (scores(eham)[0], possible(eham[0])) == (
            6,
            [("40% chance, temporarily", 8)],
        )

    @pytest.mark.it("shows an unscorable possible state as unknown (F5)")
    def test_possible_unknown(self):
        rec = record("taf_lfpg_becmg", "LFPG")
        rec["fcsts"][1]["clouds"][0]["base"] = None  # the raw group states BKN007
        meta, periods = taf.parse_taf(rec, "LFPG")
        hours = taf.hourly_outlook(meta, periods, NOW)
        assert ("40% chance, temporarily", None) in possible(hours[0])

    @pytest.mark.it(
        "marks hours before validity as not yet valid and cuts at validity end"
    )
    def test_coverage(self):
        early = outlook("taf_pilots", "RJBB", now=utc(8, 22, 10))
        assert [h["status"] for h in early[:2]] == ["not_yet_valid", "not_yet_valid"]
        assert early[0]["prevailing"] is None
        assert early[2]["status"] == "forecast"
        late = outlook("taf_pilots", "RJBB", now=utc(10, 2, 45))
        assert len(late) == 4 and late[-1]["end"] == utc(10, 6)

    @pytest.mark.it("makes hours no prevailing period covers unknown (a gap)")
    def test_gap(self):
        rec = record("taf_pilots", "RJBB")
        rec["fcsts"][0]["timeTo"] = rec["validTimeFrom"] + 3600  # base ends 01:00
        meta, periods = taf.parse_taf(rec, "RJBB")
        hours = taf.hourly_outlook(meta, periods, NOW)
        assert scores(hours) == [None] * 12
        assert {h["status"] for h in hours} == {"unknown"}

    @pytest.mark.it("makes an hour unknown when a gap starts part-way through it")
    def test_mid_hour_gap(self):
        rec = record("taf_pilots", "RJBB")
        rec["fcsts"][0]["timeTo"] = int(utc(9, 7, 30).timestamp())
        meta, periods = taf.parse_taf(rec, "RJBB")
        hours = taf.hourly_outlook(meta, periods, NOW)
        assert hours[0]["prevailing"]["conditions"]["score"] is None

    @pytest.mark.it("makes the sky unknown when raw and decoded cloud layers disagree")
    @pytest.mark.parametrize(
        "raw, layer, known",
        [
            ("FEW030", {"cover": "FEW", "base": 3000}, True),
            ("FEW030", {"cover": "FEW", "base": 200}, False),  # height
            ("BKN002", {"cover": "FEW", "base": 200}, False),  # cover
            ("BKN///", {"cover": "BKN", "base": 6000}, False),  # unknown ceiling height
            ("FEW///", {"cover": "FEW", "base": 6000}, True),  # not a ceiling
        ],
    )
    def test_cloud_mismatch(self, raw, layer, known):
        rec = record("taf_pilots", "RJBB")
        rec["rawTAF"] = rec["rawTAF"].replace("FEW030", raw)
        rec["fcsts"][0]["clouds"] = [dict(layer, type=None)]
        _, periods = taf.parse_taf(rec, "RJBB")
        assert (periods[0].elements["sky"] is not taf.UNKNOWN) == known

    @pytest.mark.it(
        "makes the sky unknown when raw and decoded vertical visibility disagree"
    )
    def test_vertical_visibility_mismatch(self):
        rec = record("taf_eham_variants", "EHAM")
        i = next(i for i, f in enumerate(rec["fcsts"]) if f.get("vertVis"))
        rec["fcsts"][i]["vertVis"] = 6000  # raw says VV001
        _, periods = taf.parse_taf(rec, "EHAM")
        assert periods[i].elements["sky"] is taf.UNKNOWN

    @pytest.mark.it("uses forecast wording, never observation or delay claims")
    def test_wording(self):
        texts = []
        for name, station in [
            ("taf_pilots", "EGLL"),
            ("taf_pilots", "KJFK"),
            ("taf_lfpg_becmg", "LFPG"),
        ]:
            for h in outlook(name, station):
                for c in [h["prevailing"]["conditions"]] + [
                    p["conditions"] for p in h["possible"]
                ]:
                    assert c["disclaimer"] == taf.index.FORECAST_DISCLAIMER
                    texts.append(c["explanation"])
                    texts += [f["detail"] for f in c["factors"]]
        joined = " ".join(texts).lower()
        assert "forecast conditions index" in joined
        for banned in ("observed", "delay", "safe", "reported"):
            assert banned not in joined


@pytest.fixture
def client():
    return TestClient(app)


def get_forecast(client, code, rec=None, error=None, now=NOW):
    with mock.patch(
        "app.api.forecast.taf.get_latest_forecast", return_value=rec, side_effect=error
    ) as lookup, mock.patch("app.api.forecast.utc_now", return_value=now):
        response = client.get(f"/v1/airports/{code}/forecast")
    return response, lookup


@pytest.mark.describe("Forecast endpoint")
class TestEndpoint:
    @pytest.mark.it("returns the TAF summary and hourly outlook")
    def test_available(self, client):
        response, lookup = get_forecast(client, "lhr", record("taf_pilots", "EGLL"))
        assert response.status_code == 200
        lookup.assert_called_once_with("EGLL")
        body = response.json()
        assert body["data_status"] == "available"
        assert body["forecast"]["station"] == "EGLL"
        assert body["forecast"]["raw_text"].startswith("TAF EGLL")
        assert body["forecast"]["valid_to"] == "2026-11-10T06:00:00Z"
        assert len(body["hours"]) == 12
        assert body["hours"][5]["possible"][0]["probability"] == 30
        assert body["hours"][0]["prevailing"]["conditions"]["factors"][3]["value"] == [
            "FG"
        ]

    @pytest.mark.it("says no forecast is available when AWC returns none")
    def test_no_forecast(self, client):
        body = get_forecast(client, "LHR", None)[0].json()
        assert (body["data_status"], body["unavailable_reason"], body["hours"]) == (
            "unavailable",
            "no_forecast",
            [],
        )

    @pytest.mark.it("withdraws an expired forecast")
    def test_expired(self, client):
        body = get_forecast(
            client, "LHR", record("taf_pilots", "EGLL"), now=utc(10, 6)
        )[0].json()
        assert body["unavailable_reason"] == "forecast_expired"
        assert body["hours"] == [] and body["forecast"]["station"] == "EGLL"

    @pytest.mark.it("reports an airport without an ICAO station")
    def test_no_station(self, client):
        with mock.patch("app.api.forecast.resolve_airport") as resolve:
            resolve.return_value = (mock.Mock(icao=None), {"code": "XXX"})
            from app.api.forecast import forecast_query

            body = forecast_query("XXX")
        assert body["unavailable_reason"] == "no_metar_station"

    @pytest.mark.it("maps provider failures like the conditions endpoint")
    @pytest.mark.parametrize(
        "error, status, reason",
        [
            (MetarTimeout("timeout"), 504, "provider_timeout"),
            (MetarUpstreamError("http_500"), 502, "provider_error"),
            (
                MetarUpstreamError("invalid_forecast", "station mismatch"),
                502,
                "invalid_forecast",
            ),
            (MetarRateLimited(12.2), 503, "rate_limited"),
        ],
    )
    def test_errors(self, client, error, status, reason):
        response, _ = get_forecast(client, "LHR", error=error)
        assert response.status_code == status
        assert response.json()["reason"] == reason
        if status == 503:
            assert response.headers["Retry-After"] == "13"

    @pytest.mark.it("rejects bad and unknown codes")
    def test_codes(self, client):
        assert get_forecast(client, "L!")[0].status_code == 400
        assert get_forecast(client, "QQQ")[0].status_code == 404


@pytest.mark.describe("Forecast adapter: cache and provider")
class TestAdapter:
    def run(self, cached=None, fetched=None):
        with mock.patch(
            "app.services.taf.check_cache", return_value=cached
        ), mock.patch("app.services.taf.cache_response") as store, mock.patch(
            "app.services.taf.fetch_metar_records", return_value=fetched
        ) as fetch:
            result = taf.get_latest_forecast("egll")
        return result, store, fetch

    @pytest.mark.it("fetches, validates and caches the TAF for 30 minutes")
    def test_fetch(self):
        rec = record("taf_pilots", "EGLL")
        result, store, fetch = self.run(fetched=[rec])
        assert result is rec
        fetch.assert_called_once_with("EGLL", taf.AWC_TAF_URL)
        store.assert_called_once_with("taf:v1:EGLL", rec, 1800)

    @pytest.mark.it("caches an empty response as no forecast")
    def test_empty(self):
        result, store, _ = self.run(fetched=[])
        assert result is None
        store.assert_called_once_with("taf:v1:EGLL", taf.NO_FORECAST, 1800)
        assert self.run(cached=taf.NO_FORECAST)[0] is None

    @pytest.mark.it("serves a valid cached TAF and refetches an invalid one")
    def test_cached(self):
        rec = record("taf_pilots", "EGLL")
        result, _, fetch = self.run(cached=rec)
        assert result == rec and not fetch.called
        result, _, fetch = self.run(cached={"icaoId": "EGLL"}, fetched=[rec])
        assert result is rec and fetch.called

    @pytest.mark.it("doesn't cache an invalid TAF")
    def test_invalid_not_cached(self):
        rec = dict(record("taf_pilots", "EGLL"), fcsts=[])
        with pytest.raises(MetarUpstreamError):
            self.run(fetched=[rec])
