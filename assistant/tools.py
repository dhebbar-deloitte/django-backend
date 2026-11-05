import httpx
from langchain_core.tools import tool

WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Light rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm",
}


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    try:
        geo = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
            timeout=10,
        )
        geo.raise_for_status()
        results = geo.json().get("results")
        if not results:
            return f"No city named {city} was found."
        place = results[0]
        forecast = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,weather_code",
            },
            timeout=10,
        )
        forecast.raise_for_status()
        current = forecast.json()["current"]
    except (httpx.HTTPError, KeyError, ValueError):
        return "The weather service is unavailable right now."
    condition = WEATHER_CODES.get(current["weather_code"], "Unknown")
    return (
        f"{place['name']}: {current['temperature_2m']}°C, {condition}, "
        f"humidity {current['relative_humidity_2m']}%"
    )