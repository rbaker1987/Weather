#!/usr/bin/env python
"""Clear Django cache to force fresh data fetch with updated metadata."""

import os
import sys
from pathlib import Path

import django
from django.core.cache import cache

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "weather_app"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

print("Clearing Django cache...")
cache.clear()
print("Cache cleared successfully!")
print("\nAll cached model detail data has been removed.")
print("Next page load will fetch fresh data with model_source and cycle metadata.")
