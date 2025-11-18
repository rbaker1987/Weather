"""Basic web views for Django weather app (to be expanded)."""

from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta

from .models import Location, DailyForecast, WeatherAlert
from .serializers import LocationSerializer, DailyForecastSerializer


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