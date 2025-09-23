import math
import logging
from datetime import datetime, timezone, timedelta

"""
Utility calculators for various metrics.
"""


def weather_risk_calc(okta, precipitation, windspeed, visibility):
    """This function calculates weather risk index (0 = no risk, 10 = severe).

    Factors:
    - Cloud cover (okta)
    - Precipitation (mm/hr)
    - Wind speed (km/h)
    - Visibility (km)
    All factors are normalized to a 0-10 scale.

    Weights:
    - Cloud = 20%
    - Precip = 30%
    - Wind = 30%
    - Visibility = 20%

    Args:
        okta (int or float): Cloud cover in okta (0-8).
        precipitation (int or float): Precipitation in mm/hr.
        windspeed (int or float): Wind speed in km/h.
        visibility (int or float): Visibility in km.

    Returns:
        int: Weather risk index from 0 to 10.
    """
    try:
        # Validate inputs
        # All parameters must be int or float and non-negative
        if not all(
            isinstance(param, (int, float)) and param >= 0
            for param in [okta, precipitation, windspeed, visibility]
        ):
            raise ValueError("All parameters must be non-negative numbers")
        if not (0 <= okta <= 8):
            raise ValueError("Okta must be between 0 and 8")

        # cloud risk calculation
        cloud_risk = round((okta / 8) * 10)  # Okta scale is 0-8
        logging.info(f"Cloud cover (okta): {okta}")

        # precipitation risk calculation
        precip_calc = 4 * math.log(1 + precipitation)
        precip_risk = min(10, precip_calc)
        logging.info(f"Precipitation: {precipitation} mm/hr")

        # wind risk calculation
        if windspeed <= 10:
            wind_risk = 0
        elif windspeed <= 30:
            wind_risk = 3
        elif windspeed <= 50:
            wind_risk = 7
        else:  # > 50 km/h
            wind_risk = 10
        logging.info(f"Wind speed: {windspeed} km/h")

        # visibility risk calculation
        if visibility >= 10:
            visibility_risk = 0
        elif visibility >= 6:
            visibility_risk = 3
        elif visibility >= 2:
            visibility_risk = 6
        else:  # < 2 km
            visibility_risk = 10
        logging.info(f"Visibility: {visibility} km")

        # Weighted sum
        weather_risk = (
            (cloud_risk * 0.2)
            + (precip_risk * 0.3)
            + (wind_risk * 0.3)
            + (visibility_risk * 0.2)
        )
        logging.info(f"Calculated weather risk: {weather_risk}")

        return round(weather_risk)

    except Exception as e:
        logging.error(f"Error calculating weather risk: {e}")
        return None


def traffic_risk_calc():
    # TODO: Implement traffic risk calculation
    pass


def okta_calc(cloud_cover):
    """This function converts cloud cover percentage to okta scale (0-8).

    Args:
        cloud_cover (int or float): Cloud cover percentage (0-100).

    Returns:
        int: Cloud cover in okta (0-8).
    """
    try:
        if not isinstance(cloud_cover, (int, float)):
            raise ValueError("Cloud cover must be a number")
        if not (0 <= cloud_cover <= 100):
            raise ValueError("Cloud cover must be between 0 and 100")

        okta = round(cloud_cover * 0.08)
        logging.info(f"Calculated okta: {okta} from cloud cover: {cloud_cover}%")
        return okta
    except Exception as e:
        logging.error(f"Error calculating okta: {e}")
        return None


def dew_point_calc(temperature, humidity):
    """This function calculates the dew point given temperature and humidity.

    Args:
        temperature (int or float): Temperature in °C.
        humidity (int or float): Relative Humidity in %.

    Returns:
        int: Dew point in °C.
    """

    # Formula: Td = T - ((100 - RH)/5)
    # Where:
    # Td = Dew Point in °C
    # T = Temperature in °C
    # RH = Relative Humidity in %

    try:
        if not (
            isinstance(temperature, (int, float)) and isinstance(humidity, (int, float))
        ):
            raise ValueError("Temperature and humidity must be numbers")
        if not (0 <= humidity <= 100):
            raise ValueError("Humidity must be between 0 and 100")
        if temperature < -100 or temperature > 100:
            raise ValueError("Temperature seems unrealistic")
        dewpoint = round(temperature - ((100 - humidity) / 5))
        return dewpoint
    except Exception as e:
        logging.error(f"Error calculating dew point: {e}")
        return None


def local_time_calc(utc_offset):
    """This function calculates the local time based on the provided UTC offset.

    Args:
        utc_offset (str or None): UTC offset in hours (e.g., "-5", "+3", "0").

    Returns:
        tuple: A tuple containing the current UTC time and the local time as datetime objects.
    """

    current_utc = datetime.now(timezone.utc)

    try:
        if utc_offset is None:
            return current_utc, current_utc
        else:
            offset_hours = int(utc_offset)
            if not (-12 <= offset_hours <= 14):
                raise ValueError("UTC offset must be between -12 and +14 hours")
            # Create timezone offset
            tz_offset = timezone(timedelta(hours=offset_hours))

            # Convert UTC to offset time
            local_time = current_utc.astimezone(tz_offset)
            return current_utc, local_time
    except Exception as e:
        logging.error(f"Error calculating local time: {e}")
        return current_utc, None  # Fallback to UTC if error


def pressure_inhg_calc(pressure_hpa: int | float):
    """This function converts pressure from hPa to inHg.

    Args:
        pressure_hpa (int or float): Air pressure in hPa.

    Returns:
        float: Air pressure in inHg.
    """
    try:
        return round(pressure_hpa * 0.02953, 2)
    except Exception as e:
        logging.error(f"Error converting pressure: {e}")
        return None


def visibility_mi_calc(visibility_km: int):
    """This function converts visibility from kilometers to miles.

    Args:
        visibility_km (int): Visibility in kilometers.

    Returns:
        int: Visibility in miles.
    """
    try:
        return round(visibility_km * 0.621371)
    except Exception as e:
        logging.error(f"Error converting visibility: {e}")
        return None


def windspeed_knots_calc(windspeed_kmh):
    """This function converts wind speed from km/h to knots.

    Args:
        windspeed_kmh (int): Wind speed in km/h.

    Returns:
        int: wind speed in knots.
    """
    try:
        return round(windspeed_kmh * 0.539957)
    except Exception as e:
        logging.error(f"Error converting wind speed: {e}")
        return None
