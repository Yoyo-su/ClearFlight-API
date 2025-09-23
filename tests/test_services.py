import pytest
from unittest import mock
from app.services.aviationstack import get_airport_info
from app.services.weatherstack import get_current_weather_info
import requests


"""
Test suite for the AviationStack service
"""


@pytest.mark.describe("AviationStack Service Tests")
class TestAviationStack:
    airport_keys = [
        "gmt",
        "airport_name",
        "iata_code",
        "icao_code",
        "country_name",
        "latitude",
        "longitude",
        "timezone",
        "country_iso2",
    ]
    test_response = {
        "data": [
            {
                "gmt": "-5",
                "airport_name": "John F Kennedy International",
                "iata_code": "JFK",
                "icao_code": "KJFK",
                "country_name": "United States",
                "latitude": "40.642334",
                "longitude": "-73.78817",
                "timezone": "America/New_York",
                "country_iso2": "US",
            }
        ]
    }

    @pytest.mark.it("get_airport_info returns a valid response for iata code")
    @mock.patch("app.services.aviationstack.requests.get")
    def test_get_airport_info_iata(self, mock_get):
        mock_response = self.test_response
        mock_get.return_value.json.return_value = mock_response
        response = get_airport_info(airport_code="JFK")
        assert response is not None
        assert isinstance(response, dict)
        assert "data" in response
        assert isinstance(response["data"], list)
        assert len(response["data"]) == 1
        for key in self.airport_keys:
            assert key in response["data"][0]
        assert response["data"][0]["icao_code"] == "KJFK"

    @pytest.mark.it("get_airport_info returns a valid response for icao code")
    @mock.patch("app.services.aviationstack.requests.get")
    def test_get_airport_info_icao(self, mock_get):
        mock_response = self.test_response
        mock_get.return_value.json.return_value = mock_response
        response = get_airport_info(airport_code="KJFK")
        assert response is not None
        assert isinstance(response, dict)
        assert "data" in response
        assert isinstance(response["data"], list)
        assert len(response["data"]) == 1
        for key in self.airport_keys:
            assert key in response["data"][0]
        assert response["data"][0]["iata_code"] == "JFK"

    @pytest.mark.it("get_airport_info raises ValueError for multiple results")
    @mock.patch("app.services.aviationstack.requests.get")
    def test_get_airport_info_multiple_results(self, mock_get):
        mock_response = {
            "data": [
                {"iata_code": "BFT", "icao_code": "KNBC"},
                {"iata_code": "BFT", "icao_code": "KARW"},
            ]
        }
        mock_get.return_value.json.return_value = mock_response
        with pytest.raises(
            ValueError, match="Airport code BFT not found or multiple results returned"
        ):
            get_airport_info(airport_code="BFT")

    @pytest.mark.it("get_airport_info raises ValueError for missing API key")
    def test_get_airport_info_missing_api_key(self):
        with pytest.raises(
            ValueError,
            match="AVIATIONSTACK_API_KEY is not set in the environment variables",
        ):
            get_airport_info(airport_code="JFK", as_api_key=None)

    @pytest.mark.it("get_airport_info raises ValueError for invalid airport codes")
    def test_get_airport_info_missing_code(self):
        with pytest.raises(ValueError, match="Airport code must be provided"):
            get_airport_info()
        with pytest.raises(
            ValueError, match="Airport code must be 3 or 4 characters long"
        ):
            get_airport_info(airport_code="JFKXX")

    @pytest.mark.it("get_airport_info raises RequestException for API errors")
    @mock.patch("app.services.aviationstack.requests.get")
    def test_get_airport_info_raises_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        with pytest.raises(requests.exceptions.RequestException, match="API error"):
            get_airport_info(airport_code="BWI")

    @pytest.mark.it("get_airport_info raises Exception for unexpected errors")
    @mock.patch("app.services.aviationstack.requests.get")
    def test_get_airport_info_raises_unexpected_error(self, mock_get):
        mock_get.side_effect = Exception("Unexpected error")
        with pytest.raises(Exception, match="Unexpected error"):
            get_airport_info(airport_code="BWI")

    @pytest.mark.it("get_airport_info uses cache when available")
    @mock.patch("app.services.aviationstack.requests.get")
    @mock.patch("app.services.aviationstack.check_cache")
    @mock.patch("app.services.aviationstack.cache_response")
    def test_get_airport_info_uses_cache(
        self, mock_cache_response, mock_check_cache, mock_get
    ):
        mock_response = self.test_response
        mock_get.return_value.json.return_value = mock_response
        mock_check_cache.return_value = mock_response

        get_airport_info(airport_code="JFK")

        # Ensure cache was checked and response was cached
        mock_check_cache.assert_called_once()
        mock_cache_response.assert_not_called()

        # Ensure the API was not called since cache was hit
        mock_get.assert_not_called()

    @pytest.mark.it("get_airport_info caches response when not in cache")
    @mock.patch("app.services.aviationstack.requests.get")
    @mock.patch("app.services.aviationstack.get_cache_key")
    @mock.patch("app.services.aviationstack.check_cache")
    @mock.patch("app.services.aviationstack.cache_response")
    def test_get_airport_info_caches_response(
        self, mock_cache_response, mock_check_cache, mock_get_cache_key, mock_get
    ):
        mock_response = self.test_response
        mock_get.return_value.json.return_value = mock_response
        mock_check_cache.return_value = None
        mock_get_cache_key.return_value = "mock_cache_key"

        get_airport_info(airport_code="JFK")
        # Ensure cache was checked and response was cached
        mock_check_cache.assert_called_once()
        mock_cache_response.assert_called_once_with("mock_cache_key", mock_response)


