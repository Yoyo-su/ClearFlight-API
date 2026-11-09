import logging
import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from app.services import conditions as index
from app.services.cache import cache_response, check_cache
from app.services.metar import (
    METRES_PER_STATUTE_MILE,
    METRES_TEN_KM,
    STATION_PATTERN,
    MetarUpstreamError,
    fetch_metar_records,
    number,
    parse_visibility,
)

"""
Airport forecasts (TAF) from the Aviation Weather Center, turned into an
hourly outlook (CF-008 design spec r3, D-011).

AWC decodes each TAF into periods; the raw text decides which elements each
change group actually states, so an element a TEMPO/BECMG group omits is
inherited, while one it states but that can't be read is unknown (never
inherited). Overlapping transitions are handled as sets of candidate states,
and an hour scores the worst candidate (F3).
"""

logger = logging.getLogger(__name__)

AWC_TAF_URL = "https://aviationweather.gov/api/data/taf"
SOURCE = "NOAA Aviation Weather Center: Terminal Aerodrome Forecast"
FORECAST_CACHE_TTL = 1800  # seconds; TAFs are issued about every 6 h
NO_FORECAST = {"no_forecast": True}
HORIZON_HOURS = 12  # F2

ELEMENTS = ("wind", "visibility", "weather", "sky")
UNKNOWN = object()  # an element a group states but that can't be read
OMITTED = object()  # an element a group doesn't state

KNOWN_CHANGES = (None, "FM", "BECMG", "TEMPO", "PROB")
CHANGE_TOKEN = re.compile(r"^(FM\d{6}|BECMG|TEMPO|PROB30|PROB40)$")
WIND_TOKEN = re.compile(r"^(\d{3}|VRB)\d{2,3}(G\d{2,3})?(KT|MPS)$")
VISIBILITY_TOKEN = re.compile(r"^(\d{4}|[PM]?\d+SM|[PM]?\d+/\d+SM|CAVOK)$")
WEATHER_TOKEN = re.compile(
    r"^(NSW|(-|\+|VC)?(MI|PR|BC|DR|BL|SH|TS|FZ)?"
    r"(DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+"
    r"|(-|\+|VC)?(TS|SH))$"
)
SKY_TOKEN = re.compile(
    r"^((FEW|SCT|BKN|OVC)(\d{3}|///)(CB|TCU)?|NSC|SKC|CLR|VV(\d{3}|///)|CAVOK)$"
)
CEILING_COVERS = {"BKN", "OVC"}
LAYER_COVERS = {"FEW", "SCT", "BKN", "OVC"}


@dataclass(frozen=True)
class ForecastState:
    """Forecast conditions, with the attributes the conditions index reads."""

    wind_speed_kt: int | None = None
    wind_gust_kt: int | None = None
    wind_direction_deg: int | None = None
    wind_variable: bool = False
    visibility_m: int | None = None
    visibility_at_least: bool = False
    sky_condition: str = "unknown"
    ceiling_ft: int | None = None
    weather_phenomena: tuple | None = ()  # None: unknown
    known: frozenset = field(default_factory=frozenset)  # elements with values

    def with_elements(self, elements: dict) -> "ForecastState":
        """This state with some elements replaced (values, or UNKNOWN)."""
        updates, known = {}, set(self.known)
        for name, value in elements.items():
            if value is OMITTED:
                continue
            if value is UNKNOWN:
                updates.update(UNKNOWN_FIELDS[name])
                known.discard(name)
            else:
                updates.update(value)
                known.add(name)
        return replace(self, **updates, known=frozenset(known))


UNKNOWN_FIELDS = {
    "wind": {
        "wind_speed_kt": None,
        "wind_gust_kt": None,
        "wind_direction_deg": None,
        "wind_variable": False,
    },
    "visibility": {"visibility_m": None, "visibility_at_least": False},
    "weather": {"weather_phenomena": None},
    "sky": {"sky_condition": "unknown", "ceiling_ft": None},
}
EMPTY_STATE = ForecastState().with_elements({name: UNKNOWN for name in ELEMENTS})


@dataclass(frozen=True)
class Period:
    change: str | None  # None (base), FM, BECMG, TEMPO, PROB
    probability: int | None
    start: datetime
    end: datetime
    becoming: datetime | None
    elements: dict  # element -> values dict, UNKNOWN or OMITTED


