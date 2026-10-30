import zoneinfo
from datetime import datetime, timedelta, timezone

import pytest

from app.services.airport_catalogue import (
    SNAPSHOT_PATH,
    Airport,
    AirportCatalogue,
    get_catalogue,
    normalise,
)
from app.services.airport_import import (
    SnapshotValidationError,
    read_snapshot,
    write_snapshot,
)

"""
Test suite for the airport catalogue, the committed snapshot and timezones
"""


def airport(**fields):
    row = {
        "icao": "",
        "iata": "",
        "name": "Test Airport",
        "city": "",
        "country_code": "GB",
        "country": "United Kingdom",
        "type": "small_airport",
        "latitude": "51.0",
        "longitude": "0.0",
        "timezone": "Europe/London",
    }
    row.update(fields)
    return Airport.from_row(row)


@pytest.fixture
def catalogue():
    return AirportCatalogue(
        [
            airport(
                icao="EGLL",
                iata="LHR",
                name="London Heathrow Airport",
                city="London",
                type="large_airport",
            ),
            airport(
                icao="EGLC",
                iata="LCY",
                name="London City Airport",
                city="London",
                type="medium_airport",
            ),
            airport(icao="EGKB", name="London Biggin Hill Airport", city="London"),
            airport(icao="EGSS", iata="STN", name="Stansted Airport", city="London"),
            airport(
                icao="SBGR",
                iata="GRU",
                name="São Paulo/Guarulhos International Airport",
                city="São Paulo",
                type="large_airport",
                timezone="",
            ),
            airport(iata="AAI", name="Arraias Airport", city="Arraias"),
            airport(
                icao="FAEL",
                iata="ELS",
                name="East London Airport",
                city="East London",
                type="medium_airport",
            ),
            airport(icao="KXYZ", name="Hollondale Field", city="Hollondale"),
        ]
    )


@pytest.mark.describe("Text normalisation")
class TestNormalise:
    @pytest.mark.it("casefolds, strips accents and collapses punctuation")
    def test_normalise(self):
        assert normalise("  São Paulo/Guarulhos–Int'l  ") == "sao paulo guarulhos int l"
        assert normalise("Ürümqi") == "urumqi"
        assert normalise("") == ""


@pytest.mark.describe("Airport lookup")
class TestGet:
    @pytest.mark.it("finds airports by IATA or ICAO code, ignoring case")
    @pytest.mark.parametrize("code", ["LHR", "lhr", "EGLL", " egll "])
    def test_get_by_code(self, catalogue, code):
        assert catalogue.get(code).icao == "EGLL"

    @pytest.mark.it("returns None for unknown or badly sized codes")
    @pytest.mark.parametrize("code", ["XXX", "XXXX", "EG", "EGLLX", ""])
    def test_get_unknown(self, catalogue, code):
        assert catalogue.get(code) is None

    @pytest.mark.it("finds single-code airports and uses ICAO, else IATA, as code")
    def test_single_code(self, catalogue):
        assert catalogue.get("AAI").code == "AAI"
        assert catalogue.get("AAI").icao is None
        assert catalogue.get("EGKB").code == "EGKB"
        assert catalogue.get("EGKB").iata is None


@pytest.mark.describe("Airport search")
class TestSearch:
    def codes(self, results):
        return [a.code for a in results]

    @pytest.mark.it("puts an exact code match first")
    def test_exact_code_first(self, catalogue):
        assert self.codes(catalogue.search("lhr", 10)) == ["EGLL"]
        assert self.codes(catalogue.search("kxyz", 10)) == ["KXYZ"]

    @pytest.mark.it("ranks name/city prefix, then word prefix, then substring")
    def test_rank_order(self, catalogue):
        # Name/city prefix (London...), then word prefix (East London), then
        # substring (Hollondale); match tier outranks airport size.
        assert self.codes(catalogue.search("lon", 10)) == [
            "EGLL",
            "EGLC",
            "EGKB",
            "EGSS",
            "FAEL",
            "KXYZ",
        ]

    @pytest.mark.it("orders ties by airport size then name")
    def test_tie_break(self, catalogue):
        results = self.codes(catalogue.search("london", 10))
        assert results == ["EGLL", "EGLC", "EGKB", "EGSS", "FAEL"]

    @pytest.mark.it("matches a word inside the name")
    def test_word_prefix(self, catalogue):
        assert self.codes(catalogue.search("heathrow", 10)) == ["EGLL"]
        assert self.codes(catalogue.search("guarulhos", 10)) == ["SBGR"]

    @pytest.mark.it("ignores accents and case")
    def test_accents(self, catalogue):
        assert self.codes(catalogue.search("SAO PAULO", 10)) == ["SBGR"]

    @pytest.mark.it("respects the limit")
    def test_limit(self, catalogue):
        assert len(catalogue.search("london", 2)) == 2

    @pytest.mark.it("returns nothing for no match or punctuation only")
    @pytest.mark.parametrize("query", ["zzzz", "--"])
    def test_no_match(self, catalogue, query):
        assert catalogue.search(query, 10) == []

    @pytest.mark.it("serialises missing codes, city and timezone as None")
    def test_to_dict(self, catalogue):
        result = catalogue.get("AAI").to_dict()
        assert result["icao"] is None and result["code"] == "AAI"
        assert catalogue.get("GRU").to_dict()["timezone"] is None
        assert airport(iata="XYZ").to_dict()["city"] is None


