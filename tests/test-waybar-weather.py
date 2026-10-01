#!/usr/bin/env python3
"""Check forecast formatting and offline cache behavior."""

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError


sys.dont_write_bytecode = True
script = Path(__file__).resolve().parents[1] / ".local/bin/waybar-weather.py"
spec = importlib.util.spec_from_file_location("waybar_weather", script)
weather = importlib.util.module_from_spec(spec)
spec.loader.exec_module(weather)

sample = {
    "current": {
        "time": "2026-10-01T01:15", "temperature_2m": 23.3,
        "relative_humidity_2m": 85, "apparent_temperature": 27.2,
        "precipitation": 0.0, "weather_code": 0,
        "wind_speed_10m": 2.3, "wind_direction_10m": 331, "is_day": 0,
    },
    "daily": {
        "time": ["2026-10-01"], "temperature_2m_max": [32.5],
        "temperature_2m_min": [22.0], "sunrise": ["2026-10-01T06:21"],
        "sunset": ["2026-10-01T18:12"],
        "precipitation_probability_max": [2], "weather_code": [0],
    },
}
info = weather.details(sample)
assert info["description"] == "Clear sky"
assert info["temperature"] == 23.3
assert "feels like 27°C" in weather.bar(info)["tooltip"]

with TemporaryDirectory() as directory:
    weather.CACHE = Path(directory) / "weather.json"
    weather.CACHE.write_text(json.dumps({"fetched_at": 1000, "data": sample}))
    with patch.object(weather.urllib.request, "urlopen", side_effect=URLError("offline")):
        assert weather.weather_data(now=1500) == (sample, False)
        assert weather.weather_data(now=2000) == (sample, True)
        assert weather.weather_data(now=30000) == (None, True)

print("waybar weather formatting and offline cache checks passed")
