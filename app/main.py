from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.airport import airport_query
from app.api.airport_search import AirportSearchResponse, search_query
from app.services.airport_catalogue import get_catalogue


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load and validate the airport snapshot now, so a missing or corrupt
    # snapshot stops startup instead of failing requests later.
    get_catalogue()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/", status_code=200)
async def get_health_check():
    return {"status": "ok"}


@app.get("/v1/airports/search", response_model=AirportSearchResponse)
def search_airports(q: str | None = None, limit: str | None = None):
    """Search airports by IATA/ICAO code, name or city."""
    return search_query(q, limit)


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
