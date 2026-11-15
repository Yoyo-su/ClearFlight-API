from dataclasses import dataclass
from datetime import datetime, timedelta

from app.services.positions import FeedResult, Target, distance_nm

"""
Movement detection from live positions (CF-011 design r3 §3-§5).

`detect` is pure: (state, poll) -> (new state, changes). The store keeps one
JSON state per (provider, airport) and applies it with a compare-and-set on
the poll's data time, so a poll is processed at most once.

Vocabulary:
- usable poll: a fresh provider answer newer than the last processed one;
- failed poll: an error, a quota stop, a busy result or an unusable answer;
  it ends the watched window and never counts as absence;
- fix state: "ground", "airborne" (not on ground AND a numeric altitude) or
  "unknown" (no evidence either way).
"""

MAX_POLL_GAP = timedelta(seconds=90)  # consecutive usable polls in one window
FRESH_FEED = timedelta(seconds=60)  # provider data time vs fetch time
AIRCRAFT_TTL = timedelta(minutes=15)  # forget aircraft not seen for this long
RETENTION = timedelta(hours=6)  # movements and windows (V4)
COVERAGE_TTL = timedelta(hours=24)
DEDUPE = timedelta(minutes=10)  # one movement per aircraft and kind
REAPPEAR = timedelta(minutes=10)  # withdraws an inferred arrival
ATTRIBUTION_NM = 4.0  # nearest airport within (V2)
AMBIGUITY_NM = 1.0  # second-nearest closer than nearest + this: dropped (V2)
INFER_NM = 2.0  # inferred: within this of the attributed airport (V3)
INFER_AGL_FT = 1500  # inferred: below this above field elevation (V3)
INFER_RATE_FPM = 200  # inferred: climbing/descending faster than this (V3)
ABSENT_POLLS = 2  # inferred arrival: absent from this many usable polls (V3)
HELICOPTER = "A7"  # excluded (V6)


@dataclass(frozen=True)
class Place:
    code: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class AirportContext:
    """The viewed airport and the catalogue airports near it (for attribution)."""

    code: str
    latitude: float
    longitude: float
    elevation_ft: int | None
    neighbours: tuple[
        Place, ...
    ]  # every catalogue airport within ~10 nm, incl. this one


def iso(t: datetime) -> str:
    return t.isoformat()


def parse(t: str) -> datetime:
    return datetime.fromisoformat(t)


def empty_state() -> dict:
    return {
        "last_poll": None,  # data time of the last processed usable poll
        "window": None,  # {"from", "to", "polls"} while watching
        "windows": [],  # closed: {"from", "to", "ended_by"}
        "aircraft": {},  # id -> last fix {"t", "state", "lat", "lon", "alt", "vr", "callsign"}
        "pending": {},  # id -> inferred-arrival candidate {"fix", "absent"}
        "recent": {},  # id -> {"departure"|"arrival"|"observed": time} for de-duplication/guards
        "movements": [],
        "coverage": [],  # hourly buckets {"hour", "polls", "ground_near", "low_air_near", "observed", "airborne"}
    }


def fix_state(t: Target) -> str:
    if t.on_ground:
        return "ground"
    return "airborne" if t.altitude_ft is not None else "unknown"


def attribute(
    lat: float, lon: float, ctx: AirportContext, limit_nm: float
) -> str | None:
    """The nearest airport within limit_nm, or None if none or ambiguous (V2)."""
    ranked = sorted(
        (distance_nm(lat, lon, p.latitude, p.longitude), p.code) for p in ctx.neighbours
    )
    if not ranked or ranked[0][0] > limit_nm:
        return None
    if len(ranked) > 1 and ranked[1][0] - ranked[0][0] < AMBIGUITY_NM:
        return None  # two airports almost equally close: never guess
    return ranked[0][1]


def is_replay(result: FeedResult, state: dict) -> bool:
    """Data time already processed (or older): a no-op, never a failed poll."""
    return state["last_poll"] is not None and result.observed_at <= parse(
        state["last_poll"]
    )


def usable(result: FeedResult, state: dict) -> bool:
    if abs(result.fetched_at - result.observed_at) > FRESH_FEED:
        return False
    if not result.targets and result.dropped:
        return False  # nothing usable in the answer
    return True


def end_window(state: dict, reason: str) -> None:
    window = state["window"]
    if window is not None:
        state["windows"].append(
            {"from": window["from"], "to": window["to"], "ended_by": reason}
        )
        state["window"] = None
    state["aircraft"] = {}  # no transition or inference across a break
    state["pending"] = {}


