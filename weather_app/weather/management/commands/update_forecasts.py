"""Django management command to update weather forecasts."""

import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from weather.models import Location
from weather.services import SyncWeatherService

logger = logging.getLogger("weather")


class Command(BaseCommand):
    """Update weather forecasts for locations."""

    help = "Update weather forecasts for specified locations or all locations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--locations",
            nargs="+",
            help="Location IDs to update (if not specified, updates all active locations)",
        )
        parser.add_argument(
            "--force", action="store_true", help="Force update even if recently updated"
        )
        parser.add_argument("--verbose", action="store_true", help="Verbose output")

    def handle(self, *args, **options):
        """Execute the command."""
        verbosity = options.get("verbosity", 1)
        verbose = options.get("verbose", False)

        # Configure logging level
        if verbose or verbosity > 1:
            logging.getLogger("weather").setLevel(logging.DEBUG)

        location_ids = options.get("locations")
        force = options.get("force", False)

        try:
            if location_ids:
                # Update specific locations
                locations = Location.objects.filter(id__in=location_ids, is_active=True)
                if not locations.exists():
                    raise CommandError("No valid locations found with provided IDs")

                self.stdout.write(
                    f"Updating {locations.count()} specified locations..."
                )

                for location in locations:
                    if verbose:
                        self.stdout.write(f"Updating {location.name}...")

                    result = SyncWeatherService.update_forecasts_for_location(location)

                    if result.get("success"):
                        daily = result.get("daily_forecasts", 0)
                        hourly = result.get("hourly_forecasts", 0)
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"✓ {location.name}: {daily} daily, {hourly} hourly forecasts"
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.ERROR(
                                f"✗ {location.name}: {result.get('error', 'Unknown error')}"
                            )
                        )
            else:
                # Update all locations
                if not force:
                    # Only update stale locations (older than 1 hour)
                    from datetime import timedelta

                    one_hour_ago = timezone.now() - timedelta(hours=1)
                    locations = Location.objects.filter(is_active=True).filter(
                        models.Q(last_forecast_update__lt=one_hour_ago)
                        | models.Q(last_forecast_update__isnull=True)
                    )
                else:
                    locations = Location.objects.filter(is_active=True)

                if not locations.exists():
                    self.stdout.write(self.style.WARNING("No locations need updating"))
                    return

                self.stdout.write(f"Updating {locations.count()} locations...")

                # Use bulk update
                location_ids = [str(loc.id) for loc in locations]
                result = SyncWeatherService.bulk_update_forecasts(location_ids)

                if result.get("success"):
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ Bulk update completed for {result.get('total_locations', 0)} locations"
                        )
                    )

                    if verbose:
                        for location_result in result.get("results", []):
                            location_name = location_result.get("location", "Unknown")
                            location_data = location_result.get("result", {})

                            if location_data.get("success"):
                                daily = location_data.get("daily_forecasts", 0)
                                hourly = location_data.get("hourly_forecasts", 0)
                                self.stdout.write(
                                    f"  {location_name}: {daily} daily, {hourly} hourly"
                                )
                            else:
                                error = location_data.get("error", "Unknown error")
                                self.stdout.write(f"  {location_name}: ERROR - {error}")
                else:
                    self.stdout.write(self.style.ERROR("Bulk update failed"))

        except Exception as e:
            logger.exception("Command failed")
            raise CommandError(f"Command failed: {e}")


# Import Django ORM for queries
from django.db import models
