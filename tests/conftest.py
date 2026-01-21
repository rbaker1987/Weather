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
