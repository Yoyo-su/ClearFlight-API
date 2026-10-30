import csv
import json
import os
import re
import tempfile
import zoneinfo
from pathlib import Path
from typing import Callable, Iterable

"""
Transform and validation steps for building the airport catalogue snapshot
from OurAirports data. The download and the timezone lookup library live in
scripts/import_ourairports.py so neither is a runtime dependency.
"""

OURAIRPORTS_AIRPORTS_URL = (
    "https://davidmegginson.github.io/ourairports-data/airports.csv"
)
OURAIRPORTS_COUNTRIES_URL = (
    "https://davidmegginson.github.io/ourairports-data/countries.csv"
)

INCLUDED_TYPES = ("large_airport", "medium_airport", "small_airport")
SNAPSHOT_FIELDS = [
    "icao",
    "iata",
    "name",
    "city",
    "country_code",
    "country",
    "type",
    "latitude",
    "longitude",
    "timezone",
]
PILOT_AIRPORTS = {
    "EGLL": "Europe/London",
    "RJBB": "Asia/Tokyo",
    "KJFK": "America/New_York",
}
MAX_SIZE_CHANGE = 0.10  # fraction of the previous snapshot's row count

IATA_PATTERN = re.compile(r"[A-Z]{3}")
ICAO_PATTERN = re.compile(r"[A-Z0-9]{4}")

TimezoneLookup = Callable[[float, float], str | None]


class SnapshotValidationError(ValueError):
    """Raised when a snapshot fails validation; the message lists the problems."""


def parse_countries(country_rows: Iterable[dict]) -> dict[str, str]:
    """Map ISO country codes to names from OurAirports countries.csv rows."""
    return {
        row["code"].strip(): row["name"].strip()
        for row in country_rows
        if row.get("code", "").strip()
    }


def parse_overrides(override_rows: Iterable[dict]) -> dict[str, str]:
    """Map airport codes (ICAO, or IATA when there is no ICAO) to IANA zones."""
    return {
        row["code"].strip().upper(): row["timezone"].strip()
        for row in override_rows
        if row.get("code", "").strip()
    }


