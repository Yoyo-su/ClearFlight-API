import requests
from app.core.config import settings
from .cache import get_cache_key, check_cache, cache_response

# Load the AviationStack API key from environment variables
as_api_key = settings.AVIATIONSTACK_API_KEY


def get_airport_info(airport_code: str = None, as_api_key: str = as_api_key):
    """This function retrieves airport information from the AviationStack API based
    on the provided airport code (either IATA or ICAO) and returns the airport data.

    Args:
        airport_code (str, optional): Airport code (IATA or ICAO) to look up. Defaults to None.
        as_api_key (str, optional): AviationStack API key. Defaults to the value from environment variables.

    Raises:
        ValueError: - If the API key is missing.
                    - If the airport code is not 3 or 4 characters long.
                    - If the airport code is not found or if multiple results are returned.
                    - If the airport code is not provided.
                    - If there is any other validation error with the input parameters.
        RequestException: If there is an error with the request to the AviationStack API.
        Exception: If any unexpected errors during the execution.

    Returns:
        dict: A dictionary containing airport information if the request is successful.
    """
    try:
        # Validate variables
        if not as_api_key:
            raise ValueError(
                "AVIATIONSTACK_API_KEY is not set in the environment variables"
            )
        if not airport_code:
            raise ValueError("Airport code must be provided")

        # Determine the query based on the airport code length
        if len(airport_code) == 3:
            query = f"iata_code={airport_code}"
        elif len(airport_code) == 4:
            query = f"icao_code={airport_code}"
        else:
            raise ValueError("Airport code must be 3 or 4 characters long")

        # Construct the URL with the query
        url = (
            f"https://api.aviationstack.com/v1/airports?access_key={as_api_key}&{query}"
        )
        cache_key = get_cache_key(url)
        if cache_key:
            # Check if the data is already cached
            cache_data = check_cache(cache_key)

        if cache_data:
            print("Using cached data...")
            airport_info = cache_data
        else:
            # Make the API request
            print("Making API request...")
            response = requests.get(url)
            airport_info = response.json()
            cache_response(cache_key, airport_info)

        # If the response does not contain exactly one airport, raise an error
        if len(airport_info["data"]) != 1:
            raise ValueError(
                f"Airport code {airport_code} not found or multiple results returned"
            )

        # If the response is valid, return the airport information
        print(f"airport info for {airport_code} retrieved successfully")
        return airport_info

    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        raise e
    except ValueError as e:
        print(f"Value error: {e}")
        raise e
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise e
