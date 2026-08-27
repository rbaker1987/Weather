"""Celery tasks for background weather processing."""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from .models import (
    CurrentConditions,
    DailyForecast,
    ForecastRequest,
    HourlyForecast,
    Location,
    WeatherAlert,
)
from .services import SyncWeatherService

logger = logging.getLogger("weather")


def _celery_enabled() -> bool:
    return bool(getattr(settings, "CELERY_ENABLED", False))


def enqueue_current_conditions(location_id: str) -> str:
    if _celery_enabled():
        update_current_conditions_for_location.delay(str(location_id))
        return "queued"

    from .services import CurrentConditionsService

    location = Location.objects.get(id=location_id)
    CurrentConditionsService.fetch_and_cache_current_conditions(location)
    return "direct"


def enqueue_forecasts(location_id: str) -> str:
    if _celery_enabled():
        update_forecasts_for_location.delay(str(location_id))
        return "queued"

    from .services import ForecastService

    location = Location.objects.get(id=location_id)
    ForecastService.get_or_fetch_hourly_forecasts(location, force_refresh=True)
    ForecastService.get_or_fetch_daily_forecasts(location, force_refresh=True)
    return "direct"


def enqueue_alerts(location_id: str) -> str:
    if _celery_enabled():
        update_alerts_for_location.delay(str(location_id))
        return "queued"

    from .services import AlertsService

    location = Location.objects.get(id=location_id)
    AlertsService.fetch_and_cache_alerts(location)
    return "direct"


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

    # Get all locations that haven't been updated in the last 15 minutes
    stale_cutoff = timezone.now() - timedelta(minutes=15)
    stale_locations = Location.objects.filter(is_active=True).filter(
        Q(last_forecast_update__lt=stale_cutoff) | Q(last_forecast_update__isnull=True)
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
                forecasts = HourlyForecast.objects.filter(
                    location=location,
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
        cache_key = f"forecast_report_{report_type}_{'-'.join(location_ids or ['all'])}"
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


# ============================================================================
# Cache-aware background tasks for CurrentConditions and Forecasts
# ============================================================================


@shared_task(bind=True, max_retries=3)
def update_current_conditions_for_location(self, location_id: str):
    """
    Update current conditions for a single location using cache-aware service.

    This task is called by the periodic task below, or can be triggered manually.

    Args:
        location_id: UUID of the Location to update
    """
    try:
        from .services import CurrentConditionsService

        location = Location.objects.get(id=location_id)
        logger.info(f"Background task: Updating current conditions for {location.name}")

        current_conditions = (
            CurrentConditionsService.fetch_and_cache_current_conditions(location)
        )

        if current_conditions:
            logger.info(
                f"✓ Successfully updated current conditions for {location.name} - "
                f"Temp: {current_conditions.temperature}°F"
            )
            return {
                "location": location.name,
                "status": "success",
                "temperature": current_conditions.temperature,
            }
        logger.warning(f"✗ Failed to fetch conditions for {location.name}")
        raise Exception(f"Failed to fetch conditions for {location.name}")

    except Location.DoesNotExist:
        logger.error(f"Location {location_id} not found")
        return {"location_id": location_id, "status": "not_found"}
    except Exception as exc:
        logger.error(f"Error updating conditions for {location_id}: {str(exc)}")
        # Retry after 60 seconds
        raise self.retry(exc=exc, countdown=60, max_retries=self.max_retries) from exc


@shared_task
def update_all_current_conditions():
    """
    Periodic task to update current conditions for all active locations.

    This should be scheduled to run every 15 minutes to keep data relatively fresh.

    Configure in Django settings CELERY_BEAT_SCHEDULE:
    ```
    CELERY_BEAT_SCHEDULE = {
        'update-current-conditions-every-15-min': {
            'task': 'weather.tasks.update_all_current_conditions',
            'schedule': timedelta(minutes=15),
        },
    }
    ```
    """
    from .services import CurrentConditionsService

    logger.info("Starting periodic update of all current conditions")

    # Get all enabled locations with coordinates
    locations = Location.objects.filter(
        is_enabled=True, latitude__isnull=False, longitude__isnull=False
    )

    logger.info(f"Found {locations.count()} locations to update")

    results = []
    for location in locations:
        try:
            current_conditions = (
                CurrentConditionsService.fetch_and_cache_current_conditions(location)
            )
            if current_conditions:
                results.append(
                    {
                        "location": location.name,
                        "status": "success",
                        "temperature": current_conditions.temperature,
                    }
                )
            else:
                results.append(
                    {
                        "location": location.name,
                        "status": "failed",
                    }
                )
        except Exception as e:
            logger.error(f"Error updating {location.name}: {str(e)}")
            results.append(
                {
                    "location": location.name,
                    "status": "error",
                    "error": str(e),
                }
            )

    successful = sum(1 for r in results if r["status"] == "success")
    logger.info(f"Periodic update complete: {successful}/{len(results)} successful")
    return results


@shared_task(bind=True, max_retries=3)
def update_forecasts_for_location(self, location_id: str):
    """
    Update hourly and daily forecasts for a single location.

    Args:
        location_id: UUID of the Location to update
    """
    try:
        from .services import ForecastService

        location = Location.objects.get(id=location_id)
        logger.info(f"Background task: Updating forecasts for {location.name}")

        # Get forecasts with cache validation
        hourly = ForecastService.get_or_fetch_hourly_forecasts(
            location, force_refresh=True
        )
        daily = ForecastService.get_or_fetch_daily_forecasts(
            location, force_refresh=True
        )

        logger.info(
            f"✓ Updated forecasts for {location.name} "
            f"({hourly.count()} hourly, {daily.count()} daily)"
        )

        return {
            "location": location.name,
            "status": "success",
            "hourly_count": hourly.count(),
            "daily_count": daily.count(),
        }

    except Location.DoesNotExist:
        logger.error(f"Location {location_id} not found")
        return {"location_id": location_id, "status": "not_found"}
    except Exception as exc:
        logger.error(f"Error updating forecasts for {location_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60, max_retries=self.max_retries) from exc


@shared_task
def update_all_forecasts():
    """
    Periodic task to update forecasts for all active locations.

    This should be scheduled to run every 15 minutes.

    Configure in Django settings CELERY_BEAT_SCHEDULE:
    ```
    CELERY_BEAT_SCHEDULE = {
        'update-forecasts-every-15-min': {
            'task': 'weather.tasks.update_all_forecasts',
            'schedule': timedelta(minutes=15),
        },
    }
    ```
    """
    from .services import ForecastService

    logger.info("Starting periodic update of all forecasts")

    locations = Location.objects.filter(
        is_enabled=True, latitude__isnull=False, longitude__isnull=False
    )

    logger.info(f"Found {locations.count()} locations to update")

    results = []
    for location in locations:
        try:
            hourly = ForecastService.get_or_fetch_hourly_forecasts(
                location, force_refresh=True
            )
            daily = ForecastService.get_or_fetch_daily_forecasts(
                location, force_refresh=True
            )

            results.append(
                {
                    "location": location.name,
                    "status": "success",
                    "hourly_count": hourly.count(),
                    "daily_count": daily.count(),
                }
            )
        except Exception as e:
            logger.error(f"Error updating forecasts for {location.name}: {str(e)}")
            results.append(
                {
                    "location": location.name,
                    "status": "error",
                    "error": str(e),
                }
            )

    successful = sum(1 for r in results if r["status"] == "success")
    logger.info(
        f"Periodic forecast update complete: {successful}/{len(results)} successful"
    )
    return results


@shared_task(bind=True, max_retries=3)
def update_alerts_for_location(self, location_id: str):
    """Update weather alerts for a single location."""
    try:
        from .services import AlertsService

        location = Location.objects.get(id=location_id)
        logger.info(f"Background task: Updating alerts for {location.name}")

        alerts = AlertsService.fetch_and_cache_alerts(location)
        return {
            "location": location.name,
            "status": "success",
            "alert_count": alerts.count(),
        }
    except Location.DoesNotExist:
        logger.error(f"Location {location_id} not found")
        return {"location_id": location_id, "status": "not_found"}
    except Exception as exc:
        logger.error(f"Error updating alerts for {location_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60, max_retries=self.max_retries) from exc


@shared_task
def update_all_alerts():
    """Periodic task to update alerts for all active locations."""
    from .services import AlertsService

    logger.info("Starting periodic update of all alerts")

    locations = Location.objects.filter(
        is_enabled=True, latitude__isnull=False, longitude__isnull=False
    )

    results = []
    for location in locations:
        try:
            alerts = AlertsService.fetch_and_cache_alerts(location)
            results.append(
                {
                    "location": location.name,
                    "status": "success",
                    "alert_count": alerts.count(),
                }
            )
        except Exception as exc:
            logger.error(f"Error updating alerts for {location.name}: {str(exc)}")
            results.append(
                {
                    "location": location.name,
                    "status": "error",
                    "error": str(exc),
                }
            )

    successful = sum(1 for r in results if r["status"] == "success")
    logger.info(f"Periodic alerts update complete: {successful}/{len(results)}")
    return results


@shared_task
def cleanup_cached_weather_data():
    """Clear cached conditions, alerts, and forecasts at 2 AM daily."""
    current_deleted, _ = CurrentConditions.objects.all().delete()
    alerts_deleted, _ = WeatherAlert.objects.all().delete()
    hourly_deleted, _ = HourlyForecast.objects.all().delete()
    daily_deleted, _ = DailyForecast.objects.all().delete()

    logger.info(
        "Cleanup complete: Cleared %s current conditions, %s alerts, %s hourly, %s daily",
        current_deleted,
        alerts_deleted,
        hourly_deleted,
        daily_deleted,
    )

    return {
        "current_conditions_deleted": current_deleted,
        "alerts_deleted": alerts_deleted,
        "hourly_deleted": hourly_deleted,
        "daily_deleted": daily_deleted,
    }
