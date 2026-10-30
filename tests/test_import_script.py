import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import requests

from app.services.airport_import import SnapshotValidationError, read_snapshot

"""
Test suite for scripts/import_ourairports.py (downloads and timezone lookup mocked)
"""

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "import_ourairports.py"
)
PILOTS = [
    ("EGLL", "LHR", "London Heathrow Airport", "London", "GB", "Europe/London"),
    ("RJBB", "KIX", "Kansai International Airport", "Osaka", "JP", "Asia/Tokyo"),
    (
        "KJFK",
        "JFK",
        "John F. Kennedy International Airport",
        "New York",
        "US",
        "America/New_York",
    ),
]


@pytest.fixture
def script(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("import_ourairports", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SNAPSHOT_PATH", tmp_path / "airports.csv")
    monkeypatch.setattr(module, "META_PATH", tmp_path / "airports.meta.json")
    overrides = tmp_path / "timezone_overrides.csv"
    overrides.write_text("code,timezone,reason\n")
    monkeypatch.setattr(module, "OVERRIDES_PATH", overrides)
    return module


def write_sources(tmp_path, pilots=PILOTS):
    airports = tmp_path / "source_airports.csv"
    with open(airports, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "type",
                "name",
                "latitude_deg",
                "longitude_deg",
                "iso_country",
                "municipality",
                "icao_code",
                "iata_code",
            ]
        )
        for i, (icao, iata, name, city, country, _) in enumerate(pilots):
            writer.writerow(
                [
                    "large_airport",
                    name,
                    str(10 + i),
                    str(20 + i),
                    country,
                    city,
                    icao,
                    iata,
                ]
            )
    countries = tmp_path / "source_countries.csv"
    countries.write_text("code,name\nGB,United Kingdom\nJP,Japan\nUS,United States\n")
    return str(airports), str(countries)


def fake_timezonefinder(pilots=PILOTS):
    zones = {(10.0 + i, 20.0 + i): p[5] for i, p in enumerate(pilots)}

    class FakeFinder:
        def timezone_at(self, lng, lat):
            return zones.get((lat, lng))

    return SimpleNamespace(TimezoneFinder=FakeFinder)


def run_main(script, args):
    with mock.patch.object(sys, "argv", ["import_ourairports.py", *args]):
        with mock.patch.dict(sys.modules, {"timezonefinder": fake_timezonefinder()}):
            with mock.patch.object(script, "version", return_value="test"):
                return script.main()


@pytest.mark.describe("Import script: downloads")
class TestLoadCsv:
    @pytest.mark.it("reads a local CSV file")
    def test_local(self, script, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("code,name\nGB,United Kingdom\n")
        assert script.load_csv(str(path), "https://unused") == [
            {"code": "GB", "name": "United Kingdom"}
        ]

    @pytest.mark.it("downloads with a timeout and parses the CSV")
    def test_download(self, script):
        response = mock.Mock(text="code,name\nJP,Japan\n")
        with mock.patch.object(script.requests, "get", return_value=response) as get:
            rows = script.load_csv(None, "https://example.test/countries.csv")
        get.assert_called_once_with(
            "https://example.test/countries.csv", timeout=script.DOWNLOAD_TIMEOUT
        )
        response.raise_for_status.assert_called_once_with()
        assert rows == [{"code": "JP", "name": "Japan"}]

    @pytest.mark.it("raises on an HTTP error status")
    def test_download_error(self, script):
        response = mock.Mock()
        response.raise_for_status.side_effect = requests.HTTPError("503")
        with mock.patch.object(script.requests, "get", return_value=response):
            with pytest.raises(requests.HTTPError):
                script.load_csv(None, "https://example.test/airports.csv")


@pytest.mark.describe("Import script: end to end")
class TestMain:
    @pytest.mark.it("builds, validates and writes the snapshot and metadata")
    def test_main_writes_snapshot(self, script, tmp_path):
        airports, countries = write_sources(tmp_path)
        assert run_main(script, ["--airports", airports, "--countries", countries]) == 0
        rows = read_snapshot(script.SNAPSHOT_PATH)
        assert {r["icao"]: r["timezone"] for r in rows} == {p[0]: p[5] for p in PILOTS}
        meta = json.loads(script.META_PATH.read_text())
        assert meta["row_count"] == 3
        assert meta["unresolved_timezones"] == []
        assert meta["sources"]["airports"] == airports

    @pytest.mark.it("leaves the current snapshot when validation fails")
    def test_main_validation_failure(self, script, tmp_path):
        airports, countries = write_sources(tmp_path)
        run_main(script, ["--airports", airports, "--countries", countries])
        before = script.SNAPSHOT_PATH.read_text()
        airports, countries = write_sources(tmp_path, PILOTS[:2])
        with pytest.raises(SnapshotValidationError, match="pilot airport KJFK missing"):
            run_main(script, ["--airports", airports, "--countries", countries])
        assert script.SNAPSHOT_PATH.read_text() == before
