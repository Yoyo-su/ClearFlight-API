from app.services.aviationstack import get_airport_info
from app.services.weatherstack import get_current_weather_info


def airport_query(airport_code: str = None):
    try:
        airport_info = get_airport_info(airport_code)
        latitude = airport_info["data"][0]["latitude"]
        longitude = airport_info["data"][0]["longitude"]
        weather_info = get_current_weather_info(latitude, longitude)
        current_airport = airport_info["data"][0]
        current_weather = weather_info["current"]

        # airport_profile = generate_airport_profile(airport_info, weather_info)
        return {
            "airport_info": current_airport,
            "weather_info": current_weather,
        }
        # TODO: Return airport profile instead of raw data
    except ValueError as e:
        print(f"ValueError: {e}")
        raise e
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise e


def generate_airport_profile(airport_info, weather_info):
    # airport = airport_info["data"][0]
    # weather = weather_info["current"]
    # current_time_calc()

    # airport_profile = {
    #     "airport_profile": {
    #         "name": airport["airport_name"],
    #         "iata": airport["iata_code"],
    #         "icao": airport["icao_code"],
    #         "city": weather_info["location"]["name"],
    #         "country": airport["country_name"],
    #         # "current_time_utc": "15:33",
    #         # "current_time_local": "16:33",
    #         "timezone": airport["timezone"],
    #     },
    #     "weather_info": {
    #         "wind_direction": weather["wind_dir"],
    #         "wind_speed": weather["wind_speed"],
    #         "wind_degree": weather["wind_degree"],
    #         "temperature": weather["temperature"],
    #         # "dew_point": 4.3,
    #         "precipitation_mm": 0,
    #         "visibility_km": 10,
    #         "visibility_mi": 6,
    #         "cloud_cover_percent": weather["cloudcover"],
    #         "cloud_cover_okta": 2,
    #         "description": "Sunny",
    #         "pressure_hpa": 1029,
    #         "pressure_inhg": 30.38,
    #         "humidity": 51,
    #         "weather_rating": 8,
    #     },
    # }

    pass
