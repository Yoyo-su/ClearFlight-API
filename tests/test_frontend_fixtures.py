import importlib.util
import json
from pathlib import Path

import pytest

from app.api.models import AirportSearchResponse, ConditionsResponse, ErrorResponse

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
        assert statuses == {"current", "stale", "unavailable"}
        assert reasons == {"no_metar_station", "no_report", "observation_too_old"}
        assert errors == {
            "invalid_code",
            "airport_not_found",
            "provider_error",
            "rate_limited",
            "provider_timeout",
        }
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
