"""Celery tasks for background weather processing."""

import logging
from datetime import timedelta

from celery import shared_task
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from .models import (
    DailyForecast,
    ForecastRequest,
    HourlyForecast,
    Location,
    WeatherAlert,
)
from .services import SyncWeatherService

logger = logging.getLogger("weather")


@shared_task(bind=True, max_retries=3)
def update_location_forecast(self, location_id: str):
    """Update forecast for a single location."""
    try:
        from .models import Location

        location = Location.objects.get(id=location_id, is_active=True)

        # Create forecast request record
        request = ForecastRequest.objects.create(
            request_type="background_update",
            status=ForecastRequest.RequestStatus.PENDING,
        )
        request.locations_requested.add(location)

        # Update forecast
        result = SyncWeatherService.update_forecasts_for_location(location)

        if result.get("success"):
            request.status = ForecastRequest.RequestStatus.SUCCESS
            logger.info(f"Successfully updated forecast for {location.name}")
        else:
            request.status = ForecastRequest.RequestStatus.FAILED
            request.error_message = result.get("error", "Unknown error")
            logger.error(
                f"Failed to update forecast for {location.name}: {result.get('error')}"
            )

        request.save()
        return result

    except Location.DoesNotExist:
        logger.error(f"Location {location_id} not found")
        return {"error": "Location not found"}
    except Exception as exc:
        logger.error(f"Error updating forecast for location {location_id}: {exc}")
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from exc


@shared_task
def bulk_update_forecasts(location_ids=None):
    """Update forecasts for multiple locations."""
    try:
        # Create forecast request record
        request = ForecastRequest.objects.create(
            request_type="bulk_background_update",
            status=ForecastRequest.RequestStatus.PENDING,
        )

        if location_ids:
            locations = Location.objects.filter(id__in=location_ids, is_active=True)
        else:
            locations = Location.objects.filter(is_active=True)

        request.locations_requested.set(locations)

        # Update forecasts
        result = SyncWeatherService.bulk_update_forecasts(location_ids)

        if result.get("success"):
            request.status = ForecastRequest.RequestStatus.SUCCESS
            logger.info(
                f"Successfully bulk updated forecasts for {len(locations)} locations"
            )
        else:
            request.status = ForecastRequest.RequestStatus.FAILED
            request.error_message = "Bulk update failed"
            logger.error("Bulk forecast update failed")

        request.save()
        return result

    except Exception as exc:
        logger.error(f"Error in bulk forecast update: {exc}")
        raise exc


@shared_task
def cleanup_old_forecasts():
    """Clean up old forecast data."""
    try:
        import asyncio

        from .services import WeatherIntegrationService

        async def _cleanup():
            async with WeatherIntegrationService() as service:
                return await service.cleanup_old_forecasts()

        # Run the async cleanup
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_cleanup())
            logger.info(f"Cleanup completed: {result}")
            return result
        finally:
            loop.close()

    except Exception as exc:
        logger.error(f"Error during cleanup: {exc}")
        raise exc


@shared_task
def periodic_forecast_updates():
    """Periodic task to update all location forecasts."""
    logger.info("Starting periodic forecast updates")

    # Get all locations that haven't been updated in the last 2 hours
    two_hours_ago = timezone.now() - timedelta(hours=2)
    stale_locations = Location.objects.filter(is_active=True).filter(
        Q(last_forecast_update__lt=two_hours_ago) | Q(last_forecast_update__isnull=True)
    )

    if stale_locations.exists():
        location_ids = list(stale_locations.values_list("id", flat=True))
        logger.info(f"Updating {len(location_ids)} stale locations")

        # Trigger bulk update
        return bulk_update_forecasts.delay(location_ids)
    logger.info("No stale locations found")
    return {"message": "No updates needed"}


@shared_task
def cache_weather_statistics():
    """Cache weather statistics for dashboard."""
    try:
        stats = {
            "total_locations": Location.objects.filter(is_active=True).count(),
            "total_forecasts": (
                DailyForecast.objects.count() + HourlyForecast.objects.count()
            ),
            "active_alerts": WeatherAlert.objects.filter(
                is_active=True, expires__gt=timezone.now()
            ).count(),
            "recent_requests": ForecastRequest.objects.filter(
                created_at__gte=timezone.now() - timedelta(hours=24)
            ).count(),
        }

        # Cache for 15 minutes
        cache.set("weather_dashboard_stats", stats, 15 * 60)
        logger.info("Cached weather statistics")
        return stats

    except Exception as exc:
        logger.error(f"Error caching statistics: {exc}")
        raise exc


@shared_task
def process_weather_alerts():
    """Process and update weather alerts."""
    # This would integrate with your existing alert processing logic
    # For now, just clean up expired alerts
    try:
        expired_count = WeatherAlert.objects.filter(
            expires__lt=timezone.now(), is_active=True
        ).update(is_active=False)

        logger.info(f"Deactivated {expired_count} expired alerts")
        return {"expired_alerts_deactivated": expired_count}

    except Exception as exc:
        logger.error(f"Error processing alerts: {exc}")
        raise exc


@shared_task
def generate_forecast_report(location_ids=None, report_type="daily"):
    """Generate forecast reports in background."""
    try:
        if location_ids:
            locations = Location.objects.filter(id__in=location_ids, is_active=True)
        else:
            locations = Location.objects.filter(is_active=True)[:10]  # Limit for demo

        # This would integrate with your existing text output generation
        # from weather_app.ui.components.text_output

        report_data = []
        for location in locations:
            if report_type == "daily":
                forecasts = location.forecasts.filter(
                    forecast_date__gte=timezone.now().date()
                )[:7]
            else:
                forecasts = location.hourlyforecast_set.filter(
                    period_start__gte=timezone.now()
                )[:24]

            report_data.append(
                {
                    "location": location.name,
                    "forecast_count": forecasts.count(),
                    "data": list(forecasts.values()),
                }
            )

        # Cache the report
        cache_key = f'forecast_report_{report_type}_{"-".join(location_ids or ["all"])}'
        cache.set(cache_key, report_data, 60 * 60)  # Cache for 1 hour

        logger.info(f"Generated {report_type} report for {len(locations)} locations")
        return {
            "report_type": report_type,
            "locations": len(locations),
            "cache_key": cache_key,
        }

    except Exception as exc:
        logger.error(f"Error generating report: {exc}")
        raise exc
