"""URL configuration for weather app."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# DRF Router for ViewSets
router = DefaultRouter()
router.register(r'locations', views.LocationViewSet, basename='location')
router.register(r'hourly-forecasts', views.HourlyForecastViewSet, basename='hourlyforecast')
router.register(r'daily-forecasts', views.DailyForecastViewSet, basename='dailyforecast')
router.register(r'alerts', views.WeatherAlertViewSet, basename='weatheralert')

# URL patterns
urlpatterns = [
    # API endpoints
    path('api/', include(router.urls)),
    path('api/bulk-forecast/', views.BulkForecastAPIView.as_view(), name='bulk-forecast'),
    path('api/stats/', views.WeatherStatsAPIView.as_view(), name='weather-stats'),
    path('api/export/', views.ExportAPIView.as_view(), name='weather-export'),
    
    # Web interface
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('locations/', views.LocationListView.as_view(), name='location-list'),
    path('locations/<uuid:pk>/', views.LocationDetailView.as_view(), name='location-detail'),
    path('forecasts/', views.ForecastListView.as_view(), name='forecast-list'),
    path('alerts/', views.AlertListView.as_view(), name='alert-list'),
    
    # DRF browsable API
    path('api-auth/', include('rest_framework.urls')),
]

# App name for namespacing
app_name = 'weather'