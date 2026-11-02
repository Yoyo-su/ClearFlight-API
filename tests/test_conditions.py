import re
from datetime import datetime, timezone

import pytest

from app.services import conditions
from app.services.conditions import DISCLAIMER, evaluate, level, weather_token_score
from app.services.metar import Observation

"""
Test suite for the conditions index v0.1 (D-007)
"""

OBSERVED_AT = datetime(2026, 10, 30, 7, 20, tzinfo=timezone.utc)


def obs(**fields):
    base = {
        "station": "EGLL",
        "report_type": "METAR",
        "observed_at": OBSERVED_AT,
        "fetched_at": OBSERVED_AT,
        "raw_text": "METAR EGLL ...",
        "temperature_c": 10,
        "dewpoint_c": 8,
        "wind_direction_deg": 70,
        "wind_variable": False,
        "wind_speed_kt": 5,
        "wind_gust_kt": None,
        "visibility_m": 9999,
        "visibility_at_least": False,
        "sky_condition": "clear",
        "cloud_layers": [],
        "ceiling_ft": None,
        "pressure_hpa": 1020,
        "weather_phenomena": [],
    }
    base.update(fields)
    return Observation(**base)


def factor(result, name):
    return next(f for f in result["factors"] if f["name"] == name)


def score_of(**fields):
    return evaluate(obs(**fields), "current")["score"]


@pytest.mark.describe("Conditions index: component bands")
class TestBands:
    @pytest.mark.it("scores wind on the higher of speed and gust")
    @pytest.mark.parametrize(
        "speed, gust, expected",
        [
            (0, None, 0),
            (9, None, 0),
            (10, None, 2),
            (19, None, 2),
            (20, None, 4),
            (29, None, 4),
            (30, None, 6),
            (39, None, 6),
            (40, None, 8),
            (49, None, 8),
            (50, None, 10),
            (15, 33, 6),
            (8, 12, 2),
        ],
    )
    def test_wind(self, speed, gust, expected):
        result = evaluate(obs(wind_speed_kt=speed, wind_gust_kt=gust), "current")
        assert factor(result, "wind")["score"] == expected

    @pytest.mark.it("scores visibility in metres, allowing for mile rounding")
    @pytest.mark.parametrize(
        "metres, expected",
        [
            (16093, 0),
            (8000, 0),
            (7998, 0),  # 8000 m reported, sent as 4.97 SM
            (7900, 3),
            (4800, 3),
            (4796, 3),  # 4800 m sent as 2.98 SM
            (4700, 6),
            (1600, 6),
            (1593, 6),  # 1600 m sent as 0.99 SM
            (1500, 8),
            (800, 8),
            (790, 8),
            (780, 10),
            (0, 10),
        ],
    )
    def test_visibility(self, metres, expected):
        result = evaluate(obs(visibility_m=metres), "current")
        assert factor(result, "visibility")["score"] == expected

    @pytest.mark.it("scores the ceiling, with no ceiling scoring 0")
    @pytest.mark.parametrize(
        "sky, ceiling, expected",
        [
            ("clear", None, 0),
            ("cavok", None, 0),
            ("clouds", None, 0),
            ("clouds", 3001, 0),
            ("clouds", 3000, 3),
            ("clouds", 1000, 3),
            ("clouds", 999, 6),
            ("clouds", 500, 6),
            ("clouds", 499, 8),
            ("clouds", 200, 8),
            ("clouds", 199, 10),
            ("clouds", 0, 10),
        ],
    )
    def test_ceiling(self, sky, ceiling, expected):
        result = evaluate(obs(sky_condition=sky, ceiling_ft=ceiling), "current")
        assert factor(result, "ceiling")["score"] == expected


