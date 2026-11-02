"""
List the METAR weather groups the conditions index couldn't interpret.

Run where the API's Redis is reachable, e.g. inside the container:

    docker compose exec clearflightapi python scripts/unrecognised_weather.py

Each group is shown with how many observations contained it and the last
example report, so it can be added to the scoring table (D-007).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.unrecognised_weather import summary  # noqa: E402


def main() -> int:
    rows = summary()
    if not rows:
        print("No unrecognised weather groups recorded.")
        return 0
    for row in rows:
        example = row["example"] or {}
        print(
            f"{row['group']}: {row['count']} observation(s); last at "
            f"{example.get('station')} {example.get('observed_at')}\n"
            f"  {example.get('raw_text')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
