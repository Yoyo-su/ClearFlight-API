import pytest
from datetime import datetime

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


@pytest.mark.describe("Weather Risk Function Tests")
class TestWeatherRiskCalc:
    @pytest.mark.it("weather_risk_calc returns a value between 0 and 10")
    def test_weather_risk_calc_range(self):
        risk = weather_risk_calc(
            okta=4, precipitation=2.0, windspeed=15.0, visibility=8.0
        )
        assert 0 <= risk <= 10

    @pytest.mark.it("weather_risk_calc returns None for invalid inputs")
    def test_weather_risk_calc_invalid_inputs(self):
        assert (
            weather_risk_calc(okta=1, precipitation=-2.0, windspeed=15, visibility=8.0)
            is None
        )
        assert (
            weather_risk_calc(okta=9, precipitation=1.0, windspeed=15.0, visibility=8.0)
            is None
        )
        assert (
            weather_risk_calc(
                okta=4, precipitation=2.0, windspeed="5.0", visibility=8.0
            )
            is None
        )

    @pytest.mark.it("weather_risk_calc handles boundary conditions")
    def test_weather_risk_calc_boundary_conditions(self):
        assert (
            weather_risk_calc(okta=0, precipitation=0, windspeed=0, visibility=20) == 0
        )
        assert (
            weather_risk_calc(okta=8, precipitation=10, windspeed=51, visibility=1)
            == 10
        )

    @pytest.mark.it("weather_risk_calc handles edge cases")
    def test_weather_risk_calc_edge_cases(self):
        assert (
            weather_risk_calc(okta=4, precipitation=0, windspeed=10, visibility=10)
            is not None
        )
        assert (
            weather_risk_calc(okta=4, precipitation=5, windspeed=25, visibility=5)
            is not None
        )
        assert (
            weather_risk_calc(okta=4, precipitation=10, windspeed=45, visibility=2)
            is not None
        )

    @pytest.mark.it("weather_risk_calc handles missing parameters")
    def test_weather_risk_calc_missing_parameters(self):
        with pytest.raises(TypeError):
            weather_risk_calc(
                okta=4, precipitation=2.0, windspeed=15.0
            )  # Missing visibility


@pytest.mark.describe("Okta Calculation Function Tests")
class TestOktaCalc:
    @pytest.mark.it("okta_calc returns correct okta value")
    def test_okta_calc(self):
        assert okta_calc(0) == 0
        assert okta_calc(50.00) == 4
        assert okta_calc(100) == 8
        assert okta_calc(25) == 2
        assert okta_calc(75) == 6

    @pytest.mark.it("okta_calc handles edge cases")
    def test_okta_calc_edge_cases(self):
        assert okta_calc(0) == 0
        assert okta_calc(100) == 8
        assert okta_calc(12.5) == 1
        assert okta_calc(87.5) == 7

    @pytest.mark.it("okta_calc handles invalid inputs")
    def test_okta_calc_invalid_inputs(self):
        with pytest.raises(TypeError):
            okta_calc()  # Missing cloud cover parameter
        assert okta_calc(None) is None
        assert okta_calc(-10) is None
        assert okta_calc(150) is None
        assert okta_calc(-10) is None
        assert okta_calc("fifty") is None

    @pytest.mark.it("okta_calc handles boundary conditions")
    def test_okta_calc_boundary_conditions(self):
        assert okta_calc(0) == 0
        assert okta_calc(100) == 8


@pytest.mark.describe("Dew Point Calculation Function Tests")
class TestDewPointCalc:
    @pytest.mark.it("dew_point_calc returns correct value")
    def test_okta_calc(self):
        assert dew_point_calc(30, 70) == 24
        assert dew_point_calc(25, 50) == 15.0
        assert dew_point_calc(10, 90) == 8.0
        assert dew_point_calc(0, 100) == 0.0
        assert dew_point_calc(-10, 80) == -14.0
        assert dew_point_calc(20, 100) == 20.0
        assert dew_point_calc(-20, 50) == -30.0

    @pytest.mark.it("dew_point_calc handles invalid inputs")
    def test_okta_calc_invalid_inputs(self):
        with pytest.raises(TypeError):
            dew_point_calc()  # Missing parameters
        assert dew_point_calc(None, 50) is None
        assert dew_point_calc(20, None) is None
        assert dew_point_calc("twenty", 50) is None
        assert dew_point_calc(20, "fifty") is None
        assert dew_point_calc(20, -10) is None
        assert dew_point_calc(20, 150) is None
        assert dew_point_calc(-150, 50) is None
        assert dew_point_calc(150, 50) is None

    @pytest.mark.it("dew_point_calc handles boundary conditions")
    def test_okta_calc_boundary_conditions(self):
        assert dew_point_calc(0, 0) == -20.0
        assert dew_point_calc(100, 100) == 100.0


