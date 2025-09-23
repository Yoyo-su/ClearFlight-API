import math
import logging

"""
Utility calculators for various metrics.
"""

def weather_risk_calc(okta:int or bool, precipitation, windspeed, visibility):
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
        okta (int): Cloud cover in okta (0-8).
        precipitation (int): Precipitation in mm/hr.
        windspeed (int): Wind speed in km/h.
        visibility (int): Visibility in km.
        
    Returns:
        int: Weather risk index from 0 to 10.
    """
    try:
        # Validate inputs
        # All parameters must be int or float and non-negative
        if not all(isinstance(param, (int, float)) and param >= 0 for param in [okta, precipitation, windspeed, visibility]):
            logging.error("Invalid input types or negative values")
            raise ValueError("All parameters must be non-negative numbers")
        if not (0 <= okta <= 8):
            logging.error("Invalid okta value")
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
            (cloud_risk * 0.2) +
            (precip_risk * 0.3) +
            (wind_risk * 0.3) +
            (visibility_risk * 0.2)
        )
        logging.info(f"Calculated weather risk: {weather_risk}")

        return round(weather_risk)
    
    except Exception as e:
        logging.error(f"Error calculating weather risk: {e}")
        return None

def traffic_risk_calc():
    # TODO: Implement traffic risk calculation
    pass

def okta_calc():
    #     Okta scale = 0–8
    # Formula:

    # okta=round(cloud%×0.08)
    pass

def dew_point_calc():
    # Dew Point (°C)
    # Formula: Td = T - ((100 - RH)/5)
    # Where:
    # Td = Dew Point in °C
    # T = Temperature in °C
    # RH = Relative Humidity in %
    pass

def local_time_calc():
    # Convert UTC time to local time based on timezone
    pass

def pressure_inhg_calc():
    # Convert pressure from hPa to inHg
    pass

def visibility_mi_calc():
    # Convert visibility from kilometers to miles
    pass
    
def windspeed_knots_calc():
    # Convert wind speed from km/h to knots
    pass
