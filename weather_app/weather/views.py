"""Django REST Framework views for weather API."""

import json
import logging
import os
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import login
from django.core.cache import cache
from django.db.models import Avg, Case, Count, IntegerField, Q, When
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .forms import UniqueUsernameCreationForm
from .models import (
    CurrentConditions,
    DailyForecast,
    ForecastRequest,
    HourlyForecast,
    Location,
    WeatherAlert,
)
from .serializers import (
    BulkForecastRequestSerializer,
    CurrentConditionsSerializer,
    DailyForecastSerializer,
    HourlyForecastSerializer,
    LocationSerializer,
    WeatherAlertSerializer,
)
from .utils.apparent_temperature import calculate_apparent_temperature

logger = logging.getLogger("weather")


def fetch_current_conditions(location):
    """Helper function to fetch and update current conditions for a location."""
    if not location.latitude or not location.longitude:
        return False

    try:
        from .services import CurrentConditionsService

        current_conditions = (
            CurrentConditionsService.fetch_and_cache_current_conditions(location)
        )
        return current_conditions is not None
    except Exception as e:
        logger.warning(
            f"Could not fetch current conditions for {location.name}: {str(e)}"
        )
        return False


class LocationViewSet(viewsets.ModelViewSet):
    """API ViewSet for managing locations."""

    queryset = Location.objects.filter(is_active=True)
    serializer_class = LocationSerializer
    permission_classes = [permissions.AllowAny]
    search_fields = ["name", "zip_code"]
    ordering_fields = ["name", "created_at", "last_forecast_update"]
    ordering = ["name"]

    def get_queryset(self):
        """Filter locations by session."""
        queryset = super().get_queryset()

        if self.request.user.is_authenticated:
            queryset = queryset.filter(owner=self.request.user)
        else:
            # Only show locations in session for anonymous users
            location_ids = self.request.session.get("location_ids", [])
            queryset = queryset.filter(id__in=location_ids)

        return queryset.annotate(forecast_count=Count("forecasts"))

    def perform_create(self, serializer):
        """Save location and add to session."""
        owner = self.request.user if self.request.user.is_authenticated else None
        location = serializer.save(owner=owner)

        # Save location ID in session (convert UUID to string)
        if "location_ids" not in self.request.session:
            self.request.session["location_ids"] = []
        self.request.session["location_ids"].append(str(location.id))
        self.request.session.modified = True

        # If location doesn't have coordinates, try to geocode
        if not location.latitude or not location.longitude:
            try:
                import requests

                headers = {"User-Agent": "WeatherApp/1.0"}

                # Try zip code first if available
                if location.zip_code:
                    geocode_url = (
                        "https://nominatim.openstreetmap.org/search?"
                        f"postalcode={location.zip_code}&country=US&format=json&limit=1"
                    )
                else:
                    # Otherwise geocode the name
                    geocode_url = (
                        "https://nominatim.openstreetmap.org/search?"
                        f"q={location.name}&format=json&limit=1"
                    )

                geo_response = requests.get(geocode_url, headers=headers, timeout=10)
                geo_response.raise_for_status()
                geo_data = geo_response.json()

                if geo_data and len(geo_data) > 0:
                    location.latitude = float(geo_data[0]["lat"])
                    location.longitude = float(geo_data[0]["lon"])
                    location.save()
            except Exception as e:
                # Log error but don't fail the creation
                logger.warning(f"Geocoding error: {str(e)}")

        # Kick off background refreshes (best-effort)
        if location.latitude and location.longitude:
            try:
                from .tasks import (
                    update_alerts_for_location,
                    update_current_conditions_for_location,
                    update_forecasts_for_location,
                )

                update_current_conditions_for_location.delay(str(location.id))
                update_forecasts_for_location.delay(str(location.id))
                update_alerts_for_location.delay(str(location.id))
            except Exception:
                fetch_current_conditions(location)
                _refresh_forecasts_for_location(location)

    @action(detail=False, methods=["post"])
    def ensure_browser_location(self, request):
        """Create or update a 'current' location from browser coordinates.
        Payload: { name: str, latitude: float, longitude: float }
        Ensures the location is enabled, marked current, and added to session.
        Returns the location id.
        """
        try:
            data = request.data or {}
            name = data.get("name") or "My Location"
            lat = data.get("latitude")
            lon = data.get("longitude")
            if lat is None or lon is None:
                return Response(
                    {
                        "status": "error",
                        "message": "latitude and longitude are required",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # If a current location exists, update its coordinates and name
            location = Location.objects.filter(is_current_location=True).first()
            if location is None:
                location = Location.objects.create(
                    name=name,
                    latitude=lat,
                    longitude=lon,
                    is_active=True,
                    is_enabled=True,
                    is_current_location=True,
                )
            else:
                location.name = name or location.name
                location.latitude = lat
                location.longitude = lon
                location.is_active = True
                location.is_enabled = True
                location.is_current_location = True
                location.save(
                    update_fields=[
                        "name",
                        "latitude",
                        "longitude",
                        "is_active",
                        "is_enabled",
                        "is_current_location",
                    ]
                )

            # Ensure in session (store as strings)
            session_ids = request.session.get("location_ids", [])
            session_ids_str = [str(x) for x in session_ids]
            loc_id_str = str(location.id)
            if loc_id_str not in session_ids_str:
                session_ids_str.append(loc_id_str)
                request.session["location_ids"] = session_ids_str
                request.session.modified = True

            # Kick off background refreshes (best-effort)
            try:
                from .tasks import (
                    update_alerts_for_location,
                    update_current_conditions_for_location,
                    update_forecasts_for_location,
                )

                update_current_conditions_for_location.delay(str(location.id))
                update_forecasts_for_location.delay(str(location.id))
                update_alerts_for_location.delay(str(location.id))
            except Exception:
                _refresh_forecasts_for_location(location)

            return Response({"status": "success", "location_id": str(location.id)})
        except Exception as e:
            logger.exception("ensure_browser_location failed: %s", e)
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"])
    def update_forecast(self, request, pk=None):
        """Manually trigger forecast update for a location."""
        location = self.get_object()

        # Check if location has coordinates
        if not location.latitude or not location.longitude:
            # Try to get coordinates from zip code
            if location.zip_code:
                try:
                    import requests

                    # Use OpenStreetMap Nominatim (free, no API key required)
                    # Must include User-Agent header per usage policy
                    headers = {"User-Agent": "WeatherApp/1.0"}
                    geocode_url = f"https://nominatim.openstreetmap.org/search?postalcode={location.zip_code}&country=US&format=json&limit=1"
                    geo_response = requests.get(
                        geocode_url, headers=headers, timeout=10
                    )
                    geo_response.raise_for_status()
                    geo_data = geo_response.json()

                    if geo_data and len(geo_data) > 0:
                        location.latitude = float(geo_data[0]["lat"])
                        location.longitude = float(geo_data[0]["lon"])
                        location.save()
                    else:
                        return Response(
                            {
                                "status": "error",
                                "message": f"Could not geocode zip code {location.zip_code}. Please manually add coordinates.",
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                except Exception as e:
                    return Response(
                        {
                            "status": "error",
                            "message": f"Error geocoding zip code: {str(e)}. Please manually add coordinates.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                return Response(
                    {
                        "status": "error",
                        "message": "Location does not have coordinates or zip code. Please update the location.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            import requests

            headers = {"User-Agent": "(Weather App, contact@example.com)"}
            grid_url = f"https://api.weather.gov/points/{location.latitude},{location.longitude}"
            grid_response = requests.get(grid_url, headers=headers, timeout=10)
            grid_response.raise_for_status()
            grid_data = grid_response.json()

            properties = grid_data.get("properties", {})
            location.nws_office = properties.get("gridId", "")
            location.grid_x = properties.get("gridX")
            location.grid_y = properties.get("gridY")

            # Fetch current conditions from observation station
            try:
                observation_stations_url = properties.get("observationStations")
                if observation_stations_url:
                    stations_response = requests.get(
                        observation_stations_url, headers=headers, timeout=10
                    )
                    stations_response.raise_for_status()
                    stations_data = stations_response.json()

                    stations = stations_data.get("features", [])
                    if stations:
                        station_id = (
                            stations[0].get("properties", {}).get("stationIdentifier")
                        )
                        if station_id:
                            obs_url = (
                                "https://api.weather.gov/stations/"
                                f"{station_id}/observations/latest"
                            )
                            obs_response = requests.get(
                                obs_url, headers=headers, timeout=10
                            )
                            obs_response.raise_for_status()
                            obs_data = obs_response.json()

                            obs_props = obs_data.get("properties", {})
                            temp_c = obs_props.get("temperature", {}).get("value")
                            temp_f = (
                                int(temp_c * 9 / 5 + 32) if temp_c is not None else 32
                            )

                            cc, created = CurrentConditions.objects.get_or_create(
                                location=location,
                                defaults={
                                    "temperature": temp_f,
                                    "condition": obs_props.get(
                                        "textDescription", "Unknown"
                                    ),
                                    "humidity": 50,
                                    "wind_speed": 0,
                                    "wind_direction": "",
                                    "last_observation_time": timezone.now(),
                                },
                            )

                            cc.temperature = temp_f
                            cc.condition = obs_props.get("textDescription", "Unknown")

                            humidity = obs_props.get("relativeHumidity", {}).get(
                                "value"
                            )
                            if humidity is not None:
                                cc.humidity = int(humidity)
                            elif cc.humidity is None:
                                cc.humidity = 50

                            wind_speed_kmh = obs_props.get("windSpeed", {}).get("value")
                            if wind_speed_kmh is not None:
                                try:
                                    cc.wind_speed = int(wind_speed_kmh * 0.621371)
                                except (ValueError, TypeError):
                                    cc.wind_speed = 0
                            else:
                                cc.wind_speed = 0

                            wind_gust_kmh = obs_props.get("windGust", {}).get("value")
                            if wind_gust_kmh is not None:
                                try:
                                    cc.wind_gust = int(wind_gust_kmh * 0.621371)
                                except (ValueError, TypeError):
                                    cc.wind_gust = None
                            else:
                                cc.wind_gust = None

                            wind_dir_deg = obs_props.get("windDirection", {}).get(
                                "value"
                            )
                            if wind_dir_deg is not None:
                                try:
                                    deg = float(wind_dir_deg)
                                    directions = [
                                        "N",
                                        "NE",
                                        "E",
                                        "SE",
                                        "S",
                                        "SW",
                                        "W",
                                        "NW",
                                    ]
                                    cc.wind_direction = directions[
                                        int((deg + 22.5) / 45) % 8
                                    ]
                                except (ValueError, TypeError):
                                    cc.wind_direction = ""
                            else:
                                cc.wind_direction = ""

                            if cc.temperature is not None:
                                dew_point_c = obs_props.get("dewpoint", {}).get("value")
                                cc.feels_like_temperature = (
                                    calculate_apparent_temperature(
                                        temp_f=cc.temperature,
                                        humidity_pct=cc.humidity or 50,
                                        wind_speed_mph=cc.wind_speed or 0,
                                        dew_point_c=dew_point_c,
                                    )
                                )

                            timestamp = obs_props.get("timestamp")
                            if timestamp:
                                cc.last_observation_time = datetime.fromisoformat(
                                    timestamp.replace("Z", "+00:00")
                                )
                            elif cc.last_observation_time is None:
                                cc.last_observation_time = timezone.now()

                            cc.save()
            except Exception as e:
                logger.warning(
                    "Could not fetch current conditions for %s: %s",
                    location.name,
                    e,
                )

            def parse_wind_speed(value):
                if not value:
                    return 0
                import re

                numbers = re.findall(r"\d+", str(value))
                if numbers:
                    if len(numbers) > 1:
                        return int((int(numbers[0]) + int(numbers[1])) / 2)
                    return int(numbers[0])
                return 0

            forecast_url = properties.get("forecast")
            if not forecast_url:
                return Response(
                    {"status": "error", "message": "Forecast URL not found."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            forecast_response = requests.get(forecast_url, headers=headers, timeout=10)
            forecast_response.raise_for_status()
            forecast_data = forecast_response.json()

            periods = forecast_data.get("properties", {}).get("periods", [])
            DailyForecast.objects.filter(location=location).delete()
            now = timezone.now()

            for period in periods[:14]:
                raw_start = datetime.fromisoformat(
                    period["startTime"].replace("Z", "+00:00")
                )
                raw_end = datetime.fromisoformat(
                    period["endTime"].replace("Z", "+00:00")
                )
                local_start = raw_start.astimezone(timezone.get_current_timezone())
                local_end = raw_end.astimezone(timezone.get_current_timezone())

                is_daytime = period.get("isDaytime", True)
                if is_daytime:
                    forecast_date = local_start.date()
                else:
                    if local_start.hour >= 18:
                        forecast_date = local_start.date()
                    else:
                        forecast_date = (local_start - timedelta(days=1)).date()

                precip_value = period.get("probabilityOfPrecipitation", {}).get("value")
                if precip_value is not None:
                    try:
                        precip_value = int(precip_value)
                    except (TypeError, ValueError):
                        precip_value = None

                DailyForecast.objects.create(
                    location=location,
                    forecast_date=forecast_date,
                    period_start=local_start,
                    period_end=local_end,
                    is_daytime=is_daytime,
                    temperature=period.get("temperature") or 0,
                    temperature_unit=period.get("temperatureUnit", "F"),
                    short_forecast=period.get("shortForecast", ""),
                    detailed_forecast=period.get("detailedForecast", ""),
                    wind_speed=parse_wind_speed(period.get("windSpeed", "")),
                    wind_direction=period.get("windDirection", ""),
                    precipitation_probability=precip_value,
                    nws_data_url=forecast_url,
                    raw_data=period,
                    last_api_update=now,
                )

            location.last_forecast_update = now
            location.save(
                update_fields=["nws_office", "grid_x", "grid_y", "last_forecast_update"]
            )

            alerts_created = 0
            alerts_updated = 0
            try:
                alerts_url = (
                    "https://api.weather.gov/alerts/active?"
                    f"point={location.latitude},{location.longitude}"
                )
                alerts_response = requests.get(alerts_url, headers=headers, timeout=10)
                alerts_response.raise_for_status()
                alerts_data = alerts_response.json()

                active_alert_ids = []
                for feature in alerts_data.get("features", []):
                    props = feature.get("properties", {})
                    alert_id = props.get("id")
                    if not alert_id:
                        continue

                    onset = props.get("onset")
                    expires = props.get("expires")
                    if onset:
                        onset = datetime.fromisoformat(onset.replace("Z", "+00:00"))
                    if expires:
                        expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))

                    alert, created = WeatherAlert.objects.update_or_create(
                        nws_alert_id=alert_id,
                        defaults={
                            "location": location,
                            "event": props.get("event", "Unknown"),
                            "headline": props.get("headline", ""),
                            "description": props.get("description", ""),
                            "severity": props.get("severity", "unknown").lower(),
                            "urgency": props.get("urgency", "unknown").lower(),
                            "onset": onset,
                            "expires": expires,
                            "is_active": True,
                            "raw_data": props,
                        },
                    )
                    active_alert_ids.append(alert.nws_alert_id)
                    if created:
                        alerts_created += 1
                    else:
                        alerts_updated += 1

                if active_alert_ids:
                    WeatherAlert.objects.filter(
                        location=location, is_active=True
                    ).exclude(nws_alert_id__in=active_alert_ids).update(is_active=False)
            except Exception as e:
                logger.warning(
                    "Could not fetch alerts for %s: %s",
                    location.name,
                    e,
                )

            return Response(
                {
                    "status": "success",
                    "periods_created": min(len(periods), 14),
                    "alerts_created": alerts_created,
                    "alerts_updated": alerts_updated,
                }
            )
        except requests.exceptions.RequestException as e:
            logger.error("Error fetching data from external service: %s", e)
            return Response(
                {
                    "status": "error",
                    "message": "An internal error occurred while fetching data.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"])
    def clear_all(self, request):
        """Clear all locations."""
        try:
            count = Location.objects.filter(is_active=True).count()
            Location.objects.filter(is_active=True).delete()
            return Response(
                {
                    "status": "success",
                    "deleted": count,
                    "message": f"Removed {count} location(s)",
                }
            )
        except Exception as e:
            return Response(
                {"status": "error", "message": f"Error clearing locations: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # Removed favorite support; reordering replaces this feature.

    @action(detail=True, methods=["post"])
    def set_current(self, request, pk=None):
        """Set this location as current/home location."""
        location = self.get_object()

        try:
            # Unset any existing current location
            Location.objects.filter(is_current_location=True).update(
                is_current_location=False
            )

            # Set this location as current and ensure it's enabled
            location.is_current_location = True
            location.is_enabled = True
            location.save(update_fields=["is_current_location", "is_enabled"])

            # Ensure this location is tracked in session
            session_ids = request.session.get("location_ids", [])
            # Normalize all IDs to strings
            session_ids_str = [str(x) for x in session_ids]
            loc_id_str = str(location.id)
            if loc_id_str not in session_ids_str:
                session_ids_str.append(loc_id_str)
                request.session["location_ids"] = session_ids_str
                request.session.modified = True

            return Response(
                {
                    "status": "success",
                    "message": f"{location.display_name} set as current location",
                }
            )
        except Exception as e:
            return Response(
                {
                    "status": "error",
                    "message": f"Error setting current location: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"])
    def toggle_enabled(self, request, pk=None):
        """Toggle location enabled/disabled state."""
        location = self.get_object()

        try:
            # Toggle the is_enabled field
            location.is_enabled = not location.is_enabled
            location.save()

            return Response(
                {
                    "status": "success",
                    "is_enabled": location.is_enabled,
                    "message": f"{location.display_name} {'enabled' if location.is_enabled else 'disabled'}",
                }
            )
        except Exception as e:
            return Response(
                {"status": "error", "message": f"Error toggling location: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get", "post"])
    def forecasts(self, request, pk=None):
        """Return or create forecasts for a location."""
        location = self.get_object()

        if request.method.lower() == "post":
            data = request.data or {}
            date_str = data.get("date")
            if not date_str:
                return Response(
                    {"status": "error", "message": "date is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                forecast_date = datetime.fromisoformat(date_str).date()
            except ValueError:
                return Response(
                    {"status": "error", "message": "invalid date format"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            is_daytime = bool(data.get("is_daytime", True))
            temp = data.get("temperature")
            short_forecast = data.get("short_forecast") or ""
            if temp is None:
                return Response(
                    {"status": "error", "message": "temperature is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if is_daytime:
                start_time = datetime.combine(forecast_date, time(6, 0))
                end_time = datetime.combine(forecast_date, time(18, 0))
            else:
                start_time = datetime.combine(forecast_date, time(18, 0))
                end_time = datetime.combine(
                    forecast_date + timedelta(days=1), time(6, 0)
                )

            DailyForecast.objects.create(
                location=location,
                forecast_date=forecast_date,
                period_start=timezone.make_aware(start_time),
                period_end=timezone.make_aware(end_time),
                is_daytime=is_daytime,
                temperature=int(temp),
                short_forecast=short_forecast,
                wind_speed=0,
                last_api_update=timezone.now(),
            )

            return Response({"status": "success"}, status=status.HTTP_201_CREATED)

        forecast_type = request.query_params.get("type", "daily")
        days = int(request.query_params.get("days", "3"))
        start_date = timezone.now().date()
        end_date = start_date + timedelta(days=days)

        if forecast_type == "hourly":
            qs = HourlyForecast.objects.filter(
                location=location,
                forecast_date__gte=start_date,
                forecast_date__lte=end_date,
            ).order_by("period_start")
            serializer = HourlyForecastSerializer(qs, many=True)
        else:
            qs = DailyForecast.objects.filter(
                location=location,
                forecast_date__gte=start_date,
                forecast_date__lte=end_date,
            ).order_by("forecast_date", "-is_daytime")
            serializer = DailyForecastSerializer(qs, many=True)

        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def alerts(self, request, pk=None):
        """Return alerts for a location."""
        location = self.get_object()
        alerts = WeatherAlert.objects.filter(location=location).order_by("-onset")
        serializer = WeatherAlertSerializer(alerts, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        """Reorder locations by provided list of ids."""
        location_order = request.data.get("location_order")
        if not location_order:
            return Response(
                {"status": "error", "message": "location_order is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            for index, location_id in enumerate(location_order):
                Location.objects.filter(id=location_id).update(display_order=index)
            return Response({"status": "success"})
        except Exception as e:
            logger.error("Error reordering locations: %s", e)
            return Response(
                {
                    "status": "error",
                    "message": "Internal server error while reordering locations.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"])
    def geocode_search(self, request):
        """Proxy geocoding search request to Nominatim API.

        Query parameters:
        - q: Search query (required)
        """
        try:
            q = request.query_params.get("q", "").strip()
            if not q:
                return Response(
                    {"status": "error", "message": "Search query required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            import requests

            headers = {"User-Agent": "WeatherApp/1.0"}
            url = (
                f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1"
            )

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            results = response.json()

            if not results:
                return Response({"results": []})

            # Return first result
            result = results[0]
            return Response(
                {
                    "status": "success",
                    "results": [
                        {
                            "lat": float(result.get("lat", 0)),
                            "lon": float(result.get("lon", 0)),
                            "display_name": result.get("display_name", ""),
                        }
                    ],
                }
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Geocoding search error: {str(e)}")
            return Response(
                {"status": "error", "message": "Geocoding service error"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.error(f"Geocoding search error: {str(e)}")
            return Response(
                {"status": "error", "message": f"Error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"])
    def geocode_reverse(self, request):
        """Proxy reverse geocoding request to Nominatim API.

        Query parameters:
        - lat: Latitude (required)
        - lon: Longitude (required)
        """
        try:
            lat = request.query_params.get("lat", "").strip()
            lon = request.query_params.get("lon", "").strip()

            if not lat or not lon:
                return Response(
                    {"status": "error", "message": "Latitude and longitude required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            import requests

            headers = {"User-Agent": "WeatherApp/1.0"}
            url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            return Response(
                {
                    "status": "success",
                    "address": data.get("address", {}),
                    "display_name": data.get("display_name", ""),
                }
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Reverse geocoding error: {str(e)}")
            return Response(
                {"status": "error", "message": "Geocoding service error"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.error(f"Reverse geocoding error: {str(e)}")
            return Response(
                {"status": "error", "message": f"Error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class HourlyForecastViewSet(viewsets.ReadOnlyModelViewSet):
    """API ViewSet for hourly forecasts."""

    queryset = HourlyForecast.objects.all()
    serializer_class = HourlyForecastSerializer
    permission_classes = [permissions.AllowAny]
    filterset_fields = ["location", "forecast_date"]
    ordering = ["location", "period_start"]

    def get_queryset(self):
        """Filter forecasts by date range and location."""
        queryset = super().get_queryset()

        # Filter by date range
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if start_date:
            queryset = queryset.filter(forecast_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(forecast_date__lte=end_date)

        # Filter by location name or zip
        location_query = self.request.query_params.get("location")
        if location_query:
            queryset = queryset.filter(
                Q(location__name__icontains=location_query)
                | Q(location__zip_code=location_query)
            )

        return queryset


class DailyForecastViewSet(viewsets.ReadOnlyModelViewSet):
    """API ViewSet for daily forecasts."""

    queryset = DailyForecast.objects.all()
    serializer_class = DailyForecastSerializer
    permission_classes = [permissions.AllowAny]
    filterset_fields = ["location", "forecast_date"]
    ordering = ["location", "forecast_date"]

    def get_queryset(self):
        """Filter forecasts by date range and location."""
        queryset = super().get_queryset()

        # Filter by date range
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if start_date:
            queryset = queryset.filter(forecast_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(forecast_date__lte=end_date)

        # Filter by location
        location_query = self.request.query_params.get("location")
        if location_query:
            queryset = queryset.filter(
                Q(location__name__icontains=location_query)
                | Q(location__zip_code=location_query)
            )

        return queryset


class WeatherAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """API ViewSet for weather alerts."""

    queryset = WeatherAlert.objects.filter(is_active=True)
    serializer_class = WeatherAlertSerializer
    permission_classes = [permissions.AllowAny]


class CurrentConditionsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API ViewSet for current weather conditions with cache-aware fetching.

    This endpoint serves cached conditions from the database if fresh (<15 min),
    or fetches from the API if stale. Use ?refresh=true to force a fresh API call.
    """

    queryset = CurrentConditions.objects.select_related("location")
    serializer_class = CurrentConditionsSerializer
    permission_classes = [permissions.AllowAny]

    @action(detail=False, methods=["get"])
    def by_location(self, request):
        """Get current conditions for a specific location by location_id."""
        from .services import CurrentConditionsService

        location_id = request.query_params.get("location_id")
        force_refresh = request.query_params.get("refresh", "false").lower() == "true"

        if not location_id:
            return Response(
                {"error": "location_id query parameter required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            location = Location.objects.get(id=location_id)
        except Location.DoesNotExist:
            return Response(
                {"error": f"Location with id {location_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Use cache-aware fetching
        current_conditions = CurrentConditionsService.get_or_fetch_current_conditions(
            location, force_refresh=force_refresh
        )

        if not current_conditions:
            return Response(
                {"error": f"Unable to fetch current conditions for {location.name}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = self.get_serializer(current_conditions)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def for_locations(self, request):
        """Get current conditions for multiple locations."""
        from .services import CurrentConditionsService

        location_ids = request.query_params.getlist("location_ids")
        force_refresh = request.query_params.get("refresh", "false").lower() == "true"

        if not location_ids:
            return Response(
                {
                    "error": "location_ids query parameter required (comma-separated or repeated)"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        locations = Location.objects.filter(id__in=location_ids)
        results = []

        for location in locations:
            conditions = CurrentConditionsService.get_or_fetch_current_conditions(
                location, force_refresh=force_refresh
            )
            if conditions:
                results.append(conditions)

        serializer = self.get_serializer(results, many=True)
        return Response(serializer.data)

    filterset_fields = ["location", "severity", "urgency"]
    ordering = ["-onset", "-created_at"]

    def get_queryset(self):
        """Filter active alerts."""
        queryset = super().get_queryset()

        # Only show non-expired alerts by default
        show_expired = (
            self.request.query_params.get("include_expired", "false").lower() == "true"
        )
        if not show_expired:
            queryset = queryset.filter(expires__gt=timezone.now())

        # Filter by location
        location_query = self.request.query_params.get("location")
        if location_query:
            queryset = queryset.filter(
                Q(location__name__icontains=location_query)
                | Q(location__zip_code=location_query)
            )

        return queryset


class BulkForecastAPIView(APIView):
    """API view for bulk forecast requests."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Process bulk forecast request."""
        serializer = BulkForecastRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data

        # Create forecast request record
        forecast_request = ForecastRequest.objects.create(
            session_key=request.session.session_key or "",
            request_type="bulk_forecast",
            status=ForecastRequest.RequestStatus.PENDING,
        )

        try:
            # Process locations (this would integrate with your existing geocoding logic)
            locations_data = []
            for location_input in validated_data["locations"]:
                # Try to find existing location
                location = Location.objects.filter(
                    Q(name__icontains=location_input) | Q(zip_code=location_input)
                ).first()

                if location:
                    locations_data.append(
                        {
                            "location": LocationSerializer(location).data,
                            "forecasts": self._get_forecast_data(
                                location, validated_data
                            ),
                        }
                    )
                else:
                    # Would create new location using your geocoding service
                    locations_data.append(
                        {"error": f"Location not found: {location_input}"}
                    )

            forecast_request.status = ForecastRequest.RequestStatus.SUCCESS
            forecast_request.save()

            return Response(
                {
                    "request_id": forecast_request.id,
                    "status": "success",
                    "locations": locations_data,
                }
            )

        except Exception as e:
            forecast_request.status = ForecastRequest.RequestStatus.FAILED
            forecast_request.error_message = str(e)
            forecast_request.save()

            logger.error(f"Bulk forecast request failed: {e}")
            return Response(
                {"error": "Forecast request failed", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _get_forecast_data(self, location, validated_data):
        """Get forecast data for a location."""
        forecast_type = validated_data["forecast_type"]
        days = validated_data["days"]
        end_date = timezone.now().date() + timedelta(days=days)

        result = {}

        if forecast_type in ["daily", "both"]:
            daily_forecasts = DailyForecast.objects.filter(
                location=location, forecast_date__lte=end_date
            ).order_by("forecast_date")
            result["daily"] = DailyForecastSerializer(daily_forecasts, many=True).data

        if forecast_type in ["hourly", "both"]:
            hourly_forecasts = HourlyForecast.objects.filter(
                location=location, forecast_date__lte=end_date
            ).order_by("period_start")
            result["hourly"] = HourlyForecastSerializer(
                hourly_forecasts, many=True
            ).data

        if validated_data["include_alerts"]:
            alerts = WeatherAlert.objects.filter(
                location=location, is_active=True, expires__gt=timezone.now()
            ).order_by("-severity")
            result["alerts"] = WeatherAlertSerializer(alerts, many=True).data

        return result


class WeatherStatsAPIView(APIView):
    """API view for weather statistics."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        """Get weather statistics."""
        stats = {
            "total_locations": Location.objects.filter(is_active=True).count(),
            "total_forecasts": DailyForecast.objects.count()
            + HourlyForecast.objects.count(),
            "active_alerts": WeatherAlert.objects.filter(
                is_active=True, expires__gt=timezone.now()
            ).count(),
            "recent_requests": ForecastRequest.objects.filter(
                created_at__gte=timezone.now() - timedelta(hours=24)
            ).count(),
        }

        # Temperature stats for last 7 days
        week_ago = timezone.now() - timedelta(days=7)
        recent_forecasts = DailyForecast.objects.filter(
            created_at__gte=week_ago
        ).aggregate(
            avg_temp=Avg("temperature"),
            avg_high=Avg("high_temperature"),
            avg_low=Avg("low_temperature"),
        )

        stats["recent_averages"] = {
            "temperature": round(recent_forecasts["avg_temp"] or 0, 1),
            "high_temperature": round(recent_forecasts["avg_high"] or 0, 1),
            "low_temperature": round(recent_forecasts["avg_low"] or 0, 1),
        }

        return Response(stats)


class ExportAPIView(APIView):
    """API view for exporting forecast data."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Export forecast data in various formats."""
        export_format = request.data.get("format", "json")
        location_ids = request.data.get("locations", [])

        if not location_ids:
            return Response(
                {"error": "No locations specified"}, status=status.HTTP_400_BAD_REQUEST
            )

        locations = Location.objects.filter(id__in=location_ids)

        if export_format == "kml":
            return self._export_kml(locations)
        if export_format == "csv":
            return self._export_csv(locations)
        return self._export_json(locations)

    def _export_json(self, locations):
        """Export as JSON."""
        data = []
        for location in locations:
            location_data = LocationSerializer(location).data
            location_data["forecasts"] = DailyForecastSerializer(
                location.forecasts.all()[:7], many=True
            ).data
            data.append(location_data)

        response = HttpResponse(
            json.dumps(data, indent=2, default=str), content_type="application/json"
        )
        response["Content-Disposition"] = 'attachment; filename="weather_export.json"'
        return response

    def _export_csv(self, locations):
        """Export as CSV."""
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Location",
                "Date",
                "High Temp",
                "Low Temp",
                "Forecast",
                "Wind Speed",
                "Wind Direction",
            ]
        )

        for location in locations:
            for forecast in location.forecasts.all()[:7]:
                # Handle both DailyForecast (has high/low) and base ForecastPeriod
                high_temp = (
                    getattr(forecast, "high_temperature", None) or forecast.temperature
                )
                low_temp = (
                    getattr(forecast, "low_temperature", None) or forecast.temperature
                )
                writer.writerow(
                    [
                        location.name,
                        forecast.forecast_date,
                        high_temp,
                        low_temp,
                        forecast.short_forecast,
                        forecast.wind_speed,
                        forecast.wind_direction,
                    ]
                )

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="weather_export.csv"'
        return response

    def _export_kml(self, locations):
        """Export as KML using existing export utilities."""
        try:
            # This would use your existing export_utils.py
            kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
    <name>Weather Forecast Locations</name>
    {"".join([self._location_to_kml(location) for location in locations])}
</Document>
</kml>"""

            response = HttpResponse(
                kml_content, content_type="application/vnd.google-earth.kml+xml"
            )
            response["Content-Disposition"] = (
                'attachment; filename="weather_locations.kml"'
            )
            return response

        except Exception as e:
            return Response(
                {"error": "KML export failed", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _location_to_kml(self, location):
        """Convert location to KML placemark."""
        if not location.latitude or not location.longitude:
            return ""

        return f"""
    <Placemark>
        <name>{location.name}</name>
        <description>
            Last updated: {location.last_forecast_update or "Never"}
            ZIP: {location.zip_code or "N/A"}
        </description>
        <Point>
            <coordinates>{location.longitude},{location.latitude},0</coordinates>
        </Point>
    </Placemark>"""


# Web view: Alerts list with precomputed counts
class AlertListView(ListView):
    """List active weather alerts for session locations."""

    model = WeatherAlert
    template_name = "weather/alert_list.html"
    context_object_name = "alerts"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            WeatherAlert.objects.filter(is_active=True, expires__gt=timezone.now())
            .select_related("location")
            .order_by("-severity", "-onset")
        )
        location_ids = self.request.session.get("location_ids")
        if location_ids:
            qs = qs.filter(location_id__in=location_ids)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        alerts = ctx.get("alerts") or []
        severe_extreme = sum(1 for a in alerts if a.severity in ("severe", "extreme"))
        moderate = sum(1 for a in alerts if a.severity == "moderate")
        ctx.update(
            {
                "severe_extreme_count": severe_extreme,
                "moderate_count": moderate,
            }
        )
        return ctx


# =============================================================================
# Django Web Interface Views
# =============================================================================


class SignUpView(CreateView):
    """Create a new user account."""

    template_name = "registration/signup.html"
    form_class = UniqueUsernameCreationForm
    success_url = reverse_lazy("weather:dashboard")

    def form_valid(self, form):
        self.object = form.save()
        login(self.request, self.object)

        # Attach anonymous session locations to the new user.
        session_ids = self.request.session.get("location_ids", [])
        if session_ids:
            Location.objects.filter(id__in=session_ids, owner__isnull=True).update(
                owner=self.object
            )
            owner_ids = list(
                Location.objects.filter(owner=self.object).values_list("id", flat=True)
            )
            self.request.session["location_ids"] = [
                str(location_id) for location_id in owner_ids
            ]
            self.request.session.modified = True

        return redirect(self.get_success_url())


class DashboardView(TemplateView):
    """Main dashboard view with weather overview."""

    template_name = "weather/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get recent locations (ordered same as location list page)
        # Order: current-location flag first (for saved entries), then by location_type priority, then display_order/name
        type_priority = Case(
            When(location_type="home", then=1),
            When(location_type="work", then=2),
            When(location_type="school", then=3),
            default=4,
            output_field=IntegerField(),
        )

        # Filter locations by session
        location_filter = Q(is_active=True, is_enabled=True)
        location_ids = self.request.session.get("location_ids", [])
        location_filter &= Q(id__in=location_ids)

        locations = (
            Location.objects.filter(location_filter)
            .annotate(type_priority=type_priority)
            .order_by("-is_current_location", "type_priority", "display_order", "name")[
                :8
            ]
        )

        # Ensure forecasts and current conditions for displayed locations
        for location in locations:
            # Check if we need to refresh data (older than 15 minutes or no data)
            try:
                cc = location.current_conditions_cache
                current_stale = timezone.now() - cc.last_observation_time > timedelta(
                    minutes=15
                )
            except (AttributeError, CurrentConditions.DoesNotExist):
                current_stale = True

            needs_refresh = (
                location.last_forecast_update is None
                or (
                    timezone.now() - location.last_forecast_update
                    > timedelta(minutes=15)
                )
                or current_stale
            )
            if needs_refresh:
                try:
                    from .tasks import (
                        update_current_conditions_for_location,
                        update_forecasts_for_location,
                    )

                    update_current_conditions_for_location.delay(str(location.id))
                    update_forecasts_for_location.delay(str(location.id))
                except Exception as e:
                    logger.warning(f"Failed to refresh data for {location.name}: {e}")

        # Get locations with current conditions
        locations_with_current = (
            Location.objects.filter(location_filter)
            .annotate(type_priority=type_priority)
            .order_by("-is_current_location", "type_priority", "display_order", "name")
        )

        # Select primary location as first in ordered list
        favorite_location = locations[0] if locations else None

        # Get 3-day forecast grouped by date (NWS forecasts only)
        daily_forecasts = []
        if favorite_location:
            from collections import defaultdict

            forecasts = (
                DailyForecast.objects.filter(
                    location=favorite_location,
                    forecast_date__gte=timezone.now().date(),
                )
                .exclude(nws_data_url="")  # Only show NWS forecasts on dashboard
                .order_by("forecast_date", "-is_daytime")[:6]
            )  # Get up to 6 periods (3 days x 2 periods)
            grouped = defaultdict(lambda: {"date": None, "day": None, "night": None})
            for forecast in forecasts:
                date = forecast.forecast_date
                grouped[date]["date"] = date
                if forecast.is_daytime:
                    grouped[date]["day"] = forecast
                else:
                    grouped[date]["night"] = forecast
                daily_forecasts = [grouped[date] for date in sorted(grouped.keys())[:3]]

        # Get active alerts ordered by location order
        active_alerts = (
            WeatherAlert.objects.filter(is_active=True, expires__gt=timezone.now())
            .select_related("location")
            .annotate(
                type_priority=Case(
                    When(location__location_type="home", then=1),
                    When(location__location_type="work", then=2),
                    When(location__location_type="school", then=3),
                    default=4,
                    output_field=IntegerField(),
                )
            )
            .order_by(
                "-location__is_current_location",
                "type_priority",
                "location__display_order",
                "location__name",
                "-severity",
                "-onset",
            )[:10]
        )

        # Dashboard statistics
        context.update(
            {
                "locations": locations,
                "locations_with_current": locations_with_current,
                "favorite_location": favorite_location,
                "daily_forecasts": daily_forecasts,
                "active_alerts": active_alerts,
                "total_locations": Location.objects.filter(location_filter).count(),
                "total_forecasts": DailyForecast.objects.count(),
                "recent_alerts": active_alerts,
                "page_title": "Weather Dashboard",
            }
        )
        return context


class ModelsView(TemplateView):
    """View for comparing weather models."""

    template_name = "weather/models.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location_ids = self.request.session.get("location_ids", [])
        locations_qs = Location.objects.filter(
            is_active=True, id__in=location_ids
        ).order_by("-is_current_location", "display_order", "name")
        locations = list(locations_qs)
        context["locations"] = locations
        # Default to current location if no location is set
        current_location = next(
            (loc for loc in locations if getattr(loc, "is_current_location", False)),
            None,
        )
        context["default_location_id"] = (
            current_location.id
            if current_location
            else (locations[0].id if locations else None)
        )
        # Include climate normals for the current location
        if current_location:
            context["avg_high_temp"] = current_location.avg_high_temp
            context["avg_low_temp"] = current_location.avg_low_temp
        context["page_title"] = "Weather Models"
        return context


class TempLocationView(TemplateView):
    """View for temporary location forecast (map-selected coordinates)."""

    template_name = "weather/location_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lat = self.request.GET.get("latitude")
        lon = self.request.GET.get("longitude")

        if not lat or not lon:
            context["error"] = "Latitude and longitude are required"
            context["page_title"] = "Temporary Location"
            return context

        try:
            latitude = float(lat)
            longitude = float(lon)
        except (ValueError, TypeError):
            context["error"] = "Invalid coordinates"
            context["page_title"] = "Temporary Location"
            return context

        # Create a pseudo-location object for template compatibility
        from datetime import datetime
        from itertools import groupby
        from types import SimpleNamespace

        import requests

        location = SimpleNamespace(
            id=None,
            name=f"Map Location ({lat}, {lon})",
            display_name="📍 Map Location",
            latitude=latitude,
            longitude=longitude,
            zip_code=None,
            nws_office="",
            grid_x=None,
            grid_y=None,
            last_forecast_update=None,
            last_observation_time=None,
            current_temp=None,
            current_conditions="",
            current_humidity=None,
            current_wind_speed=None,
            current_wind_gust=None,
            current_wind_direction="",
            current_apparent_temp=None,
            is_current_location=False,
        )
        location.alerts = SimpleNamespace(filter=lambda **_kwargs: [])

        # Fetch forecast data from NWS
        daily_forecasts = []
        hourly_forecasts = []
        active_alerts = []

        try:
            headers = {"User-Agent": "(Weather App, contact@example.com)"}

            # Get grid point data
            grid_url = f"https://api.weather.gov/points/{latitude},{longitude}"
            grid_response = requests.get(grid_url, headers=headers, timeout=10)
            grid_response.raise_for_status()
            grid_data = grid_response.json()

            properties = grid_data.get("properties", {})
            location.nws_office = properties.get("gridId", "")
            location.grid_x = properties.get("gridX")
            location.grid_y = properties.get("gridY")

            # Fetch current conditions
            try:
                observation_stations_url = properties.get("observationStations")
                if observation_stations_url:
                    stations_response = requests.get(
                        observation_stations_url, headers=headers, timeout=10
                    )
                    stations_response.raise_for_status()
                    stations_data = stations_response.json()

                    stations = stations_data.get("features", [])
                    if stations:
                        station_id = (
                            stations[0].get("properties", {}).get("stationIdentifier")
                        )
                        if station_id:
                            obs_url = f"https://api.weather.gov/stations/{station_id}/observations/latest"
                            obs_response = requests.get(
                                obs_url, headers=headers, timeout=10
                            )
                            obs_response.raise_for_status()
                            obs_data = obs_response.json()

                            obs_props = obs_data.get("properties", {})

                            # Extract temperature FIRST before creating object
                            temp_c = obs_props.get("temperature", {}).get("value")
                            temp_f = (
                                int(temp_c * 9 / 5 + 32) if temp_c is not None else 32
                            )

                            # Get or create CurrentConditions with temperature in defaults
                            cc, created = CurrentConditions.objects.get_or_create(
                                location=location,
                                defaults={
                                    "temperature": temp_f,
                                    "condition": obs_props.get(
                                        "textDescription", "Unknown"
                                    ),
                                    "humidity": 50,
                                    "wind_speed": 0,
                                    "wind_direction": "",
                                    "last_observation_time": timezone.now(),
                                },
                            )

                            # Always update fields (whether new or existing)
                            cc.temperature = temp_f
                            cc.condition = obs_props.get("textDescription", "Unknown")

                            humidity = obs_props.get("relativeHumidity", {}).get(
                                "value"
                            )
                            if humidity is not None:
                                cc.humidity = int(humidity)
                            elif cc.humidity is None:
                                cc.humidity = 50  # Default humidity

                            wind_speed_kmh = obs_props.get("windSpeed", {}).get("value")
                            if wind_speed_kmh is not None:
                                cc.wind_speed = int(wind_speed_kmh * 0.621371)
                            else:
                                cc.wind_speed = 0

                            wind_gust_kmh = obs_props.get("windGust", {}).get("value")
                            if wind_gust_kmh is not None:
                                cc.wind_gust = int(wind_gust_kmh * 0.621371)
                            else:
                                cc.wind_gust = None

                            wind_dir_deg = obs_props.get("windDirection", {}).get(
                                "value"
                            )
                            if wind_dir_deg is not None:
                                deg = float(wind_dir_deg)
                                directions = [
                                    "N",
                                    "NE",
                                    "E",
                                    "SE",
                                    "S",
                                    "SW",
                                    "W",
                                    "NW",
                                ]
                                cc.wind_direction = directions[
                                    int((deg + 22.5) / 45) % 8
                                ]
                            else:
                                cc.wind_direction = ""

                            timestamp = obs_props.get("timestamp")
                            if timestamp:
                                cc.last_observation_time = datetime.fromisoformat(
                                    timestamp.replace("Z", "+00:00")
                                )
                            elif cc.last_observation_time is None:
                                cc.last_observation_time = timezone.now()

                            cc.save()
            except Exception as e:
                print(f"Warning: Could not fetch current conditions: {str(e)}")

            # Get forecast URL
            forecast_url = properties.get("forecast")
            if forecast_url:
                forecast_response = requests.get(
                    forecast_url, headers=headers, timeout=10
                )
                forecast_response.raise_for_status()
                forecast_data = forecast_response.json()

                periods = forecast_data.get("properties", {}).get("periods", [])

                # Parse periods into daily forecast objects
                for period in periods[:14]:
                    raw_start = datetime.fromisoformat(
                        period["startTime"].replace("Z", "+00:00")
                    )
                    local_start = raw_start.astimezone(timezone.get_current_timezone())
                    raw_end = datetime.fromisoformat(
                        period["endTime"].replace("Z", "+00:00")
                    )
                    local_end = raw_end.astimezone(timezone.get_current_timezone())

                    # For night periods, associate with the same day (not the next day)
                    # E.g., "Friday Night" should be associated with Friday, not Saturday
                    is_daytime = period.get("isDaytime", True)
                    if is_daytime:
                        forecast_date = local_start.date()
                    else:
                        # Night period: if it starts late in the day (e.g., 6 PM), use that date
                        # Otherwise if it starts after midnight, subtract one day
                        if local_start.hour >= 18:  # Starts at or after 6 PM
                            forecast_date = local_start.date()
                        else:
                            forecast_date = (local_start - timedelta(days=1)).date()

                    daily_forecasts.append(
                        SimpleNamespace(
                            forecast_date=forecast_date,
                            period_start=local_start,
                            period_end=local_end,
                            is_daytime=period.get("isDaytime", True),
                            temperature=period.get("temperature"),
                            temperature_unit=period.get("temperatureUnit", "F"),
                            wind_speed=self._parse_wind_speed(
                                period.get("windSpeed", "")
                            ),
                            wind_direction=period.get("windDirection", ""),
                            short_forecast=period.get("shortForecast", ""),
                            detailed_forecast=period.get("detailedForecast", ""),
                            precipitation_probability=period.get(
                                "probabilityOfPrecipitation", {}
                            ).get("value"),
                        )
                    )

            # Fetch alerts
            try:
                alerts_url = f"https://api.weather.gov/alerts/active?point={latitude},{longitude}"
                alerts_response = requests.get(alerts_url, headers=headers, timeout=10)
                alerts_response.raise_for_status()
                alerts_data = alerts_response.json()

                features = alerts_data.get("features", [])
                for feature in features:
                    props = feature.get("properties", {})
                    onset = props.get("onset")
                    expires = props.get("expires")

                    if onset:
                        onset = datetime.fromisoformat(onset.replace("Z", "+00:00"))
                    if expires:
                        expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))

                    active_alerts.append(
                        SimpleNamespace(
                            event=props.get("event", "Unknown"),
                            headline=props.get("headline", ""),
                            description=props.get("description", ""),
                            severity=props.get("severity", "unknown").lower(),
                            urgency=props.get("urgency", "unknown").lower(),
                            onset=onset,
                            expires=expires,
                        )
                    )
            except Exception as e:
                print(f"Warning: Failed to fetch alerts: {str(e)}")

            location.last_forecast_update = timezone.now()

        except Exception as e:
            print(f"Warning: Failed to fetch forecast data: {str(e)}")

        # Group daily forecasts by date
        grouped_forecasts = []
        if daily_forecasts:
            for date, periods in groupby(
                daily_forecasts, key=lambda f: f.forecast_date
            ):
                periods_list = list(periods)
                day_forecast = next((p for p in periods_list if p.is_daytime), None)
                night_forecast = next(
                    (p for p in periods_list if not p.is_daytime), None
                )
                grouped_forecasts.append(
                    {"date": date, "day": day_forecast, "night": night_forecast}
                )

        context["location"] = location
        context["latitude"] = lat
        context["longitude"] = lon
        context["page_title"] = f"Temporary Location - {lat}, {lon}"
        context["daily_forecasts"] = grouped_forecasts
        context["hourly_forecasts"] = hourly_forecasts
        context["hourly_forecasts_json"] = "[]"
        context["has_custom_daily"] = False
        context["has_custom_hourly"] = False
        context["active_alerts"] = active_alerts
        context["is_temp_location"] = True

        # Add locations list for selector
        try:
            location_ids = self.request.session.get("location_ids", [])
            locations_qs = Location.objects.filter(is_active=True)
            if location_ids:
                locations_qs = locations_qs.filter(id__in=location_ids)
            context["locations"] = locations_qs.order_by(
                "-is_current_location", "display_order", "name"
            )
        except Exception:
            context["locations"] = Location.objects.none()

        return context

    @staticmethod
    def _parse_wind_speed(wind_speed_str):
        """Extract numeric wind speed from string like '10 to 15 mph' or '10 mph'."""
        if not wind_speed_str:
            return 0
        import re

        numbers = re.findall(r"\d+", str(wind_speed_str))
        if numbers:
            if len(numbers) > 1:
                return int((int(numbers[0]) + int(numbers[1])) / 2)
            return int(numbers[0])
        return 0


class ModelDetailView(TemplateView):
    """Detailed view for a single weather model with extended variables."""

    template_name = "weather/model_detail.html"

    # Supported model configurations (subset, HRDPS removed)
    MODEL_CONFIGS = {
        # max_days chosen to reflect typical availability from Open-Meteo for each model
        "GFS": {
            "url": "https://api.open-meteo.com/v1/gfs",
            "models": None,
            "max_days": 16,
        },
        "ICON": {
            "url": "https://api.open-meteo.com/v1/dwd-icon",
            "models": None,
            "max_days": 7,
        },
        "ECMWF": {
            "url": "https://api.open-meteo.com/v1/ecmwf",
            "models": None,
            "max_days": 10,
        },
        "GEM": {
            "url": "https://api.open-meteo.com/v1/gem",
            "models": None,
            "max_days": 10,
        },
        "HRRR": {
            "url": "https://api.open-meteo.com/v1/forecast",
            "models": "ncep_hrrr_conus",
            "max_days": 2,
        },
        "NAM": {
            "url": "https://api.open-meteo.com/v1/forecast",
            "models": "ncep_nam_conus",
            "max_days": 3,
        },
        "RGEM": {
            "url": "https://api.open-meteo.com/v1/gem",
            "models": "cmc_gem_rdps",
            "max_days": 2,
        },
        "NBM": {
            "url": "https://api.open-meteo.com/v1/gfs",
            "models": "ncep_nbm_conus",
            "max_days": 11,
        },
    }

    EXTENDED_HOURLY = (
        # Temperatures (2m + dense sampling 975–500 hPa every 25 mb, keeping existing levels)
        "temperature_2m,"
        "temperature_975hPa,temperature_950hPa,temperature_925hPa,temperature_900hPa,temperature_875hPa,temperature_850hPa,temperature_825hPa,"
        "temperature_800hPa,temperature_775hPa,temperature_750hPa,temperature_725hPa,temperature_700hPa,temperature_675hPa,"
        "temperature_650hPa,temperature_625hPa,temperature_600hPa,temperature_575hPa,temperature_550hPa,temperature_525hPa,"
        "temperature_500hPa,temperature_400hPa,apparent_temperature,"
        # Humidity
        "relativehumidity_2m,relativehumidity_925hPa,relativehumidity_850hPa,relativehumidity_700hPa,relativehumidity_500hPa,"
        # Other surface / diagnostic fields
        "dewpoint_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
        # Precipitation & cloud
        "precipitation,snowfall,cloudcover,pressure_msl,"
        # Precip type probabilities (available for GFS/HRRR/NBM; inferred for others via _classify_precip_types)
        "rain_probability,snowfall_probability,freezing_rain_probability,ice_pellets_probability"
    )

    @staticmethod
    def _classify_precip_types(hourly: dict) -> tuple[list[str], list[float]]:
        """
        Infer precip phase and snow-to-liquid ratio per hour using surface and low/mid-level temps.

        Returns:
            (types, slrs) where:
            - types: list of precip phases ("snow", "sleet", "freezing_rain", "rain", "unknown")
            - slrs: list of snow-to-liquid ratios (1.0 for sleet, <1.0 for freezing rain, 5-30 for snow)
        """

        def val(seq, idx):
            if seq is None:
                return None
            if idx < len(seq):
                try:
                    return float(seq[idx])
                except Exception:
                    return None
            return None

        temps = hourly.get("temperature_2m") or []
        t975 = hourly.get("temperature_975hPa") or []
        t950 = hourly.get("temperature_950hPa") or []
        t925 = hourly.get("temperature_925hPa") or []
        t900 = hourly.get("temperature_900hPa") or []
        t875 = hourly.get("temperature_875hPa") or []
        t850 = hourly.get("temperature_850hPa") or []
        t825 = hourly.get("temperature_825hPa") or []
        t800 = hourly.get("temperature_800hPa") or []
        t775 = hourly.get("temperature_775hPa") or []
        t750 = hourly.get("temperature_750hPa") or []
        t725 = hourly.get("temperature_725hPa") or []
        t700 = hourly.get("temperature_700hPa") or []
        t675 = hourly.get("temperature_675hPa") or []
        t650 = hourly.get("temperature_650hPa") or []
        t625 = hourly.get("temperature_625hPa") or []
        t600 = hourly.get("temperature_600hPa") or []
        t575 = hourly.get("temperature_575hPa") or []
        t550 = hourly.get("temperature_550hPa") or []
        t525 = hourly.get("temperature_525hPa") or []
        t500 = hourly.get("temperature_500hPa") or []
        snowfall = hourly.get("snowfall") or []
        precip = hourly.get("precipitation") or []

        n = max(
            len(temps),
            len(t975),
            len(t950),
            len(t925),
            len(t900),
            len(t875),
            len(t850),
            len(t825),
            len(t800),
            len(t775),
            len(t750),
            len(t725),
            len(t700),
            len(t675),
            len(t650),
            len(t625),
            len(t600),
            len(t575),
            len(t550),
            len(t525),
            len(t500),
            len(snowfall),
            len(precip),
        )
        if n == 0:
            return [], []

        freeze_c = 0.0
        surface_slush_c = 2.0  # 2°C threshold for wet snow
        warm_nose_min_c = (
            1.0  # warm nose by definition is where temp is > 1°C (strictly greater)
        )

        # Helper: Fahrenheit to Celsius for SLR/dendritic logic
        def f_to_c(v: float | None) -> float | None:
            if v is None:
                return None
            return (v - 32.0) * (5.0 / 9.0)

        # Helper to estimate SLR for snow with DGZ thickness, dendritic factor, and surface adjustment
        def snow_slr(
            dendritic_c: float | None,
            ts: float | None,
            warmest_c: float | None,
            profile_levels: list[tuple[float, float]],
        ) -> float:
            # Base SLR logic: if good dendritic zone and cold surface, use higher base despite warm mid-layer
            base_slr = 12.0  # default

            # Check for strong dendritic conditions: optimal DGZ temp + cold surface
            strong_dendritic = (
                dendritic_c is not None
                and -16 <= dendritic_c <= -11
                and ts is not None
                and ts < -2.0
            )

            if warmest_c is not None:
                if warmest_c < -18:
                    base_slr = 30.0
                elif warmest_c < -12:
                    base_slr = 22.0
                elif warmest_c < -5:
                    # If strong dendritic + cold surface, use 18 instead of 12
                    base_slr = 18.0 if strong_dendritic else 12.0
                else:
                    # If strong dendritic + cold surface, use 12 instead of 8
                    base_slr = 12.0 if strong_dendritic else 8.0

            # Dendritic factor from ~550 hPa temp (multiplicative)
            dendritic_factor = 1.0
            if dendritic_c is not None:
                if -16 <= dendritic_c <= -11:
                    dendritic_factor = 1.10  # strong DGZ near optimal temp
                elif (-20 <= dendritic_c < -16) or (-11 < dendritic_c <= -8):
                    dendritic_factor = 1.07  # moderate
                else:
                    dendritic_factor = 1.03  # weak but present

            # Compute DGZ thickness between -18°C and -12°C using a 5 hPa grid
            dgz_thickness = 0.0
            try:
                profile_sorted = sorted(
                    profile_levels, key=lambda x: x[0], reverse=True
                )

                def interp_temp_local(p_target: float) -> float | None:
                    for idx in range(len(profile_sorted) - 1):
                        p1, t1 = profile_sorted[idx]
                        p2, t2 = profile_sorted[idx + 1]
                        if (p1 >= p_target >= p2) or (p2 >= p_target >= p1):
                            if p1 == p2:
                                return t1
                            frac = (p_target - p2) / (p1 - p2)
                            return t2 + (t1 - t2) * frac
                    return profile_sorted[-1][1] if profile_sorted else None

                if profile_sorted:
                    max_p = max(p for p, _ in profile_sorted)
                    min_p = min(p for p, _ in profile_sorted)
                    step_hpa_local = 5.0
                    p_cursor = max_p
                    while p_cursor > min_p:
                        p_next = max(p_cursor - step_hpa_local, min_p)
                        p_mid = (p_cursor + p_next) / 2.0
                        t_mid_c = interp_temp_local(p_mid)
                        if t_mid_c is not None and -18.0 <= t_mid_c <= -12.0:
                            dgz_thickness += abs(p_cursor - p_next)
                        p_cursor = p_next
            except Exception:
                dgz_thickness = 0.0

            # DGZ thickness factor: up to +25% boost for deep DGZ (cap at 150 hPa)
            dgz_factor = 1.0 + min(dgz_thickness, 150.0) / 600.0

            # Surface wet-snow penalty
            surface_factor = 1.0
            if ts is not None:
                if ts >= 3.0:
                    surface_factor = 0.75
                elif ts >= -0.6:
                    surface_factor = 0.90

            slr_calc = base_slr * dendritic_factor * dgz_factor * surface_factor
            # Clamp to reasonable bounds
            return max(6.0, min(35.0, slr_calc))

        types: list[str] = []
        slrs: list[float] = []

        for i in range(n):
            # snowfall value (sf) not needed - using inferred classification
            ts_f = val(temps, i)
            t975v_f = val(t975, i)
            t950v_f = val(t950, i)
            t925v_f = val(t925, i)
            t900v_f = val(t900, i)
            t875v_f = val(t875, i)
            t850v_f = val(t850, i)
            t825v_f = val(t825, i)
            t800v_f = val(t800, i)
            t775v_f = val(t775, i)
            t750v_f = val(t750, i)
            t725v_f = val(t725, i)
            t700v_f = val(t700, i)
            t675v_f = val(t675, i)
            t650v_f = val(t650, i)
            t625v_f = val(t625, i)
            t600v_f = val(t600, i)
            t575v_f = val(t575, i)
            t550v_f = val(t550, i)
            t525v_f = val(t525, i)
            t500v_f = val(t500, i)

            # Convert all temps to Celsius immediately
            ts = f_to_c(ts_f)
            t975v = f_to_c(t975v_f)
            t950v = f_to_c(t950v_f)
            t925v = f_to_c(t925v_f)
            t900v = f_to_c(t900v_f)
            t875v = f_to_c(t875v_f)
            t850v = f_to_c(t850v_f)
            t825v = f_to_c(t825v_f)
            t800v = f_to_c(t800v_f)
            t775v = f_to_c(t775v_f)
            t750v = f_to_c(t750v_f)
            t725v = f_to_c(t725v_f)
            t700v = f_to_c(t700v_f)
            t675v = f_to_c(t675v_f)
            t650v = f_to_c(t650v_f)
            t625v = f_to_c(t625v_f)
            t600v = f_to_c(t600v_f)
            t575v = f_to_c(t575v_f)
            t550v = f_to_c(t550v_f)
            t525v = f_to_c(t525v_f)
            t500v = f_to_c(t500v_f)

            # If 550 hPa not available, interpolate from nearby levels
            if t550v is None:
                available_temps = [
                    (975, t975v),
                    (950, t950v),
                    (925, t925v),
                    (900, t900v),
                    (875, t875v),
                    (850, t850v),
                    (825, t825v),
                    (800, t800v),
                    (775, t775v),
                    (750, t750v),
                    (725, t725v),
                    (700, t700v),
                    (675, t675v),
                    (650, t650v),
                    (625, t625v),
                    (600, t600v),
                    (575, t575v),
                    (525, t525v),
                    (500, t500v),
                ]
                available_temps = [(p, t) for p, t in available_temps if t is not None]
                if available_temps:
                    for idx in range(len(available_temps) - 1):
                        p1, t1 = available_temps[idx]
                        p2, t2 = available_temps[idx + 1]
                        if (p1 >= 550 >= p2) or (p2 >= 550 >= p1):
                            frac = (550.0 - p2) / (p1 - p2)
                            t550v = t2 + (t1 - t2) * frac
                            break

            # Warmest temperature in column (similar to Kuchera method) in °C
            warmest_c = max(
                [
                    v
                    for v in (
                        ts,
                        t975v,
                        t950v,
                        t925v,
                        t900v,
                        t875v,
                        t850v,
                        t825v,
                        t800v,
                        t775v,
                        t750v,
                        t725v,
                        t700v,
                        t675v,
                        t650v,
                        t625v,
                        t600v,
                        t575v,
                        t550v,
                        t525v,
                        t500v,
                    )
                    if v is not None
                ],
                default=None,
            )

            # Build profile with surface and key levels
            profile_levels: list[tuple[float, float]] = []
            if ts is not None:
                profile_levels.append((1013.25, ts))
            pressure_levels = [
                (975, t975v),
                (950, t950v),
                (925, t925v),
                (900, t900v),
                (875, t875v),
                (850, t850v),
                (825, t825v),
                (800, t800v),
                (775, t775v),
                (750, t750v),
                (725, t725v),
                (700, t700v),
                (675, t675v),
                (650, t650v),
            ]
            valid_levels = [(p, t) for p, t in pressure_levels if t is not None]
            profile_levels.extend(valid_levels)

            # Dendritic growth zone temp (around 550 hPa)
            dendritic_c = t550v

            if ts is None:
                types.append("unknown")
                slrs.append(1.0)
                continue

            if not profile_levels:
                types.append("unknown")
                slrs.append(1.0)
                continue

            ptype = "unknown"
            slr = 1.0

            # If a warm layer exists, honor it before snowfall hints to avoid false snow
            has_warm_nose = warmest_c is not None and warmest_c > warm_nose_min_c

            if not has_warm_nose:
                ptype = "snow"
                slr = snow_slr(dendritic_c, ts, warmest_c, profile_levels)
                types.append(ptype)
                slrs.append(slr)
                continue

            # If surface is above the slushy cutoff, default to rain despite aloft structure
            if ts > surface_slush_c:
                types.append("rain")
                slrs.append(1.0)
                continue

            # Build a finely interpolated profile (5 hPa spacing) to integrate warm vs cold area
            profile_sorted = sorted(profile_levels, key=lambda x: x[0], reverse=True)

            def interp_temp_helper(
                profile_sorted: list[tuple[float, float]], p_target: float
            ) -> float:
                for idx in range(len(profile_sorted) - 1):
                    p1, t1 = profile_sorted[idx]
                    p2, t2 = profile_sorted[idx + 1]
                    if (p1 >= p_target >= p2) or (p2 >= p_target >= p1):
                        if p1 == p2:
                            return t1
                        frac = (p_target - p2) / (p1 - p2)
                        return t2 + (t1 - t2) * frac
                return profile_sorted[-1][1]

            max_p = max(p for p, _ in profile_sorted)
            min_p = min(p for p, _ in profile_sorted)
            step_hpa = 5.0
            grid_pressures: list[float] = []
            p_cursor = max_p
            while p_cursor > min_p:
                grid_pressures.append(p_cursor)
                p_cursor -= step_hpa
            grid_pressures.append(min_p)

            grid_temps = [interp_temp_helper(profile_sorted, p) for p in grid_pressures]

            warm_indices = [
                i for i, t in enumerate(grid_temps) if t is not None and t > freeze_c
            ]
            if not warm_indices:
                ptype = "snow"
                slr = snow_slr(dendritic_c, ts, warmest_c, profile_levels)
                types.append(ptype)
                slrs.append(slr)
                continue

            warm_band_bottom = max(grid_pressures[i] for i in warm_indices)

            warm_area_total = 0.0
            cold_area_total = 0.0
            cold_layer_depth_mb = 0.0
            warmest_in_warm_nose = None
            coldest_in_cold_layer = None
            has_thick_cold_section = False  # Track if >50mb of <-5°C exists

            # Helper to integrate temperature above/below freezing across a segment (all in Celsius)
            def segment_areas(t1: float, t2: float, dp: float) -> tuple[float, float]:
                warm_area = 0.0
                cold_area = 0.0
                if t1 >= freeze_c and t2 >= freeze_c:
                    warm_area = ((t1 - freeze_c) + (t2 - freeze_c)) / 2.0 * dp
                elif t1 <= freeze_c and t2 <= freeze_c:
                    cold_area = (abs(t1 - freeze_c) + abs(t2 - freeze_c)) / 2.0 * dp
                else:
                    frac = (freeze_c - t1) / (t2 - t1) if t1 != t2 else 0.5
                    dp1 = abs(dp * frac)
                    dp2 = abs(dp - dp1)
                    if t1 > freeze_c:
                        warm_area = ((t1 - freeze_c) + 0.0) / 2.0 * dp1
                        cold_area = (abs(t2 - freeze_c) + 0.0) / 2.0 * dp2
                    else:
                        cold_area = (abs(t1 - freeze_c) + 0.0) / 2.0 * dp1
                        warm_area = ((t2 - freeze_c) + 0.0) / 2.0 * dp2
                return warm_area, cold_area

            # Track continuous cold sections for refreeze potential
            current_cold_depth = 0.0

            for idx in range(len(grid_pressures) - 1):
                p1 = grid_pressures[idx]
                p2 = grid_pressures[idx + 1]
                t1 = grid_temps[idx]
                t2 = grid_temps[idx + 1]
                if t1 is None or t2 is None:
                    continue
                dp = abs(p2 - p1)
                w_area, c_area = segment_areas(t1, t2, dp)
                warm_area_total += w_area
                if min(p1, p2) >= warm_band_bottom:
                    cold_area_total += c_area
                    cold_layer_depth_mb += dp

                    # Track continuous sections colder than -5°C for refreeze potential
                    if t1 < -5.0 and t2 < -5.0:
                        current_cold_depth += dp
                        if current_cold_depth > 50.0:
                            has_thick_cold_section = True
                    else:
                        current_cold_depth = 0.0

                # Track extremes in warm band (above freeze)
                if min(p1, p2) < warm_band_bottom:  # within warm band
                    if t1 > freeze_c and (
                        warmest_in_warm_nose is None or t1 > warmest_in_warm_nose
                    ):
                        warmest_in_warm_nose = t1
                    if t2 > freeze_c and (
                        warmest_in_warm_nose is None or t2 > warmest_in_warm_nose
                    ):
                        warmest_in_warm_nose = t2

                # Track extremes in cold layer (below warm band, below freeze)
                if min(p1, p2) >= warm_band_bottom:
                    if t1 <= freeze_c and (
                        coldest_in_cold_layer is None or t1 < coldest_in_cold_layer
                    ):
                        coldest_in_cold_layer = t1
                    if t2 <= freeze_c and (
                        coldest_in_cold_layer is None or t2 < coldest_in_cold_layer
                    ):
                        coldest_in_cold_layer = t2

            # Hybrid classification: area-based + temperature-based
            # Thresholds: warm nose needs to be somewhat strong to produce freezing rain
            # Cold layer needs to be moderately cold to refreeze sleet

            area_ratio_cold_to_warm = cold_area_total / max(warm_area_total, 1.0)
            area_ratio_warm_to_cold = warm_area_total / max(cold_area_total, 1.0)

            # Default to area-based decision
            if warm_area_total > cold_area_total:
                ptype = "freezing_rain"
                slr = min(1.0, 2.0 / area_ratio_warm_to_cold)
            else:
                ptype = "sleet"
                slr = 1.5 + min(area_ratio_cold_to_warm, 2.5)

            # Freezing rain requires surface at or below 0°C to freeze on contact
            # If surface is too warm, demote to sleet (if cold layer exists) or rain
            if ptype == "freezing_rain" and ts is not None and ts > 0.0:
                if cold_area_total > 0 and cold_layer_depth_mb > 20.0:
                    # Sufficient cold layer exists below warm nose - classify as sleet
                    ptype = "sleet"
                    slr = 1.5 + min(area_ratio_cold_to_warm, 2.5)
                else:
                    # No significant refreezing layer - just rain
                    ptype = "rain"
                    slr = 1.0

            # Refine with temperature logic
            # First: if there's a thick cold section (>50mb of <-5°C), demote freezing rain to sleet (sufficient refreeze)
            if ptype == "freezing_rain" and has_thick_cold_section:
                ptype = "sleet"
                slr = 1.5 + min(area_ratio_cold_to_warm, 2.5)

            # Second: if cold layer is very weak (> -6°C / 21°F) or thick but marginal (>50mb but warmer than -5°C), promote to freezing rain
            # BUT: only if there's no thick cold section (already checked above) AND surface is cold enough (≤0°C)
            if (
                ptype == "sleet"
                and coldest_in_cold_layer is not None
                and not has_thick_cold_section
                and ts is not None
                and ts <= 0.0  # Surface must be at or below 0°C for freezing rain
            ):
                weak_cold_layer = coldest_in_cold_layer > -6.0
                thick_but_marginal = (
                    cold_layer_depth_mb > 50.0 and coldest_in_cold_layer > -5.0
                )
                if (
                    (weak_cold_layer or thick_but_marginal)
                    and warmest_in_warm_nose is not None
                    and warmest_in_warm_nose > 1.0
                ):
                    ptype = "freezing_rain"
                    slr = min(1.0, 2.0 / max(area_ratio_warm_to_cold, 0.5))

            # Refine SLR scaling with temperature extremes
            if ptype == "freezing_rain" and warmest_in_warm_nose is not None:
                # Sliding scale for liquid fraction (SLR) between 0.2:1 (very wet) and 1.0:1 (cold/freezing mix)
                # Inputs: warmest_in_warm_nose (>1°C by definition) and near-surface temperature ts
                if ts > -1.0 or warmest_in_warm_nose >= 6.0:
                    slr = 0.2  # very wet, pure liquid end
                elif warmest_in_warm_nose <= 1.0:
                    slr = 1.0  # coldest freezing rain / sleet-like mix
                else:
                    # Linear interpolation from 1.0 at 1°C down to 0.2 at 6°C
                    frac = (warmest_in_warm_nose - 1.0) / (6.0 - 1.0)
                    slr = max(0.2, min(1.0, 1.0 - frac * (1.0 - 0.2)))

                # Boost SLR if there's a strong refreezing layer below despite warm mid-layer
                # More refreezing → higher SLR (thicker accretion)
                if coldest_in_cold_layer is not None:
                    if coldest_in_cold_layer < -10.0:
                        slr = min(1.0, slr * 1.5)  # strong refreezing boost
                    elif coldest_in_cold_layer < -5.0:
                        slr = min(1.0, slr * 1.25)  # moderate refreezing boost

            if ptype == "sleet" and coldest_in_cold_layer is not None:
                # Colder cold layer → more complete refreezing → higher SLR (drier sleet)
                # Warmer cold layer → incomplete refreezing → lower SLR (wetter sleet)
                if coldest_in_cold_layer < -15.0:
                    slr = min(4.0, slr * 1.15)  # very dry sleet
                elif coldest_in_cold_layer < -10.0:
                    slr = min(4.0, slr * 1.05)  # dry sleet
                else:
                    slr = max(1.5, slr * 0.95)  # wet sleet

            # Borderline sleet/snow transition: if warm layer is marginal, blend SLR toward snow
            # Check if this is close to being snow (weak/shallow warm layer)
            if (
                ptype == "sleet"
                and warmest_in_warm_nose is not None
                and 1.0 < warmest_in_warm_nose <= 3.0
            ):
                # Calculate snow SLR for comparison
                snow_slr_value = snow_slr(dendritic_c, ts, warmest_c, profile_levels)
                # Blend factor: closer to 1°C = more snow-like, closer to 3°C = more sleet-like
                # Linear interpolation: at 1°C use 70% snow SLR, at 3°C use 0% snow SLR
                blend_factor = (3.0 - warmest_in_warm_nose) / 2.0  # ranges 0.0 to 1.0
                blend_factor = max(0.0, min(0.7, blend_factor))  # clamp to 0-70%
                # Interpolate between current sleet SLR and snow SLR
                slr = slr * (1.0 - blend_factor) + snow_slr_value * blend_factor

            # Borderline sleet/freezing rain transition: blend when area ratios are close
            if ptype == "freezing_rain" and area_ratio_warm_to_cold < 1.5:
                # Borderline: warm area only slightly dominates (ratio 1.0-1.5)
                # Sleet SLR would be ~1.5-4.0, freezing rain SLR ~0.2-1.0
                # Blend toward sleet as warm dominance decreases
                sleet_slr = 1.5 + min(area_ratio_cold_to_warm, 2.5)
                # At ratio 1.0 (equal areas): 50% sleet SLR, at 1.5: 0% sleet SLR
                blend_factor = (
                    1.5 - area_ratio_warm_to_cold
                ) / 0.5  # ranges 0.0 to 1.0
                blend_factor = max(0.0, min(0.5, blend_factor))  # clamp to 0-50%
                slr = slr * (1.0 - blend_factor) + sleet_slr * blend_factor
            elif ptype == "sleet" and area_ratio_cold_to_warm < 1.5:
                # Borderline: cold area only slightly dominates (ratio 1.0-1.5)
                # Blend toward freezing rain as cold dominance decreases
                frzr_slr = min(1.0, 2.0 / area_ratio_warm_to_cold)
                # At ratio 1.0 (equal areas): 50% freezing rain SLR, at 1.5: 0% freezing rain SLR
                blend_factor = (
                    1.5 - area_ratio_cold_to_warm
                ) / 0.5  # ranges 0.0 to 1.0
                blend_factor = max(0.0, min(0.5, blend_factor))  # clamp to 0-50%
                slr = slr * (1.0 - blend_factor) + frzr_slr * blend_factor

            types.append(ptype)
            slrs.append(slr)

        return types, slrs

    @staticmethod
    def aggregate_precip_by_6hour(hourly: dict, times: list[str]) -> dict:
        """
        Aggregate hourly precipitation by type into 6-hour periods with actual accumulation.

        Multiplies precipitation by SLR (from _classify_precip_types) to get actual depth accumulation.
        Uses type-based SLR defaults if SLR values missing.

        Args:
            hourly: dict with keys like 'precipitation', 'precip_type', 'snow_liquid_ratio', 'time'
            times: list of ISO datetime strings (e.g., forecast period end times)

        Returns:
            dict mapping each time to {'snow': X_mm, 'sleet': Y_mm, 'freezing_rain': Z_mm, 'rain': W_mm, 'total': T_mm}
            where values are actual depth accumulation (precip_mm × SLR)
        """
        precips = hourly.get("precipitation") or []
        precip_types = hourly.get("precip_type") or []
        slrs = hourly.get("snow_liquid_ratio") or []
        times_list = hourly.get("time") or []

        if not precips or not times or not precip_types:
            return {}

        from datetime import datetime

        # SLR defaults by precip type (from _classify_precip_types logic)
        default_slr = {
            "snow": 10.0,  # 10:1 snow
            "sleet": 2.5,  # 2.5:1 sleet
            "freezing_rain": 0.35,  # 0.35:1 freezing rain
            "rain": 1.0,  # Rain is 1:1 by definition
        }

        aggregated = {}

        for time_str in times:
            try:
                # Parse the target forecast time
                target_time = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            # Sum precip by type for the 6 hours LEADING UP TO this time
            # Multiply each hour by its calculated SLR to get actual accumulation depth
            snow_total = 0.0
            sleet_total = 0.0
            freezing_rain_total = 0.0
            rain_total = 0.0

            for i, hour_time_str in enumerate(times_list):
                try:
                    hour_time = datetime.fromisoformat(
                        hour_time_str.replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    continue

                # Include hours from target_time - 6 hours to target_time (inclusive of target)
                if (
                    hour_time <= target_time
                    and (target_time - hour_time).total_seconds() < 21600
                ):  # 6 hours in seconds
                    precip_val = precips[i] if i < len(precips) else 0.0
                    precip_type = precip_types[i] if i < len(precip_types) else "rain"

                    # Use calculated SLR from _classify_precip_types, or default by type
                    slr = (
                        slrs[i]
                        if i < len(slrs) and slrs[i] > 0
                        else default_slr.get(precip_type, 1.0)
                    )

                    if precip_val and precip_val > 0:
                        # Multiply by SLR to get actual accumulation depth
                        actual_accumulation = precip_val * slr

                        if precip_type == "snow":
                            snow_total += actual_accumulation
                        elif precip_type == "sleet":
                            sleet_total += actual_accumulation
                        elif precip_type == "freezing_rain":
                            freezing_rain_total += actual_accumulation
                        else:  # rain or unknown
                            rain_total += actual_accumulation

            total = snow_total + sleet_total + freezing_rain_total + rain_total
            aggregated[time_str] = {
                "snow": round(snow_total, 2),
                "sleet": round(sleet_total, 2),
                "freezing_rain": round(freezing_rain_total, 2),
                "rain": round(rain_total, 2),
                "total": round(total, 2),
            }

        return aggregated

    def get_context_data(self, **kwargs):
        import time

        fetch_start = time.time()
        context = super().get_context_data(**kwargs)
        request = self.request
        model_name = kwargs.get("model_name", "").upper()
        config = self.MODEL_CONFIGS.get(model_name)
        if not config:
            from django.http import Http404

            raise Http404("Unknown model")

        # Acquire lat/lon parameters; fallback to first active location if missing
        lat = request.GET.get("latitude")
        lon = request.GET.get("longitude")
        # Determine requested forecast_days; default to model's max_days if not provided
        config_max_days = config.get("max_days", 5)
        forecast_days_param = request.GET.get("forecast_days")
        if forecast_days_param is None:
            forecast_days = str(config_max_days)
        else:
            # Clamp to model maximum
            try:
                req_days_int = int(forecast_days_param)
                if req_days_int < 1:
                    req_days_int = 1
                if req_days_int > config_max_days:
                    req_days_int = config_max_days
                forecast_days = str(req_days_int)
            except ValueError:
                forecast_days = str(config_max_days)
        # Ensemble selection (for GFS/GEFS via NOMADS)
        ensemble = request.GET.get("ens", "det").lower()
        valid_ens = {"det", "control", "mean"} | {f"p{i:02d}" for i in range(1, 31)}
        if ensemble not in valid_ens:
            ensemble = "det"
        location_obj = None
        if not (lat and lon):
            location_ids = request.session.get("location_ids", [])
            location_obj = (
                Location.objects.filter(is_active=True, id__in=location_ids)
                .order_by("-is_current_location", "display_order", "name")
                .first()
            )
            if location_obj:
                lat = location_obj.latitude
                lon = location_obj.longitude

        data = None
        error = None
        run_time = None
        model_source = "Open-Meteo"
        cycle = None
        forecast_hours = None
        if lat and lon:
            from datetime import datetime

            import requests

            from .noaa_nomads import fetch_gfs_nomads
            from .noaa_service import NOAA_MODELS, fetch_noaa_forecast

            # Temporary: rely solely on Open-Meteo for all models (skip NOMADS/NOAA)
            only_open_meteo = True
            # Try cache first to avoid repeated slow fetches
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except Exception:
                lat_f = lat
                lon_f = lon
            cache_key = f"model_detail:v4:{model_name}:{ensemble}:{lat_f}:{lon_f}:days:{forecast_days}"
            cached = cache.get(cache_key)
            if cached is not None:
                data = cached
                # Extract metadata from cached data if present
                model_source = data.get("model_source", "Open-Meteo")
                cycle = data.get("cycle")
                # Extract model run time from first forecast hour (hour 0 = initialization)
                # Times from API are in local timezone, convert to UTC to get model cycle
                if data.get("hourly", {}).get("time"):
                    import pytz

                    first_time = data["hourly"]["time"][0]
                    # Parse the local time
                    first_dt = datetime.fromisoformat(str(first_time).replace("Z", ""))
                    # Get timezone from API response
                    tz_str = data.get("timezone", "America/Chicago")
                    local_tz = pytz.timezone(tz_str)
                    # Localize to the proper timezone, then convert to UTC
                    if first_dt.tzinfo is None:
                        first_dt_local = local_tz.localize(first_dt)
                    else:
                        first_dt_local = first_dt
                    run_time = first_dt_local.astimezone(dt_timezone.utc)
                logger.info(
                    f"ModelDetailView cache hit for {cache_key} (source={model_source}, cycle={cycle})"
                )

            # Prefer NOMADS GRIB for GFS deterministic/ensemble to get full fields
            # Use 45s timeout to allow fetching many forecast hours despite 404s
            if not only_open_meteo and not data and model_name == "GFS":
                try:
                    nomads_start = time.time()
                    logger.info(
                        f"Attempting NOMADS fetch for GFS {ensemble} at {lat},{lon}"
                    )
                    nomads_data = fetch_gfs_nomads(
                        float(lat), float(lon), ensemble, timeout=45
                    )
                    if nomads_data:
                        data = nomads_data
                        model_source = nomads_data.get("model_source", "NOAA-NOMADS")
                        cycle = nomads_data.get("cycle")
                        forecast_hours = nomads_data.get("forecast_hours")
                        # Ensure metadata is in the data dict for caching
                        data["model_source"] = model_source
                        data["cycle"] = cycle
                        nomads_elapsed = time.time() - nomads_start
                        logger.info(
                            f"NOMADS successful in {nomads_elapsed:.2f}s: {len(data.get('hourly', {}).get('time', []))} time points"
                        )
                        # NOMADS returns UTC times, so run_time is already in UTC
                        if data.get("hourly", {}).get("time"):
                            first_time = data["hourly"]["time"][0]
                            run_time = datetime.fromisoformat(
                                str(first_time).replace("Z", "+00:00")
                            )
                        # Cache will be set after precipitation classification
                    else:
                        logger.warning(f"NOMADS returned None for GFS {ensemble}")
                except Exception as exc:  # noqa: BLE001
                    nomads_elapsed = time.time() - nomads_start
                    logger.warning(
                        f"NOMADS fetch failed in {nomads_elapsed:.2f}s for {model_name} ({ensemble}), falling back: {exc}"
                    )

            # For GFS: if NOMADS failed, prefer Open-Meteo next for richer fields
            if not data and model_name == "GFS":
                try:
                    om_start = time.time()
                    params = {
                        "latitude": lat,
                        "longitude": lon,
                        "hourly": self.EXTENDED_HOURLY,
                        "temperature_unit": "fahrenheit",
                        "precipitation_unit": "inch",
                        "windspeed_unit": "mph",
                        "timezone": "auto",
                        "forecast_days": forecast_days,
                    }
                    if config["models"]:
                        params["models"] = config["models"]

                    headers = {
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                    }

                    resp = requests.get(
                        config["url"],
                        params=params,
                        headers=headers,
                        timeout=int(os.getenv("OPEN_METEO_TIMEOUT", "15")),
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    model_source = "Open-Meteo"
                    cycle = None  # Open-Meteo doesn't provide cycle info
                    # Inject metadata into data dict for caching
                    data["model_source"] = model_source
                    data["cycle"] = cycle
                    # Extract model run time from first forecast hour (hour 0 = initialization)
                    # Times from API are in local timezone, convert to UTC to get model cycle
                    if data.get("hourly", {}).get("time"):
                        import pytz

                        first_time = data["hourly"]["time"][0]
                        # Parse the local time
                        first_dt = datetime.fromisoformat(first_time.replace("Z", ""))
                        # Get timezone from API response
                        tz_str = data.get("timezone", "America/Chicago")
                        local_tz = pytz.timezone(tz_str)
                        # Localize to the proper timezone, then convert to UTC
                        if first_dt.tzinfo is None:
                            first_dt_local = local_tz.localize(first_dt)
                        else:
                            first_dt_local = first_dt
                        run_time = first_dt_local.astimezone(dt_timezone.utc)
                    om_elapsed = time.time() - om_start
                    logger.info(f"Open-Meteo fetched in {om_elapsed:.2f}s")
                    # Cache will be set after precipitation classification
                except Exception as exc:  # noqa: BLE001
                    om_elapsed = time.time() - om_start
                    logger.warning(f"Open-Meteo failed in {om_elapsed:.2f}s: {exc}")

            # If still no data and model in NOAA set, try gridpoint API (surface-only)
            if not only_open_meteo and not data and model_name in NOAA_MODELS:
                try:
                    noaa_data = fetch_noaa_forecast(float(lat), float(lon), model_name)
                    if noaa_data:
                        data = noaa_data
                        model_source = "NOAA"
                        cycle = None  # NOAA gridpoint doesn't provide cycle info
                        # Inject metadata into data dict for caching
                        data["model_source"] = model_source
                        data["cycle"] = cycle
                        if data.get("hourly", {}).get("time"):
                            first_time = data["hourly"]["time"][0]
                            run_time = datetime.fromisoformat(
                                first_time.replace("Z", "+00:00")
                            )
                        # Cache will be set after precipitation classification
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        f"NOAA fetch failed for {model_name} after other fallbacks: {exc}"
                    )

            # Fallback for all other models (ICON, ECMWF, AIFS, GEM, etc.) - use Open-Meteo
            if not data and model_name != "GFS":
                try:
                    om_start = time.time()
                    logger.info(f"Fetching {model_name} from Open-Meteo")  # noqa: S101
                    params = {
                        "latitude": lat,
                        "longitude": lon,
                        "hourly": self.EXTENDED_HOURLY,
                        "temperature_unit": "fahrenheit",
                        "precipitation_unit": "inch",
                        "windspeed_unit": "mph",
                        "timezone": "auto",
                        "forecast_days": forecast_days,
                    }
                    if config["models"]:
                        params["models"] = config["models"]

                    headers = {
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                    }

                    resp = requests.get(
                        config["url"],
                        params=params,
                        headers=headers,
                        timeout=int(os.getenv("OPEN_METEO_TIMEOUT", "15")),
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    model_source = "Open-Meteo"
                    cycle = None  # Open-Meteo doesn't provide cycle info
                    # Inject metadata into data dict for caching
                    data["model_source"] = model_source
                    data["cycle"] = cycle
                    # Extract model run time from first forecast hour - convert local to UTC
                    if data.get("hourly", {}).get("time"):
                        import pytz

                        first_time = data["hourly"]["time"][0]
                        first_dt = datetime.fromisoformat(first_time.replace("Z", ""))
                        tz_str = data.get("timezone", "America/Chicago")
                        local_tz = pytz.timezone(tz_str)
                        if first_dt.tzinfo is None:
                            first_dt_local = local_tz.localize(first_dt)
                        else:
                            first_dt_local = first_dt
                        run_time = first_dt_local.astimezone(dt_timezone.utc)
                    om_elapsed = time.time() - om_start
                    logger.info(f"Open-Meteo {model_name} fetched in {om_elapsed:.2f}s")
                    # Cache will be set after precipitation classification
                except Exception as exc:  # noqa: BLE001
                    om_elapsed = time.time() - om_start
                    logger.warning(
                        f"Open-Meteo {model_name} failed in {om_elapsed:.2f}s: {exc}"
                    )
        else:
            error = "Latitude/longitude not provided and no fallback location available"

        import json

        # Get locations from session if available, otherwise show all active locations
        location_ids = request.session.get("location_ids", [])
        if location_ids:
            locations_qs = Location.objects.filter(
                is_active=True,
                id__in=location_ids,
            ).order_by("-is_current_location", "display_order", "name")
        else:
            # Fallback: show all active locations if session is empty
            locations_qs = Location.objects.filter(is_active=True).order_by(
                "-is_current_location", "display_order", "name"
            )

        # Trim hourly data to requested forecast_days window to reduce JSON payload
        if data and data.get("hourly") and data["hourly"].get("time"):
            try:
                from datetime import timedelta

                times = data["hourly"]["time"]
                if times:
                    first_time = datetime.fromisoformat(
                        str(times[0]).replace("Z", "+00:00")
                    )
                    cutoff = first_time + timedelta(days=int(forecast_days))
                    trim_idx = 0
                    for i, t in enumerate(times):
                        t_dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
                        if t_dt > cutoff:
                            trim_idx = i
                            break
                    else:
                        trim_idx = len(times)  # use all if none exceed cutoff
                    if trim_idx > 0 and trim_idx < len(times):
                        # Trim all hourly arrays
                        for key in data["hourly"]:
                            if isinstance(data["hourly"][key], list):
                                data["hourly"][key] = data["hourly"][key][:trim_idx]
                        logger.info(
                            f"Trimmed hourly data from {len(times)} to {trim_idx} points (forecast_days={forecast_days})"
                        )
            except Exception as e:
                logger.warning(f"Failed to trim hourly data: {e}")

        # Derive precip phase (snow/sleet/freezing_rain/rain) and SLRs per hour
        # NBM provides native probabilities but only liquid equivalent, use static default SLRs
        # GFS/HRRR have both probabilities and temperature profiles, use dynamic classification
        if data and data.get("hourly"):
            if model_name == "NBM":
                # NBM: apply static default SLRs for accumulation calculation
                num_hours = len(data["hourly"].get("time", []))
                default_slrs = {
                    "snow": 10.0,  # Standard 10:1 snow ratio
                    "sleet": 2.5,  # Ice pellets ~2.5:1
                    "freezing_rain": 0.5,  # Freezing rain accretion ~0.5:1
                    "rain": 1.0,  # Rain is 1:1
                }
                # Create a SLR array per precipitation type for frontend calculation
                # Frontend will use default_slrs dict to look up correct ratio based on precip_type
                data["hourly"]["snow_liquid_ratio"] = [
                    1.0
                ] * num_hours  # Placeholder, frontend uses default_slrs
                data["hourly"]["default_slrs"] = default_slrs
                logger.info(
                    f"Using static SLRs for NBM precipitation types: {default_slrs}"
                )
            else:
                # All other models: prioritize classification approach based on available data
                try:
                    # Check if model provides native precipitation type probabilities with actual signal
                    # Require at least one probability > 0 to consider them usable
                    prob_keys = [
                        "rain_probability",
                        "snowfall_probability",
                        "freezing_rain_probability",
                        "ice_pellets_probability",
                    ]
                    prob_signals: dict[str, float] = {}
                    has_native_probs = False
                    for prob_key in prob_keys:
                        vals = data["hourly"].get(prob_key) or []
                        max_val = max([(v or 0) for v in vals], default=0)
                        prob_signals[prob_key] = max_val
                        if max_val > 0:
                            has_native_probs = True
                    logger.info(
                        "Precip probs signal check for %s: has_native_probs=%s, max_vals=%s",
                        model_name,
                        has_native_probs,
                        prob_signals,
                    )

                    # Check if model has sufficient atmospheric levels for thermodynamic classification
                    required_levels = [
                        "temperature_2m",
                        "temperature_850hPa",
                        "temperature_700hPa",
                    ]
                    has_sufficient_levels = all(
                        level in data["hourly"] and data["hourly"][level]
                        for level in required_levels
                    )

                    # Check if model has ANY atmospheric levels beyond surface
                    atmospheric_level_keys = [
                        k for k in data["hourly"] if "hPa" in k and "temperature" in k
                    ]
                    has_any_levels = len(atmospheric_level_keys) > 0

                    logger.info(
                        "Precip classification availability for %s: sufficient_levels=%s, any_levels=%s, native_probs=%s",
                        model_name,
                        has_sufficient_levels,
                        has_any_levels,
                        has_native_probs,
                    )

                    # Local helper to convert Fahrenheit to Celsius for simple surface checks
                    def f_to_c_local(v):
                        try:
                            return (float(v) - 32.0) * (5.0 / 9.0)
                        except Exception:
                            return None

                    if has_sufficient_levels:
                        # Priority 1: If sufficient levels, use thermodynamic classification
                        precip_types, slrs = self._classify_precip_types(data["hourly"])
                        data["hourly"]["precip_type"] = precip_types
                        data["hourly"]["snow_liquid_ratio"] = slrs
                        logger.info(
                            f"Derived precip_type and SLRs for {len(precip_types)} hours using sufficient atmospheric levels"
                        )
                    elif has_native_probs:
                        # Priority 2: If insufficient levels but have probabilities, derive precip_type from probs.
                        # If probs are all zero/None, fall back to surface temp to avoid misclassifying cold precip as rain.
                        logger.info(
                            f"Using native precipitation probabilities for {model_name} (insufficient atmospheric levels)"
                        )
                        num_hours = len(data["hourly"].get("time", []))
                        temps2m = data["hourly"].get("temperature_2m") or []
                        rain_probs = data["hourly"].get("rain_probability") or []
                        snow_probs = data["hourly"].get("snowfall_probability") or []
                        frz_probs = (
                            data["hourly"].get("freezing_rain_probability") or []
                        )
                        ice_probs = data["hourly"].get("ice_pellets_probability") or []

                        precip_types: list[str] = []
                        slrs: list[float] = []

                        for i in range(num_hours):
                            rp = rain_probs[i] if i < len(rain_probs) else 0
                            sp = snow_probs[i] if i < len(snow_probs) else 0
                            fp = frz_probs[i] if i < len(frz_probs) else 0
                            ip = ice_probs[i] if i < len(ice_probs) else 0
                            t2m_f = temps2m[i] if i < len(temps2m) else None
                            t2m_c = f_to_c_local(t2m_f)

                            max_prob = max(rp or 0, sp or 0, fp or 0, ip or 0)

                            if max_prob == 0 and t2m_c is not None and t2m_c <= 0.0:
                                # No probability signal but subfreezing surface: treat as snow
                                ptype = "snow"
                            elif max_prob == 0:
                                ptype = "rain"
                            else:
                                # Pick the type with the highest probability
                                if (sp or 0) >= max_prob and (sp or 0) > 0:
                                    ptype = "snow"
                                elif (ip or 0) >= max_prob and (ip or 0) > 0:
                                    ptype = "sleet"
                                elif (fp or 0) >= max_prob and (fp or 0) > 0:
                                    ptype = "freezing_rain"
                                else:
                                    ptype = "rain"

                            # Assign SLR defaults by precip type
                            if ptype == "snow":
                                slr = 10.0
                            elif ptype == "sleet":
                                slr = 2.5
                            elif ptype == "freezing_rain":
                                slr = 0.5
                            else:
                                slr = 1.0

                            precip_types.append(ptype)
                            slrs.append(slr)

                        data["hourly"]["precip_type"] = precip_types
                        data["hourly"]["snow_liquid_ratio"] = slrs
                        logger.info(
                            f"Derived precip_type from native probabilities for {num_hours} hours (with subfreezing fallback)"
                        )
                    elif has_any_levels:
                        # Priority 3: If insufficient levels but have SOME levels, still try thermodynamic with limited data
                        precip_types, slrs = self._classify_precip_types(data["hourly"])
                        data["hourly"]["precip_type"] = precip_types
                        data["hourly"]["snow_liquid_ratio"] = slrs
                        logger.info(
                            f"Derived precip_type and SLRs for {len(precip_types)} hours using limited atmospheric levels"
                        )
                    else:
                        # Priority 4: No atmospheric levels - use simple surface temperature rule
                        surface_temps = data["hourly"].get("temperature_2m") or []
                        num_hours = len(data["hourly"].get("time", []))
                        slrs = []
                        precip_types = []

                        for temp_f in surface_temps:
                            temp_c = f_to_c_local(temp_f)

                            if temp_c is not None and temp_c <= 0.0:
                                # Cold surface: snow (cannot determine warm nose/sleet without upper data)
                                ptype = "snow"
                                # Estimate SLR based on how cold it is
                                if temp_c <= -10.0:
                                    slr = 12.0
                                elif temp_c <= -5.0:
                                    slr = 10.0
                                else:  # -5 < temp <= 0
                                    slr = 8.0
                            else:
                                # Warm surface: rain
                                ptype = "rain"
                                slr = 1.0

                            precip_types.append(ptype)
                            slrs.append(slr)

                        # Pad if needed
                        while len(slrs) < num_hours:
                            slrs.append(1.0)
                            precip_types.append("rain")

                        data["hourly"]["precip_type"] = precip_types[:num_hours]
                        data["hourly"]["snow_liquid_ratio"] = slrs[:num_hours]
                        logger.info(
                            f"Using surface temperature-based precip type and SLR for {model_name} (no atmospheric levels, no probabilities)"
                        )

                    # Debug snapshot for NAM to verify per-hour classification and temps
                    if model_name == "NAM" and data["hourly"]:
                        try:
                            sample_n = 12
                            pt = (data["hourly"].get("precip_type") or [])[:sample_n]
                            slr_sample = (
                                data["hourly"].get("snow_liquid_ratio") or []
                            )[:sample_n]
                            t2m_f = (data["hourly"].get("temperature_2m") or [])[
                                :sample_n
                            ]
                            t2m_c = [f_to_c_local(v) for v in t2m_f]
                            rp = (data["hourly"].get("rain_probability") or [])[
                                :sample_n
                            ]
                            sp = (data["hourly"].get("snowfall_probability") or [])[
                                :sample_n
                            ]
                            frp = (
                                data["hourly"].get("freezing_rain_probability") or []
                            )[:sample_n]
                            ipp = (data["hourly"].get("ice_pellets_probability") or [])[
                                :sample_n
                            ]
                            logger.info(
                                "NAM debug sample: precip_type=%s, slr=%s, t2m_f=%s, t2m_c=%s, rain_prob=%s, snow_prob=%s, frz_prob=%s, ice_prob=%s",
                                pt,
                                slr_sample,
                                t2m_f,
                                t2m_c,
                                rp,
                                sp,
                                frp,
                                ipp,
                            )
                        except Exception as debug_exc:
                            logger.warning(f"NAM debug snapshot failed: {debug_exc}")
                except Exception as e:
                    logger.warning(f"Failed to classify precip types: {e}")

            # Safety fallback: if precip_type still missing/empty, derive from surface temps per hour
            if data and data.get("hourly") and not data["hourly"].get("precip_type"):
                try:
                    temps2m = data["hourly"].get("temperature_2m") or []
                    num_hours = len(data["hourly"].get("time", []))
                    precip_types: list[str] = []
                    slrs: list[float] = []

                    def f_to_c_safe(v):
                        try:
                            return (float(v) - 32.0) * (5.0 / 9.0)
                        except Exception:
                            return None

                    for temp_f in temps2m:
                        temp_c = f_to_c_safe(temp_f)
                        if temp_c is not None and temp_c <= 0.0:
                            precip_types.append("snow")
                            # keep same SLR scaling as surface fallback
                            if temp_c <= -10.0:
                                slrs.append(12.0)
                            elif temp_c <= -5.0:
                                slrs.append(10.0)
                            else:
                                slrs.append(8.0)
                        else:
                            precip_types.append("rain")
                            slrs.append(1.0)

                    while len(precip_types) < num_hours:
                        precip_types.append("rain")
                        slrs.append(1.0)

                    data["hourly"]["precip_type"] = precip_types[:num_hours]
                    data["hourly"]["snow_liquid_ratio"] = slrs[:num_hours]
                    logger.info(
                        "Safety fallback applied: precip_type derived from surface temps (%s hours)",
                        len(precip_types[:num_hours]),
                    )
                except Exception as fallback_exc:
                    logger.warning(
                        f"Safety fallback failed to set precip_type: {fallback_exc}"
                    )

            # Derive cycle from run_time if not provided (snap to prior 6-hour boundary)
            if run_time and not cycle:
                try:
                    cycle_hour = (run_time.hour // 6) * 6
                    cycle = f"{cycle_hour:02d}Z"
                    data["cycle"] = cycle
                    logger.info(f"Derived cycle from run_time: {cycle}")
                except Exception as cycle_exc:
                    logger.warning(f"Failed to derive cycle from run_time: {cycle_exc}")

        # Cache the final data with all derived fields
        if data and cache_key:
            cache.set(
                cache_key,
                data,
                timeout=getattr(
                    settings,
                    "MODEL_DETAIL_CACHE_SECONDS",
                    getattr(settings, "CACHE_TIMEOUT", 300),
                ),
            )
            logger.info("Model data cached")  # noqa: S101

        # Inject metadata into data dict so it's available in the frontend
        if data:
            data["model_source"] = model_source
            data["cycle"] = cycle
            data["elevation"] = data.get(
                "elevation"
            )  # preserve existing elevation if present

        # Convert to list to ensure it's always a renderable object
        locations_list = list(locations_qs)
        locations_payload = [
            {
                "id": str(loc.id),
                "display_name": loc.display_name,
                "latitude": float(loc.latitude) if loc.latitude is not None else None,
                "longitude": float(loc.longitude)
                if loc.longitude is not None
                else None,
                "is_current_location": loc.is_current_location,
            }
            for loc in locations_list
        ]

        context.update(
            {
                "model_name": model_name,
                "model_config": config,
                "data": data,  # original Python object (for server-side uses if any)
                "data_json": json.dumps(data) if data is not None else "null",
                "error": error,
                "run_time": run_time,
                "model_source": model_source,
                "ensemble": ensemble,
                "cycle": cycle,
                "forecast_hours": forecast_hours,
                "latitude": lat,
                "longitude": lon,
                "forecast_days": forecast_days,
                "locations": locations_list,
                "locations_json": json.dumps(locations_payload),
                "available_models": list(self.MODEL_CONFIGS.keys()),
                "page_title": f"{model_name} Model Details",
            }
        )
        fetch_elapsed = time.time() - fetch_start
        logger.info(f"ModelDetailView completed in {fetch_elapsed:.2f}s")
        return context


class LocationListView(ListView):
    """List view for weather locations."""

    model = Location
    template_name = "weather/location_list.html"
    context_object_name = "locations"
    paginate_by = 12

    def get_queryset(self):
        """Get active locations with forecast counts, favorite first."""
        # Filter by owner for authenticated users, otherwise use session
        if self.request.user.is_authenticated:
            queryset = Location.objects.filter(is_active=True, owner=self.request.user)
        else:
            location_ids = self.request.session.get("location_ids", [])
            if location_ids:
                queryset = Location.objects.filter(is_active=True, id__in=location_ids)
            else:
                # If no location_ids in session, show no locations
                queryset = Location.objects.none()

        # Search functionality
        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(zip_code__icontains=search)
            )

        type_priority = Case(
            When(location_type="home", then=1),
            When(location_type="work", then=2),
            When(location_type="school", then=3),
            default=4,
            output_field=IntegerField(),
        )
        return queryset.annotate(
            forecast_count=Count("forecasts"),
            type_priority=type_priority,
        ).order_by("-is_current_location", "type_priority", "display_order", "name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Weather Locations"
        context["search_query"] = self.request.GET.get("search", "")

        # Fetch current conditions for all locations on page load
        from datetime import date, timedelta

        today = date.today()

        locations_data = []
        for location in context["locations"]:
            # Check if current conditions need updating (older than 15 minutes or don't exist)
            try:
                cc = location.current_conditions_cache
                needs_update = timezone.now() - cc.last_observation_time > timedelta(
                    minutes=15
                )
            except (AttributeError, CurrentConditions.DoesNotExist):
                # CurrentConditions doesn't exist, fetch immediately
                needs_update = True

            if needs_update:
                try:
                    from .tasks import update_current_conditions_for_location

                    update_current_conditions_for_location.delay(str(location.id))
                except Exception:
                    fetch_current_conditions(location)

            # Get today's daytime forecast (NWS only)
            today_forecast = (
                DailyForecast.objects.filter(
                    location=location, forecast_date=today, is_daytime=True
                )
                .exclude(nws_data_url="")
                .first()
            )  # Only show NWS forecasts on location list

            # Get active alerts (cache-aware)
            try:
                from .services import AlertsService

                active_alerts = AlertsService.get_or_fetch_alerts(location)
            except Exception:
                active_alerts = location.alerts.filter(is_active=True)

            locations_data.append(
                {
                    "location": location,
                    "today_forecast": today_forecast,
                    "active_alerts": active_alerts,
                    "alert_count": active_alerts.count(),
                }
            )

        context["locations_data"] = locations_data

        return context


class LocationDetailView(DetailView):
    """Detail view for individual weather locations."""

    model = Location
    template_name = "weather/location_detail.html"
    context_object_name = "location"

    def get_queryset(self):
        queryset = Location.objects.filter(is_active=True)
        if self.request.user.is_authenticated:
            queryset = queryset.filter(owner=self.request.user)
        else:
            location_ids = self.request.session.get("location_ids", [])
            queryset = queryset.filter(Q(id__in=location_ids) | Q(owner__isnull=True))
        return queryset.prefetch_related("alerts")

    def get(self, request, *args, **kwargs):
        """Override get to trigger forecast update on page load."""
        self.object = self.get_object()

        # Check if forecast needs updating (older than 15 minutes or doesn't exist)
        from datetime import timedelta

        needs_update = (
            not self.object.last_forecast_update
            or timezone.now() - self.object.last_forecast_update > timedelta(minutes=15)
        )

        if needs_update and self.object.latitude and self.object.longitude:
            try:
                from .tasks import (
                    update_alerts_for_location,
                    update_current_conditions_for_location,
                    update_forecasts_for_location,
                )

                update_current_conditions_for_location.delay(str(self.object.id))
                update_forecasts_for_location.delay(str(self.object.id))
                update_alerts_for_location.delay(str(self.object.id))
            except Exception as e:
                logger.warning(f"Failed to enqueue refresh for {self.object.name}: {e}")
                fetch_current_conditions(self.object)
                _refresh_forecasts_for_location(self.object)

        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location = self.object

        # Get all daily forecasts
        all_daily = DailyForecast.objects.filter(location=location).order_by(
            "period_start"
        )

        # Check if we have custom forecasts (those without nws_data_url)
        custom_daily = all_daily.filter(nws_data_url="")
        nws_daily = all_daily.exclude(nws_data_url="")

        # For detail page, prefer custom forecasts if they exist, otherwise show NWS
        if custom_daily.exists():
            daily_to_show = custom_daily
            has_custom_daily = True
        else:
            daily_to_show = nws_daily
            has_custom_daily = False

        # Group forecasts by date (day and night together)
        from itertools import groupby

        grouped_forecasts = []
        for date, periods in groupby(daily_to_show, key=lambda f: f.forecast_date):
            periods_list = list(periods)
            day_forecast = next((p for p in periods_list if p.is_daytime), None)
            night_forecast = next((p for p in periods_list if not p.is_daytime), None)
            grouped_forecasts.append(
                {"date": date, "day": day_forecast, "night": night_forecast}
            )

        # Get hourly forecasts (include slightly past forecasts to handle timing edge cases)
        from datetime import timedelta as td

        cutoff_time = timezone.now() - td(
            hours=1
        )  # Include last hour to handle edge cases
        all_hourly = HourlyForecast.objects.filter(
            location=location, period_start__gte=cutoff_time
        ).order_by("period_start")

        # Check if we have custom hourly forecasts
        custom_hourly = all_hourly.filter(nws_data_url="")[
            :48
        ]  # Get more to ensure coverage
        nws_hourly = all_hourly.exclude(nws_data_url="")[:48]

        # For detail page, prefer custom forecasts if they exist
        if custom_hourly.exists():
            hourly_to_show = custom_hourly
            has_custom_hourly = True
        else:
            hourly_to_show = nws_hourly
            has_custom_hourly = False

        # Serialize hourly forecasts for JavaScript
        # For editing: merge custom and NWS data - use custom where it exists, NWS for the rest
        import json
        from datetime import timedelta

        # Build dictionaries for faster lookup and track used forecasts
        custom_list = list(custom_hourly)
        nws_list = list(nws_hourly)
        used_custom_indices = set()
        used_nws_indices = set()

        # Start from current hour and go forward 24 hours
        current_time = timezone.now().replace(minute=0, second=0, microsecond=0)
        merged_hourly = []

        for i in range(24):
            hour_time = current_time + timedelta(hours=i)
            forecast_to_use = None

            # Try to find the closest custom forecast for this hour (within 60 min, not yet used)
            best_custom_match = None
            best_custom_diff = float("inf")
            best_custom_idx = None

            for idx, custom_forecast in enumerate(custom_list):
                if idx in used_custom_indices:
                    continue
                time_diff = abs(
                    (custom_forecast.period_start - hour_time).total_seconds()
                )
                if (
                    time_diff < 3600 and time_diff < best_custom_diff
                ):  # Within 60 minutes
                    best_custom_match = custom_forecast
                    best_custom_diff = time_diff
                    best_custom_idx = idx

            if best_custom_match:
                forecast_to_use = best_custom_match
                used_custom_indices.add(best_custom_idx)
            else:
                # Find closest NWS forecast (within 60 min, not yet used)
                best_nws_match = None
                best_nws_diff = float("inf")
                best_nws_idx = None

                for idx, nws_forecast in enumerate(nws_list):
                    if idx in used_nws_indices:
                        continue
                    time_diff = abs(
                        (nws_forecast.period_start - hour_time).total_seconds()
                    )
                    if time_diff < 3600 and time_diff < best_nws_diff:
                        best_nws_match = nws_forecast
                        best_nws_diff = time_diff
                        best_nws_idx = idx

                if best_nws_match:
                    forecast_to_use = best_nws_match
                    used_nws_indices.add(best_nws_idx)

            # Add to list if we found something
            if forecast_to_use:
                merged_hourly.append(forecast_to_use)

        hourly_json = json.dumps(
            [
                {
                    "temperature": h.temperature,
                    "short_forecast": h.short_forecast,
                    "wind_speed": h.wind_speed,
                    "wind_gust": h.wind_gust,
                    "precipitation_probability": h.precipitation_probability,
                    "period_start": h.period_start.isoformat(),
                }
                for h in merged_hourly
            ]
        )

        context.update(
            {
                "page_title": f"{location.name} - Weather Details",
                "daily_forecasts": grouped_forecasts,
                "hourly_forecasts": hourly_to_show,
                "hourly_forecasts_json": hourly_json,
                "has_custom_daily": has_custom_daily,
                "has_custom_hourly": has_custom_hourly,
                "active_alerts": location.alerts.filter(is_active=True),
            }
        )

        # Add active locations list for location toggle dropdown (similar to model detail page)
        try:
            location_ids = self.request.session.get("location_ids", [])
            locations_qs = Location.objects.filter(is_active=True)
            if location_ids:
                locations_qs = locations_qs.filter(id__in=location_ids)
            context["locations"] = locations_qs.order_by(
                "-is_current_location", "display_order", "name"
            )
        except Exception:
            # Fallback: empty list if any error occurs
            context["locations"] = Location.objects.none()

        return context


def _refresh_forecasts_for_location(location: Location):
    """Fetch and store forecasts for a location using NWS API directly.
    Fallback used by forecast list to guarantee data on first load.
    """
    try:
        import requests

        headers = {"User-Agent": "(Weather App, contact@example.com)"}
        # Get grid point
        grid_url = (
            f"https://api.weather.gov/points/{location.latitude},{location.longitude}"
        )
        grid_response = requests.get(grid_url, headers=headers, timeout=10)
        grid_response.raise_for_status()
        grid_data = grid_response.json()
        props = grid_data.get("properties", {})
        location.nws_office = props.get("gridId", "")
        location.grid_x = props.get("gridX")
        location.grid_y = props.get("gridY")
        # Forecast URL
        fcst_url = props.get("forecast")
        if not fcst_url:
            return False
        r = requests.get(fcst_url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        periods = data.get("properties", {}).get("periods", [])
        # Replace existing
        DailyForecast.objects.filter(location=location).delete()
        from datetime import datetime

        def parse_ws(ws):
            if not ws:
                return 0
            import re

            nums = re.findall(r"\d+", str(ws))
            if not nums:
                return 0
            if len(nums) > 1:
                return int((int(nums[0]) + int(nums[1])) / 2)
            return int(nums[0])

        for p in periods[:14]:
            DailyForecast.objects.create(
                location=location,
                forecast_date=datetime.fromisoformat(
                    p["startTime"].replace("Z", "+00:00")
                ).date(),
                period_start=datetime.fromisoformat(
                    p["startTime"].replace("Z", "+00:00")
                ),
                period_end=datetime.fromisoformat(p["endTime"].replace("Z", "+00:00")),
                is_daytime=p.get("isDaytime", True),
                temperature=p.get("temperature"),
                temperature_unit=p.get("temperatureUnit", "F"),
                wind_speed=parse_ws(p.get("windSpeed", "")),
                wind_direction=p.get("windDirection", ""),
                short_forecast=p.get("shortForecast", ""),
                detailed_forecast=p.get("detailedForecast", ""),
                precipitation_probability=p.get("probabilityOfPrecipitation", {}).get(
                    "value"
                ),
                nws_data_url=fcst_url,  # Mark as NWS forecast
                last_api_update=timezone.now(),
            )
        location.last_forecast_update = timezone.now()
        location.save(
            update_fields=["nws_office", "grid_x", "grid_y", "last_forecast_update"]
        )
        return True
    except Exception:
        logger.exception("Forecast refresh failed for %s", location.name)
        return False


class ForecastListView(ListView):
    """List view for weather forecasts."""

    model = DailyForecast
    template_name = "weather/forecast_list.html"
    context_object_name = "forecasts"
    paginate_by = None  # Show all forecasts

    def get_queryset(self):
        """Get forecasts for active locations."""
        # Ensure forecasts are available/up-to-date on page load
        threshold = timezone.now() - timedelta(minutes=15)

        # Filter locations by session - only show enabled locations
        location_ids = self.request.session.get("location_ids", [])
        active_locations = Location.objects.filter(
            is_active=True, is_enabled=True, id__in=location_ids
        )
        for loc in active_locations:
            has_upcoming = DailyForecast.objects.filter(
                location=loc, forecast_date__gte=timezone.now().date()
            ).exists()
            if (
                not has_upcoming
                or not loc.last_forecast_update
                or loc.last_forecast_update < threshold
            ):
                try:
                    from .tasks import update_forecasts_for_location

                    update_forecasts_for_location.delay(str(loc.id))
                except Exception:
                    _refresh_forecasts_for_location(loc)

        # Filter forecasts by session location_ids to match location list
        # Also include current location even if not in session
        qs = DailyForecast.objects.select_related("location").filter(
            Q(location__id__in=location_ids) | Q(location__is_current_location=True),
            location__is_active=True,
            location__is_enabled=True,
            forecast_date__gte=timezone.now().date(),
        )
        type_priority = Case(
            When(location__location_type="home", then=1),
            When(location__location_type="work", then=2),
            When(location__location_type="school", then=3),
            default=4,
            output_field=IntegerField(),
        )
        return qs.annotate(type_priority=type_priority).order_by(
            "-location__is_current_location",
            "type_priority",
            "location__display_order",
            "location__name",
            "forecast_date",
            "-is_daytime",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Weather Forecasts"

        # Add current conditions for each location
        type_priority = Case(
            When(location_type="home", then=1),
            When(location_type="work", then=2),
            When(location_type="school", then=3),
            default=4,
            output_field=IntegerField(),
        )
        # Filter locations by session - only show enabled locations
        location_ids = self.request.session.get("location_ids", [])
        location_filter = Q(is_active=True, is_enabled=True, id__in=location_ids)

        locations = (
            Location.objects.filter(location_filter)
            .filter(current_conditions_cache__isnull=False)
            .annotate(type_priority=type_priority)
            .order_by("-is_current_location", "type_priority", "display_order", "name")
        )
        context["locations_with_current"] = locations

        # Group forecasts by date first, then by location
        from collections import defaultdict

        dates_forecasts = defaultdict(dict)

        for forecast in context["forecasts"]:
            date = forecast.forecast_date
            location_id = forecast.location.id
            if location_id not in dates_forecasts[date]:
                dates_forecasts[date][location_id] = {
                    "location": forecast.location,
                    "day": None,
                    "night": None,
                }
            if forecast.is_daytime:
                dates_forecasts[date][location_id]["day"] = forecast
            else:
                dates_forecasts[date][location_id]["night"] = forecast

        # Convert to list format grouped by date with sorted locations
        grouped_by_date = []
        for date in sorted(dates_forecasts.keys()):
            # Sort locations by current flag, type priority, display_order, name
            locations_dict = dates_forecasts[date]
            sorted_locations = sorted(
                locations_dict.values(),
                key=lambda x: (
                    0 if x["location"].is_current_location else 1,
                    (
                        1
                        if x["location"].location_type == "home"
                        else 2
                        if x["location"].location_type == "work"
                        else 3
                        if x["location"].location_type == "school"
                        else 4
                    ),
                    x["location"].display_order,
                    x["location"].name,
                ),
            )

            grouped_by_date.append({"date": date, "locations": sorted_locations})

        context["grouped_by_date"] = grouped_by_date

        return context


class CustomForecastView(TemplateView):
    template_name = "weather/custom_forecast.html"

    def get_context_data(self, **kwargs):
        import requests

        from weather.models import Location

        context = super().get_context_data(**kwargs)
        request = self.request

        latitude = request.GET.get("latitude")
        longitude = request.GET.get("longitude")
        location_id = request.GET.get("location_id")

        locations = Location.objects.filter(is_active=True).order_by(
            "-is_current_location", "display_order", "name"
        )

        nws_forecast_periods = []
        climate_normals = {}

        # If location_id provided, fetch reference data
        if location_id:
            try:
                location = Location.objects.get(id=location_id)
                latitude = location.latitude
                longitude = location.longitude

                # Fetch climate normals
                if location.avg_high_temp and location.avg_low_temp:
                    climate_normals = {
                        "avg_high": location.avg_high_temp,
                        "avg_low": location.avg_low_temp,
                    }

                # Fetch NWS forecast for reference
                points_url = f"https://api.weather.gov/points/{latitude},{longitude}"
                points_resp = requests.get(
                    points_url,
                    headers={"User-Agent": "WeatherApp/1.0"},
                    timeout=10,
                )
                if points_resp.status_code == 200:
                    points_data = points_resp.json()
                    forecast_url = points_data.get("properties", {}).get("forecast")
                    if forecast_url:
                        forecast_resp = requests.get(
                            forecast_url,
                            headers={"User-Agent": "WeatherApp/1.0"},
                            timeout=10,
                        )
                        if forecast_resp.status_code == 200:
                            forecast_data = forecast_resp.json()
                            nws_forecast_periods = forecast_data.get(
                                "properties", {}
                            ).get("periods", [])[:14]  # Get 7 days (14 periods)
            except (Location.DoesNotExist, requests.RequestException):
                # Log error but continue
                pass

        context.update(
            {
                "locations": locations,
                "latitude": latitude,
                "longitude": longitude,
                "location_id": location_id,
                "nws_forecast_periods": nws_forecast_periods,
                "climate_normals": climate_normals,
            }
        )
        return context


# Duplicate AlertListView removed to avoid F811 redefinition; earlier definition retained.