@pytest.mark.describe("Local Time Calculation Function Tests")
class TestLocalTimeCalc:
    @pytest.mark.it("local_time_calc returns a tuple of UTC and local time")
    def test_local_time_calc(self):
        assert isinstance(local_time_calc("-5"), tuple)
        utc_time, local_time = local_time_calc("-5")
        assert isinstance(utc_time, datetime)
        assert isinstance(local_time, datetime)

    @pytest.mark.it("local_time_calc returns correct local time")
    def test_local_time_calc_correctness(self):
        utc_time, local_time = local_time_calc("-5")
        utc_time_str = utc_time.strftime("%H")
        local_time_str = local_time.strftime("%H")
        assert int(local_time_str) == (int(utc_time_str) - 5)
        utc_time, local_time = local_time_calc("2")
        utc_time_str = utc_time.strftime("%H")
        local_time_str = local_time.strftime("%H")
        assert int(local_time_str) == (int(utc_time_str) + 2)
        utc_time, local_time = local_time_calc(3)
        utc_time_str = utc_time.strftime("%H")
        local_time_str = local_time.strftime("%H")
        assert int(local_time_str) == (int(utc_time_str) + 3)

    @pytest.mark.it("local_time_calc handles invalid inputs")
    def test_local_time_calc_invalid_inputs(self):
        with pytest.raises(TypeError):
            local_time_calc()  # Missing parameter
        utc_time, local_time = local_time_calc(None)
        assert utc_time == local_time
        utc_time, local_time = local_time_calc("invalid")
        assert local_time is None
        utc_time, local_time = local_time_calc("+15")  # Out of range
        assert local_time is None
        utc_time, local_time = local_time_calc("-15")  # Out of range
        assert local_time is None

    @pytest.mark.it("local_time_calc handles boundary conditions")
    def test_local_time_calc_boundary_conditions(self):
        utc_time, local_time = local_time_calc("+15")  # Out of range
        assert isinstance(utc_time, datetime)
        assert local_time is None
        utc_time, local_time = local_time_calc("-15")  # Out of range
        assert isinstance(utc_time, datetime)
        assert local_time is None


@pytest.mark.describe("Pressure Conversion Function Tests")
class TestPressureInhgCalc:
    @pytest.mark.it("pressure_inhg_calc returns correct value")
    def test_pressure_inhg_calc(self):
        assert pressure_inhg_calc(1013.25) == 29.92
        assert pressure_inhg_calc(1020) == 30.12
        assert pressure_inhg_calc(980) == 28.94
        assert pressure_inhg_calc(950) == 28.05

    @pytest.mark.it("pressure_inhg_calc handles invalid inputs")
    def test_pressure_inhg_calc_invalid_inputs(self):
        with pytest.raises(TypeError):
            pressure_inhg_calc()  # Missing parameter
        assert pressure_inhg_calc(None) is None
        assert pressure_inhg_calc("one thousand") is None

    @pytest.mark.it("pressure_inhg_calc handles boundary conditions")
    def test_pressure_inhg_calc_boundary_conditions(self):
        assert pressure_inhg_calc(0) == 0.0
        assert pressure_inhg_calc(1085) == 32.04  # Highest recorded sea-level pressure


@pytest.mark.describe("Visibility Conversion Function Tests")
class TestVisibilityMiCalc:
    @pytest.mark.it("visibility_mi_calc returns correct value")
    def test_visibility_mi_calc(self):
        assert visibility_mi_calc(10) == 6
        assert visibility_mi_calc(5) == 3
        assert visibility_mi_calc(20) == 12
        assert visibility_mi_calc(0) == 0

    @pytest.mark.it("visibility_mi_calc handles invalid inputs")
    def test_visibility_mi_calc_invalid_inputs(self):
        with pytest.raises(TypeError):
            visibility_mi_calc()  # Missing parameter
        assert visibility_mi_calc(None) is None
        assert visibility_mi_calc("ten") is None

    @pytest.mark.it("visibility_mi_calc handles boundary conditions")
    def test_visibility_mi_calc_boundary_conditions(self):
        assert visibility_mi_calc(0) == 0
        assert visibility_mi_calc(100) == 62  # Very high visibility


@pytest.mark.describe("Windspeed Conversion Function Tests")
class TestWindspeedKnotsCalc:
    @pytest.mark.it("windspeed_knots_calc returns correct value")
    def test_windspeed_knots_calc(self):
        assert windspeed_knots_calc(10) == 5
        assert windspeed_knots_calc(20) == 11
        assert windspeed_knots_calc(0) == 0
        assert windspeed_knots_calc(50) == 27

    @pytest.mark.it("windspeed_knots_calc handles invalid inputs")
    def test_windspeed_knots_calc_invalid_inputs(self):
        with pytest.raises(TypeError):
            windspeed_knots_calc()  # Missing parameter
        assert windspeed_knots_calc(None) is None
        assert windspeed_knots_calc("ten") is None

    @pytest.mark.it("windspeed_knots_calc handles boundary conditions")
    def test_windspeed_knots_calc_boundary_conditions(self):
        assert windspeed_knots_calc(0) == 0
        assert windspeed_knots_calc(300) == 162  # Very high windspeed
