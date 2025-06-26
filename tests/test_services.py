import pytest
from unittest import mock
from app.services.aviationstack import get_airport_info
import requests

####################################################
###                                              ###
###   Test suite for the AviationStack service   ###
###                                              ###
####################################################

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

    @pytest.mark.it("get_airport_info returns a valid response for iata code")
    def test_get_airport_info_iata(self):
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
    def test_get_airport_info_icao(self):
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
            ValueError, match="Airport code JFK not found or multiple results returned"
        ):
            get_airport_info(airport_code="JFK")

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
            get_airport_info(airport_code="JFK")

    @pytest.mark.it("get_airport_info raises Exception for unexpected errors")
    @mock.patch("app.services.aviationstack.requests.get")
    def test_get_airport_info_raises_unexpected_error(self, mock_get):
        mock_get.side_effect = Exception("Unexpected error")
        with pytest.raises(Exception, match="Unexpected error"):
            get_airport_info(airport_code="JFK")
