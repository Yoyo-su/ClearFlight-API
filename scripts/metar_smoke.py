"""
Live smoke check of the METAR adapter for the pilot airports (or given stations).

Run from the repository root (makes real requests to the Aviation Weather Center):

    python scripts/metar_smoke.py
    python scripts/metar_smoke.py EGKK LFPG

Prints each observation's source, observation and fetch times, age and
freshness. Exits non-zero if any lookup fails. Not run in CI.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.airport_import import PILOT_AIRPORTS  # noqa: E402
from app.services.metar import (  # noqa: E402
    MetarError,
    age_minutes,
    freshness,
    get_latest_observation,
)


def main(stations: list[str]) -> int:
    failures = 0
    now = datetime.now(timezone.utc)
    for station in stations:
        try:
            obs = get_latest_observation(station)
        except (MetarError, ValueError) as e:
            print(f"{station}: FAILED ({type(e).__name__}: {e})")
            failures += 1
            continue
        if obs is None:
            print(f"{station}: no report available")
            continue
        print(
            f"{station}: source={obs.source} observed_at={obs.observed_at.isoformat()} "
            f"fetched_at={obs.fetched_at.isoformat(timespec='seconds')} "
            f"age={age_minutes(obs.observed_at, now):.0f} min "
            f"freshness={freshness(obs.observed_at, now)}\n  {obs.raw_text}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or list(PILOT_AIRPORTS)))
