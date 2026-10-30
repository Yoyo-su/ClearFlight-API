import csv
import json
import os
from unittest import mock

import pytest

from app.services.airport_import import (
    SNAPSHOT_FIELDS,
    SnapshotValidationError,
    build_snapshot_rows,
    parse_countries,
    parse_overrides,
    read_snapshot,
    validate_snapshot,
    write_snapshot,
)

"""
Test suite for building and validating the airport catalogue snapshot
"""


def source_row(**overrides):
    row = {
        "type": "large_airport",
        "name": "London Heathrow Airport",
        "latitude_deg": "51.470748",
        "longitude_deg": "-0.459909",
        "iso_country": "GB",
        "municipality": "London",
        "icao_code": "EGLL",
        "iata_code": "LHR",
    }
    row.update(overrides)
    return row


def snapshot_row(**overrides):
    row = {
        "icao": "EGLL",
        "iata": "LHR",
        "name": "London Heathrow Airport",
        "city": "London",
        "country_code": "GB",
        "country": "United Kingdom",
        "type": "large_airport",
        "latitude": "51.470748",
        "longitude": "-0.459909",
        "timezone": "Europe/London",
    }
    row.update(overrides)
    return row


def pilot_rows():
    return [
        snapshot_row(),
        snapshot_row(
            icao="RJBB",
            iata="KIX",
            name="Kansai International Airport",
            timezone="Asia/Tokyo",
        ),
        snapshot_row(
            icao="KJFK",
            iata="JFK",
            name="John F. Kennedy International Airport",
            timezone="America/New_York",
        ),
    ]


def fixed_lookup(zone):
    return lambda latitude, longitude: zone


@pytest.mark.describe("Snapshot build from OurAirports rows")
class TestBuildSnapshotRows:
    @pytest.mark.it("keeps large, medium and small airports with a code")
    def test_filters_by_type_and_code(self):
        rows = [
            source_row(),
            source_row(type="medium_airport", icao_code="EGKK", iata_code="LGW"),
            source_row(type="small_airport", icao_code="EGLC", iata_code="LCY"),
            source_row(type="heliport", icao_code="EGLW", iata_code=""),
            source_row(type="closed", icao_code="EGXX", iata_code=""),
            source_row(type="small_airport", icao_code="", iata_code=""),
        ]
        snapshot, unresolved = build_snapshot_rows(
            rows, {"GB": "United Kingdom"}, fixed_lookup("Europe/London")
        )
        assert [r["icao"] for r in snapshot] == ["EGKK", "EGLC", "EGLL"]
        assert unresolved == []

    @pytest.mark.it("maps OurAirports columns to snapshot columns")
    def test_maps_columns(self):
        lookup = mock.Mock(return_value="Europe/London")
        snapshot, _ = build_snapshot_rows(
            [source_row(icao_code=" egll ")], {"GB": "United Kingdom"}, lookup
        )
        assert snapshot == [snapshot_row()]
        assert list(snapshot[0]) == SNAPSHOT_FIELDS
        lookup.assert_called_once_with(51.470748, -0.459909)

    @pytest.mark.it("keeps airports with only an IATA or only an ICAO code")
    def test_single_code_rows(self):
        rows = [
            source_row(icao_code="", iata_code="AAI"),
            source_row(icao_code="SBXX", iata_code=""),
        ]
        snapshot, _ = build_snapshot_rows(rows, {}, fixed_lookup("America/Recife"))
        assert [(r["icao"], r["iata"]) for r in snapshot] == [("", "AAI"), ("SBXX", "")]
        assert snapshot[0]["country"] == ""

    @pytest.mark.it("leaves the timezone empty when the lookup fails or gives Etc/*")
    @pytest.mark.parametrize("zone", [None, "", "Etc/GMT+10"])
    def test_unresolved_timezone(self, zone):
        snapshot, unresolved = build_snapshot_rows(
            [source_row()], {}, fixed_lookup(zone)
        )
        assert snapshot[0]["timezone"] == ""
        assert unresolved == ["EGLL"]

    @pytest.mark.it("applies an override before the coordinate lookup")
    def test_override(self):
        lookup = mock.Mock(return_value="Australia/Sydney")
        rows = [
            source_row(icao_code="YBCG", iata_code="OOL"),
            source_row(icao_code="", iata_code="AAI"),
        ]
        overrides = {"YBCG": "Australia/Brisbane", "AAI": "America/Araguaina"}
        snapshot, _ = build_snapshot_rows(rows, {}, lookup, overrides)
        assert {r["icao"] or r["iata"]: r["timezone"] for r in snapshot} == overrides
        lookup.assert_not_called()


@pytest.mark.describe("Country and override parsing")
class TestParsing:
    @pytest.mark.it("maps country codes to names and skips blank codes")
    def test_parse_countries(self):
        rows = [{"code": "GB", "name": "United Kingdom"}, {"code": " ", "name": "x"}]
        assert parse_countries(rows) == {"GB": "United Kingdom"}

    @pytest.mark.it("upper-cases override codes and skips blank codes")
    def test_parse_overrides(self):
        rows = [
            {"code": "ybcg", "timezone": " Australia/Brisbane ", "reason": "border"},
            {"code": "", "timezone": "Europe/London", "reason": ""},
        ]
        assert parse_overrides(rows) == {"YBCG": "Australia/Brisbane"}


