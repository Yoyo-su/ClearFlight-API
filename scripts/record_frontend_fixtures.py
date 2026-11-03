"""
Record the API responses the frontend tests use (frontend/tests/fixtures/).

Responses are produced by the real API code with the METAR lookup replaced by
recorded AWC reports and a fixed clock, so the output is deterministic and no
network is used. Re-run after any change to the v1 response models:

    python scripts/record_frontend_fixtures.py [output folder]

tests/test_frontend_fixtures.py fails until the fixtures match the models.
"""

import json
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
    for name, query in SEARCHES.items():
        save(name, client.get("/v1/airports/search", params={"q": query}))

    print(f"Wrote {len(written)} fixtures to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT))
