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


class ErrorResponse(BaseModel):
    detail: str
    reason: str
