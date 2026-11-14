"""Інтеграція із зовнішнім API погоди."""

import math
import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 10


class WeatherError(Exception):
    """Помилка, яку веб-рівень може безпечно показати клієнту."""

    status_code = 502

class CityNotFoundError(WeatherError):
    status_code = 404

class WeatherTimeoutError(WeatherError):
    status_code = 504

class WeatherUnavailableError(WeatherError):
    status_code = 503


def _request_json(url: str, params: dict, service: str) -> dict:
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
    except requests.Timeout:
        raise WeatherTimeoutError(f"Час очікування {service} вичерпано.") from None
    except requests.RequestException:
        raise WeatherUnavailableError(f"Не вдалося підключитися до {service}.") from None

    if response.status_code == 429 or response.status_code >= 500:
        raise WeatherUnavailableError(f"{service.capitalize()} тимчасово недоступний.")

    if response.status_code >= 400:
        raise WeatherError(f"{service.capitalize()} відхилив запит.")

    try:
        data = response.json()
    except ValueError:
        raise WeatherError(f"{service.capitalize()} повернув відповідь не у форматі JSON.") from None

    if not isinstance(data, dict):
        raise WeatherError(f"{service.capitalize()} повернув відповідь неочікуваного формату.")
    return data


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def find_city(name: str) -> dict:
    """Знайти координати міста за його назвою."""
    data = _request_json(
        GEOCODING_URL,
        {"name": name, "count": 1, "language": "uk", "format": "json"},
        "сервіс геокодування",
    )
    if "results" not in data:
        raise CityNotFoundError(f"Місто '{name}' не знайдено.")
    results = data["results"]
    if not isinstance(results, list):
        raise WeatherError("Сервіс геокодування повернув некоректні дані про місто.")
    if not results:
        raise CityNotFoundError(f"Місто '{name}' не знайдено.")
    if not isinstance(results[0], dict):
        raise WeatherError("Сервіс геокодування повернув некоректні дані про місто.")

    city_data = results[0]
    latitude = city_data.get("latitude")
    longitude = city_data.get("longitude")
    city_name = city_data.get("name")
    if not (
        isinstance(city_name, str)
        and _is_number(latitude)
        and _is_number(longitude)
    ):
        raise WeatherError("Сервіс геокодування повернув некоректні дані про місто.")
    return {
        "name": city_name,
        "latitude": latitude,
        "longitude": longitude,
    }


def get_current_weather(city: str):
    """Повернути поточну температуру й швидкість вітру для міста."""
    location = find_city(city)

    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": "temperature_2m,wind_speed_10m",
    }
    data = _request_json(FORECAST_URL, params, "сервіс погоди")
    current = data.get("current")
    if not isinstance(current, dict):
        raise WeatherError("Сервіс погоди повернув відповідь без даних про погоду.")

    temperature = current.get("temperature_2m")
    wind_speed = current.get("wind_speed_10m")
    if not (_is_number(temperature) and _is_number(wind_speed)):
        raise WeatherError("Сервіс погоди повернув некоректні дані про погоду.")

    return {
        "city": location["name"],
        "temperature": temperature,
        "wind_speed": wind_speed,
    }
