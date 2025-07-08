from fastapi import FastAPI
from app.api.airport import airport_query

app = FastAPI()


@app.get("/", status_code=200)
async def get_health_check():
    return {"status": "ok"}


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
