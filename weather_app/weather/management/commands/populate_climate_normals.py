"""Management command to populate climate normals for locations."""

import requests
from django.core.management.base import BaseCommand
from django.db import transaction

from weather.models import Location


class Command(BaseCommand):
    help = "Populate climate normals (average high/low temps) for all locations from NWS/NOAA"

    def add_arguments(self, parser):
        parser.add_argument(
            "--location-id",
            type=str,
            help="Populate climate normals for a specific location ID",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        location_id = options.get("location_id")

        if location_id:
            locations = Location.objects.filter(id=location_id)
        else:
            locations = Location.objects.filter(
                latitude__isnull=False, longitude__isnull=False
            )

        self.stdout.write(f"Processing {locations.count()} location(s)...")

        for location in locations:
            try:
                self.stdout.write(f"  Fetching normals for {location.name}...")
                avg_high, avg_low = self._fetch_climate_normals(
                    float(location.latitude), float(location.longitude)
                )

                if avg_high is not None and avg_low is not None:
                    location.avg_high_temp = avg_high
                    location.avg_low_temp = avg_low
                    location.save(update_fields=["avg_high_temp", "avg_low_temp"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"    ✓ Set avg high: {avg_high}°F, avg low: {avg_low}°F"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING("    ✗ Could not retrieve climate data")
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"    ✗ Error for {location.name}: {str(e)}")
                )

        self.stdout.write(self.style.SUCCESS("✓ Climate normals population complete!"))

    def _fetch_climate_normals(self, latitude, longitude):
        """
        Fetch climate normals from NWS/NOAA API.
        Returns (avg_high_temp, avg_low_temp) or (None, None) if failed.
        """
        try:
            # First, get the gridpoint from NWS API
            points_url = f"https://api.weather.gov/points/{latitude},{longitude}"
            points_response = requests.get(points_url, timeout=10)
            points_response.raise_for_status()
            points_data = points_response.json()

            # Extract the grid data URL
            if "properties" not in points_data:
                return None, None

            properties = points_data["properties"]

            # Get the forecast grid point
            forecast_url = properties.get("forecast")
            if not forecast_url:
                return None, None

            # Fetch the forecast data
            forecast_response = requests.get(forecast_url, timeout=10)
            forecast_response.raise_for_status()
            forecast_data = forecast_response.json()

            if "properties" not in forecast_data:
                return None, None

            forecast_props = forecast_data["properties"]
            periods = forecast_props.get("periods", [])

            if not periods:
                return None, None

            # Calculate averages from forecast data
            highs = []
            lows = []

            for period in periods:
                if period.get("isDaytime"):
                    temp = period.get("temperature")
                    if temp is not None:
                        highs.append(temp)
                else:
                    temp = period.get("temperature")
                    if temp is not None:
                        lows.append(temp)

            if highs and lows:
                avg_high = sum(highs) / len(highs)
                avg_low = sum(lows) / len(lows)
                return round(avg_high, 1), round(avg_low, 1)

            return None, None
        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.ERROR(f"NWS API error: {str(e)}"))
            return None, None
