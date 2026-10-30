import re
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from app.services.airport_import import read_snapshot, validate_snapshot

"""
In-memory airport catalogue built from the committed OurAirports snapshot.
"""

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "airports.csv"
TYPE_RANK = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}


def normalise(text: str) -> str:
    """Casefold, strip accents and collapse punctuation to single spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.split(r"[^0-9a-z]+", without_accents.casefold())).strip()


@dataclass(frozen=True)
class Airport:
    icao: str | None
    iata: str | None
    name: str
    city: str | None
    country_code: str
    country: str | None
    type: str
    latitude: float
    longitude: float
    timezone: str | None
    search_name: str = field(repr=False, compare=False)
    search_city: str = field(repr=False, compare=False)

    @property
    def code(self) -> str:
        """Canonical code: ICAO when the airport has one, otherwise IATA."""
        return self.icao or self.iata

    @classmethod
    def from_row(cls, row: dict) -> "Airport":
        return cls(
            icao=row["icao"] or None,
            iata=row["iata"] or None,
            name=row["name"],
            city=row["city"] or None,
            country_code=row["country_code"],
            country=row["country"] or None,
            type=row["type"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            timezone=row["timezone"] or None,
            search_name=normalise(row["name"]),
            search_city=normalise(row["city"]),
        )

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "icao": self.icao,
            "iata": self.iata,
            "name": self.name,
            "city": self.city,
            "country": self.country,
            "country_code": self.country_code,
            "type": self.type,
            "timezone": self.timezone,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


class AirportCatalogue:
    def __init__(self, airports: list[Airport]):
        self.airports = airports
        self.by_icao = {a.icao: a for a in airports if a.icao}
        self.by_iata = {a.iata: a for a in airports if a.iata}

    @classmethod
    def from_snapshot(
        cls, path: Path = SNAPSHOT_PATH, require_pilots: bool = True
    ) -> "AirportCatalogue":
        """Load and validate a snapshot.

        Raises:
            OSError: if the snapshot can't be read.
            SnapshotValidationError: if the snapshot is malformed.
        """
        rows = read_snapshot(path)
        validate_snapshot(rows, require_pilots=require_pilots)
        return cls([Airport.from_row(row) for row in rows])

    def get(self, code: str) -> Airport | None:
        """Look up an airport by IATA (3 characters) or ICAO (4 characters) code."""
        code = code.strip().upper()
        if len(code) == 3:
            return self.by_iata.get(code)
        if len(code) == 4:
            return self.by_icao.get(code)
        return None

    def search(self, query: str, limit: int) -> list[Airport]:
        """Search by code, name or city.

        Results are ordered: exact IATA/ICAO match, then name or city starting
        with the query, then a word in the name or city starting with it, then
        any other substring match. Ties go to larger airports, then by name.
        """
        term = normalise(query)
        if not term:
            return []
        code = query.strip().upper()
        matches = []
        for airport in self.airports:
            rank = self._match_rank(airport, term, code)
            if rank is not None:
                matches.append(
                    (rank, TYPE_RANK.get(airport.type, 3), airport.name, airport)
                )
        matches.sort(key=lambda m: m[:3])
        return [m[3] for m in matches[:limit]]

    @staticmethod
    def _match_rank(airport: Airport, term: str, code: str) -> int | None:
        if code in (airport.iata, airport.icao):
            return 0
        fields = (airport.search_name, airport.search_city)
        if any(f.startswith(term) for f in fields):
            return 1
        if any(f" {term}" in f for f in fields):
            return 2
        if any(term in f for f in fields):
            return 3
        return None


@cache
def get_catalogue() -> AirportCatalogue:
    """Return the catalogue, loading it from the snapshot on first use."""
    return AirportCatalogue.from_snapshot()
