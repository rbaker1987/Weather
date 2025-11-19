"""Basic web views for Django weather app (to be expanded)."""

import logging
from datetime import timedelta

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView

from .models import DailyForecast, Location, WeatherAlert
from .serializers import DailyForecastSerializer, LocationSerializer
from .views import fetch_current_conditions

logger = logging.getLogger("weather")


class DashboardView(TemplateView):
    """Main dashboard view."""
    template_name = 'weather/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get recent locations and forecasts
        context['locations'] = Location.objects.filter(is_active=True)[:10]
        context['recent_forecasts'] = DailyForecast.objects.select_related('location').order_by('-created_at')[:5]
        context['active_alerts'] = WeatherAlert.objects.filter(
            is_active=True,
            expires__gt=timezone.now()
        ).select_related('location').order_by('-severity')[:5]

        # Statistics
        context['stats'] = {
            'total_locations': Location.objects.filter(is_active=True).count(),
            'total_forecasts': DailyForecast.objects.count(),
            'active_alerts': WeatherAlert.objects.filter(
                is_active=True,
                expires__gt=timezone.now()
            ).count(),
        }

        return context


class LocationListView(ListView):
    """List view for locations."""
    model = Location
    template_name = 'weather/location_list.html'
    context_object_name = 'locations'
    paginate_by = 20

    def get_queryset(self):
        return Location.objects.filter(is_active=True).order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Fetch current conditions for all locations
        locations = context.get('locations', self.object_list)
        for location in locations:
            if location.latitude and location.longitude:
                try:
                    # Only fetch if conditions are stale (older than 30 minutes) or missing
                    if not location.last_observation_time or \
                       (timezone.now() - location.last_observation_time).total_seconds() > 1800:
                        fetch_current_conditions(location)
                except Exception as e:
                    logger.warning(f"Failed to fetch conditions for {location.name}: {str(e)}")

        return context


class LocationDetailView(DetailView):
    """Detail view for a specific location."""
    model = Location
    template_name = 'weather/location_detail.html'
    context_object_name = 'location'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location = self.object

        # Get forecasts for next 7 days
        end_date = timezone.now().date() + timedelta(days=7)
        context['forecasts'] = DailyForecast.objects.filter(
            location=location,
            forecast_date__lte=end_date
        ).order_by('forecast_date')

        # Get active alerts
        context['alerts'] = WeatherAlert.objects.filter(
            location=location,
            is_active=True,
            expires__gt=timezone.now()
        ).order_by('-severity')
        return context


# API views for AJAX calls
def location_forecast_api(request, location_id):
    """API endpoint for getting location forecast data."""
    location = get_object_or_404(Location, id=location_id)
    days = int(request.GET.get('days', 7))

    end_date = timezone.now().date() + timedelta(days=days)
    forecasts = DailyForecast.objects.filter(
        location=location,
        forecast_date__lte=end_date
    ).order_by('forecast_date')

    data = {
        'location': LocationSerializer(location).data,
        'forecasts': DailyForecastSerializer(forecasts, many=True).data
    }
    return JsonResponse(data)
