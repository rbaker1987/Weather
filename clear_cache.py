#!/usr/bin/env python
"""Clear Django cache to force fresh data fetch with updated metadata."""

import os
import sys

import django

# Add the weather_app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "weather_app"))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.core.cache import cache

print("Clearing Django cache...")
cache.clear()
print("Cache cleared successfully!")
print("\nAll cached model detail data has been removed.")
print("Next page load will fetch fresh data with model_source and cycle metadata.")
