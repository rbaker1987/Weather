"""Test fixtures and configuration for pytest."""

import os
import sys
from pathlib import Path

import django

# Add the weather_app directory to the Python path
weather_app_dir = Path(__file__).parent.parent / "weather_app"
sys.path.insert(0, str(weather_app_dir))

# Configure Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_upstream_cache():
    """The process-local cache would otherwise leak upstream responses between tests."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