def get_latest_forecast(icao: str) -> dict | None:
    """The station's latest valid TAF record from AWC, using the cache.

    Raises:
        ValueError: if icao isn't 4 letters or digits.
        MetarTimeout, MetarUpstreamError (incl. reason "invalid_forecast"),
        MetarRateLimited: provider failures.

    Returns:
        dict or None: the selected TAF record; None when AWC has no TAF.
    """
    station = icao.strip().upper()
    if not STATION_PATTERN.fullmatch(station):
        raise ValueError("Station must be a 4-character ICAO code")
    cache_key = f"taf:v1:{station}"
    cached = check_cache(cache_key)
    if cached == NO_FORECAST:
        return None
    if isinstance(cached, dict):
        try:
            parse_taf(cached, station)
            return cached
        except MetarUpstreamError:
            logger.warning("Ignoring invalid cached TAF for %s", station)
    records = fetch_metar_records(station, AWC_TAF_URL)
    if not records:
        cache_response(cache_key, NO_FORECAST, FORECAST_CACHE_TTL)
        return None
    record = select_taf(records, station)
    parse_taf(record, station)  # validate before caching (raises if invalid)
    cache_response(cache_key, record, FORECAST_CACHE_TTL)
    return record


def select_taf(records: list, station: str) -> dict:
    """The most recent TAF for the station (mostRecent, else latest issueTime)."""
    own = [r for r in records if isinstance(r, dict) and r.get("icaoId") == station]
    if not own:
        raise MetarUpstreamError("invalid_forecast", "no TAF for the requested station")
    flagged = [r for r in own if r.get("mostRecent") == 1]
    pool = flagged or own
    return max(pool, key=lambda r: str(r.get("issueTime") or ""))


def epoch(value, name: str) -> datetime:
    seconds = number(value, 0, 4102444800, name)  # up to 2100-01-01
    if seconds is None:
        raise MetarUpstreamError("invalid_forecast", f"bad {name}")
    return datetime.fromtimestamp(seconds, timezone.utc)