def record_failure(state: dict, reason: str) -> dict:
    """A failed poll (error, quota, busy, unusable): ends the watched window."""
    end_window(state, reason)
    return state


def bucket(state: dict, t: datetime) -> dict:
    hour = t.replace(minute=0, second=0, microsecond=0).isoformat()
    for b in state["coverage"]:
        if b["hour"] == hour:
            return b
    b = {
        "hour": hour,
        "polls": 0,
        "ground_near": 0,
        "low_air_near": 0,
        "observed": 0,
        "airborne": 0,
    }
    state["coverage"].append(b)
    return b


def add_movement(
    state, ctx, kind, method, target_id, callsign, fix, t_from, t_to
) -> bool:
    recent = state["recent"].setdefault(target_id, {})
    last = recent.get(kind)
    if last is not None and t_to - parse(last) < DEDUPE:
        return False
    recent[kind] = iso(t_to)
    if method == "observed":
        recent["observed"] = iso(t_to)
    state["movements"].append(
        {
            "kind": kind,
            "method": method,
            "id": target_id,
            "callsign": callsign,
            "time_from": iso(t_from),
            "time_to": iso(t_to),
            "distance_nm": round(
                distance_nm(ctx.latitude, ctx.longitude, fix["lat"], fix["lon"]), 1
            ),
        }
    )
    return True


def low_and_close(fix: dict, ctx: AirportContext) -> bool:
    if ctx.elevation_ft is None or fix["alt"] is None:
        return False
    return (
        fix["alt"] - ctx.elevation_ft < INFER_AGL_FT
        and attribute(fix["lat"], fix["lon"], ctx, INFER_NM) == ctx.code
    )


def recently_observed(state: dict, target_id: str, t: datetime) -> bool:
    last = state["recent"].get(target_id, {}).get("observed")
    return last is not None and t - parse(last) < DEDUPE


def detect(state: dict, result: FeedResult, ctx: AirportContext) -> dict:
    """Process one fresh provider answer for the viewed airport (spec §3-§4)."""
    if is_replay(result, state):
        return state  # exactly once by data time (spec §5)
    if not usable(result, state):
        return record_failure(state, "unusable")
    t = result.observed_at
    window = state["window"]
    first_of_window = window is None or t - parse(window["to"]) > MAX_POLL_GAP
    if first_of_window:
        end_window(state, "gap")
        state["window"] = {"from": iso(t), "to": iso(t), "polls": 1}
    else:
        window["to"] = iso(t)
        window["polls"] += 1
    previous_poll = None if first_of_window else state["last_poll"]
    state["last_poll"] = iso(t)
    cov = bucket(state, t)
    cov["polls"] += 1

    seen = set()
    for target in result.targets:
        if target.category == HELICOPTER:
            continue
        status = fix_state(target)
        fix = {
            "t": iso(t),
            "state": status,
            "lat": target.latitude,
            "lon": target.longitude,
            "alt": target.altitude_ft,
            "vr": target.vertical_rate_fpm,
            "callsign": target.callsign,
            "seen": iso(t),  # the last usable poll the aircraft was present in
        }
        seen.add(target.id)
        if status == "airborne":
            cov["airborne"] += 1
        if status == "ground" and target.distance_nm <= ATTRIBUTION_NM:
            cov["ground_near"] += 1
        if status == "airborne" and low_and_close(fix, ctx):
            cov["low_air_near"] += 1
        prev = state["aircraft"].get(target.id)
        if status == "unknown":
            # No evidence: keep the previous fix, but the aircraft was present,
            # so it isn't absent (pending arrival) and the chain isn't broken.
            state["pending"].pop(target.id, None)
            if prev is not None and prev.get("seen", prev["t"]) == previous_poll:
                prev["seen"] = iso(t)
            continue
        # The last known fix, in this window (state is cleared at every break),
        # at most 90 s ago, with the aircraft present at every usable poll
        # since (spec §3: consecutive polls); "unknown" fixes in between
        # neither complete nor break the transition.
        consecutive = (
            prev is not None
            and prev.get("seen", prev["t"]) == previous_poll
            and t - parse(prev["t"]) <= MAX_POLL_GAP
        )

        # A reappearance within 10 min withdraws an inferred arrival (go-around, coverage drop).
        if status == "airborne":
            withdraw_reappeared(state, target.id, t)
        state["pending"].pop(target.id, None)

        if consecutive and prev["state"] == "ground" and status == "airborne":
            if attribute(prev["lat"], prev["lon"], ctx, ATTRIBUTION_NM) == ctx.code:
                if add_movement(
                    state,
                    ctx,
                    "departure",
                    "observed",
                    target.id,
                    target.callsign,
                    prev,
                    parse(prev["t"]),
                    t,
                ):
                    cov["observed"] += 1
        elif consecutive and prev["state"] == "airborne" and status == "ground":
            if attribute(fix["lat"], fix["lon"], ctx, ATTRIBUTION_NM) == ctx.code:
                if add_movement(
                    state,
                    ctx,
                    "arrival",
                    "observed",
                    target.id,
                    target.callsign,
                    fix,
                    parse(prev["t"]),
                    t,
                ):
                    cov["observed"] += 1
        elif (
            prev is None
            and not first_of_window
            and status == "airborne"
            and (fix["vr"] or 0) > INFER_RATE_FPM
            and low_and_close(fix, ctx)
            and not recently_observed(state, target.id, t)
        ):
            add_movement(
                state,
                ctx,
                "departure",
                "inferred",
                target.id,
                target.callsign,
                fix,
                parse(previous_poll),
                t,
            )
        state["aircraft"][target.id] = fix

    # Inferred arrivals: last seen low, close and descending, then absent.
    for target_id, prev in list(state["aircraft"].items()):
        if target_id in seen:
            continue
        if (
            prev["t"] == previous_poll
            and prev["state"] == "airborne"
            and (prev["vr"] or 0) < -INFER_RATE_FPM
            and low_and_close(prev, ctx)
        ):
            state["pending"].setdefault(target_id, {"fix": prev, "absent": 0})
        candidate = state["pending"].get(target_id)
        if candidate is not None:
            candidate["absent"] += 1
            if candidate["absent"] >= ABSENT_POLLS:
                fix = candidate["fix"]
                if not recently_observed(state, target_id, t):
                    add_movement(
                        state,
                        ctx,
                        "arrival",
                        "inferred",
                        target_id,
                        fix["callsign"],
                        fix,
                        parse(fix["t"]),
                        t,
                    )
                state["pending"].pop(target_id)

    trim(state, t)
    return state