"""
Test suite for the WeatherStack service
"""


@pytest.mark.describe("WeatherStack Service Tests")
class TestWeatherStack:
    test_lat = "40.642334"
    test_long = "-73.78817"
    weather_keys = [
        "request",
        "location",
        "current",
    ]
    test_response = {
        "request": {
            "type": "LatLon",
            "query": "Lat 40.64 and Lon -73.79",
            "language": "en",
            "unit": "m",
        },
        "location": {
            "name": "Valley Stream",
            "country": "United States of America",
            "region": "New York",
            "lat": "40.664",
            "lon": "-73.709",
            "timezone_id": "America/New_York",
            "localtime": "2025-07-23 11:40",
            "localtime_epoch": 1753270800,
            "utc_offset": "-4.0",
        },
        "current": {
            "observation_time": "03:40 PM",
            "temperature": 27,
            "weather_code": 116,
            "weather_icons": [
                "https://cdn.worldweatheronline.com/images/wsymbols01_png_64/wsymbol_0002_sunny_intervals.png"
            ],
            "weather_descriptions": ["Partly cloudy"],
            "astro": {
                "sunrise": "05:44 AM",
                "sunset": "08:19 PM",
                "moonrise": "03:56 AM",
                "moonset": "08:00 PM",
                "moon_phase": "Waning Crescent",
                "moon_illumination": 4,
            },
            "air_quality": {
                "co": "308.95",
                "no2": "10.73",
                "o3": "133",
                "so2": "5.18",
                "pm2_5": "21.275",
                "pm10": "24.235",
                "us-epa-index": "2",
                "gb-defra-index": "2",
            },
            "wind_speed": 12,
            "wind_degree": 170,
            "wind_dir": "S",
            "pressure": 1025,
            "precip": 0,
            "humidity": 56,
            "cloudcover": 75,
            "feelslike": 28,
            "uv_index": 7,
            "visibility": 16,
            "is_day": "yes",
        },
    }

    @pytest.mark.it("get_current_weather_info returns a valid response")
    @mock.patch("app.services.weatherstack.requests.get")
    def test_get_current_weather_info_returns_info(self, mock_get):
        mock_response = self.test_response
        mock_get.return_value.json.return_value = mock_response
        response = get_current_weather_info(self.test_lat, self.test_long)
        assert response is not None
        assert isinstance(response, dict)
        assert len(response) == 3
        for key in self.weather_keys:
            assert key in response
            assert isinstance(response[key], dict)
            assert len(response[key]) > 0

    @pytest.mark.it("get_current_weather_info raises ValueError for missing API key")
    def test_get_current_weather_info_missing_api_key(self):
        with pytest.raises(
            ValueError,
            match="WEATHERSTACK_API_KEY is not set in the environment variables",
        ):
            get_current_weather_info(self.test_lat, self.test_long, ws_api_key=None)

    @pytest.mark.it("get_current_weather_info raises ValueError for invalid lat/long")
    def test_get_current_weather_info_missing_code(self):
        with pytest.raises(ValueError, match="Latitude and longitude must be provided"):
            get_current_weather_info()

    @pytest.mark.it("get_current_weather_info raises RequestException for API errors")
    @mock.patch("app.services.weatherstack.requests.get")
    def test_get_current_weather_info_raises_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        with pytest.raises(requests.exceptions.RequestException, match="API error"):
            get_current_weather_info("40.200000", "-73.60007")

    @pytest.mark.it("get_current_weather_info raises Exception for unexpected errors")
    @mock.patch("app.services.weatherstack.requests.get")
    def test_get_current_weather_info_raises_unexpected_error(self, mock_get):
        mock_get.side_effect = Exception("Unexpected error")
        with pytest.raises(Exception, match="Unexpected error"):
            get_current_weather_info("40.200000", "-73.60007")

    @pytest.mark.it("get_current_weather_info uses cache when available")
    @mock.patch("app.services.weatherstack.requests.get")
    @mock.patch("app.services.weatherstack.check_cache")
    @mock.patch("app.services.weatherstack.cache_response")
    def test_get_current_weather_info_uses_cache(
        self, mock_cache_response, mock_check_cache, mock_get
    ):
        mock_response = self.test_response
        mock_get.return_value.json.return_value = mock_response
        mock_check_cache.return_value = mock_response

        get_current_weather_info(self.test_lat, self.test_long)

        # Ensure cache was checked and response was cached
        mock_check_cache.assert_called_once()
        mock_cache_response.assert_not_called()

        # Ensure the API was not called since cache was hit
        mock_get.assert_not_called()

    @pytest.mark.it("get_current_weather_info caches response when not in cache")
    @mock.patch("app.services.weatherstack.requests.get")
    @mock.patch("app.services.weatherstack.get_cache_key")
    @mock.patch("app.services.weatherstack.check_cache")
    @mock.patch("app.services.weatherstack.cache_response")
    def test_get_current_weather_info_caches_response(
        self, mock_cache_response, mock_check_cache, mock_get_cache_key, mock_get
    ):
        mock_response = self.test_response
        mock_get.return_value.json.return_value = mock_response
        mock_check_cache.return_value = None
        mock_get_cache_key.return_value = "mock_cache_key"

        get_current_weather_info(self.test_lat, self.test_long)
        # Ensure cache was checked and response was cached
        mock_check_cache.assert_called_once()
        mock_cache_response.assert_called_once_with("mock_cache_key", mock_response)
