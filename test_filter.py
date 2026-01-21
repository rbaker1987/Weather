import os
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "weather_app"))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from weather.templatetags.ui_tags import (  # noqa: E402
    is_snow_precip,
    needs_chance_layout,
)


class MockPeriod:
    def __init__(self, text, pop):
        self.short_forecast = text
        self.precipitation_probability = pop


test_cases = [
    ("Slight Chance Light Snow", 20),
    ("Snow", 20),
    ("Light Snow", 30),
    ("Chance of Rain and Snow", 25),
    ("Snow", 50),
    ("Snow", 10),
]

for text, pop in test_cases:
    p = MockPeriod(text, pop)
    snow_result = is_snow_precip(p)
    layout_result = needs_chance_layout(p)
    print(
        f"'{text}' @ {pop}% -> is_snow_precip: {snow_result}, needs_chance_layout: '{layout_result}'"
    )
