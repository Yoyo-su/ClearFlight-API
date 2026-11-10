from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.api.airport import airport_query
from app.api.aircraft import aircraft_query
from app.api.airport_search import search_query
from app.api.conditions import ConditionsError, conditions_query
from app.api.forecast import forecast_query
from app.api.models import (
    AircraftResponse,
    AirportSearchResponse,
    ConditionsResponse,
    ErrorResponse,
    ForecastResponse,
)
from app.services.airport_catalogue import get_catalogue


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load and validate the airport snapshot now, so a missing or corrupt
    # snapshot stops startup instead of failing requests later.
    get_catalogue()
    yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(ConditionsError)
async def conditions_error_handler(request: Request, exc: ConditionsError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "reason": exc.reason},
        headers=exc.headers,
    )


@app.get("/", status_code=200)
async def get_health_check():
    return {"status": "ok"}


@app.get("/health", status_code=200)
async def get_health():
    """Lightweight liveness check."""
    return {"status": "ok"}


@app.get("/v1/airports/search", response_model=AirportSearchResponse)
def search_airports(q: str | None = None, limit: str | None = None):
    """Search airports by IATA/ICAO code, name or city."""
    return search_query(q, limit)


ERROR_RESPONSES = {
    status: {"model": ErrorResponse} for status in (400, 404, 502, 503, 504)
}


@app.get(
    "/v1/airports/{code}/conditions",
    response_model=ConditionsResponse,
    responses=ERROR_RESPONSES,
)
def get_airport_conditions(code: str):
    """Observed conditions for an airport (IATA or ICAO code)."""
    return conditions_query(code)


@app.get(
    "/v1/airports/{code}/forecast",
    response_model=ForecastResponse,
    responses=ERROR_RESPONSES,
)
def get_airport_forecast(code: str):
    """Forecast outlook for an airport from its TAF (next 12 hours)."""
    return forecast_query(code)


@app.get(
    "/v1/airports/{code}/aircraft",
    response_model=AircraftResponse,
    responses=ERROR_RESPONSES,
)
def get_airport_aircraft(code: str):
    """Live aircraft positions within 25 nm of an airport (CF-009)."""
    return aircraft_query(code)


# Legacy prototype route, replaced by /v1/airports/{code}/conditions;
# to be removed in CF-006 before public deployment (D-007).
@app.get("/airport/{airport_code}", status_code=200)
async def get_airport_info(airport_code: str):
    return airport_query(airport_code)
    # """
    # Get airport information by airport ID.

    # Args:
    #     airport_id (str): The ID of the airport to retrieve information for.

    # Returns:
    #     dict: A dictionary containing airport information.
    # """
    # # Placeholder for actual implementation
    # return {
    #     "airport_id": airport_id,
    #     "name": "Mock Airport",
    #     "location": "Mock Location",
    # }
