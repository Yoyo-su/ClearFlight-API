import requests
from app.core.config import settings
from .cache import get_cache_key, check_cache, cache_response

# Load the WeatherStack API key from environment variables
ws_api_key = settings.WEATHERSTACK_API_KEY


def get_current_weather_info(
    latitude: str = None, longtitude: str = None, ws_api_key: str = ws_api_key
):
    """This function retrieves weather information from the AviationStack API based
    on the provided latitude and longitude, and returns the current weather data.

    Args:
        latitude (str, optional): Latitude of the airport. Defaults to None.
        longtitude (str, optional): Longitude of the airport. Defaults to None.
        ws_api_key (str, optional): WeatherStack API key. Defaults to the value from environment variables.

    Raises:
        ValueError: - If the API key is missing.
                    - If the latitude or longitude is not provided.
                    - If there is any other validation error with the input parameters.
        RequestException: If there is an error with the request to the WeatherStack API.
        Exception: If any unexpected errors during the execution.

    Returns:
        dict: A dictionary containing weather information if the request is successful.
    """
    try:
        # Validate variables
        if not ws_api_key:
            raise ValueError(
                "WEATHERSTACK_API_KEY is not set in the environment variables"
            )
        if not latitude or not longtitude:
            raise ValueError("Latitude and longitude must be provided")

        # Construct the query
        query = f"query={latitude},{longtitude}"
        # Construct the URL with the query
        url = f"https://api.weatherstack.com/current?access_key={ws_api_key}&{query}"
        cache_key = get_cache_key(url)
        if cache_key:
            # Check if the data is already cached
            cache_data = check_cache(cache_key)

        if cache_data:
            print("Using cached data...")
            weather_info = cache_data
        else:
            # Make the API request
            print("Making API request...")
            response = requests.get(url)
            weather_info = response.json()
            cache_response(cache_key, weather_info)

        # If the response is valid, return the weather information
        print(f"weather info for {latitude}, {longtitude} retrieved successfully")
        return weather_info

    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        raise e
    except ValueError as e:
        print(f"Value error: {e}")
        raise e
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise e