def build_snapshot_rows(
    airport_rows: Iterable[dict],
    countries: dict[str, str],
    tz_lookup: TimezoneLookup,
    overrides: dict[str, str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Filter OurAirports rows and derive each airport's IANA timezone.

    Keeps large, medium and small airports that have an IATA or ICAO code.
    The timezone comes from the override for the airport's code if there is
    one, otherwise from tz_lookup(latitude, longitude). A missing or Etc/*
    zone is left empty, never replaced by a fixed offset.

    Args:
        airport_rows: rows from OurAirports airports.csv.
        countries: ISO country code to country name.
        tz_lookup: callable taking (latitude, longitude), returning a zone or None.
        overrides: airport code to IANA zone, applied before the lookup.

    Returns:
        tuple: (snapshot rows sorted by code, codes whose timezone is unresolved).
    """
    overrides = overrides or {}
    snapshot = []
    unresolved = []
    for row in airport_rows:
        if row.get("type") not in INCLUDED_TYPES:
            continue
        icao = row.get("icao_code", "").strip().upper()
        iata = row.get("iata_code", "").strip().upper()
        if not icao and not iata:
            continue
        code = icao or iata
        latitude = float(row["latitude_deg"])
        longitude = float(row["longitude_deg"])
        timezone = overrides.get(code) or tz_lookup(latitude, longitude) or ""
        if timezone.startswith("Etc/"):
            timezone = ""
        if not timezone:
            unresolved.append(code)
        country_code = row.get("iso_country", "").strip()
        snapshot.append(
            {
                "icao": icao,
                "iata": iata,
                "name": row.get("name", "").strip(),
                "city": row.get("municipality", "").strip(),
                "country_code": country_code,
                "country": countries.get(country_code, ""),
                "type": row["type"],
                "latitude": f"{latitude:.6f}",
                "longitude": f"{longitude:.6f}",
                "timezone": timezone,
            }
        )
    snapshot.sort(key=lambda r: r["icao"] or r["iata"])
    return snapshot, sorted(unresolved)


def validate_snapshot(
    rows: list[dict],
    previous_count: int | None = None,
    allow_size_change: bool = False,
    require_pilots: bool = True,
) -> None:
    """Check a snapshot before it is written or served.

    Raises:
        SnapshotValidationError: listing every problem found.
    """
    problems = []
    valid_zones = zoneinfo.available_timezones()
    seen_icao = set()
    seen_iata = set()
    for index, row in enumerate(rows, start=2):  # line 1 is the CSV header
        missing = [field for field in SNAPSHOT_FIELDS if row.get(field) is None]
        if missing:
            problems.append(f"line {index}: missing fields {missing}")
            continue
        icao, iata = row["icao"], row["iata"]
        if not icao and not iata:
            problems.append(f"line {index}: no IATA or ICAO code")
        if icao and not ICAO_PATTERN.fullmatch(icao):
            problems.append(f"line {index}: invalid ICAO code {icao!r}")
        if iata and not IATA_PATTERN.fullmatch(iata):
            problems.append(f"line {index}: invalid IATA code {iata!r}")
        if icao and icao in seen_icao:
            problems.append(f"line {index}: duplicate ICAO code {icao}")
        if iata and iata in seen_iata:
            problems.append(f"line {index}: duplicate IATA code {iata}")
        seen_icao.add(icao)
        seen_iata.add(iata)
        if not row["name"]:
            problems.append(f"line {index}: empty name")
        if row["type"] not in INCLUDED_TYPES:
            problems.append(f"line {index}: unexpected type {row['type']!r}")
        try:
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError
        except ValueError:
            problems.append(f"line {index}: invalid coordinates")
        if row["timezone"] and row["timezone"] not in valid_zones:
            problems.append(f"line {index}: unknown timezone {row['timezone']!r}")

    if require_pilots:
        by_icao = {row.get("icao"): row for row in rows}
        for icao, expected_zone in PILOT_AIRPORTS.items():
            pilot = by_icao.get(icao)
            if pilot is None:
                problems.append(f"pilot airport {icao} missing")
            elif pilot.get("timezone") != expected_zone:
                problems.append(
                    f"pilot airport {icao} has timezone {pilot.get('timezone')!r}, "
                    f"expected {expected_zone}"
                )

    if previous_count and not allow_size_change:
        change = abs(len(rows) - previous_count) / previous_count
        if change > MAX_SIZE_CHANGE:
            problems.append(
                f"row count changed from {previous_count} to {len(rows)} "
                f"(more than {MAX_SIZE_CHANGE:.0%})"
            )

    if problems:
        raise SnapshotValidationError(
            f"{len(problems)} problem(s): " + "; ".join(problems[:20])
        )


def read_snapshot(path: Path) -> list[dict]:
    """Read a snapshot CSV into a list of row dicts."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != SNAPSHOT_FIELDS:
            raise SnapshotValidationError(
                f"unexpected snapshot columns {reader.fieldnames}"
            )
        return list(reader)


def write_snapshot(
    rows: list[dict], meta: dict, snapshot_path: Path, meta_path: Path
) -> None:
    """Write the snapshot and its metadata, replacing the old files only on success.

    Both files are written to temporary files in the target directory first and
    then moved into place, so a failure while writing leaves the previous files.
    The two moves are separate: if the second one fails, the new snapshot is in
    place (complete and valid) with the previous metadata, and rerunning the
    import fixes the metadata.
    """
    snapshot_path = Path(snapshot_path)
    meta_path = Path(meta_path)
    temp_paths = []
    try:
        fd, temp_snapshot = tempfile.mkstemp(
            dir=snapshot_path.parent, suffix=".csv.tmp"
        )
        temp_paths.append(temp_snapshot)
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SNAPSHOT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.chmod(temp_snapshot, 0o644)
        fd, temp_meta = tempfile.mkstemp(dir=meta_path.parent, suffix=".json.tmp")
        temp_paths.append(temp_meta)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, sort_keys=True)
            f.write("\n")
        os.chmod(temp_meta, 0o644)
        os.replace(temp_snapshot, snapshot_path)
        os.replace(temp_meta, meta_path)
    finally:
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                os.remove(temp_path)
