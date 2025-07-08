from app.services.aviationstack import get_airport_info
from app.services.weatherstack import get_current_weather_info

def airport_query(airport_code: str = None):
    try:
        airport_info = get_airport_info(airport_code)
        latitude = airport_info["data"][0]["latitude"]
        longitude = airport_info["data"][0]["longitude"]
        weather_info = get_current_weather_info(latitude, longitude)
        return {
            "airport_info": airport_info["data"][0],
            "weather_info": weather_info,
        }
    except ValueError as e:
        print(f"ValueError: {e}")
        raise e
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise e
    
    