@pytest.mark.describe("Snapshot validation")
class TestValidateSnapshot:
    @pytest.mark.it("accepts a valid snapshot")
    def test_valid(self):
        validate_snapshot(pilot_rows() + [snapshot_row(icao="", iata="AAI")])

    @pytest.mark.it("rejects invalid rows")
    @pytest.mark.parametrize(
        "row, message",
        [
            (snapshot_row(icao="", iata=""), "no IATA or ICAO code"),
            (snapshot_row(icao="egll1", iata=""), "invalid ICAO code"),
            (snapshot_row(icao="", iata="L1R"), "invalid IATA code"),
            (snapshot_row(name=""), "empty name"),
            (snapshot_row(type="heliport"), "unexpected type"),
            (snapshot_row(latitude="91"), "invalid coordinates"),
            (snapshot_row(longitude="east"), "invalid coordinates"),
            (snapshot_row(timezone="GMT+1"), "unknown timezone"),
            ({"icao": "EGLL"}, "missing fields"),
        ],
    )
    def test_invalid_row(self, row, message):
        with pytest.raises(SnapshotValidationError, match=message):
            validate_snapshot([row], require_pilots=False)

    @pytest.mark.it("rejects duplicate codes")
    def test_duplicates(self):
        rows = pilot_rows() + [snapshot_row(name="Copy")]
        with pytest.raises(SnapshotValidationError) as error:
            validate_snapshot(rows)
        assert "duplicate ICAO code EGLL" in str(error.value)
        assert "duplicate IATA code LHR" in str(error.value)

    @pytest.mark.it("requires the pilot airports with their expected timezones")
    def test_pilots(self):
        rows = pilot_rows()[:2]
        rows[1]["timezone"] = "Asia/Seoul"
        with pytest.raises(SnapshotValidationError) as error:
            validate_snapshot(rows)
        assert "pilot airport KJFK missing" in str(error.value)
        assert "pilot airport RJBB has timezone 'Asia/Seoul'" in str(error.value)

    @pytest.mark.it("rejects a row count change over 10% unless allowed")
    def test_size_change(self):
        rows = pilot_rows()
        with pytest.raises(SnapshotValidationError, match="row count changed"):
            validate_snapshot(rows, previous_count=4)
        validate_snapshot(rows, previous_count=4, allow_size_change=True)
        validate_snapshot(rows, previous_count=3)


@pytest.mark.describe("Snapshot files")
class TestSnapshotFiles:
    @pytest.mark.it("writes the snapshot and metadata, readable by read_snapshot")
    def test_write_and_read(self, tmp_path):
        snapshot_path = tmp_path / "airports.csv"
        meta_path = tmp_path / "airports.meta.json"
        write_snapshot(pilot_rows(), {"row_count": 3}, snapshot_path, meta_path)
        assert read_snapshot(snapshot_path) == pilot_rows()
        assert json.loads(meta_path.read_text()) == {"row_count": 3}
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "airports.csv",
            "airports.meta.json",
        ]

    @pytest.mark.it("leaves the previous files when writing fails")
    def test_failed_write_keeps_previous(self, tmp_path):
        snapshot_path = tmp_path / "airports.csv"
        meta_path = tmp_path / "airports.meta.json"
        write_snapshot(pilot_rows(), {"row_count": 3}, snapshot_path, meta_path)
        with mock.patch(
            "app.services.airport_import.json.dump", side_effect=OSError("disk full")
        ):
            with pytest.raises(OSError):
                write_snapshot(
                    [snapshot_row()], {"row_count": 1}, snapshot_path, meta_path
                )
        assert read_snapshot(snapshot_path) == pilot_rows()
        assert json.loads(meta_path.read_text()) == {"row_count": 3}
        assert len(list(tmp_path.iterdir())) == 2

    @pytest.mark.it("keeps a complete new snapshot if only the metadata move fails")
    def test_second_replace_fails(self, tmp_path):
        snapshot_path = tmp_path / "airports.csv"
        meta_path = tmp_path / "airports.meta.json"
        write_snapshot(pilot_rows(), {"row_count": 3}, snapshot_path, meta_path)
        real_replace = os.replace

        def replace(source, target):
            if str(target) == str(meta_path):
                raise OSError("interrupted")
            real_replace(source, target)

        new_rows = pilot_rows()[:2]
        with mock.patch("app.services.airport_import.os.replace", side_effect=replace):
            with pytest.raises(OSError):
                write_snapshot(new_rows, {"row_count": 2}, snapshot_path, meta_path)
        assert read_snapshot(snapshot_path) == new_rows
        assert json.loads(meta_path.read_text()) == {"row_count": 3}
        assert len(list(tmp_path.iterdir())) == 2

    @pytest.mark.it("rejects a snapshot with unexpected columns")
    def test_read_wrong_columns(self, tmp_path):
        path = tmp_path / "airports.csv"
        with open(path, "w", newline="") as f:
            csv.writer(f).writerows([["icao", "name"], ["EGLL", "Heathrow"]])
        with pytest.raises(
            SnapshotValidationError, match="unexpected snapshot columns"
        ):
            read_snapshot(path)