def withdraw_reappeared(state: dict, target_id: str, t: datetime) -> None:
    for m in list(state["movements"]):
        if (
            m["id"] == target_id
            and m["method"] == "inferred"
            and m["kind"] == "arrival"
            and t - parse(m["time_to"]) < REAPPEAR
        ):
            state["movements"].remove(m)
            state["recent"].get(target_id, {}).pop("arrival", None)


def trim(state: dict, now: datetime) -> None:
    state["aircraft"] = {
        k: v for k, v in state["aircraft"].items() if now - parse(v["t"]) < AIRCRAFT_TTL
    }
    state["movements"] = [
        m for m in state["movements"] if now - parse(m["time_to"]) < RETENTION
    ]
    state["windows"] = [w for w in state["windows"] if now - parse(w["to"]) < RETENTION]
    state["coverage"] = [
        b for b in state["coverage"] if now - parse(b["hour"]) < COVERAGE_TTL
    ]
    state["recent"] = {
        k: {kind: when for kind, when in v.items() if now - parse(when) < DEDUPE}
        for k, v in state["recent"].items()
    }
    state["recent"] = {k: v for k, v in state["recent"].items() if v}


def coverage_mode(state: dict) -> tuple[str, str | None]:
    """surface / airborne_only / unknown with a reason (spec §4)."""
    polls = sum(b["polls"] for b in state["coverage"])
    if polls < 10:
        return "unknown", "not_enough_watching"
    observed = sum(b["observed"] for b in state["coverage"])
    ground = sum(b["ground_near"] for b in state["coverage"])
    low = sum(b["low_air_near"] for b in state["coverage"])
    airborne = sum(b["airborne"] for b in state["coverage"])
    if observed or ground >= 3:
        return "surface", None
    if ground:
        return "unknown", "not_enough_watching"  # some ground evidence, not enough
    if low:
        return "airborne_only", None
    if airborne:
        return "unknown", "no_low_traffic_seen"
    return "unknown", "no_recent_data"


# -- Store (spec §5) -----------------------------------------------------------

import json  # noqa: E402
import logging  # noqa: E402

logger = logging.getLogger(__name__)

STATE_TTL_S = int(
    COVERAGE_TTL.total_seconds()
)  # contents are trimmed to 6 h at every write
NEIGHBOUR_NM = 10.0

