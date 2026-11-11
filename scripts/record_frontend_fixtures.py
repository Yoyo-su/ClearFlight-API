"""
Record the API responses the frontend tests use (frontend/tests/fixtures/).

Responses are produced by the real API code with the METAR lookup replaced by
recorded AWC reports and a fixed clock, so the output is deterministic and no
network is used. Re-run after any change to the v1 response models:

    python scripts/record_frontend_fixtures.py [output folder]

tests/test_frontend_fixtures.py fails until the fixtures match the models.
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.metar import (  # noqa: E402
    MetarRateLimited,
    MetarTimeout,
    MetarUpstreamError,
    select_observation,
)

AWC = ROOT / "tests" / "testfiles" / "awc"
OUT = ROOT / "frontend" / "tests" / "fixtures"
NOW = datetime(2026, 10, 30, 7, 55, tzinfo=timezone.utc)


def recorded(name: str, station: str, minutes_old: int, **changes):
    records = json.loads((AWC / f"{name}.json").read_text())
    obs = select_observation(records, station, NOW)
    return obs.model_copy(
        update={
            "observed_at": NOW - timedelta(minutes=minutes_old),
            "fetched_at": NOW,
            **changes,
        }
    )


CONDITIONS = {
    "conditions-egll-severe": ("EGLL", recorded("pilots_latest", "EGLL", 35)),
    "conditions-kjfk-low": ("KJFK", recorded("pilots_latest", "KJFK", 64)),
    "conditions-rjbb-moderate": ("RJBB", recorded("pilots_latest", "RJBB", 25)),
    "conditions-egkk-fog": ("EGKK", recorded("egkk_obscured_fog", "EGKK", 65)),
    "conditions-panc-high": ("PANC", recorded("panc_10plus_gust_rain", "PANC", 62)),
    "conditions-egll-unknown": (
        "EGLL",
        recorded(
            "pilots_latest",
            "EGLL",
            35,
            visibility_m=None,
            weather_phenomena=[],
            raw_text="METAR EGLL 300720Z AUTO 07004KT //// OVC002 10/10 Q1029",
        ),
    ),
    "conditions-egll-stale": ("EGLL", recorded("pilots_latest", "EGLL", 125)),
    "conditions-egll-too-old": ("EGLL", recorded("pilots_latest", "EGLL", 245)),
    "conditions-rjbb-no-report": ("RJBB", None),
    "conditions-aai-no-station": ("AAI", None),
}
ERRORS = {
    "error-400-invalid-code": ("XX", None),
    "error-404-not-found": ("ZZZ", None),
    "error-502-provider": ("EGLL", MetarUpstreamError("http_500")),
    "error-503-busy": ("EGLL", MetarRateLimited(12.3)),
    "error-504-timeout": ("EGLL", MetarTimeout("timeout")),
}


def taf_recorded(name: str, station: str, **changes):
    """A recorded TAF shifted 10 days earlier, so it is current at NOW.

    The TAFs were recorded around 2026-11-09 07:30Z; the shift keeps the hours
    and moves the day-of-month in the raw text to match.
    """
    rows = json.loads((AWC / f"{name}.json").read_text())
    rec = json.loads(json.dumps(next(r for r in rows if r["icaoId"] == station)))
    shift = 10 * 86400
    for key in ("validTimeFrom", "validTimeTo"):
        rec[key] -= shift
    for fcst in rec["fcsts"]:
        for key in ("timeFrom", "timeTo", "timeBec"):
            if fcst.get(key) is not None:
                fcst[key] -= shift
    issued = datetime.fromisoformat(rec["issueTime"].replace("Z", "+00:00"))
    rec["issueTime"] = (issued - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    days = {"08": "29", "09": "30", "10": "31"}

    def shift_token(token):
        # Only time tokens: ddhhmmZ, ddhh/ddhh, FMddhhmm, TX../ddhhZ, TN../ddhhZ.
        def day(d):
            return days.get(d, d)

        if m := re.fullmatch(r"(\d{2})(\d{4}Z)", token):
            return day(m[1]) + m[2]
        if m := re.fullmatch(r"(\d{2})(\d{2})/(\d{2})(\d{2})", token):
            return f"{day(m[1])}{m[2]}/{day(m[3])}{m[4]}"
        if m := re.fullmatch(r"FM(\d{2})(\d{4})", token):
            return f"FM{day(m[1])}{m[2]}"
        if m := re.fullmatch(r"(T[XN]M?\d{2}/)(\d{2})(\d{2}Z)", token):
            return m[1] + day(m[2]) + m[3]
        return token

    rec["rawTAF"] = " ".join(shift_token(t) for t in rec["rawTAF"].split())
    rec.update(changes)
    return rec


FORECASTS = {
    "forecast-egll-fog": ("EGLL", taf_recorded("taf_pilots", "EGLL"), NOW),
    "forecast-lfpg-possible": ("LFPG", taf_recorded("taf_lfpg_becmg", "LFPG"), NOW),
    "forecast-kjfk-low": ("KJFK", taf_recorded("taf_pilots", "KJFK"), NOW),
    "forecast-rjbb-not-yet-valid": (
        "RJBB",
        taf_recorded("taf_pilots", "RJBB"),
        datetime(2026, 10, 29, 22, 10, tzinfo=timezone.utc),
    ),
    "forecast-rjbb-no-forecast": ("RJBB", None, NOW),
    "forecast-egll-expired": (
        "EGLL",
        taf_recorded("taf_pilots", "EGLL"),
        datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc),
    ),
    "forecast-aai-no-station": ("AAI", None, NOW),
}
FORECAST_ERRORS = {
    "error-502-invalid-forecast": (
        "EGLL",
        MetarUpstreamError("invalid_forecast", "station mismatch"),
    ),
}
# CF-009/CF-010 map layers, recorded at NOW like the rest.
POSITIONS = ROOT / "tests" / "testfiles"


def aircraft_feed(name: str, **area):
    """A recorded adsb.lol answer re-dated so its data time is NOW."""
    from app.services.positions import Area
    from app.services.positions_providers import AdsbLol

    body = json.loads((POSITIONS / "adsblol" / f"point_{name}.json").read_text())
    body["now"] = int(NOW.timestamp() * 1000)
    return AdsbLol.parse(body, Area(**area), NOW)


def aircraft_cases():
    from app.services.positions_providers import AdsbLol, QuotaExhausted

    kjfk = dict(latitude=40.639447, longitude=-73.779317, radius_nm=25.0)
    egll = dict(latitude=51.470748, longitude=-0.459909, radius_nm=25.0)
    empty = aircraft_feed("rjbb", latitude=34.4273, longitude=135.244, radius_nm=25.0)
    empty.targets, empty.airborne = [], 0
    return {
        "aircraft-kjfk-available": (
            "KJFK",
            (aircraft_feed("kjfk", **kjfk), True, AdsbLol()),
            None,
        ),
        "aircraft-egll-available": (
            "EGLL",
            (aircraft_feed("egll", **egll), True, AdsbLol()),
            None,
        ),
        "aircraft-rjbb-no-aircraft": ("RJBB", (empty, True, AdsbLol()), None),
        "aircraft-rjbb-coverage-unknown": ("RJBB", (empty, False, AdsbLol()), None),
        "aircraft-egll-quota": (
            "EGLL",
            None,
            QuotaExhausted("daily_budget", datetime(2026, 10, 31, tzinfo=timezone.utc)),
        ),
    }


def nearby_result():
    """The recorded bbox answer near EGLL, re-dated: newest report 20 min old."""
    from app.services.nearby import parse_nearby
    from app.services.positions import Area

    records = json.loads((AWC / "metar_bbox_egll.json").read_text())
    shift = int((NOW - timedelta(minutes=20)).timestamp()) - max(
        r["obsTime"] for r in records
    )
    for record in records:
        record["obsTime"] += shift
    area = Area(51.470748, -0.459909, 50.0)
    return parse_nearby(records, area, "EGLL", NOW)


def radar_index(minutes_old: int = 5, **changes):
    latest = int((NOW - timedelta(minutes=minutes_old)).timestamp())
    index = {
        "host": "https://tilecache.rainviewer.com",
        "radar": {
            "past": [
                {"time": latest - 600 * i, "path": f"/v2/radar/fixture{i}"}
                for i in range(3, -1, -1)
            ]
        },
    }
    index.update(changes)
    return index


SEARCHES = {
    "search-lon": "lon",
    "search-osaka": "osaka",
    "search-jfk": "jfk",
    "search-none": "zzqq",
}


def main(out: Path = OUT) -> int:
    out.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    written = []

    def save(name, response):
        body = {
            "status": response.status_code,
            "headers": (
                {"Retry-After": response.headers["Retry-After"]}
                if "Retry-After" in response.headers
                else {}
            ),
            "body": response.json(),
        }
        (out / f"{name}.json").write_text(
            json.dumps(body, indent=2, ensure_ascii=False) + "\n"
        )
        written.append(name)

    with mock.patch("app.api.conditions.utc_now", return_value=NOW), mock.patch(
        "app.api.conditions.unrecognised_weather.record"
    ):
        for name, (code, obs) in CONDITIONS.items():
            with mock.patch(
                "app.api.conditions.get_latest_observation", return_value=obs
            ):
                save(name, client.get(f"/v1/airports/{code}/conditions"))
        for name, (code, error) in ERRORS.items():
            with mock.patch(
                "app.api.conditions.get_latest_observation", side_effect=error
            ):
                save(name, client.get(f"/v1/airports/{code}/conditions"))
    for name, (code, rec, now) in FORECASTS.items():
        with mock.patch("app.api.forecast.utc_now", return_value=now), mock.patch(
            "app.api.forecast.taf.get_latest_forecast", return_value=rec
        ):
            save(name, client.get(f"/v1/airports/{code}/forecast"))
    for name, (code, error) in FORECAST_ERRORS.items():
        with mock.patch("app.api.forecast.taf.get_latest_forecast", side_effect=error):
            save(name, client.get(f"/v1/airports/{code}/forecast"))
    from app.services.positions_providers import ProviderDisabled

    for name, (code, result, error) in {
        **aircraft_cases(),
        "aircraft-egll-disabled": (
            "EGLL",
            None,
            ProviderDisabled("educational_use_not_enabled"),
        ),
    }.items():
        with mock.patch(
            "app.api.aircraft.utc_now", return_value=NOW + timedelta(seconds=1)
        ), mock.patch(
            "app.api.aircraft.positions_service.get_positions",
            return_value=result,
            side_effect=error,
        ):
            save(name, client.get(f"/v1/airports/{code}/aircraft"))
    for name, result in {
        "nearby-egll-available": nearby_result(),
        "nearby-rjbb-no-stations": {
            "stations": [],
            "complete": True,
            "dropped": 0,
            "fetched_at": NOW,
            "records": 0,
        },
    }.items():
        code = "EGLL" if "egll" in name else "RJBB"
        with mock.patch("app.api.nearby.utc_now", return_value=NOW), mock.patch(
            "app.api.nearby.get_nearby", return_value=result
        ):
            save(name, client.get(f"/v1/airports/{code}/nearby-conditions"))

    class IndexReply:
        def __init__(self, body):
            self.status_code, self.body = 200, body

        def json(self):
            return self.body

    from app.core.config import settings
    from app.services import radar

    radar_cases = {
        "radar-disabled": (False, radar_index()),
        "radar-available": (True, radar_index()),
        "radar-invalid-index": (True, radar_index(host="https://evil.example")),
    }
    for name, (enabled, index) in radar_cases.items():
        with mock.patch.multiple(
            settings, RAINVIEWER_EDUCATIONAL_USE=enabled
        ), mock.patch("app.api.radar.utc_now", return_value=NOW), mock.patch.object(
            radar, "cached_index", return_value=index
        ):
            save(name, client.get("/v1/map/radar"))
    for name, query in SEARCHES.items():
        save(name, client.get("/v1/airports/search", params={"q": query}))

    print(f"Wrote {len(written)} fixtures to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT))
