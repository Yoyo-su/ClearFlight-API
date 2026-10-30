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


@pytest.mark.describe("Airport search endpoint")
class TestAirportSearch:
    @pytest.mark.it("returns matching airports with their timezone")
    def test_search_by_code(self, client):
        response = client.get("/v1/airports/search", params={"q": "LHR"})
        assert response.status_code == 200
        body = response.json()
        assert body["query"] == "LHR"
        assert body["count"] == 1
        assert body["results"][0] == {
            "code": "EGLL",
            "icao": "EGLL",
            "iata": "LHR",
            "name": "London Heathrow Airport",
            "city": "London",
            "country": "United Kingdom",
            "country_code": "GB",
            "type": "large_airport",
            "timezone": "Europe/London",
            "latitude": 51.470748,
            "longitude": -0.459909,
        }

    @pytest.mark.it("finds each pilot airport by IATA and ICAO code")
    @pytest.mark.parametrize(
        "q, code",
        [
            ("EGLL", "EGLL"),
            ("rjbb", "RJBB"),
            ("KIX", "RJBB"),
            ("KJFK", "KJFK"),
            ("jfk", "KJFK"),
        ],
    )
    def test_search_pilot_codes(self, client, q, code):
        response = client.get("/v1/airports/search", params={"q": q})
        assert response.status_code == 200
        assert response.json()["results"][0]["code"] == code

    @pytest.mark.it("finds the pilot airports by name and city")
    @pytest.mark.parametrize(
        "q, code", [("Kansai", "RJBB"), ("osaka", "RJBB"), ("New York", "KJFK")]
    )
    def test_search_by_text(self, client, q, code):
        response = client.get("/v1/airports/search", params={"q": q, "limit": "1"})
        assert response.status_code == 200
        assert [r["code"] for r in response.json()["results"]] == [code]

    @pytest.mark.it("returns null for a missing code")
    def test_single_code_result(self, client):
        response = client.get("/v1/airports/search", params={"q": "AAI"})
        result = response.json()["results"][0]
        assert (result["code"], result["iata"], result["icao"]) == ("AAI", "AAI", None)

    @pytest.mark.it("returns an empty list when nothing matches")
    def test_search_no_results(self, client):
        response = client.get("/v1/airports/search", params={"q": " zzqqzz "})
        assert response.status_code == 200
        assert response.json() == {"query": "zzqqzz", "count": 0, "results": []}

    @pytest.mark.it("caps the number of results at the limit")
    def test_search_limit(self, client):
        response = client.get("/v1/airports/search", params={"q": "lon", "limit": 25})
        assert response.json()["count"] == 25

    @pytest.mark.it("returns 400 for a missing, short or long query")
    @pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": " a "}, {"q": "x" * 65}])
    def test_search_bad_query(self, client, params):
        response = client.get("/v1/airports/search", params=params)
        assert response.status_code == 400
        assert response.json() == {"detail": "q must be 2-64 characters"}

    @pytest.mark.it("returns 400 for an invalid limit")
    @pytest.mark.parametrize(
        "limit", ["0", "26", "-1", "ten", "2.5", "", " 5 ", "+5", "1_0", "５"]
    )
    def test_search_bad_limit(self, client, limit):
        response = client.get(
            "/v1/airports/search", params={"q": "london", "limit": limit}
        )
        assert response.status_code == 400
        assert "limit must be" in response.json()["detail"]

    @pytest.mark.it("loads the catalogue at startup")
    def test_startup_loads_catalogue(self):
        with mock.patch("app.main.get_catalogue") as get_catalogue:
            with TestClient(app):
                get_catalogue.assert_called_once_with()

    @pytest.mark.it("fails startup when the catalogue can't be loaded")
    def test_startup_fails_on_bad_catalogue(self):
        with mock.patch("app.main.get_catalogue", side_effect=FileNotFoundError):
            with pytest.raises(FileNotFoundError):
                with TestClient(app):
                    pass
