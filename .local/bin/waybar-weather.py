#!/usr/bin/env python3
"""Cached Open-Meteo weather for the Waybar label and its popup."""

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


LOCATION = "Jalandhar"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "waybar/weather.json"
PARAMS = {
    "latitude": 31.32556,
    "longitude": 75.57917,
    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m,is_day",
    "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max,weather_code",
    "timezone": "Asia/Kolkata",
    "forecast_days": 3,
}
URL = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(PARAMS)


def condition(code, is_day=True):
    if code == 0:
        return ("Clear sky", "☀" if is_day else "☾")
    if code in (1, 2, 3):
        return ({1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast"}[code], "☁")
    if code in (45, 48):
        return ("Fog", "☁")
    if code in (51, 53, 55, 56, 57):
        return ("Drizzle", "☂")
    if code in (61, 63, 65, 66, 67):
        return ("Rain", "☂")
    if code in (71, 73, 75, 77, 85, 86):
        return ("Snow", "❄")
    if code in (80, 81, 82):
        return ("Showers", "☂")
    if code in (95, 96, 99):
        return ("Thunderstorm", "⚡")
    return ("Weather unavailable", "󰖐")


def weather_data(now=None):
    now = time.time() if now is None else now
    cached = None
    try:
        cached = json.loads(CACHE.read_text())
        if not isinstance(cached, dict) or not isinstance(cached.get("data"), dict):
            raise ValueError("invalid weather cache")
        if now - cached["fetched_at"] < 900:
            return cached["data"], False
    except (OSError, ValueError, KeyError, TypeError):
        cached = None
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "WaybarWeather/1.0"})
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.load(response)
        if "current" not in data or "daily" not in data:
            raise ValueError("weather response is incomplete")
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=CACHE.parent,
                                         prefix=".weather-", delete=False) as temporary:
            json.dump({"fetched_at": now, "data": data}, temporary)
        Path(temporary.name).replace(CACHE)
        return data, False
    except (OSError, ValueError, urllib.error.URLError):
        if cached and now - cached.get("fetched_at", 0) < 21600:
            return cached["data"], True
        return None, True


def details(data, stale=False):
    current, daily = data["current"], data["daily"]
    description, icon = condition(current.get("weather_code"), current.get("is_day") == 1)
    forecast = []
    for index, day in enumerate(daily.get("time", [])):
        forecast.append({
            "day": day,
            "high": daily["temperature_2m_max"][index],
            "low": daily["temperature_2m_min"][index],
            "rain_chance": daily["precipitation_probability_max"][index],
            "condition": condition(daily["weather_code"][index])[0],
        })
    return {
        "location": LOCATION,
        "updated": current["time"],
        "stale": stale,
        "description": description,
        "icon": icon,
        "temperature": current["temperature_2m"],
        "feels_like": current["apparent_temperature"],
        "humidity": current["relative_humidity_2m"],
        "precipitation": current["precipitation"],
        "wind_speed": current["wind_speed_10m"],
        "wind_direction": current["wind_direction_10m"],
        "sunrise": daily["sunrise"][0],
        "sunset": daily["sunset"][0],
        "forecast": forecast,
    }


def bar(info):
    if not info:
        return {"text": "󰖐 --°", "tooltip": "Jalandhar weather unavailable"}
    tooltip = (
        f"{info['location']} · {info['description']}\n"
        f"{info['temperature']:.0f}°C · feels like {info['feels_like']:.0f}°C\n"
        f"Humidity {info['humidity']}% · wind {info['wind_speed']:.0f} km/h\n"
        f"Today {info['forecast'][0]['low']:.0f}–{info['forecast'][0]['high']:.0f}°C · "
        f"rain {info['forecast'][0]['rain_chance']}%\n"
        f"Open-Meteo · {info['updated'].replace('T', ' ')}"
    )
    if info["stale"]:
        tooltip += " · cached"
    return {"text": f"{info['icon']} {info['temperature']:.0f}°C", "tooltip": tooltip}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("bar", "details"):
        print("usage: waybar-weather.py {bar|details}", file=sys.stderr)
        sys.exit(2)
    data, stale = weather_data()
    try:
        info = details(data, stale) if data else None
    except (KeyError, IndexError, TypeError, ValueError):
        info = None
    print(json.dumps(bar(info) if sys.argv[1] == "bar" else info))
