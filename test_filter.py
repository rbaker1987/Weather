import os
import sys
import django

# Add the weather_app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'weather_app'))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from weather.templatetags.ui_tags import is_snow_precip, needs_chance_layout

class MockPeriod:
    def __init__(self, text, pop):
        self.short_forecast = text
        self.precipitation_probability = pop

test_cases = [
    ('Slight Chance Light Snow', 20),
    ('Snow', 20),
    ('Light Snow', 30),
    ('Chance of Rain and Snow', 25),
    ('Snow', 50),
    ('Snow', 10),
]

for text, pop in test_cases:
    p = MockPeriod(text, pop)
    snow_result = is_snow_precip(p)
    layout_result = needs_chance_layout(p)
    print(f"'{text}' @ {pop}% -> is_snow_precip: {snow_result}, needs_chance_layout: '{layout_result}'")