def iso(value, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise MetarUpstreamError("invalid_forecast", f"bad {name}")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def raw_groups(raw: str) -> list[tuple[str, int | None, list[str]]]:
    """Split a raw TAF into (change, probability, tokens) groups, base first."""
    tokens = raw.split()
    if "RMK" in tokens:
        tokens = tokens[: tokens.index("RMK")]
    # Skip the header: TAF [AMD|COR] STATION ddhhmmZ ddhh/ddhh
    i = 0
    while i < len(tokens) and not re.fullmatch(r"\d{4}/\d{4}", tokens[i]):
        i += 1
    groups = [[None, None, []]]
    i += 1
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("FM") and CHANGE_TOKEN.fullmatch(token):
            groups.append(["FM", None, []])
        elif token in ("BECMG", "TEMPO"):
            if groups[-1][0] == "PROB" and not groups[-1][2]:
                groups[-1][0] = "TEMPO"  # PROB30 TEMPO is one group
            else:
                groups.append([token, None, []])
        elif token in ("PROB30", "PROB40"):
            groups.append(["PROB", int(token[4:]), []])
        else:
            groups[-1][2].append(token)
        i += 1
    return [(c, p, t) for c, p, t in groups]


def stated(tokens: list[str]) -> dict:
    """Which elements a raw group states."""
    words = [t for t in tokens if not re.fullmatch(r"\d{4}/\d{4}", t)]
    return {
        "wind": any(WIND_TOKEN.fullmatch(t) for t in words),
        "visibility": any(VISIBILITY_TOKEN.fullmatch(t) for t in words),
        "weather": any(WEATHER_TOKEN.fullmatch(t) for t in words),
        "sky": any(SKY_TOKEN.fullmatch(t) for t in words),
    }


def decode_elements(fcst: dict, tokens: list[str], raw_taf: str, full: bool) -> dict:
    """Element values for one period: values, UNKNOWN, or OMITTED."""
    present = stated(tokens)
    cavok = "CAVOK" in tokens
    elements = {}

    if present["wind"]:
        speed = number(fcst.get("wspd"), 0, 250, "wspd")
        gust = number(fcst.get("wgst"), 0, 300, "wgst")
        if gust is not None and speed is not None and gust < speed:
            gust = None
        direction = fcst.get("wdir")
        variable = direction == "VRB"
        elements["wind"] = (
            UNKNOWN
            if speed is None
            else {
                "wind_speed_kt": round(speed),
                "wind_gust_kt": None if gust is None else round(gust),
                "wind_direction_deg": (
                    None
                    if variable
                    else (
                        None
                        if (d := number(direction, 0, 360, "wdir")) is None
                        else round(d)
                    )
                ),
                "wind_variable": variable,
            }
        )

    if present["visibility"]:
        metric = next((t for t in tokens if re.fullmatch(r"\d{4}", t)), None)
        if cavok or metric == "9999":
            elements["visibility"] = {
                "visibility_m": METRES_TEN_KM,
                "visibility_at_least": True,
            }
        elif metric:  # exact metres, rather than AWC's rounded statute miles
            elements["visibility"] = {
                "visibility_m": int(metric),
                "visibility_at_least": False,
            }
        else:
            miles, at_least = parse_visibility(fcst.get("visib"), raw_taf)
            metres = (
                None
                if miles is None
                else number(miles * METRES_PER_STATUTE_MILE, 0, math.inf, "visib")
            )
            elements["visibility"] = (
                UNKNOWN
                if metres is None
                else {"visibility_m": round(metres), "visibility_at_least": at_least}
            )

    if present["weather"] or cavok:
        text = fcst.get("wxString")
        if cavok and not present["weather"]:
            elements["weather"] = {"weather_phenomena": ()}
        elif isinstance(text, str) and text.strip():
            groups = tuple(g for g in text.split() if g != "NSW")
            elements["weather"] = {"weather_phenomena": groups}
        else:
            elements["weather"] = UNKNOWN

    if present["sky"]:
        elements["sky"] = decode_sky(fcst, tokens)

    if full and "weather" not in elements:
        # A base or FM group without weather forecasts no significant weather.
        elements["weather"] = {"weather_phenomena": ()}
    for name in ELEMENTS:
        if name not in elements:
            # A base or FM group must be complete; elsewhere, omitted = unchanged.
            elements[name] = UNKNOWN if full else OMITTED
    return elements


def decode_sky(fcst: dict, tokens: list[str]):
    if any(t in ("CAVOK",) for t in tokens):
        return {"sky_condition": "cavok", "ceiling_ft": None}
    if any(t in ("NSC", "SKC", "CLR") for t in tokens):
        return {"sky_condition": "clear", "ceiling_ft": None}
    vv = next((t for t in tokens if t.startswith("VV")), None)
    if vv == "VV///":
        return {"sky_condition": "obscured", "ceiling_ft": None}
    if vv:
        height = number(fcst.get("vertVis"), 0, 100000, "vertVis")
        if height is None:
            height = int(vv[2:]) * 100
        return {"sky_condition": "clouds", "ceiling_ft": round(height)}
    raw_layers = [t for t in tokens if SKY_TOKEN.fullmatch(t) and t[:3] in LAYER_COVERS]
    decoded = fcst.get("clouds") if isinstance(fcst.get("clouds"), list) else []
    layers = []
    for layer in decoded:
        if not isinstance(layer, dict) or layer.get("cover") not in LAYER_COVERS:
            continue
        base = number(layer.get("base"), 0, 100000, "cloud base")
        if base is None:
            return UNKNOWN
        layers.append((layer["cover"], round(base)))
    if len(layers) != len(raw_layers) or not layers:
        return UNKNOWN  # raw and decoded disagree: never guess
    ceilings = [base for cover, base in layers if cover in CEILING_COVERS]
    return {
        "sky_condition": "clouds",
        "ceiling_ft": min(ceilings) if ceilings else None,
    }


def parse_taf(record: dict, station: str) -> tuple[dict, list[Period]]:
    """Validate a TAF record and decode its periods (spec §3.1–3.3).

    Raises:
        MetarUpstreamError("invalid_forecast"): the record can't be used.
    """
    if not isinstance(record, dict) or record.get("icaoId") != station:
        raise MetarUpstreamError("invalid_forecast", "station mismatch")
    raw = record.get("rawTAF")
    fcsts = record.get("fcsts")
    if not isinstance(raw, str) or not isinstance(fcsts, list) or not fcsts:
        raise MetarUpstreamError("invalid_forecast", "missing raw text or periods")
    meta = {
        "source": SOURCE,
        "station": station,
        "issued_at": iso(record.get("issueTime"), "issueTime"),
        "valid_from": epoch(record.get("validTimeFrom"), "validTimeFrom"),
        "valid_to": epoch(record.get("validTimeTo"), "validTimeTo"),
        "raw_text": raw,
    }
    if meta["valid_from"] >= meta["valid_to"]:
        raise MetarUpstreamError("invalid_forecast", "empty validity")

    groups = raw_groups(raw)
    aligned = len(groups) == len(fcsts) and all(
        isinstance(fcst, dict)
        and (group[0], group[1]) == (fcst.get("fcstChange"), fcst.get("probability"))
        for group, fcst in zip(groups, fcsts)
    )
    if not aligned:
        logger.warning("TAF %s: raw groups don't match decoded periods", station)
    periods = []
    for i, fcst in enumerate(fcsts):
        if not isinstance(fcst, dict):
            raise MetarUpstreamError("invalid_forecast", "bad period")
        change = fcst.get("fcstChange")
        probability = fcst.get("probability")
        start = epoch(fcst.get("timeFrom"), "timeFrom")
        end = epoch(fcst.get("timeTo"), "timeTo")
        becoming = (
            epoch(fcst.get("timeBec"), "timeBec")
            if fcst.get("timeBec") is not None
            else None
        )
        if not (meta["valid_from"] <= start < end <= meta["valid_to"]):
            raise MetarUpstreamError("invalid_forecast", "period outside validity")
        if becoming is not None and not (start <= becoming <= meta["valid_to"]):
            raise MetarUpstreamError("invalid_forecast", "bad transition time")
        if i == 0 and (change is not None or start != meta["valid_from"]):
            raise MetarUpstreamError("invalid_forecast", "no base period")
        if aligned and change in KNOWN_CHANGES:
            elements = decode_elements(fcst, groups[i][2], raw, change in (None, "FM"))
        else:
            elements = {name: UNKNOWN for name in ELEMENTS}  # never guess
        if probability is not None and probability not in (30, 40):
            probability = None
        periods.append(Period(change, probability, start, end, becoming, elements))
    return meta, periods


def candidates_at(periods: list[Period], t: datetime) -> list[ForecastState]:
    """The prevailing states that could be in force at time t (spec §3.4)."""
    candidates = [EMPTY_STATE.with_elements(periods[0].elements)]
    for period in periods[1:]:
        if period.change == "FM" and t >= period.start:
            candidates = [EMPTY_STATE.with_elements(period.elements)]
        elif period.change == "BECMG" and t >= period.start:
            changed = [c.with_elements(period.elements) for c in candidates]
            done = period.becoming or period.end
            candidates = changed if t >= done else candidates + changed
        elif period.change not in KNOWN_CHANGES and period.start <= t < period.end:
            candidates = candidates + [EMPTY_STATE]  # unknown change type
    unique = []
    for c in candidates:
        if c not in unique:
            unique.append(c)
    return unique


def worst(states: list[ForecastState]) -> tuple[ForecastState, dict]:
    """The state with the worst forecast index: 10, else unknown, else highest."""
    scored = [(s, index.evaluate_forecast(s)) for s in states]
    ten = [x for x in scored if x[1]["score"] == index.MAX_SCORE]
    if ten:
        return ten[0]
    unknown = [x for x in scored if x[1]["score"] is None]
    if unknown:
        return unknown[0]
    return max(scored, key=lambda x: x[1]["score"])


def could_be_worse(variant: int | None, prevailing: int | None) -> bool:
    """Whether a possible state is worth showing next to the prevailing one."""
    if prevailing == index.MAX_SCORE:
        return False
    if variant is None or prevailing is None:
        return True  # "may be worse (details unknown)" (F5)
    return variant > prevailing


def overlay_label(period: Period) -> str:
    if period.change == "TEMPO" and period.probability:
        return f"{period.probability}% chance, temporarily"
    if period.change == "TEMPO":
        return "temporarily"
    return f"{period.probability}% chance" if period.probability else "possible"


def hourly_outlook(meta: dict, periods: list[Period], now: datetime) -> list[dict]:
    """Hours from the current hour, up to HORIZON_HOURS, cut at validity (F2)."""
    first = now.replace(minute=0, second=0, microsecond=0)
    hours = []
    for i in range(HORIZON_HOURS):
        start = first + timedelta(hours=i)
        end = start + timedelta(hours=1)
        if start >= meta["valid_to"]:
            break
        hour = {
            "start": start,
            "end": end,
            "status": "forecast",
            "prevailing": None,
            "possible": [],
        }
        if end <= meta["valid_from"]:
            hour["status"] = "not_yet_valid"
            hours.append(hour)
            continue
        # Instants that matter in this hour: its start and every change inside it.
        lo = max(start, meta["valid_from"])
        hi = min(end, meta["valid_to"])
        instants = {lo} | {
            t
            for p in periods
            for t in (p.start, p.becoming)
            if t is not None and lo < t < hi
        }
        states = []
        for t in sorted(instants):
            for c in candidates_at(periods, t):
                if c not in states:
                    states.append(c)
        prevailing_state, prevailing = worst(states)
        hour["prevailing"] = {"conditions": prevailing, "changing": len(states) > 1}
        if prevailing["score"] is None and prevailing_state == EMPTY_STATE:
            hour["status"] = "unknown"
        for period in periods:
            if period.change not in ("TEMPO", "PROB") or not (
                period.start < hi and period.end > lo
            ):
                continue
            variants = [s.with_elements(period.elements) for s in states]
            _, possible = worst(variants)
            if not could_be_worse(possible["score"], prevailing["score"]):
                continue
            hour["possible"].append(
                {
                    "label": overlay_label(period),
                    "probability": period.probability,
                    "temporary": period.change == "TEMPO",
                    "conditions": possible,
                }
            )
        hours.append(hour)
    return hours
