from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.services.metar import CloudLayer

"""
Pydantic response models for the v1 API (D-007).
"""


class AirportResult(BaseModel):
    code: str
    icao: str | None
    iata: str | None
    name: str
    city: str | None
    country: str | None
    country_code: str
    type: str
    timezone: str | None
    latitude: float
    longitude: float


class AirportSearchResponse(BaseModel):
    query: str
    count: int
    results: list[AirportResult]


class ConditionsAirport(BaseModel):
    code: str
    icao: str | None
    iata: str | None
    name: str
    city: str | None
    country: str | None
    country_code: str
    timezone: str | None


class ConditionsObservation(BaseModel):
    source: str
    station: str
    report_type: str | None
    observed_at: datetime
    fetched_at: datetime
    age_minutes: int
    raw_text: str | None
    temperature_c: float | None
    dewpoint_c: float | None
    wind_direction_deg: int | None
    wind_variable: bool
    wind_speed_kt: int | None
    wind_gust_kt: int | None
    visibility_m: int | None
    visibility_at_least: bool
    sky_condition: Literal["clear", "cavok", "clouds", "obscured", "unknown"]
    ceiling_ft: int | None
    cloud_layers: list[CloudLayer]
    pressure_hpa: float | None
    weather_phenomena: list[str]


class ConditionsFactor(BaseModel):
    name: Literal["wind", "visibility", "ceiling", "weather"]
    value: int | list[str] | None
    unit: str | None
    score: int | None
    detail: str


class Conditions(BaseModel):
    version: str
    score: int | None
    level: Literal["low", "moderate", "high", "severe", "unknown"]
    factors: list[ConditionsFactor]
    explanation: str
    disclaimer: str


class ConditionsResponse(BaseModel):
    airport: ConditionsAirport
    observation: ConditionsObservation | None
    conditions: Conditions
    data_status: Literal["current", "stale", "unavailable"]
    unavailable_reason: (
        Literal["no_metar_station", "no_report", "observation_too_old"] | None
    )
    last_observed_at: datetime | None
    # When the observation stops being current and when it expires (D-008);
    # null when there is no observation.
    current_until: datetime | None
    stale_until: datetime | None


class ForecastSummary(BaseModel):
    source: str
    station: str
    issued_at: datetime
    valid_from: datetime
    valid_to: datetime
    raw_text: str


class ForecastPrevailing(BaseModel):
    conditions: Conditions
    # True when more than one state may apply, e.g. during a BECMG transition.
    changing: bool


class ForecastPossible(BaseModel):
    label: str  # e.g. "temporarily", "30% chance", "40% chance, temporarily"
    probability: Literal[30, 40] | None
    temporary: bool
    conditions: Conditions


class ForecastHour(BaseModel):
    start: datetime
    end: datetime
    status: Literal["forecast", "not_yet_valid", "unknown"]
    prevailing: ForecastPrevailing | None  # null when not yet valid
    # Only states that could be worse than the prevailing one (F1, F5).
    possible: list[ForecastPossible]


class ForecastResponse(BaseModel):
    airport: ConditionsAirport
    forecast: ForecastSummary | None
    hours: list[ForecastHour]
    data_status: Literal["available", "unavailable"]
    unavailable_reason: (
        Literal["no_metar_station", "no_forecast", "forecast_expired"] | None
    )
    disclaimer: str


class AircraftArea(BaseModel):
    latitude: float
    longitude: float
    radius_nm: float


class AircraftSource(BaseModel):
    provider: Literal["adsblol", "opensky"]
    name: str
    attribution_url: str
    access: Literal["keyless", "anonymous", "account"]
    privacy_filter: Literal["applied", "unavailable"]


class AircraftPosition(BaseModel):
    id: str
    callsign: str | None
    latitude: float
    longitude: float
    altitude_ft: int | None
    on_ground: bool
    ground_speed_kt: int | None
    track_deg: int | None
    vertical_rate_fpm: int | None
    category: str | None
    kind: Literal["aircraft", "unclassified"]
    position_at: datetime
    expires_at: datetime  # never shown after this (C4)
    distance_nm: float


class AircraftResponse(BaseModel):
    airport: ConditionsAirport
    area: AircraftArea
    source: AircraftSource | None  # null when the provider is disabled
    observed_at: datetime | None
    fetched_at: datetime | None
    aircraft: list[AircraftPosition]
    withheld: int  # privacy (LADD/PIA)
    excluded: int  # surface vehicles and towers
    dropped: int  # invalid or expired positions
    data_status: Literal[
        "available", "no_aircraft", "coverage_unknown", "quota_exhausted", "unavailable"
    ]
    unavailable_reason: (
        Literal[
            "no_location",
            "provider_disabled",
            "no_coverage_evidence",
            "stale_feed",
            "busy",
            "unusable_data",
            "daily_budget",
            "budget_unavailable",
        ]
        | None
    )
    retry_at: datetime | None
    disclaimer: str


class NearbyStation(BaseModel):
    station: str
    name: str | None
    latitude: float
    longitude: float
    distance_nm: float
    observed_at: datetime
    current_until: datetime
    stale_until: datetime
    data_status: Literal["current", "stale"]
    conditions: Conditions


class NearbyConditionsResponse(BaseModel):
    airport: ConditionsAirport
    area: AircraftArea
    stations: list[NearbyStation]  # sorted by distance; the airport itself excluded
    complete: bool  # false when AWC's 400-record cap was reached
    dropped: int  # records without a valid station, position or time
    fetched_at: datetime | None
    data_status: Literal["available", "unavailable"]
    unavailable_reason: Literal["no_stations", "unusable_data"] | None
    source: str


class RadarFrame(BaseModel):
    time: datetime
    tile_url: str  # {z}/{x}/{y} template on tilecache.rainviewer.com only
    current_until: datetime  # hide the frame after this


class RadarResponse(BaseModel):
    enabled: bool
    data_status: Literal["available", "unavailable"]
    unavailable_reason: (
        Literal["provider_disabled", "invalid_index", "no_frames"] | None
    )
    frame: RadarFrame | None
    attribution: str
    attribution_url: str


class ErrorResponse(BaseModel):
    detail: str
    reason: str
