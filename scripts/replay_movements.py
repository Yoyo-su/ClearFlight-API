"""
Replay recorded adsb.lol answers through the CF-011 parser and detector.

Each file is one poll (`<anything>-YYYYmmddTHHMMSS.json`, fetch time in UTC).
Used for the probe checks and the P5 validation (docs/cf-011-design.md §9):

    python scripts/replay_movements.py CODE FILE... [--json OUT]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import movements  # noqa: E402
from app.services.positions import Area  # noqa: E402
from app.services.positions_providers import AdsbLol  # noqa: E402


def fetched_at(path: Path) -> datetime:
    stamp = re.search(r"(\d{8}T\d{6})", path.name).group(1)
    return datetime.strptime(stamp, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)


def replay(code: str, files: list[Path]) -> dict:
    ctx = movements.context_for(code)
    if ctx is None:
        raise SystemExit(f"unknown airport {code}")
    area = Area(ctx.latitude, ctx.longitude, 25.0)
    state = movements.empty_state()
    for path in sorted(files, key=fetched_at):
        try:
            body = json.loads(path.read_text())
            result = AdsbLol.parse(body, area, fetched_at(path))
        except Exception:  # noqa: BLE001 - an unreadable poll is a failed poll
            state = movements.record_failure(state, "provider_error")
            continue
        state = movements.detect(state, result, ctx)
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("code")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    state = replay(args.code.upper(), args.files)
    found = state["movements"]
    summary = {}
    for m in found:
        summary[(m["kind"], m["method"])] = summary.get((m["kind"], m["method"]), 0) + 1
    print(f"{args.code}: {len(args.files)} polls; " + ", ".join(f"{k[1]} {k[0]}s: {v}" for k, v in sorted(summary.items())))
    mode = movements.coverage_mode(state)
    print(f"coverage mode: {mode[0]}{f' ({mode[1]})' if mode[1] else ''}; windows: {len(state['windows']) + (1 if state['window'] else 0)}")
    if args.json:
        args.json.write_text(json.dumps(found, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
