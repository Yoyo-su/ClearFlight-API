import pytest
from unittest import mock
from fastapi.testclient import TestClient
from app.main import app

"""
Test suite for the main application
"""


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.describe("Health check and routing tests")
class TestMain:
    @pytest.mark.parametrize("airport_code", ["JFK", "KJFK"])
    def test_airport_route_preserves_response(self, client, airport_code):
        profile = {"airport_profile": {"icao": "KJFK"}, "weather_info": {}}
        with mock.patch("app.main.airport_query", return_value=profile) as query:
            response = client.get(f"/airport/{airport_code}")
        assert response.status_code == 200
        assert response.json() == profile
        query.assert_called_once_with(airport_code)

    @pytest.mark.it("root returns a 200 status code")
    def test_main_get_health_check_200(self, client):
        end_point = "/"
        response = client.get(end_point)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.it("bad endpoint returns a 404 status code")
    def test_main_bad_endpoint_400(self, client):
        end_point = "/test"
        response = client.get(end_point)
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}
