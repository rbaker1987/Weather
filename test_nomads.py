#!/usr/bin/env python
import logging
import os
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "weather_app"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django.setup()

logging.basicConfig(
    level=logging.DEBUG, format="%(name)s - %(levelname)s - %(message)s"
)

from weather.noaa_nomads import fetch_gfs_nomads  # noqa: E402

print("=" * 60)
print("Testing NOMADS fetch for NYC (40.7128, -74.0060)...")
print("=" * 60)
try:
    result = fetch_gfs_nomads(40.7128, -74.0060, "det")
    if result:
        print("\n✓ NOMADS successful!")
        hourly = result.get("hourly", {})
        print(f"  Time points: {len(hourly.get('time', []))}")
        print(f"  Temp 2m: {len(hourly.get('temperature_2m', []))}")
        print(f"  Temp 925hPa: {len(hourly.get('temperature_925hPa', []))}")
        print(f"  Gusts: {len(hourly.get('wind_gusts_10m', []))}")
        print(f"  Precipitation: {len(hourly.get('precipitation', []))}")
    else:
        print("\n✗ NOMADS returned None")
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback

    traceback.print_exc()
