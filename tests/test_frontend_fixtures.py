import importlib.util
import json
from pathlib import Path

import pytest

from app.api.models import (
    AirportSearchResponse,
    ConditionsResponse,
    ErrorResponse,
    ForecastResponse,
    AircraftResponse,
    NearbyConditionsResponse,
    RadarResponse,
)

"""
Contract test: the frontend's recorded API responses (frontend/tests/fixtures)
must match the current v1 models exactly and what the API produces now, so a
backend change can't silently break the frontend (spec cf-005 §10, D-008).
"""

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
SCRIPT = ROOT / "scripts" / "record_frontend_fixtures.py"


def fixture_files():
    return sorted(FIXTURES.glob("*.json"))


def model_for(name: str, status: int):
    if name.startswith("search-"):
        return AirportSearchResponse
    if name.startswith("forecast-"):
        return ForecastResponse
    if name.startswith("aircraft-") and status == 200:
        return AircraftResponse
    if name.startswith("nearby-") and status == 200:
        return NearbyConditionsResponse
    if name.startswith("radar-") and status == 200:
        return RadarResponse
    if status == 200:
        return ConditionsResponse
    return ErrorResponse


@pytest.mark.describe("Frontend fixtures match the v1 contract")
class TestFrontendFixtures:
    @pytest.mark.it("exist for every response kind the frontend handles")
    def test_coverage(self):
        names = {path.stem for path in fixture_files()}
        bodies = [json.loads(p.read_text())["body"] for p in fixture_files()]
        statuses = {b.get("data_status") for b in bodies} - {None}
        reasons = {b.get("unavailable_reason") for b in bodies} - {None}
        errors = {b.get("reason") for b in bodies} - {None}
        assert statuses == {
            "current",
            "stale",
            "unavailable",
            "available",
            "no_aircraft",
            "coverage_unknown",
            "quota_exhausted",
        }
        assert reasons == {
            "no_metar_station",
            "no_report",
            "observation_too_old",
            "no_forecast",
            "forecast_expired",
            "no_coverage_evidence",
            "daily_budget",
            "provider_disabled",
            "no_stations",
            "invalid_index",
        }
        assert errors == {
            "invalid_code",
            "airport_not_found",
            "provider_error",
            "rate_limited",
            "provider_timeout",
            "invalid_forecast",
        }
        hour_states = {h["status"] for b in bodies for h in b.get("hours", [])}
        assert {"forecast", "not_yet_valid"} <= hour_states
        assert {"search-lon", "search-none"} <= names

    @pytest.mark.it("validate against the current models with exactly their fields")
    @pytest.mark.parametrize("path", fixture_files(), ids=lambda p: p.stem)
    def test_matches_model(self, path):
        fixture = json.loads(path.read_text())
        model = model_for(path.stem, fixture["status"])
        parsed = model.model_validate(fixture["body"])
        # Extra fields are dropped and missing ones fail validation, so
        # equality means the field sets match exactly.
        assert parsed.model_dump(mode="json") == fixture["body"]

    @pytest.mark.it("are what the API produces now (re-record if this fails)")
    def test_up_to_date(self, tmp_path):
        spec = importlib.util.spec_from_file_location("record_fixtures", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.main(tmp_path)
        fresh = {p.name: p.read_text() for p in tmp_path.glob("*.json")}
        committed = {p.name: p.read_text() for p in fixture_files()}
        assert fresh == committed, (
            "Frontend fixtures are out of date: run "
            "python scripts/record_frontend_fixtures.py"
        )
