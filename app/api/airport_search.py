from fastapi import HTTPException
from pydantic import BaseModel

from app.services.airport_catalogue import get_catalogue

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 64
DEFAULT_LIMIT = 10
MAX_LIMIT = 25


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


def search_query(q: str | None, limit: str | None) -> dict:
    """Validate search parameters and search the airport catalogue.

    Args:
        q (str or None): search text (IATA/ICAO code, name or city).
        limit (str or None): maximum number of results, 1 to MAX_LIMIT.

    Raises:
        HTTPException: 400 when q or limit is missing or out of range.

    Returns:
        dict: the query, the result count and the matching airports.
    """
    query = (q or "").strip()
    if not MIN_QUERY_LENGTH <= len(query) <= MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"q must be {MIN_QUERY_LENGTH}-{MAX_QUERY_LENGTH} characters",
        )
    if limit is None:
        max_results = DEFAULT_LIMIT
    else:
        max_results = int(limit) if limit.isascii() and limit.isdigit() else 0
        if not 1 <= max_results <= MAX_LIMIT:
            raise HTTPException(
                status_code=400,
                detail=f"limit must be a whole number from 1 to {MAX_LIMIT}",
            )
    results = [a.to_dict() for a in get_catalogue().search(query, max_results)]
    return {"query": query, "count": len(results), "results": results}
