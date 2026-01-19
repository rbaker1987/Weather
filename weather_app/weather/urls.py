"""URL configuration for weather app."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .api.climate_normals_api import ClimateNormalsAPIView
from .api.hourly_forecast_api import HourlyForecastForLocationAPIView
from .api.model_comparison_api import ModelComparisonAPIView
from .api.summarize_api import SummarizeForecastAPIView

# DRF Router for ViewSets
router = DefaultRouter()
router.register(r"locations", views.LocationViewSet, basename="location")
router.register(
    r"hourly-forecasts", views.HourlyForecastViewSet, basename="hourlyforecast"
)
router.register(
    r"daily-forecasts", views.DailyForecastViewSet, basename="dailyforecast"
)
router.register(r"alerts", views.WeatherAlertViewSet, basename="weatheralert")

# URL patterns
urlpatterns = [
    # API endpoints
    path("api/", include(router.urls)),
    path(
        "api/bulk-forecast/", views.BulkForecastAPIView.as_view(), name="bulk-forecast"
    ),
    path("api/stats/", views.WeatherStatsAPIView.as_view(), name="weather-stats"),
    path("api/export/", views.ExportAPIView.as_view(), name="weather-export"),
    path(
        "api/hourly_forecast/",
        HourlyForecastForLocationAPIView.as_view(),
        name="hourly-forecast-location",
    ),
    path(
        "api/summarize_forecast/",
        SummarizeForecastAPIView.as_view(),
        name="summarize-forecast",
    ),
    path(
        "api/model-comparison/",
        ModelComparisonAPIView.as_view(),
        name="model-comparison",
    ),
    path(
        "api/climate-normals/",
        ClimateNormalsAPIView.as_view(),
        name="climate-normals",
    ),
    # Web interface
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("locations/", views.LocationListView.as_view(), name="location-list"),
    path(
        "locations/<uuid:pk>/",
        views.LocationDetailView.as_view(),
        name="location-detail",
    ),
    path("temp-location/", views.TempLocationView.as_view(), name="temp-location"),
    path("forecasts/", views.ForecastListView.as_view(), name="forecast-list"),
    path("alerts/", views.AlertListView.as_view(), name="alert-list"),
    path("models/", views.ModelsView.as_view(), name="models"),
    path("models/<str:model_name>/", views.ModelDetailView.as_view(), name="model-detail"),
    # DRF browsable API
    path("api-auth/", include("rest_framework.urls")),
]

# App name for namespacing
app_name = "weather"
