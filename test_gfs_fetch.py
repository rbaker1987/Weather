#!/usr/bin/env python
"""Quick test to check if NOMADS fetch works and logs show the attempt."""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'weather_app'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from weather.noaa_nomads import fetch_gfs_nomads
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')

# Test coordinates (Texas)
lat, lon = 32.490950, -95.395448

print(f"\n=== Testing NOMADS fetch for GFS at {lat}, {lon} ===\n")
result = fetch_gfs_nomads(lat, lon, ensemble="det", timeout=45)

if result:
    print(f"\n[OK] NOMADS SUCCESS")
    print(f"  - Hours fetched: {len(result.get('hourly', {}).get('time', []))}")
    print(f"  - Model source: {result.get('model_source')}")
    print(f"  - Cycle: {result.get('cycle')}")
else:
    print(f"\n[X] NOMADS FAILED - returned None")
