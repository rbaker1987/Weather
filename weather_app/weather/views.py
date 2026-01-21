"""Django REST Framework views for weather API."""

import json
import os
import logging
from datetime import datetime, time, timedelta

from django.db.models import Avg, Case, Count, IntegerField, Q, When
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    DailyForecast,
    ForecastRequest,
    HourlyForecast,
    Location,
    WeatherAlert,
)
from .serializers import (
    BulkForecastRequestSerializer,
    DailyForecastSerializer,
    HourlyForecastSerializer,
    LocationSerializer,
    WeatherAlertSerializer,
)
from .utils.apparent_temperature import calculate_apparent_temperature

logger = logging.getLogger("weather")
from django.core.cache import cache
from django.conf import settings


def fetch_current_conditions(location):
    """Helper function to fetch and update current conditions for a location."""
    if not location.latitude or not location.longitude:
        return False

    try:
        from datetime import datetime

        import requests

        headers = {"User-Agent": "(Weather App, contact@example.com)"}

        # Get grid point data
        grid_url = (
            f"https://api.weather.gov/points/{location.latitude},{location.longitude}"
        )
        grid_response = requests.get(grid_url, headers=headers, timeout=10)
        grid_response.raise_for_status()
        grid_data = grid_response.json()

        properties = grid_data.get("properties", {})
        observation_stations_url = properties.get("observationStations")

        if not observation_stations_url:
            return False

        # Get observation stations
        stations_response = requests.get(
            observation_stations_url, headers=headers, timeout=10
        )
        stations_response.raise_for_status()
        stations_data = stations_response.json()

        stations = stations_data.get("features", [])
        if not stations:
            return False

        station_id = stations[0].get("properties", {}).get("stationIdentifier")
        if not station_id:
            return False

        # Get latest observation
        obs_url = f"https://api.weather.gov/stations/{station_id}/observations/latest"
        obs_response = requests.get(obs_url, headers=headers, timeout=10)
        obs_response.raise_for_status()
        obs_data = obs_response.json()

        obs_props = obs_data.get("properties", {})

        # Extract and update current conditions
        temp_c = obs_props.get("temperature", {}).get("value")
        if temp_c:
            location.current_temp = int(temp_c * 9 / 5 + 32)

        location.current_conditions = obs_props.get("textDescription", "")

        humidity = obs_props.get("relativeHumidity", {}).get("value")
        if humidity:
            location.current_humidity = int(humidity)

        wind_speed_kmh = obs_props.get("windSpeed", {}).get("value")
        if wind_speed_kmh is not None:
            try:
                location.current_wind_speed = int(wind_speed_kmh * 0.621371)
            except (ValueError, TypeError):
                location.current_wind_speed = 0
        else:
            location.current_wind_speed = 0

        # Wind gust
        wind_gust_kmh = obs_props.get("windGust", {}).get("value")
        if wind_gust_kmh is not None:
            try:
                location.current_wind_gust = int(wind_gust_kmh * 0.621371)
            except (ValueError, TypeError):
                location.current_wind_gust = None
        else:
            location.current_wind_gust = None

        wind_dir_deg = obs_props.get("windDirection", {}).get("value")
        if wind_dir_deg is not None:
            try:
                deg = float(wind_dir_deg)
                directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
                location.current_wind_direction = directions[int((deg + 22.5) / 45) % 8]
            except (ValueError, TypeError):
                location.current_wind_direction = ""
        else:
            location.current_wind_direction = ""

        # Calculate apparent temperature
        if location.current_temp is not None:
            dew_point_c = obs_props.get("dewpoint", {}).get("value")
            location.current_apparent_temp = calculate_apparent_temperature(
                temp_f=location.current_temp,
                humidity_pct=location.current_humidity,
                wind_speed_mph=location.current_wind_speed or 0,
                dew_point_c=dew_point_c,
            )

        timestamp = obs_props.get("timestamp")
        if timestamp:
            location.last_observation_time = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )

        location.save()
        return True

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

        # Only show locations in session
        location_ids = self.request.session.get("location_ids", [])
        queryset = queryset.filter(id__in=location_ids)

        return queryset.annotate(forecast_count=Count("forecasts"))

    def perform_create(self, serializer):
        """Save location and add to session."""
        location = serializer.save()

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
                    geocode_url = f"https://nominatim.openstreetmap.org/search?postalcode={location.zip_code}&country=US&format=json&limit=1"
                else:
                    # Otherwise geocode the name
                    geocode_url = f"https://nominatim.openstreetmap.org/search?q={location.name}&format=json&limit=1"

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

        # Automatically fetch current conditions after creating location
        if location.latitude and location.longitude:
            try:
                fetch_current_conditions(location)
            except Exception as e:
                logger.warning(
                    f"Could not fetch initial conditions for {location.name}: {str(e)}"
                )

    @action(detail=True, methods=["get", "post"])
    def forecasts(self, request, pk=None):
        """Get forecasts for a specific location or create a custom forecast."""
        location = self.get_object()

        if request.method == "POST":
            # Create a custom forecast
            data = request.data.copy()
            data["location"] = location.id

            # Check if this is the first forecast in a batch (indicated by a special header or parameter)
            # If so, clear all existing forecasts to start fresh
            is_batch_start = request.data.get("_batch_start", False)
            if is_batch_start:
                DailyForecast.objects.filter(location=location).delete()

            # Parse the date and period
            forecast_date = data.get("date")
            is_daytime = data.get("is_daytime", True)

            if forecast_date:
                data["forecast_date"] = forecast_date

                # Calculate period_start and period_end
                forecast_date_obj = datetime.strptime(forecast_date, "%Y-%m-%d").date()
                if is_daytime:
                    # Day period: 6 AM to 6 PM
                    period_start = datetime.combine(forecast_date_obj, time(6, 0))
                    period_end = datetime.combine(forecast_date_obj, time(18, 0))
                else:
                    # Night period: 6 PM to 6 AM next day
                    period_start = datetime.combine(forecast_date_obj, time(18, 0))
                    period_end = datetime.combine(
                        forecast_date_obj + timedelta(days=1), time(6, 0)
                    )

                data["period_start"] = period_start.isoformat()
                data["period_end"] = period_end.isoformat()

                # Set default values for required fields if not provided
                if "wind_speed" not in data:
                    data["wind_speed"] = 0
                if "wind_direction" not in data:
                    data["wind_direction"] = ""

                # Check if forecast already exists and update it
                existing_forecast = DailyForecast.objects.filter(
                    location=location,
                    forecast_date=forecast_date_obj,
                    is_daytime=is_daytime,
                ).first()

                if existing_forecast:
                    # Update existing forecast
                    serializer = DailyForecastSerializer(
                        existing_forecast, data=data, partial=True
                    )
                else:
                    # Create new forecast
                    serializer = DailyForecastSerializer(data=data)

                if serializer.is_valid():
                    serializer.save(location=location)
                    return Response(
                        serializer.data,
                        status=status.HTTP_200_OK
                        if existing_forecast
                        else status.HTTP_201_CREATED,
                    )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            return Response(
                {"error": "forecast_date is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # GET request - return forecasts
        forecast_type = request.query_params.get("type", "daily")
        days = int(request.query_params.get("days", 5))

        end_date = timezone.now().date() + timedelta(days=days)

        if forecast_type == "hourly":
            forecasts = HourlyForecast.objects.filter(
                location=location, forecast_date__lte=end_date
            ).order_by("period_start")
            serializer = HourlyForecastSerializer(forecasts, many=True)
        else:
            forecasts = DailyForecast.objects.filter(
                location=location, forecast_date__lte=end_date
            ).order_by("forecast_date")
            serializer = DailyForecastSerializer(forecasts, many=True)

        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def alerts(self, request, pk=None):
        """Get active alerts for a specific location."""
        location = self.get_object()
        alerts = WeatherAlert.objects.filter(
            location=location, is_active=True, expires__gt=timezone.now()
        ).order_by("-severity", "-onset")

        serializer = WeatherAlertSerializer(alerts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="hourly-forecasts")
    def hourly_forecasts(self, request, pk=None):
        """Create custom hourly forecast for a location."""
        location = self.get_object()
        data = request.data.copy()
        data["location"] = location.id

        # Check if this is the first forecast in a batch
        is_batch_start = request.data.get("_batch_start", False)
        if is_batch_start:
            HourlyForecast.objects.filter(location=location).delete()

        # Parse forecast_time
        forecast_time = data.get("forecast_time")
        if not forecast_time:
            return Response(
                {"error": "forecast_time is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Convert to datetime
        from dateutil import parser as date_parser

        forecast_time_obj = date_parser.isoparse(forecast_time)

        # Set period_start and period_end (1-hour window)
        data["period_start"] = forecast_time_obj.isoformat()
        period_end = forecast_time_obj + timedelta(hours=1)
        data["period_end"] = period_end.isoformat()
        data["forecast_date"] = forecast_time_obj.date().isoformat()

        # Set default values
        if "wind_speed" not in data:
            data["wind_speed"] = 0
        if "wind_direction" not in data:
            data["wind_direction"] = ""

        # Check if forecast already exists and update it
        existing_forecast = HourlyForecast.objects.filter(
            location=location, period_start=forecast_time_obj
        ).first()

        if existing_forecast:
            serializer = HourlyForecastSerializer(
                existing_forecast, data=data, partial=True
            )
        else:
            serializer = HourlyForecastSerializer(data=data)

        if serializer.is_valid():
            serializer.save(location=location)
            return Response(
                serializer.data,
                status=status.HTTP_200_OK
                if existing_forecast
                else status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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

            # Kick off a forecast refresh (best-effort)
            try:
                from .services import SyncWeatherService

                SyncWeatherService.update_forecasts_for_location(location)
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
            # Fetch forecast data from NWS API
            import requests

            # Get grid point data
            grid_url = f"https://api.weather.gov/points/{location.latitude},{location.longitude}"
            headers = {"User-Agent": "(Weather App, contact@example.com)"}

            grid_response = requests.get(grid_url, headers=headers, timeout=10)
            grid_response.raise_for_status()
            grid_data = grid_response.json()

            # Update NWS grid info
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

                    # Get first station
                    stations = stations_data.get("features", [])
                    if stations:
                        station_id = (
                            stations[0].get("properties", {}).get("stationIdentifier")
                        )
                        if station_id:
                            # Get latest observation
                            obs_url = f"https://api.weather.gov/stations/{station_id}/observations/latest"
                            obs_response = requests.get(
                                obs_url, headers=headers, timeout=10
                            )
                            obs_response.raise_for_status()
                            obs_data = obs_response.json()

                            obs_props = obs_data.get("properties", {})

                            # Extract current conditions
                            temp_c = obs_props.get("temperature", {}).get("value")
                            if temp_c:
                                # Convert Celsius to Fahrenheit
                                location.current_temp = int(temp_c * 9 / 5 + 32)

                            location.current_conditions = obs_props.get(
                                "textDescription", ""
                            )

                            humidity = obs_props.get("relativeHumidity", {}).get(
                                "value"
                            )
                            if humidity:
                                location.current_humidity = int(humidity)

                            wind_speed_kmh = obs_props.get("windSpeed", {}).get("value")
                            if wind_speed_kmh is not None:
                                try:
                                    # Wind speed from NWS is in km/h, convert to mph
                                    location.current_wind_speed = int(
                                        wind_speed_kmh * 0.621371
                                    )
                                except (ValueError, TypeError):
                                    location.current_wind_speed = 0
                            else:
                                location.current_wind_speed = 0

                            # Wind gust
                            wind_gust_kmh = obs_props.get("windGust", {}).get("value")
                            if wind_gust_kmh is not None:
                                try:
                                    location.current_wind_gust = int(
                                        wind_gust_kmh * 0.621371
                                    )
                                except (ValueError, TypeError):
                                    location.current_wind_gust = None
                            else:
                                location.current_wind_gust = None

                            wind_dir_deg = obs_props.get("windDirection", {}).get(
                                "value"
                            )
                            if wind_dir_deg is not None:
                                # Convert degrees to cardinal direction
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
                                    location.current_wind_direction = directions[
                                        int((deg + 22.5) / 45) % 8
                                    ]
                                except (ValueError, TypeError):
                                    location.current_wind_direction = ""
                            else:
                                location.current_wind_direction = ""

                            # Calculate apparent temperature
                            if location.current_temp is not None:
                                dew_point_c = obs_props.get("dewpoint", {}).get("value")
                                location.current_apparent_temp = (
                                    calculate_apparent_temperature(
                                        temp_f=location.current_temp,
                                        humidity_pct=location.current_humidity,
                                        wind_speed_mph=location.current_wind_speed or 0,
                                        dew_point_c=dew_point_c,
                                    )
                                )

                            timestamp = obs_props.get("timestamp")
                            if timestamp:
                                location.last_observation_time = datetime.fromisoformat(
                                    timestamp.replace("Z", "+00:00")
                                )

                            # Save current conditions including apparent temperature
                            location.save()
            except Exception as e:
                print(f"Warning: Could not fetch current conditions: {str(e)}")

            # Get forecast URL
            forecast_url = properties.get("forecast")
            if not forecast_url:
                raise Exception("No forecast URL available")

            # Fetch forecast data
            forecast_response = requests.get(forecast_url, headers=headers, timeout=10)
            forecast_response.raise_for_status()
            forecast_data = forecast_response.json()

            # Parse and save forecast periods
            periods = forecast_data.get("properties", {}).get("periods", [])

            # Clear old forecasts (both daily and hourly, including custom)
            DailyForecast.objects.filter(location=location).delete()
            HourlyForecast.objects.filter(
                location=location
            ).delete()  # Clear all hourly including custom

            # Helper function to parse wind speed
            def parse_wind_speed(wind_speed_str):
                """Extract numeric wind speed from string like '10 to 15 mph' or '10 mph'."""
                if not wind_speed_str:
                    return 0
                import re

                # Extract all numbers from the string
                numbers = re.findall(r"\d+", str(wind_speed_str))
                if numbers:
                    # If range like "10 to 15", take the average
                    if len(numbers) > 1:
                        return int((int(numbers[0]) + int(numbers[1])) / 2)
                    return int(numbers[0])
                return 0

            # Create new forecasts
            for period in periods[:14]:  # Get up to 14 periods (7 days)
                raw_start = datetime.fromisoformat(
                    period["startTime"].replace("Z", "+00:00")
                )
                local_start = raw_start.astimezone(timezone.get_current_timezone())
                raw_end = datetime.fromisoformat(
                    period["endTime"].replace("Z", "+00:00")
                )
                local_end = raw_end.astimezone(timezone.get_current_timezone())
                DailyForecast.objects.create(
                    location=location,
                    forecast_date=local_start.date(),
                    period_start=local_start,
                    period_end=local_end,
                    is_daytime=period.get("isDaytime", True),
                    temperature=period.get("temperature"),
                    temperature_unit=period.get("temperatureUnit", "F"),
                    wind_speed=parse_wind_speed(period.get("windSpeed", "")),
                    wind_direction=period.get("windDirection", ""),
                    short_forecast=period.get("shortForecast", ""),
                    detailed_forecast=period.get("detailedForecast", ""),
                    precipitation_probability=period.get(
                        "probabilityOfPrecipitation", {}
                    ).get("value"),
                    nws_data_url=forecast_url,  # Mark as NWS forecast
                )

            # Fetch weather alerts
            alerts_created = 0
            alerts_updated = 0
            try:
                # Get active alerts for this location
                alerts_url = f"https://api.weather.gov/alerts/active?point={location.latitude},{location.longitude}"
                alerts_response = requests.get(alerts_url, headers=headers, timeout=10)
                alerts_response.raise_for_status()
                alerts_data = alerts_response.json()

                # Deactivate old alerts for this location
                from weather.models import WeatherAlert

                WeatherAlert.objects.filter(location=location).update(is_active=False)

                # Process each alert
                features = alerts_data.get("features", [])
                for feature in features:
                    props = feature.get("properties", {})
                    nws_id = props.get("id")

                    if not nws_id:
                        continue

                    # Parse dates
                    onset = props.get("onset")
                    expires = props.get("expires")

                    if onset:
                        onset = datetime.fromisoformat(onset.replace("Z", "+00:00"))
                    if expires:
                        expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))

                    # Create or update alert
                    alert, created = WeatherAlert.objects.update_or_create(
                        nws_alert_id=nws_id,
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

                    if created:
                        alerts_created += 1
                    else:
                        alerts_updated += 1

            except requests.exceptions.RequestException as e:
                # Don't fail the entire update if alerts fail
                print(f"Warning: Failed to fetch alerts: {str(e)}")
            except Exception as e:
                print(f"Warning: Error processing alerts: {str(e)}")

            # Update location
            location.last_forecast_update = timezone.now()
            location.save()

            return Response(
                {
                    "status": "success",
                    "message": f"Forecast updated for {location.name}",
                    "last_update": location.last_forecast_update,
                    "forecasts_created": len(periods[:14]),
                    "alerts_created": alerts_created,
                    "alerts_updated": alerts_updated,
                }
            )

        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "status": "error",
                    "message": f"Failed to fetch forecast data: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            return Response(
                {"status": "error", "message": f"Error updating forecast: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        """Reorder locations based on provided order."""
        location_order = request.data.get("location_order", [])

        if not location_order:
            return Response(
                {"status": "error", "message": "No location order provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Update display_order for each location
            for index, location_id in enumerate(location_order):
                Location.objects.filter(id=location_id).update(display_order=index)

            return Response({"status": "success", "message": "Location order updated"})
        except Exception as e:
            return Response(
                {"status": "error", "message": f"Error updating order: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"])
    def clear_all(self, request):
        """Delete all saved locations and their related data.
        Only affects persisted locations; the browser 'current location' card is not stored.
        """
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
            # Check if we need to refresh data (older than 1 hour or no data)
            needs_refresh = (
                location.last_forecast_update is None
                or (timezone.now() - location.last_forecast_update > timedelta(hours=1))
                or location.last_observation_time is None
                or (
                    timezone.now() - location.last_observation_time > timedelta(hours=1)
                )
            )
            if needs_refresh:
                try:
                    # Fetch current conditions
                    fetch_current_conditions(location)
                    # Fetch forecasts
                    _refresh_forecasts_for_location(location)
                    location.refresh_from_db()  # Reload to get updated data
                except Exception as e:
                    logger.warning(f"Failed to refresh data for {location.name}: {e}")

        # Get locations with current conditions
        locations_with_current = (
            Location.objects.filter(location_filter)
            .exclude(current_temp__isnull=True)
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
        location.alerts = SimpleNamespace(filter=lambda **k: [])

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
                            temp_c = obs_props.get("temperature", {}).get("value")
                            if temp_c:
                                location.current_temp = int(temp_c * 9 / 5 + 32)

                            location.current_conditions = obs_props.get(
                                "textDescription", ""
                            )

                            humidity = obs_props.get("relativeHumidity", {}).get(
                                "value"
                            )
                            if humidity:
                                location.current_humidity = int(humidity)

                            wind_speed_kmh = obs_props.get("windSpeed", {}).get("value")
                            if wind_speed_kmh is not None:
                                location.current_wind_speed = int(
                                    wind_speed_kmh * 0.621371
                                )

                            wind_gust_kmh = obs_props.get("windGust", {}).get("value")
                            if wind_gust_kmh is not None:
                                location.current_wind_gust = int(
                                    wind_gust_kmh * 0.621371
                                )

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
                                location.current_wind_direction = directions[
                                    int((deg + 22.5) / 45) % 8
                                ]

                            timestamp = obs_props.get("timestamp")
                            if timestamp:
                                location.last_observation_time = datetime.fromisoformat(
                                    timestamp.replace("Z", "+00:00")
                                )
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
                    daily_forecasts.append(
                        SimpleNamespace(
                            forecast_date=local_start.date(),
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
        "AIFS": {
            "url": "https://api.open-meteo.com/v1/ecmwf",
            "models": "ecmwf_aifs025",
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

        FREEZE = 32.0
        SURFACE_SLUSH = 34.0  # allow snow/sleet depiction a bit above freezing
        # Treat any slight warm nose aloft as melting layer (> 32.1°F)
        WARM = 32.1
        # Helper: Fahrenheit to Celsius for SLR/dendritic logic
        def f_to_c(v: float | None) -> float | None:
            if v is None:
                return None
            return (v - 32.0) * (5.0 / 9.0)

        types: list[str] = []
        slrs: list[float] = []

        for i in range(n):
            sf = val(snowfall, i)
            ts = val(temps, i)
            t975v = val(t975, i)
            t950v = val(t950, i)
            t925v = val(t925, i)
            t900v = val(t900, i)
            t875v = val(t875, i)
            t850v = val(t850, i)
            t825v = val(t825, i)
            t800v = val(t800, i)
            t775v = val(t775, i)
            t750v = val(t750, i)
            t725v = val(t725, i)
            t700v = val(t700, i)
            t675v = val(t675, i)
            t650v = val(t650, i)
            t625v = val(t625, i)
            t600v = val(t600, i)
            t575v = val(t575, i)
            t550v = val(t550, i)
            t525v = val(t525, i)
            t500v = val(t500, i)

            # Warmest temperature in column (similar to Kuchera method) in °C
            warmest_f = max(
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
            warmest_c = f_to_c(warmest_f) if warmest_f is not None else None

            # Warm layer: check key melting zone levels (925, 850, 800, 700)
            warm_layer = max(
                [
                    v
                    for v in (
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
                    )
                    if v is not None
                ],
                default=None,
            )
            
            # Peak dendritic growth zone temp (around 550 hPa, evaluate in °C)
            dendritic_c = f_to_c(t550v) if t550v is not None else None

            # If both 925 and 850 are cold, treat column as snow-favoring even if 700 is warmer
            if (t925v is not None and t925v <= FREEZE) and (t850v is not None and t850v <= FREEZE):
                warm_layer = None

            if ts is None:
                types.append("unknown")
                slrs.append(1.0)  # default neutral ratio
                continue

            ptype = "unknown"
            slr = 1.0

            # If a warm layer exists, honor it before snowfall hints to avoid false snow
            if warm_layer is not None and warm_layer > WARM:
                # Melting layer present; determine sleet vs freezing rain.
                # Key factors:
                # 1. Depth/intensity of warm layer (how completely snow melts)
                # 2. Depth/intensity of cold layer below (refreeze potential)
                # 3. Surface temperature (determines if refrozen drops stick or accumulate)
                
                if ts <= FREEZE:
                    # Calculate cold layer depth: how many subfreezing levels below warm layer
                    cold_levels_below_warm = []
                    for temp_val in [ts, t975v, t950v, t925v, t900v, t875v, t850v, t825v]:
                        if temp_val is not None and temp_val <= FREEZE:
                            cold_levels_below_warm.append(temp_val)
                    
                    # Calculate warm layer strength
                    warm_layer_strength = warm_layer - FREEZE  # degrees above freezing
                    warm_layer_depth = 0
                    for temp_val in [t925v, t850v, t800v, t700v]:
                        if temp_val is not None and temp_val > WARM:
                            warm_layer_depth += 1
                    
                    # Decision logic:
                    # Sleet requires: sufficient cold depth below + strong enough cold layer to refreeze
                    # Classic sleet profile: warm nose at 850/800, strong cold at surface/925
                    
                    if len(cold_levels_below_warm) >= 2:
                        # At least 2 subfreezing levels below warm layer
                        avg_cold = sum(cold_levels_below_warm) / len(cold_levels_below_warm)
                        
                        # Strong cold layer (< 28°F average) with deep warm nose = classic sleet
                        if avg_cold <= 28.0 and warm_layer_depth >= 2:
                            ptype = "sleet"
                            slr = 3.0
                        # Moderate cold with shallow warm = possible sleet if very cold
                        elif avg_cold <= 26.0:
                            ptype = "sleet"
                            slr = 3.0
                        # Otherwise: warm layer exists but not enough refreezing = freezing rain
                        else:
                            ptype = "freezing_rain"
                            slr = 0.75
                    else:
                        # Shallow/weak cold layer below warm = freezing rain (drops don't fully refreeze)
                        ptype = "freezing_rain"
                        slr = 0.75
                else:
                    # Surface above freezing = rain
                    ptype = "rain"
                    slr = 1.0
            else:
                # No strong warm layer aloft; allow snowfall flag to set snow
                if sf is not None and sf > 0.01:
                    ptype = "snow"
                    # Estimate SLR based on warmest column temp (Kuchera-like) and dendritic growth
                    if warmest_c is not None:
                        # Adjust SLR based on dendritic growth zone (550 hPa)
                        dendritic_strength = 0.0
                        if dendritic_c is not None:
                            # Peak dendritic growth at -12 to -15°C
                            if -16 <= dendritic_c <= -11:
                                dendritic_strength = 1.0  # strong dendritic zone
                            elif -20 <= dendritic_c < -16 or -11 < dendritic_c <= -8:
                                dendritic_strength = 0.7  # moderate dendritic
                            else:
                                dendritic_strength = 0.3  # weak dendritic

                        # Kuchera-inspired logic with dendritic boost (all thresholds in °C)
                        if warmest_c < -18:
                            slr = 26.0 + (2.0 * dendritic_strength)  # very cold, very light
                        elif warmest_c < -12:
                            slr = 18.0 + (4.0 * dendritic_strength)  # cold, dendritic growth zone
                        elif warmest_c < -5:
                            slr = 10.0 + (2.0 * dendritic_strength)  # moderately cold
                        else:
                            slr = 6.0 + (2.0 * dendritic_strength)  # borderline, denser snow
                    else:
                        slr = 12.0  # default to middle of range
                else:
                    # Surface-driven decision with marginal above-freezing allowance
                    if ts > SURFACE_SLUSH:
                        ptype = "rain"
                        slr = 1.0
                    else:
                        ptype = "snow"
                        # No dendritic zone active, assume moderate snow
                        slr = 10.0

            types.append(ptype)
            slrs.append(slr)

        return types, slrs

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
            import requests
            from datetime import datetime
            from .noaa_service import fetch_noaa_forecast, NOAA_MODELS
            from .noaa_nomads import fetch_gfs_nomads

            # Temporary: rely solely on Open-Meteo for all models (skip NOMADS/NOAA)
            only_open_meteo = True
            # Try cache first to avoid repeated slow fetches
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except Exception:
                lat_f = lat
                lon_f = lon
            cache_key = f"model_detail:{model_name}:{ensemble}:{lat_f}:{lon_f}:days:{forecast_days}"
            cached = cache.get(cache_key)
            if cached is not None:
                data = cached
                # Extract metadata from cached data if present
                model_source = data.get("model_source", "Open-Meteo")
                cycle = data.get("cycle")
                logger.info(f"ModelDetailView cache hit for {cache_key} (source={model_source}, cycle={cycle})")

            # Prefer NOMADS GRIB for GFS deterministic/ensemble to get full fields
            # Use 45s timeout to allow fetching many forecast hours despite 404s
            if not only_open_meteo and not data and model_name == "GFS":
                try:
                    nomads_start = time.time()
                    logger.info(f"Attempting NOMADS fetch for GFS {ensemble} at {lat},{lon}")
                    nomads_data = fetch_gfs_nomads(float(lat), float(lon), ensemble, timeout=45)
                    if nomads_data:
                        data = nomads_data
                        model_source = nomads_data.get("model_source", "NOAA-NOMADS")
                        cycle = nomads_data.get("cycle")
                        forecast_hours = nomads_data.get("forecast_hours")
                        # Ensure metadata is in the data dict for caching
                        data["model_source"] = model_source
                        data["cycle"] = cycle
                        nomads_elapsed = time.time() - nomads_start
                        logger.info(f"NOMADS successful in {nomads_elapsed:.2f}s: {len(data.get('hourly', {}).get('time', []))} time points")
                        if data.get("hourly", {}).get("time"):
                            first_time = data["hourly"]["time"][0]
                            run_time = datetime.fromisoformat(
                                str(first_time).replace("Z", "+00:00")
                            )
                        # Cache NOMADS result with metadata
                        cache.set(cache_key, data, timeout=getattr(settings, "MODEL_DETAIL_CACHE_SECONDS", getattr(settings, "CACHE_TIMEOUT", 300)))
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
                        config["url"], params=params, headers=headers, timeout=int(os.getenv("OPEN_METEO_TIMEOUT", "15"))
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    model_source = "Open-Meteo"
                    cycle = None  # Open-Meteo doesn't provide cycle info
                    # Inject metadata into data dict for caching
                    data["model_source"] = model_source
                    data["cycle"] = cycle
                    if data.get("hourly", {}).get("time"):
                        first_time = data["hourly"]["time"][0]
                        run_time = datetime.fromisoformat(
                            first_time.replace("Z", "+00:00")
                        )
                    om_elapsed = time.time() - om_start
                    logger.info(f"Open-Meteo fetched in {om_elapsed:.2f}s")
                    cache.set(cache_key, data, timeout=getattr(settings, "MODEL_DETAIL_CACHE_SECONDS", getattr(settings, "CACHE_TIMEOUT", 300)))
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
                        cache.set(cache_key, data, timeout=getattr(settings, "MODEL_DETAIL_CACHE_SECONDS", getattr(settings, "CACHE_TIMEOUT", 300)))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        f"NOAA fetch failed for {model_name} after other fallbacks: {exc}"
                    )

            # Fallback for all other models (ICON, ECMWF, AIFS, GEM, etc.) - use Open-Meteo
            if not data and model_name != "GFS":
                try:
                    om_start = time.time()
                    logger.info(f"Fetching {model_name} from Open-Meteo at {lat},{lon}")
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
                        config["url"], params=params, headers=headers, timeout=int(os.getenv("OPEN_METEO_TIMEOUT", "15"))
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    model_source = "Open-Meteo"
                    cycle = None  # Open-Meteo doesn't provide cycle info
                    # Inject metadata into data dict for caching
                    data["model_source"] = model_source
                    data["cycle"] = cycle
                    if data.get("hourly", {}).get("time"):
                        first_time = data["hourly"]["time"][0]
                        run_time = datetime.fromisoformat(
                            first_time.replace("Z", "+00:00")
                        )
                    om_elapsed = time.time() - om_start
                    logger.info(f"Open-Meteo {model_name} fetched in {om_elapsed:.2f}s")
                    cache.set(cache_key, data, timeout=getattr(settings, "MODEL_DETAIL_CACHE_SECONDS", getattr(settings, "CACHE_TIMEOUT", 300)))
                except Exception as exc:  # noqa: BLE001
                    om_elapsed = time.time() - om_start
                    logger.warning(f"Open-Meteo {model_name} failed in {om_elapsed:.2f}s: {exc}")
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
            locations_qs = Location.objects.filter(
                is_active=True
            ).order_by("-is_current_location", "display_order", "name")

        # Trim hourly data to requested forecast_days window to reduce JSON payload
        if data and data.get("hourly") and data["hourly"].get("time"):
            try:
                from datetime import timedelta
                times = data["hourly"]["time"]
                if times:
                    first_time = datetime.fromisoformat(str(times[0]).replace("Z", "+00:00"))
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
                        logger.info(f"Trimmed hourly data from {len(times)} to {trim_idx} points (forecast_days={forecast_days})")
            except Exception as e:
                logger.warning(f"Failed to trim hourly data: {e}")

        # Derive precip phase (snow/sleet/freezing_rain/rain) and SLRs per hour
        if data and data.get("hourly"):
            try:
                precip_types, slrs = self._classify_precip_types(data["hourly"])
                data["hourly"]["precip_type"] = precip_types
                data["hourly"]["snow_liquid_ratio"] = slrs
                logger.info(f"Derived precip_type and SLRs for {len(precip_types)} hours")
            except Exception as e:
                logger.warning(f"Failed to classify precip types: {e}")
        
        # Inject metadata into data dict so it's available in the frontend
        if data:
            data["model_source"] = model_source
            data["cycle"] = cycle
            data["elevation"] = data.get("elevation")  # preserve existing elevation if present
        
        # Convert to list to ensure it's always a renderable object
        locations_list = list(locations_qs)
        locations_payload = [
            {
                "id": str(loc.id),
                "display_name": loc.display_name,
                "latitude": float(loc.latitude) if loc.latitude is not None else None,
                "longitude": float(loc.longitude) if loc.longitude is not None else None,
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
        # Filter by session - show all locations including disabled ones on location list page
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
            # Check if current conditions need updating (older than 30 minutes or don't exist)
            needs_update = (
                not location.last_observation_time
                or timezone.now() - location.last_observation_time
                > timedelta(minutes=30)
            )

            if needs_update:
                fetch_current_conditions(location)

            # Get today's daytime forecast (NWS only)
            today_forecast = (
                DailyForecast.objects.filter(
                    location=location, forecast_date=today, is_daytime=True
                )
                .exclude(nws_data_url="")
                .first()
            )  # Only show NWS forecasts on location list

            # Get active alerts
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
        return Location.objects.filter(is_active=True).prefetch_related("alerts")

    def get(self, request, *args, **kwargs):
        """Override get to trigger forecast update on page load."""
        self.object = self.get_object()

        # Check if forecast needs updating (older than 1 hour or doesn't exist)
        from datetime import timedelta

        needs_update = (
            not self.object.last_forecast_update
            or timezone.now() - self.object.last_forecast_update > timedelta(hours=1)
        )

        if needs_update and self.object.latitude and self.object.longitude:
            # Fetch current conditions first
            fetch_current_conditions(self.object)

            # Update forecast data
            try:
                from datetime import datetime

                import requests

                headers = {"User-Agent": "(Weather App, contact@example.com)"}

                # Get grid point data
                grid_url = f"https://api.weather.gov/points/{self.object.latitude},{self.object.longitude}"
                grid_response = requests.get(grid_url, headers=headers, timeout=10)
                grid_response.raise_for_status()
                grid_data = grid_response.json()

                # Update NWS grid info
                properties = grid_data.get("properties", {})
                self.object.nws_office = properties.get("gridId", "")
                self.object.grid_x = properties.get("gridX")
                self.object.grid_y = properties.get("gridY")

                # Get forecast URL
                forecast_url = properties.get("forecast")
                if forecast_url:
                    # Fetch forecast data
                    forecast_response = requests.get(
                        forecast_url, headers=headers, timeout=10
                    )
                    forecast_response.raise_for_status()
                    forecast_data = forecast_response.json()

                    # Parse and save forecast periods
                    periods = forecast_data.get("properties", {}).get("periods", [])

                    # Clear old forecasts
                    DailyForecast.objects.filter(location=self.object).delete()

                    # Helper function to parse wind speed
                    def parse_wind_speed(wind_speed_str):
                        if not wind_speed_str:
                            return 0
                        import re

                        numbers = re.findall(r"\d+", str(wind_speed_str))
                        if numbers:
                            if len(numbers) > 1:
                                return int((int(numbers[0]) + int(numbers[1])) / 2)
                            return int(numbers[0])
                        return 0

                    # Create new forecasts
                    for period in periods[:14]:
                        DailyForecast.objects.create(
                            location=self.object,
                            forecast_date=datetime.fromisoformat(
                                period["startTime"].replace("Z", "+00:00")
                            ).date(),
                            period_start=datetime.fromisoformat(
                                period["startTime"].replace("Z", "+00:00")
                            ),
                            period_end=datetime.fromisoformat(
                                period["endTime"].replace("Z", "+00:00")
                            ),
                            is_daytime=period.get("isDaytime", True),
                            temperature=period.get("temperature"),
                            temperature_unit=period.get("temperatureUnit", "F"),
                            wind_speed=parse_wind_speed(period.get("windSpeed", "")),
                            wind_direction=period.get("windDirection", ""),
                            short_forecast=period.get("shortForecast", ""),
                            detailed_forecast=period.get("detailedForecast", ""),
                            precipitation_probability=period.get(
                                "probabilityOfPrecipitation", {}
                            ).get("value"),
                            nws_data_url=forecast_url,  # Mark as NWS forecast
                        )

                    # Fetch weather alerts
                    try:
                        from weather.models import WeatherAlert

                        alerts_url = f"https://api.weather.gov/alerts/active?point={self.object.latitude},{self.object.longitude}"
                        alerts_response = requests.get(
                            alerts_url, headers=headers, timeout=10
                        )
                        alerts_response.raise_for_status()
                        alerts_data = alerts_response.json()

                        # Deactivate old alerts
                        WeatherAlert.objects.filter(location=self.object).update(
                            is_active=False
                        )

                        # Process each alert
                        features = alerts_data.get("features", [])
                        for feature in features:
                            props = feature.get("properties", {})
                            nws_id = props.get("id")

                            if not nws_id:
                                continue

                            # Parse dates
                            onset = props.get("onset")
                            expires = props.get("expires")

                            if onset:
                                onset = datetime.fromisoformat(
                                    onset.replace("Z", "+00:00")
                                )
                            if expires:
                                expires = datetime.fromisoformat(
                                    expires.replace("Z", "+00:00")
                                )

                            # Create or update alert
                            WeatherAlert.objects.update_or_create(
                                nws_alert_id=nws_id,
                                defaults={
                                    "location": self.object,
                                    "event": props.get("event", "Unknown"),
                                    "headline": props.get("headline", ""),
                                    "description": props.get("description", ""),
                                    "severity": props.get(
                                        "severity", "unknown"
                                    ).lower(),
                                    "urgency": props.get("urgency", "unknown").lower(),
                                    "onset": onset,
                                    "expires": expires,
                                    "is_active": True,
                                    "raw_data": props,
                                },
                            )
                    except Exception as e:
                        print(f"Warning: Failed to fetch alerts: {str(e)}")

                    # Update location
                    self.object.last_forecast_update = timezone.now()
                    self.object.save()

            except Exception as e:
                print(f"Warning: Failed to update forecast: {str(e)}")

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
        threshold = timezone.now() - timedelta(minutes=30)

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
                # Try backend service first
                try:
                    from .services import SyncWeatherService

                    SyncWeatherService.update_forecasts_for_location(loc)
                except Exception:
                    # Service failed, fallback to direct NWS
                    _refresh_forecasts_for_location(loc)
                else:
                    # If service didn't create forecasts, fallback
                    has_after = DailyForecast.objects.filter(
                        location=loc, forecast_date__gte=timezone.now().date()
                    ).exists()
                    if not has_after:
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
            .exclude(current_temp__isnull=True)
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

        locations = (
            Location.objects.filter(is_active=True)
            .order_by("-is_current_location", "display_order", "name")
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
            except (Location.DoesNotExist, requests.RequestException) as e:
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
