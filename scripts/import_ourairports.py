"""
Rebuild the airport catalogue snapshot (app/data/airports.csv) from OurAirports.

Run from the repository root in an environment with requirements-import.txt
installed (not needed by the API or CI):

    python scripts/import_ourairports.py
    python scripts/import_ourairports.py --airports airports.csv --countries countries.csv

The new snapshot is validated before it replaces the current one; on any
failure the current snapshot is left unchanged.
"""

import argparse
import csv
import io
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.airport_import import (  # noqa: E402
    OURAIRPORTS_AIRPORTS_URL,
    OURAIRPORTS_COUNTRIES_URL,
    build_snapshot_rows,
    parse_countries,
    parse_overrides,
    read_snapshot,
    validate_snapshot,
    write_snapshot,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "app" / "data"
SNAPSHOT_PATH = DATA_DIR / "airports.csv"
META_PATH = DATA_DIR / "airports.meta.json"
OVERRIDES_PATH = DATA_DIR / "timezone_overrides.csv"
DOWNLOAD_TIMEOUT = 60  # seconds


def load_csv(local_path: str | None, url: str) -> list[dict]:
    if local_path:
        with open(local_path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
    response.raise_for_status()
    response.encoding = "utf-8"
    return list(csv.DictReader(io.StringIO(response.text)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--airports", help="local airports.csv instead of downloading")
    parser.add_argument(
        "--countries", help="local countries.csv instead of downloading"
    )
    parser.add_argument(
        "--allow-size-change",
        action="store_true",
        help="accept a row count more than 10%% different from the current snapshot",
    )
    args = parser.parse_args()

    airport_rows = load_csv(args.airports, OURAIRPORTS_AIRPORTS_URL)
    countries = parse_countries(load_csv(args.countries, OURAIRPORTS_COUNTRIES_URL))
    with open(OVERRIDES_PATH, newline="", encoding="utf-8") as f:
        overrides = parse_overrides(csv.DictReader(f))

    from timezonefinder import TimezoneFinder  # requirements-import.txt only

    finder = TimezoneFinder()
    rows, unresolved = build_snapshot_rows(
        airport_rows,
        countries,
        lambda lat, lng: finder.timezone_at(lng=lng, lat=lat),
        overrides,
    )

    previous_count = (
        len(read_snapshot(SNAPSHOT_PATH)) if SNAPSHOT_PATH.exists() else None
    )
    validate_snapshot(rows, previous_count, args.allow_size_change)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "airports": args.airports or OURAIRPORTS_AIRPORTS_URL,
            "countries": args.countries or OURAIRPORTS_COUNTRIES_URL,
        },
        "source_rows": len(airport_rows),
        "row_count": len(rows),
        "timezone_overrides": len(overrides),
        "unresolved_timezones": unresolved,
        "timezonefinder": version("timezonefinder"),
        "timezonefinder_data": version("timezonefinder-data"),
    }
    write_snapshot(rows, meta, SNAPSHOT_PATH, META_PATH)
    print(
        f"Wrote {len(rows)} airports to {SNAPSHOT_PATH} "
        f"({len(unresolved)} without a timezone: {', '.join(unresolved[:20]) or 'none'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
