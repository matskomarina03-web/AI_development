import unittest
from unittest.mock import Mock, patch

import requests

from fastapi import HTTPException

from app.main import api_weather


class WeatherIntegrationTests(unittest.TestCase):
    def test_blank_city_returns_422_without_calling_weather_service(self):
        with patch("app.main.weather.get_current_weather") as get_weather:
            with self.assertRaises(HTTPException) as error:
                api_weather("   ")

        self.assertEqual(error.exception.status_code, 422)
        get_weather.assert_not_called()

    @patch("app.weather.requests.get")
    def test_weather_success(self, get):
        geocoding = Mock(status_code=200)
        geocoding.json.return_value = {
            "results": [{"name": "Київ", "latitude": 50.45, "longitude": 30.52}]
        }
        forecast = Mock(status_code=200)
        forecast.json.return_value = {
            "current": {"temperature_2m": 18.5, "wind_speed_10m": 4.2}
        }
        get.side_effect = [geocoding, forecast]

        response = api_weather("Київ")

        self.assertEqual(response, {"city": "Київ", "temperature": 18.5, "wind_speed": 4.2})

    @patch("app.weather.requests.get")
    def test_missing_city_returns_404(self, get):
        geocoding = Mock(status_code=200)
        geocoding.json.return_value = {}
        get.return_value = geocoding

        with self.assertRaises(HTTPException) as error:
            api_weather("Невідоме")

        self.assertEqual(error.exception.status_code, 404)
        self.assertIsInstance(error.exception.detail, str)

    @patch("app.weather.requests.get")
    def test_weather_service_failure_returns_503(self, get):
        geocoding = Mock(status_code=200)
        geocoding.json.return_value = {
            "results": [{"name": "Київ", "latitude": 50.45, "longitude": 30.52}]
        }
        get.side_effect = [geocoding, Mock(status_code=503)]

        with self.assertRaises(HTTPException) as error:
            api_weather("Київ")

        self.assertEqual(error.exception.status_code, 503)
        self.assertIsInstance(error.exception.detail, str)

    @patch("app.weather.requests.get")
    def test_invalid_upstream_json_returns_502(self, get):
        geocoding = Mock(status_code=200)
        geocoding.json.side_effect = ValueError("invalid JSON")
        get.return_value = geocoding

        with self.assertRaises(HTTPException) as error:
            api_weather("Київ")

        self.assertEqual(error.exception.status_code, 502)
        self.assertIsInstance(error.exception.detail, str)

    @patch("app.weather.requests.get")
    def test_upstream_timeout_returns_504(self, get):
        get.side_effect = requests.Timeout

        with self.assertRaises(HTTPException) as error:
            api_weather("Київ")

        self.assertEqual(error.exception.status_code, 504)
        self.assertIsInstance(error.exception.detail, str)

    @patch("app.weather.requests.get")
    def test_malformed_upstream_data_returns_502(self, get):
        geocoding = Mock(status_code=200)
        geocoding.json.return_value = {"results": "not a list"}
        get.return_value = geocoding

        with self.assertRaises(HTTPException) as error:
            api_weather("Київ")

        self.assertEqual(error.exception.status_code, 502)
        self.assertIsInstance(error.exception.detail, str)


if __name__ == "__main__":
    unittest.main()