@pytest.mark.describe("Loading a snapshot")
class TestFromSnapshot:
    @pytest.mark.it("loads a valid snapshot file")
    def test_load(self, tmp_path):
        rows = read_snapshot(SNAPSHOT_PATH)[:5]
        path = tmp_path / "airports.csv"
        write_snapshot(rows, {}, path, tmp_path / "meta.json")
        loaded = AirportCatalogue.from_snapshot(path, require_pilots=False)
        assert len(loaded.airports) == 5

    @pytest.mark.it("rejects a corrupt snapshot")
    def test_corrupt(self, tmp_path):
        path = tmp_path / "airports.csv"
        write_snapshot(
            [{**read_snapshot(SNAPSHOT_PATH)[0], "timezone": "Mars/Base"}],
            {},
            path,
            tmp_path / "meta.json",
        )
        with pytest.raises(SnapshotValidationError, match="unknown timezone"):
            AirportCatalogue.from_snapshot(path, require_pilots=False)

    @pytest.mark.it("fails clearly when the snapshot is missing")
    def test_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            AirportCatalogue.from_snapshot(tmp_path / "missing.csv")


@pytest.mark.describe("Committed snapshot and pilot timezones")
class TestCommittedSnapshot:
    @pytest.mark.it("loads and validates, including the pilot airports")
    def test_committed_snapshot_valid(self):
        catalogue = get_catalogue()
        assert len(catalogue.airports) > 10000

    @pytest.mark.it("maps each pilot airport to its IANA timezone")
    @pytest.mark.parametrize(
        "code, iata, zone",
        [
            ("EGLL", "LHR", "Europe/London"),
            ("RJBB", "KIX", "Asia/Tokyo"),
            ("KJFK", "JFK", "America/New_York"),
        ],
    )
    def test_pilot_timezones(self, code, iata, zone):
        assert get_catalogue().get(code).timezone == zone
        assert get_catalogue().get(iata).icao == code

    @pytest.mark.it("finds each pilot airport by name and city in the top 5")
    @pytest.mark.parametrize(
        "query, code",
        [
            ("heathrow", "EGLL"),
            ("london", "EGLL"),
            ("kansai", "RJBB"),
            ("osaka", "RJBB"),
            ("kennedy", "KJFK"),
            ("new york", "KJFK"),
        ],
    )
    def test_pilot_search(self, query, code):
        assert code in [a.code for a in get_catalogue().search(query, 5)]


def offset_hours(zone, utc_time):
    local_time = utc_time.astimezone(zoneinfo.ZoneInfo(zone))
    return local_time.utcoffset() / timedelta(hours=1)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.mark.describe("DST boundaries for pilot airport timezones (2026)")
class TestPilotDst:
    @pytest.mark.it("applies each zone's UTC offset either side of the DST change")
    @pytest.mark.parametrize(
        "code, before, after, offset_before, offset_after",
        [
            # London: BST starts 29 Mar 01:00 UTC, ends 25 Oct 01:00 UTC
            ("EGLL", utc(2026, 3, 29, 0, 59), utc(2026, 3, 29, 1, 0), 0, 1),
            ("EGLL", utc(2026, 10, 25, 0, 59), utc(2026, 10, 25, 1, 0), 1, 0),
            # New York: EDT starts 8 Mar 07:00 UTC, ends 1 Nov 06:00 UTC
            ("KJFK", utc(2026, 3, 8, 6, 59), utc(2026, 3, 8, 7, 0), -5, -4),
            ("KJFK", utc(2026, 11, 1, 5, 59), utc(2026, 11, 1, 6, 0), -4, -5),
            # Tokyo: no DST, +9 all year
            ("RJBB", utc(2026, 1, 15, 12), utc(2026, 7, 15, 12), 9, 9),
        ],
    )
    def test_dst_boundaries(self, code, before, after, offset_before, offset_after):
        zone = get_catalogue().get(code).timezone
        assert offset_hours(zone, before) == offset_before
        assert offset_hours(zone, after) == offset_after
