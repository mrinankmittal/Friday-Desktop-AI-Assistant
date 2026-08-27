"""India weather: classify, speak Celsius, do not steal Google searches."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.tools.weather_tools import WEATHER_GET
from friday.weather.india import (
    DEFAULT_PLACE,
    fetch_forecast,
    normalize_place,
    speak_forecast,
)


class ClassifyWeatherTests(unittest.TestCase):
    def test_default_city_is_india(self) -> None:
        intent = classify("what is the weather")
        self.assertEqual(intent.name, IntentName.WEATHER)
        self.assertNotIn("place", intent.extra)

    def test_spoken_indian_city(self) -> None:
        intent = classify("weather in mumbai")
        self.assertEqual(intent.name, IntentName.WEATHER)
        self.assertEqual(intent.extra["place"], "mumbai")

    def test_natural_forecast_phrases(self) -> None:
        for phrase in (
            "weather forecast",
            "tell me regarding the weather forecast",
            "tell me about the weather",
            "in the weather",
            "weather forecast for delhi",
        ):
            intent = classify(phrase)
            self.assertEqual(intent.name, IntentName.WEATHER, phrase)
            self.assertEqual(intent.extra["action"], "forecast", phrase)
        delhi = classify("tell me regarding the weather in delhi nc")
        self.assertEqual(delhi.name, IntentName.WEATHER)
        self.assertEqual(delhi.extra["place"], "delhi nc")

    def test_does_not_steal_google_weather(self) -> None:
        self.assertEqual(
            classify("google for weather in delhi").name, IntentName.BROWSER
        )
        self.assertEqual(classify("find weather on google").name, IntentName.BROWSER)


class NormalizePlaceTests(unittest.TestCase):
    def test_aliases_and_default(self) -> None:
        self.assertEqual(normalize_place(""), DEFAULT_PLACE)
        self.assertEqual(normalize_place("dilli"), "New Delhi")
        self.assertEqual(normalize_place("bombay"), "Mumbai")
        self.assertEqual(normalize_place("bangalore"), "Bengaluru")
        self.assertEqual(normalize_place("india"), "New Delhi")
        self.assertEqual(normalize_place("delhi nc"), "New Delhi")
        self.assertEqual(normalize_place("delhi ncr"), "New Delhi")
        self.assertEqual(normalize_place("delhi n.c.r"), "New Delhi")


class SpeakForecastTests(unittest.TestCase):
    def test_uses_celsius_and_city(self) -> None:
        reply = speak_forecast(
            {
                "place": "Mumbai",
                "temp_c": 31,
                "condition": "partly cloudy skies",
                "high_c": 33,
                "low_c": 26,
                "tomorrow_high_c": 32,
                "tomorrow_low_c": 25,
                "tomorrow_condition": "light rain",
            }
        )
        self.assertIn("Mumbai", reply)
        self.assertIn("31 degrees Celsius", reply)
        self.assertNotIn("Fahrenheit", reply)
        self.assertIn("Tomorrow", reply)


class FetchForecastTests(unittest.TestCase):
    def test_reads_open_meteo_in_ist(self) -> None:
        geo = Mock()
        geo.json.return_value = {
            "results": [
                {
                    "name": "New Delhi",
                    "admin1": "Delhi",
                    "latitude": 28.6,
                    "longitude": 77.2,
                }
            ]
        }
        geo.raise_for_status = Mock()
        forecast = Mock()
        forecast.json.return_value = {
            "current": {
                "temperature_2m": 34.4,
                "weather_code": 2,
                "relative_humidity_2m": 48,
            },
            "daily": {
                "temperature_2m_max": [36.2, 35.1],
                "temperature_2m_min": [27.0, 26.4],
                "weather_code": [2, 61],
            },
        }
        forecast.raise_for_status = Mock()
        with patch(
            "friday.weather.india.requests.get", side_effect=[geo, forecast]
        ) as get:
            data = fetch_forecast("delhi")
        self.assertEqual(data["temp_c"], 34)
        self.assertEqual(data["condition"], "partly cloudy skies")
        self.assertIn("New Delhi", data["place"])
        forecast_call = get.call_args_list[-1]
        self.assertEqual(forecast_call.kwargs["params"]["timezone"], "Asia/Kolkata")


class WeatherToolTests(unittest.TestCase):
    def test_tool_name(self) -> None:
        self.assertEqual(WEATHER_GET, "weather.get")


if __name__ == "__main__":
    unittest.main()