@pytest.mark.describe("Conditions index: reported weather")
class TestWeather:
    @pytest.mark.it("scores METAR weather groups by phenomenon and intensity")
    @pytest.mark.parametrize(
        "token, expected",
        [
            ("-SN", 3),
            ("SN", 5),
            ("+SN", 8),
            ("-RA", 1),
            ("RA", 3),
            ("+RA", 5),
            ("SHRA", 3),
            ("+SHRA", 5),
            ("-DZ", 1),
            ("TS", 8),
            ("TSRA", 8),
            ("+TSRA", 10),
            ("VCTS", 5),
            ("-FZDZ", 8),
            ("FZRA", 8),
            ("FZFG", 0),
            ("GR", 10),
            ("SQ", 10),
            ("+FC", 10),
            ("VA", 10),
            ("SS", 10),
            ("DS", 10),
            ("VCSS", 5),
            ("BLSN", 3),
            ("DRSN", 0),
            ("PL", 5),
            ("GS", 5),
            ("UP", 3),
            ("VCSH", 3),
            ("BR", 0),
            ("FG", 0),
            ("MIFG", 0),
            ("HZ", 0),
            ("VCFG", 0),
            ("RASN", 5),
            ("-SHRASN", 3),
        ],
    )
    def test_token(self, token, expected):
        assert weather_token_score(token) == expected

    @pytest.mark.it("treats unparseable groups as unrecognised")
    @pytest.mark.parametrize("token", ["XYZ", "SH+RA", "FZ", "", "TSX", "+", "VC"])
    def test_unrecognised(self, token):
        assert weather_token_score(token) is None

    @pytest.mark.it("takes the highest group")
    def test_multiple(self):
        result = evaluate(obs(weather_phenomena=["-RA", "BR"]), "current")
        assert factor(result, "weather")["score"] == 1

    @pytest.mark.it("makes the weather unknown when a group is unrecognised")
    def test_unrecognised_unknown(self):
        result = evaluate(obs(weather_phenomena=["XYZ", "TSRA"]), "current")
        weather = factor(result, "weather")
        assert weather["score"] is None
        assert weather["detail"] == "XYZ TSRA (unrecognised: XYZ)"
        assert (result["score"], result["level"]) == (None, "unknown")
        assert result["explanation"] == (
            "No score: the weather group XYZ couldn't be interpreted."
        )

    @pytest.mark.it("still scores 10 when a recognised group already reaches 10")
    def test_unrecognised_with_ten(self):
        result = evaluate(obs(weather_phenomena=["XYZ", "+TSRA"]), "current")
        assert factor(result, "weather")["score"] == 10
        assert result["score"] == 10

    @pytest.mark.it("explains unrecognised groups together with missing inputs")
    def test_unrecognised_and_missing(self):
        result = evaluate(
            obs(visibility_m=None, weather_phenomena=["XYZ", "QQ"]), "current"
        )
        assert result["explanation"] == (
            "No score: the visibility wasn't reported and the weather groups "
            "XYZ QQ couldn't be interpreted."
        )

    @pytest.mark.it("lists unrecognised groups")
    def test_unrecognised_groups(self):
        assert conditions.unrecognised_groups(["-RA", "XYZ", "BR", "NSW"]) == [
            "XYZ",
            "NSW",
        ]

    @pytest.mark.it("scores snow grains and ice crystals with rain, as in the plan")
    @pytest.mark.parametrize(
        "token, expected", [("-SG", 1), ("SG", 3), ("+SG", 5), ("IC", 3)]
    )
    def test_grains_and_crystals(self, token, expected):
        assert weather_token_score(token) == expected

    @pytest.mark.it("scores 0 when no weather is reported")
    def test_none(self):
        result = evaluate(obs(), "current")
        assert factor(result, "weather")["score"] == 0
        assert factor(result, "weather")["value"] == []