# Compare-and-set on the last processed poll: KEYS state, last; ARGV expected
# last ("" for none), new state JSON, new last, ttl. Returns 1 if applied.
APPLY = """
local current = redis.call('GET', KEYS[2]) or ''
if current ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[4])
if ARGV[3] == '' then redis.call('DEL', KEYS[2]) else redis.call('SET', KEYS[2], ARGV[3], 'EX', ARGV[4]) end
return 1
"""

_contexts: dict[str, AirportContext] = {}


def context_for(code: str) -> AirportContext | None:
    """The viewed airport and its catalogue neighbours (cached per process)."""
    if code in _contexts:
        return _contexts[code]
    from app.services.airport_catalogue import get_catalogue

    catalogue = get_catalogue()
    airport = catalogue.get(code)
    if airport is None:
        return None
    neighbours = tuple(
        Place(a.code, a.latitude, a.longitude)
        for a in catalogue.airports
        if distance_nm(airport.latitude, airport.longitude, a.latitude, a.longitude)
        <= NEIGHBOUR_NM
    )
    ctx = AirportContext(
        airport.code,
        airport.latitude,
        airport.longitude,
        airport.elevation_ft,
        neighbours,
    )
    _contexts[code] = ctx
    return ctx


def keys(provider: str, code: str) -> tuple[str, str]:
    base = f"movements:v1:{provider}:{code}"
    return base, f"{base}:last"


def load(client, provider: str, code: str) -> tuple[dict, str]:
    """The stored state and the last processed poll ("" if none).

    Raises redis errors (callers treat them as a failed poll).
    """
    state_key, last_key = keys(provider, code)
    raw, last = client.get(state_key), client.get(last_key) or ""
    try:
        state = json.loads(raw) if raw else empty_state()
    except ValueError:
        state = empty_state()
    if (state.get("last_poll") or "") != last:
        # Partial loss (one key gone or out of step): a window break.
        end_window(state, "state_lost")
        state["last_poll"] = last or None
    return state, last


def save(client, provider: str, code: str, state: dict, expected_last: str) -> bool:
    state_key, last_key = keys(provider, code)
    applied = client.eval(
        APPLY,
        2,
        state_key,
        last_key,
        expected_last,
        json.dumps(state),
        state["last_poll"] or "",
        STATE_TTL_S,
    )
    return bool(applied)


def observe(client, provider: str, code: str, result: FeedResult) -> None:
    """Run the detector for one fresh provider answer (inside single-flight).

    Never raises: a store failure is logged; the next poll then finds the
    window broken (spec §5: a failed detector run is a failed poll).
    """
    ctx = context_for(code)
    if ctx is None:
        return
    try:
        state, last = load(client, provider, code)
        if is_replay(result, state):
            return  # already processed: nothing to write
        state = detect(state, result, ctx)
        if not save(client, provider, code, state, last):
            logger.info("Movements for %s already processed by another request", code)
    except Exception as e:  # noqa: BLE001 - detection must never break positions
        logger.warning("Movement detection failed for %s: %s", code, type(e).__name__)
        record_failed_poll(client, provider, code, "detector_error")


def record_failed_poll(client, provider: str, code: str, reason: str) -> None:
    """A failed poll ends the watched window (never counts as absence)."""
    try:
        state, last = load(client, provider, code)
        save(client, provider, code, record_failure(state, reason), last)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Couldn't record a failed poll for %s: %s", code, type(e).__name__
        )


def read(client, provider: str, code: str, now: datetime) -> dict | None:
    """The stored state for the API, with retention applied at read time."""
    state_key, _ = keys(provider, code)
    raw = client.get(state_key)
    if not raw:
        return None
    try:
        state = json.loads(raw)
    except ValueError:
        return None
    state["movements"] = [
        m for m in state["movements"] if now - parse(m["time_to"]) < RETENTION
    ]
    window = state.get("window")
    if window is not None and now - parse(window["to"]) > MAX_POLL_GAP:
        # Nobody is watching any more: the open window ended at its last poll.
        state["windows"].append(
            {"from": window["from"], "to": window["to"], "ended_by": "gap"}
        )
        state["window"] = None
    state["windows"] = [w for w in state["windows"] if now - parse(w["to"]) < RETENTION]
    state["coverage"] = [
        b for b in state["coverage"] if now - parse(b["hour"]) < COVERAGE_TTL
    ]
    return state
