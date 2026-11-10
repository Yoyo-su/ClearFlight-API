import re

from app.services.metar import Observation

"""
Conditions index v0.1: an explicitly heuristic 0-10 severity of the conditions
reported in a METAR (higher = more severe). It is not a forecast and does not
predict delays, cancellations or flight safety (plan §3, D-007).

Each component scores 0-10 and the index is the highest component, so one
severe factor isn't diluted. A score needs a current observation with known
wind, visibility, ceiling and weather (an unrecognised weather group makes the
weather unknown), except that known components already at 10 give 10 (the
maximum can't go higher).
"""

VERSION = "0.1"
MAX_SCORE = 10
DISCLAIMER = (
    "Experimental index of the weather reported at the airport. It is not a "
    "forecast and does not predict delays, cancellations or flight safety."
)

# (lower bound, score), checked from the top
WIND_BANDS = [(50, 10), (40, 8), (30, 6), (20, 4), (10, 2), (0, 0)]  # kt
CEILING_BANDS = [(3001, 0), (1000, 3), (500, 6), (200, 8), (0, 10)]  # ft
VISIBILITY_BANDS = [(8000, 0), (4800, 3), (1600, 6), (800, 8), (0, 10)]  # m
# AWC sends visibility in statute miles rounded to 0.01 (<= 8 m error), so a
# reported 8000 m arrives as 4.97 SM = 7998 m. Banding allows for that.
VISIBILITY_TOLERANCE_M = 10

WEATHER_PATTERN = re.compile(
    r"(?P<intensity>[-+]|VC)?(?P<descriptor>MI|PR|BC|DR|BL|SH|TS|FZ)?"
    r"(?P<phenomena>(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*)"
)
EXTREME = {"FC", "SQ", "GR", "VA", "DS", "SS"}
SNOW = {"SN", "PL", "GS"}
RAIN = {"RA", "DZ", "SG", "IC", "UP"}
BLOWN = {"SN", "SA", "DU"}
VICINITY_CAP = 5


def band(value: float, bands: list[tuple[float, int]]) -> int:
    for lower, score in bands:
        if value >= lower:
            return score
    return bands[-1][1]


def weather_token_score(token: str) -> int | None:
    """Score one METAR weather group, e.g. "+TSRA"; None if unrecognised."""
    match = WEATHER_PATTERN.fullmatch(token)
    if not match:
        return None
    intensity, descriptor, phenomena = match.group(
        "intensity", "descriptor", "phenomena"
    )
    codes = set(re.findall("..", phenomena))  # two-letter codes, e.g. TSRA
    if not codes and descriptor not in ("TS", "SH"):
        return None
    if codes & EXTREME:
        score = 10
    elif descriptor == "TS":
        score = 10 if intensity == "+" else 8
    elif descriptor == "FZ" and codes & {"RA", "DZ"}:
        score = 8
    elif descriptor == "BL" and codes & BLOWN:
        score = 3  # snow, sand or dust blown up from the ground
    elif descriptor != "DR" and codes & SNOW:
        score = {"+": 8, "-": 3}.get(intensity, 5)
    elif codes & RAIN or (descriptor == "SH" and not codes):
        score = {"+": 5, "-": 1}.get(intensity, 3)
    else:
        score = 0  # mist, haze, fog, smoke, low drifting snow: visibility covers it
    if intensity == "VC":  # in the vicinity, not at the airport
        score = min(score, VICINITY_CAP)
    return score


def factor(name, value, unit, score, detail) -> dict:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "score": score,
        "detail": detail,
    }


def wind_factor(obs: Observation) -> dict:
    speed, gust = obs.wind_speed_kt, obs.wind_gust_kt
    if speed is None:
        if gust is not None and band(gust, WIND_BANDS) == MAX_SCORE:
            # The gust alone sets the top band, whatever the sustained speed.
            detail = f"wind speed not reported, gusting {gust} kt"
            return factor("wind", gust, "kt", MAX_SCORE, detail)
        return factor("wind", None, "kt", None, "wind speed not reported")
    value = max(speed, gust or 0)
    detail = f"{'variable ' if obs.wind_variable else ''}{speed} kt"
    if gust is not None:
        detail += f" gusting {gust} kt"
    return factor("wind", value, "kt", band(value, WIND_BANDS), detail)


