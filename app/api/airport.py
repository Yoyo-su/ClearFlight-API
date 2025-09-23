import logging
from app.services.aviationstack import get_airport_info
from app.services.weatherstack import get_current_weather_info
from app.core.utils import (
    weather_risk_calc,
    # TODO traffic_risk_calc,
    okta_calc,
    dew_point_calc,
    local_time_calc,
    pressure_inhg_calc,
    visibility_mi_calc,
    windspeed_knots_calc,
)


def airport_query(airport_code: str = None):
    """This function retrieves airport information and current weather data
    for a given airport code (IATA or ICAO) and generates an airport profile.

    Args:
        airport_code (str, optional): _description_. Defaults to None.

    Raises:
        ve: ValueError - If the airport code is missing or invalid.
        e: Exception - If any unexpected errors during the execution.

    Returns:
        dict: A dictionary containing the airport profile and current weather information.
    """
    try:
        airport_info = get_airport_info(airport_code)
        latitude = airport_info["data"][0]["latitude"]
        longitude = airport_info["data"][0]["longitude"]
        weather_info = get_current_weather_info(latitude, longitude)
        airport_profile = generate_airport_profile(airport_info, weather_info)
        return airport_profile
    except ValueError as ve:
        print(f"ValueError: {ve}")
        logging.error(f"ValueError: {ve}")
        raise ve
    except Exception as e:
        print(f"Unexpected error: {e}")
        logging.error(f"Unexpected error: {e}")
        raise e


def generate_airport_profile(airport_info, weather_info):
    """This function generates a comprehensive airport profile by combining
    airport information and current weather data.

    Args:
        airport_info (dict): Airport information data.
        weather_info (dict): Weather information data.

    Raises:
        e: If any unexpected errors during the execution.

    Returns:
        dict: A dictionary containing the airport profile and current weather information.
    """
    try:
        airport = airport_info["data"][0]
        weather = weather_info["current"]

        utc_time, local_time = local_time_calc(airport["gmt"])

        airport_profile = {
            "airport_profile": {
                "name": airport["airport_name"],
                "iata": airport["iata_code"],
                "icao": airport["icao_code"],
                "city": weather_info["location"]["name"],
                "country": airport["country_name"],
                "current_time_utc": utc_time.strftime("%H:%M"),
                "current_time_local": local_time.strftime("%H:%M"),
                "timezone": airport["timezone"],
            },
            "weather_info": {
                "observation_time": weather["observation_time"],
                "wind_direction": weather["wind_dir"],
                "wind_speed_km": weather["wind_speed"],
                "windspeed_knots": windspeed_knots_calc(weather["wind_speed"]),
                "wind_degree": weather["wind_degree"],
                "temperature": weather["temperature"],
                "dew_point": dew_point_calc(
                    weather["temperature"], weather["humidity"]
                ),
                "precipitation_mm": weather["precip"],
                "visibility_km": weather["visibility"],
                "visibility_mi": visibility_mi_calc(weather["visibility"]),
                "cloud_cover_percent": weather["cloudcover"],
                "cloud_cover_okta": okta_calc(weather["cloudcover"]),
                "description": weather["weather_descriptions"][0],
                "weather_icon": weather["weather_icons"][0],
                "pressure_hpa": weather["pressure"],
                "pressure_inhg": pressure_inhg_calc(weather["pressure"]),
                "humidity": weather["humidity"],
                "weather_rating": weather_risk_calc(
                    okta=okta_calc(weather["cloudcover"]),
                    precipitation=weather["precip"],
                    windspeed=weather["wind_speed"],
                    visibility=weather["visibility"],
                ),
            },
        }
        print(
            f"Generated airport profile: {airport_profile['airport_profile']['name']} at {utc_time.strftime('%H:%M')} UTC"
        )
        logging.info(f"Generated airport profile for {airport['icao_code']}")
        return airport_profile
    except Exception as e:
        print(f"Error generating airport profile: {e}")
        logging.error(f"Error generating airport profile: {e}")
        raise e
