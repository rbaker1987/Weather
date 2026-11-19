"""URL configuration for weather app."""

from django.urls import include, path, register_converter

from . import views
from .api.climate_analysis_api import ClimateAnalysisAPIView, ClimateIndicesAPIView
from .api.climate_normals_api import ClimateNormalsAPIView
from .api.forecast_verification_api import ForecastVerificationAPIView
from .api.geocode_api import GeocodeAPIView
from .api.hourly_forecast_api import HourlyForecastForLocationAPIView
from .api.model_comparison_api import ModelComparisonAPIView
from .api.model_spread_api import ModelSpreadAPIView
from .api.summarize_api import SummarizeForecastAPIView
from .converters import CoordinatesConverter

register_converter(CoordinatesConverter, "coords")

# URL patterns
urlpatterns = [
    # API endpoints
    path(
        "api/hourly_forecast/",
        HourlyForecastForLocationAPIView.as_view(),
        name="hourly-forecast-location",
    ),
    path("api/geocode/", GeocodeAPIView.as_view(), name="geocode"),
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
        "api/forecast-verification/",
        ForecastVerificationAPIView.as_view(),
        name="forecast-verification",
    ),
    path(
        "api/model-spread/",
        ModelSpreadAPIView.as_view(),
        name="model-spread",
    ),
    path(
        "api/climate-normals/",
        ClimateNormalsAPIView.as_view(),
        name="climate-normals",
    ),
    path(
        "api/climate-indices/",
        ClimateIndicesAPIView.as_view(),
        name="climate-indices",
    ),
    path(
        "api/climate-analysis/",
        ClimateAnalysisAPIView.as_view(),
        name="climate-analysis",
    ),
    # Web interface
    path("", views.HomeView.as_view(), name="home"),
    path("temp-location/", views.TempLocationView.as_view(), name="temp-location"),
    path("weather/<coords:coords>/", views.PlaceView.as_view(), name="place"),
    path("models/", views.ModelsView.as_view(), name="models"),
    path(
        "models/<str:model_name>/", views.ModelDetailView.as_view(), name="model-detail"
    ),
    # DRF browsable API
    path("api-auth/", include("rest_framework.urls")),
]

# App name for namespacing
app_name = "weather"