def visibility_factor(obs: Observation) -> dict:
    metres = obs.visibility_m
    if metres is None:
        return factor("visibility", None, "m", None, "visibility not reported")
    text = f"{metres / 1000:.1f} km" if metres >= 1000 else f"{metres} m"
    if obs.visibility_at_least:
        text += " or more"
    return factor(
        "visibility",
        metres,
        "m",
        band(metres + VISIBILITY_TOLERANCE_M, VISIBILITY_BANDS),
        text,
    )


def ceiling_factor(obs: Observation) -> dict:
    if obs.sky_condition == "obscured":
        return factor("ceiling", None, "ft", None, "sky obscured; height not reported")
    if obs.sky_condition == "unknown":
        return factor("ceiling", None, "ft", None, "cloud ceiling not reported")
    if obs.ceiling_ft is None:  # clear, CAVOK, or no broken/overcast layer
        return factor("ceiling", None, "ft", 0, "no cloud ceiling")
    ceiling = obs.ceiling_ft
    return factor(
        "ceiling", ceiling, "ft", band(ceiling, CEILING_BANDS), f"{ceiling:,} ft"
    )


def weather_factor(obs: Observation) -> dict:
    tokens = obs.weather_phenomena
    if tokens is None:  # forecasts only: weather stated but unreadable
        return factor("weather", None, None, None, "weather not given")
    if not tokens:
        return factor("weather", [], None, 0, "no significant weather reported")
    scores = [weather_token_score(token) for token in tokens]
    top = max((s for s in scores if s is not None), default=0)
    unrecognised = unrecognised_groups(tokens)
    detail = " ".join(tokens)
    if unrecognised:
        detail += f" (unrecognised: {' '.join(unrecognised)})"
        if top < MAX_SCORE:  # an unrecognised group could be more severe
            return factor("weather", tokens, None, None, detail)
    return factor("weather", tokens, None, top, detail)


def unrecognised_groups(tokens: list[str]) -> list[str]:
    """Weather groups the index can't interpret."""
    return [token for token in tokens if weather_token_score(token) is None]


DRIVER_TEXT = {
    "wind": "wind of {detail}",
    "visibility": "visibility of {detail}",
    "ceiling": "a cloud ceiling at {detail}",
    "weather": "reported weather {detail}",
}
MISSING_TEXT = {
    "wind": "the wind speed",
    "visibility": "the visibility",
    "ceiling": "the cloud ceiling",
    "weather": "the weather",
}