@pytest.mark.describe("Conditions index: score, level and adequacy")
class TestScore:
    @pytest.mark.it("uses the highest component, not an average")
    def test_max(self):
        assert score_of(wind_speed_kt=12, weather_phenomena=["TSRA"]) == 8

    @pytest.mark.it("maps scores to levels")
    @pytest.mark.parametrize(
        "score, expected",
        [
            (None, "unknown"),
            (0, "low"),
            (2, "low"),
            (3, "moderate"),
            (5, "moderate"),
            (6, "high"),
            (7, "high"),
            (8, "severe"),
            (10, "severe"),
        ],
    )
    def test_level(self, score, expected):
        assert level(score) == expected

    @pytest.mark.it("gives no score unless the observation is current")
    def test_stale(self):
        result = evaluate(obs(visibility_m=500), "stale")
        assert (result["score"], result["level"]) == (None, "unknown")
        assert factor(result, "visibility")["score"] == 10  # factors still shown
        assert "too old to score" in result["explanation"]

    @pytest.mark.it("gives no score when an input is missing, naming it")
    @pytest.mark.parametrize(
        "fields, missing",
        [
            ({"wind_speed_kt": None}, "the wind speed"),
            ({"visibility_m": None}, "the visibility"),
            ({"sky_condition": "unknown"}, "the cloud ceiling"),
            ({"sky_condition": "obscured", "visibility_m": 1000}, "the cloud ceiling"),
        ],
    )
    def test_missing(self, fields, missing):
        result = evaluate(obs(**fields), "current")
        assert (result["score"], result["level"]) == (None, "unknown")
        assert result["explanation"] == f"No score: {missing} wasn't reported."

    @pytest.mark.it("scores 10 from a gust of 50 kt or more without a wind speed")
    def test_gust_only_ten(self):
        result = evaluate(obs(wind_speed_kt=None, wind_gust_kt=55), "current")
        wind = factor(result, "wind")
        assert (wind["score"], wind["value"]) == (10, 55)
        assert wind["detail"] == "wind speed not reported, gusting 55 kt"
        assert (result["score"], result["level"]) == (10, "severe")

    @pytest.mark.it("leaves wind unknown for a lower gust without a wind speed")
    def test_gust_only_low(self):
        result = evaluate(obs(wind_speed_kt=None, wind_gust_kt=30), "current")
        assert factor(result, "wind")["score"] is None
        assert result["score"] is None

    @pytest.mark.it("handles every factor being unknown")
    def test_all_unknown(self):
        result = evaluate(
            obs(
                wind_speed_kt=None,
                visibility_m=None,
                sky_condition="unknown",
                weather_phenomena=["XYZ"],
            ),
            "current",
        )
        assert result["score"] is None
        assert result["explanation"].startswith(
            "No score: the wind speed, the visibility and the cloud ceiling "
            "weren't reported and the weather group XYZ"
        )

    @pytest.mark.it("names every missing input")
    def test_several_missing(self):
        result = evaluate(
            obs(wind_speed_kt=None, visibility_m=None, sky_condition="unknown"),
            "current",
        )
        assert result["explanation"] == (
            "No score: the wind speed, the visibility and the cloud ceiling "
            "weren't reported."
        )

    @pytest.mark.it("scores 10 when known components already reach 10")
    def test_known_ten(self):
        result = evaluate(obs(sky_condition="obscured", visibility_m=145), "current")
        assert (result["score"], result["level"]) == (10, "severe")
        assert result["explanation"] == (
            "Observed conditions index 10/10 (severe), mainly from visibility of "
            "145 m. (The cloud ceiling wasn't reported.)"
        )

    @pytest.mark.it("explains the drivers of a score")
    def test_explanation(self):
        result = evaluate(
            obs(visibility_m=1304, sky_condition="clouds", ceiling_ft=200), "current"
        )
        assert result["explanation"] == (
            "Observed conditions index 8/10 (severe), mainly from visibility of "
            "1.3 km and a cloud ceiling at 200 ft."
        )
        result = evaluate(obs(wind_speed_kt=15, wind_gust_kt=33), "current")
        assert result["explanation"].endswith("wind of 15 kt gusting 33 kt.")
        result = evaluate(obs(wind_variable=True, wind_speed_kt=12), "current")
        assert result["explanation"].endswith("wind of variable 12 kt.")
        result = evaluate(
            obs(visibility_m=16093, visibility_at_least=True, weather_phenomena=["RA"]),
            "current",
        )
        assert factor(result, "visibility")["detail"] == "16.1 km or more"
        assert result["explanation"].endswith("reported weather RA.")

    @pytest.mark.it("explains a score of 0")
    def test_zero(self):
        result = evaluate(obs(), "current")
        assert (result["score"], result["level"]) == (0, "low")
        assert result["explanation"].startswith("Observed conditions index 0/10 (low)")

    @pytest.mark.it("explains unavailable data by reason")
    @pytest.mark.parametrize(
        "reason, text",
        [
            ("no_metar_station", "this airport has no METAR weather station"),
            ("observation_too_old", "the latest observation is too old to use"),
            ("no_report", "no current weather observation is available"),
            (None, "no current weather observation is available"),
        ],
    )
    def test_unavailable(self, reason, text):
        result = evaluate(None, "unavailable", reason)
        assert result["score"] is None and result["factors"] == []
        assert result["explanation"] == f"No score: {text}."

    @pytest.mark.it("is deterministic and versioned")
    def test_deterministic(self):
        first = evaluate(obs(wind_speed_kt=33, weather_phenomena=["+SHRA"]), "current")
        second = evaluate(obs(wind_speed_kt=33, weather_phenomena=["+SHRA"]), "current")
        assert first == second
        assert first["version"] == conditions.VERSION == "0.1"


@pytest.mark.describe("Conditions index: wording")
class TestWording:
    BANNED = re.compile(
        r"\b(safe|safety|unsafe|delay|delays|delayed|cancel\w*|disrupt\w*|risk|"
        r"forecast|predict\w*|recommend\w*|fly|flying)\b",
        re.IGNORECASE,
    )

    @pytest.mark.it("makes no safety, delay or forecast claims outside the disclaimer")
    @pytest.mark.parametrize(
        "observation, status",
        [
            (obs(), "current"),
            (obs(visibility_m=145, sky_condition="obscured"), "current"),
            (obs(wind_speed_kt=55, weather_phenomena=["+TSRA", "XYZ"]), "current"),
            (obs(visibility_m=None), "current"),
            (obs(), "stale"),
            (None, "unavailable"),
        ],
    )
    def test_banned_words(self, observation, status):
        result = evaluate(observation, status)
        text = result["explanation"] + " ".join(f["detail"] for f in result["factors"])
        assert not self.BANNED.search(text)

    @pytest.mark.it("always carries the fixed disclaimer")
    def test_disclaimer(self):
        assert evaluate(obs(), "current")["disclaimer"] == DISCLAIMER
        assert "not a forecast" in DISCLAIMER
        assert "does not predict delays" in DISCLAIMER