def level(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score <= 2:
        return "low"
    if score <= 5:
        return "moderate"
    if score <= 7:
        return "high"
    return "severe"


FORECAST_DISCLAIMER = (
    "Forecast from the airport's official TAF. It is not observed weather and "
    "does not predict delays, cancellations or flight safety."
)
# Wording per kind; the scoring itself is shared (CF-008 spec §3.6).
KIND_TEXT = {
    "observed": {
        "name": "Observed conditions index",
        "nothing": "no significant wind, visibility, cloud or weather was reported",
        "missing_one": "wasn't reported",
        "missing_many": "weren't reported",
        "weather": "reported weather {detail}",
        "disclaimer": DISCLAIMER,
    },
    "forecast": {
        "name": "Forecast conditions index",
        "nothing": "no significant wind, visibility, cloud or weather is forecast",
        "missing_one": "isn't given in the forecast",
        "missing_many": "aren't given in the forecast",
        "weather": "forecast weather {detail}",
        "disclaimer": FORECAST_DISCLAIMER,
    },
}


def unscored(
    explanation: str, factors: list | None = None, disclaimer: str = DISCLAIMER
) -> dict:
    return {
        "version": VERSION,
        "score": None,
        "level": "unknown",
        "factors": factors or [],
        "explanation": explanation,
        "disclaimer": disclaimer,
    }


def evaluate(
    obs: Observation | None, data_status: str, reason: str | None = None
) -> dict:
    """Compute the conditions index for an observation and its freshness.

    Args:
        obs: the observation, or None when there is none to use.
        data_status: "current", "stale" or "unavailable" (from metar.freshness).
        reason: why data is unavailable, for the explanation.

    Returns:
        dict: version, score (int or None), level, factors, explanation, disclaimer.
    """
    if obs is None or data_status == "unavailable":
        if reason == "no_metar_station":
            return unscored("No score: this airport has no METAR weather station.")
        if reason == "observation_too_old":
            return unscored("No score: the latest observation is too old to use.")
        return unscored("No score: no current weather observation is available.")

    factors = [
        wind_factor(obs),
        visibility_factor(obs),
        ceiling_factor(obs),
        weather_factor(obs),
    ]
    if data_status != "current":
        return unscored(
            "No score: the latest observation is too old to score; its values are "
            "shown with their age.",
            factors,
        )

    return score_conditions(obs, factors, "observed")


def evaluate_forecast(state) -> dict:
    """The conditions index for one forecast state (CF-008).

    `state` has the same condition attributes as an Observation. Forecast
    validity is checked by the caller, so there is no freshness rule here.
    """
    factors = [
        wind_factor(state),
        visibility_factor(state),
        ceiling_factor(state),
        weather_factor(state),
    ]
    for f in factors:  # factor details in forecast wording
        f["detail"] = (
            f["detail"]
            .replace(
                "no significant weather reported", "no significant weather forecast"
            )
            .replace("not reported", "not given in the forecast")
        )
    return score_conditions(state, factors, "forecast")


def score_conditions(obs, factors: list[dict], kind: str) -> dict:
    """Score factors: the highest wins; unknown unless known factors reach 10."""
    words = KIND_TEXT[kind]
    known = [f for f in factors if f["score"] is not None]
    unknown = [f for f in factors if f["score"] is None]
    top = max((f["score"] for f in known), default=None)
    if unknown and (top is None or top < MAX_SCORE):
        return unscored(
            f"No score: {why_unknown(unknown, obs, kind)}.",
            factors,
            words["disclaimer"],
        )

    driver_text = {**DRIVER_TEXT, "weather": words["weather"]}
    drivers = [
        driver_text[f["name"]].format(detail=f["detail"])
        for f in known
        if f["score"] == top
    ]
    if top == 0:
        text = f"{words['name']} 0/10 (low): {words['nothing']}."
    else:
        text = f"{words['name']} {top}/10 ({level(top)}), mainly from {join(drivers)}."
    if unknown:
        text += f" ({why_unknown(unknown, obs, kind).capitalize()}.)"
    return {
        "version": VERSION,
        "score": top,
        "level": level(top),
        "factors": factors,
        "explanation": text,
        "disclaimer": words["disclaimer"],
    }


def why_unknown(unknown: list[dict], obs, kind: str = "observed") -> str:
    """Explain the unknown factors, e.g. "the visibility wasn't reported"."""
    parts = []
    unreadable = obs.weather_phenomena is None
    missing = [
        MISSING_TEXT[f["name"]] for f in unknown if f["name"] != "weather" or unreadable
    ]
    if missing:
        parts.append(not_reported(missing, kind))
    if not unreadable and any(f["name"] == "weather" for f in unknown):
        groups = unrecognised_groups(obs.weather_phenomena)
        noun = "weather group" if len(groups) == 1 else "weather groups"
        parts.append(f"the {noun} {' '.join(groups)} couldn't be interpreted")
    return " and ".join(parts)


def not_reported(missing: list[str], kind: str = "observed") -> str:
    words = KIND_TEXT[kind]
    verb = words["missing_one"] if len(missing) == 1 else words["missing_many"]
    return f"{join(missing)} {verb}"


def join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
