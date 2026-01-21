import logging
from datetime import datetime
from datetime import timezone as dt_timezone

import pytz
import requests
from astral import LocationInfo
from astral.sun import sun
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from timezonefinder import TimezoneFinder

from ..models import HourlyForecast, Location
from ..utils.apparent_temperature import calculate_apparent_temperature

# Simple in-memory cache for timezone lookups keyed by rounded lat/lon
_TZ_CACHE = {}

logger = logging.getLogger("weather")


class HourlyForecastForLocationAPIView(APIView):
    """
    Returns hourly forecast for a location and date, or next N hours for lat/lon.
    GET params:
      - lat, lon: coordinates (required for next N hours)
      - date: YYYY-MM-DD (optional, for daily modal)
      - hours: int (optional, default 6)
    """

    def get(self, request):
        lat = request.GET.get("lat")
        lon = request.GET.get("lon")
        date_str = request.GET.get("date")
        hours_count = int(request.GET.get("hours", 6))

        if not lat or not lon:
            return Response(
                {"error": "lat and lon are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            lat_f = float(lat)
            lon_f = float(lon)

            # Determine timezone for provided lat/lon
            try:
                key = (round(lat_f, 2), round(lon_f, 2))
                tz_name = _TZ_CACHE.get(key)
                if not tz_name:
                    tf = TimezoneFinder()
                    tz_name = tf.timezone_at(lat=lat_f, lng=lon_f) or "UTC"
                    _TZ_CACHE[key] = tz_name
            except Exception:
                tz_name = "UTC"

            # Get location by coordinates to check for custom hourly forecasts
            location = None
            try:
                # Find location that matches these coordinates (within small tolerance)
                from decimal import Decimal

                lat_decimal = Decimal(str(lat_f))
                lon_decimal = Decimal(str(lon_f))
                tolerance = Decimal("0.01")

                location = Location.objects.filter(
                    latitude__gte=lat_decimal - tolerance,
                    latitude__lte=lat_decimal + tolerance,
                    longitude__gte=lon_decimal - tolerance,
                    longitude__lte=lon_decimal + tolerance,
                    is_active=True,
                ).first()
            except Exception as e:
                logger.debug(f"Could not find location for coordinates: {e}")

            # Fetch NWS hourly forecast
            headers = {"User-Agent": "(Weather App, contact@example.com)"}

            # Get grid point
            grid_url = f"https://api.weather.gov/points/{lat_f:.4f},{lon_f:.4f}"
            grid_response = requests.get(grid_url, headers=headers, timeout=10)
            grid_response.raise_for_status()
            grid_data = grid_response.json()

            # Get hourly forecast URL
            hourly_forecast_url = grid_data.get("properties", {}).get("forecastHourly")
            if not hourly_forecast_url:
                return Response(
                    {"error": "Hourly forecast not available"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Fetch hourly forecast
            hourly_response = requests.get(
                hourly_forecast_url, headers=headers, timeout=10
            )
            hourly_response.raise_for_status()
            hourly_data = hourly_response.json()

            periods = hourly_data.get("properties", {}).get("periods", [])

            # Filter by date if provided
            if date_str:
                target_date = parse_date(date_str)
                if target_date:
                    filtered_periods = [
                        p
                        for p in periods
                        if datetime.fromisoformat(
                            p["startTime"].replace("Z", "+00:00")
                        ).date()
                        == target_date
                    ]
                    periods = filtered_periods

            # Limit to requested number of hours
            periods = periods[:hours_count]

            # Build per-date sunrise/sunset map for all dates present in periods
            sun_events = {}
            unique_dates = set()
            tz = pytz.timezone(tz_name) if tz_name else pytz.UTC
            for p in periods:
                try:
                    dt = datetime.fromisoformat(p["startTime"].replace("Z", "+00:00"))
                    # Convert to local timezone to get correct date key
                    dt_local = dt.astimezone(tz)
                    unique_dates.add(dt_local.date())
                except Exception:
                    continue
            for day in sorted(unique_dates):
                sr, ss = self._compute_sunrise_sunset(day, lat_f, lon_f)
                sun_events[day.isoformat()] = {
                    "sunrise": sr.isoformat(),
                    "sunset": ss.isoformat(),
                }

            # Get custom hourly forecasts if location exists
            custom_forecasts_dict = {}
            if location:
                from datetime import timedelta as td

                cutoff_time = timezone.now() - td(hours=1)
                custom_hourly = HourlyForecast.objects.filter(
                    location=location,
                    nws_data_url="",  # Only custom forecasts
                    period_start__gte=cutoff_time,
                ).order_by("period_start")[
                    : hours_count * 2
                ]  # Get extra to ensure coverage

                # Build dictionary keyed by rounded hour for fast lookup
                for custom in custom_hourly:
                    # Round to nearest hour for matching
                    rounded_hour = custom.period_start.replace(
                        minute=0, second=0, microsecond=0
                    )
                    # Store if not already stored or if this one is closer
                    if rounded_hour not in custom_forecasts_dict:
                        custom_forecasts_dict[rounded_hour] = custom
                    else:
                        existing_diff = abs(
                            (
                                custom_forecasts_dict[rounded_hour].period_start
                                - rounded_hour
                            ).total_seconds()
                        )
                        new_diff = abs(
                            (custom.period_start - rounded_hour).total_seconds()
                        )
                        if new_diff < existing_diff:
                            custom_forecasts_dict[rounded_hour] = custom

            # Format for JS, merging custom forecasts where available
            hours_data = []
            for period in periods:
                start_time = datetime.fromisoformat(
                    period["startTime"].replace("Z", "+00:00")
                )
                rounded_hour = start_time.replace(minute=0, second=0, microsecond=0)

                # Check if we have a custom forecast for this hour
                custom_forecast = custom_forecasts_dict.get(rounded_hour)

                if custom_forecast:
                    # Use custom forecast data
                    # Determine is_daytime for icon selection
                    # Use local timezone date to match sun_events keys
                    start_time_local = start_time.astimezone(tz)
                    day_key = start_time_local.date().isoformat()
                    sr_raw = sun_events.get(day_key, {}).get("sunrise")
                    ss_raw = sun_events.get(day_key, {}).get("sunset")
                    if sr_raw and ss_raw:
                        sr_dt = datetime.fromisoformat(sr_raw)
                        ss_dt = datetime.fromisoformat(ss_raw)
                        is_daytime = sr_dt <= start_time < ss_dt
                    else:
                        is_daytime = 6 <= start_time.hour < 18

                    hours_data.append(
                        {
                            "time": start_time.strftime("%I %p").lstrip("0"),
                            "start": start_time.isoformat(),
                            "temp": custom_forecast.temperature,
                            "apparentTemp": custom_forecast.apparent_temperature,
                            "condition": custom_forecast.short_forecast,
                            "icon": self._get_weather_icon(
                                custom_forecast.short_forecast, is_daytime
                            ),
                            "wind": f"{custom_forecast.wind_speed} mph"
                            if custom_forecast.wind_speed
                            else "",
                            "windDir": custom_forecast.wind_direction or "",
                            "windGust": custom_forecast.wind_gust,
                            "pop": custom_forecast.precipitation_probability,
                        }
                    )
                else:
                    # Use NWS forecast data
                    # Extract wind gust
                    wind_gust = None
                    gust_str = period.get("windGust")
                    if gust_str:
                        gust_parts = gust_str.split()
                        if gust_parts:
                            try:
                                wind_gust = int(gust_parts[0])
                            except (ValueError, IndexError):
                                wind_gust = None

                    # Extract precipitation probability
                    precip_prob = None
                    pop = period.get("probabilityOfPrecipitation")
                    if isinstance(pop, dict):
                        value = pop.get("value")
                        if value is not None:
                            try:
                                precip_prob = int(value)
                            except (ValueError, TypeError):
                                precip_prob = None

                    # Extract apparent temperature (feels like)
                    apparent_temp = None
                    app_temp = period.get("apparentTemperature")
                    if isinstance(app_temp, dict):
                        value = app_temp.get("value")
                        if value is not None:
                            try:
                                # Convert from Celsius to Fahrenheit if needed
                                unit = app_temp.get("unitCode", "")
                                if "wmoUnit:degC" in unit:
                                    apparent_temp = int((value * 9 / 5) + 32)
                                else:
                                    apparent_temp = int(value)
                            except (ValueError, TypeError):
                                apparent_temp = None

                    # Calculate apparent temperature if NWS didn't provide it
                    if apparent_temp is None:
                        try:
                            temp = period.get("temperature")
                            humidity_data = period.get("relativeHumidity")
                            wind_speed_str = period.get("windSpeed", "")

                            # Extract humidity percentage
                            humidity = None
                            if isinstance(humidity_data, dict):
                                humidity = humidity_data.get("value")

                            # Extract wind speed (format: "10 mph" or "5 to 10 mph")
                            wind_speed = None
                            if wind_speed_str:
                                parts = wind_speed_str.split()
                                if parts:
                                    try:
                                        wind_speed = int(parts[0])
                                    except (ValueError, IndexError):
                                        pass

                            # Calculate if we have the required data
                            if (
                                temp is not None
                                and humidity is not None
                                and wind_speed is not None
                            ):
                                apparent_temp = calculate_apparent_temperature(
                                    temperature_f=temp,
                                    humidity=humidity,
                                    wind_speed_mph=wind_speed,
                                )
                        except Exception as e:
                            logger.debug(
                                f"Could not calculate apparent temperature: {e}"
                            )

                    # Determine is_daytime using that hour's date-specific sunrise/sunset
                    # Use local timezone date to match sun_events keys
                    start_time_local = start_time.astimezone(tz)
                    day_key = start_time_local.date().isoformat()
                    sr_raw = sun_events.get(day_key, {}).get("sunrise")
                    ss_raw = sun_events.get(day_key, {}).get("sunset")
                    if sr_raw and ss_raw:
                        sr_dt = datetime.fromisoformat(sr_raw)
                        ss_dt = datetime.fromisoformat(ss_raw)
                        is_daytime = sr_dt <= start_time < ss_dt
                    else:
                        # Fallback simple rule
                        is_daytime = 6 <= start_time.hour < 18

                    hours_data.append(
                        {
                            "time": start_time.strftime("%I %p").lstrip("0"),
                            "start": start_time.isoformat(),
                            "temp": period.get("temperature", "N/A"),
                            "apparentTemp": apparent_temp,
                            "condition": period.get("shortForecast", "N/A"),
                            "icon": self._get_weather_icon(
                                period.get("shortForecast", ""), is_daytime
                            ),
                            "wind": period.get("windSpeed", ""),
                            "windDir": period.get("windDirection", ""),
                            "windGust": wind_gust,
                            "pop": precip_prob,
                        }
                    )

            return Response(
                {"hours": hours_data, "sun_events": sun_events, "timezone": tz_name},
                status=status.HTTP_200_OK,
            )

        except requests.RequestException as e:
            logger.error(f"NWS API error: {e}")
            return Response(
                {"error": "Failed to fetch forecast data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            logger.error(f"Error processing hourly forecast: {e}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_weather_icon(self, conditions, is_daytime=True):
        """Return Font Awesome icon name for weather condition."""
        c = conditions.lower()
        if "storm" in c or "thunder" in c or "t-storm" in c:
            return "bolt"
        if "ice" in c or "icy" in c or "freezing" in c or "sleet" in c:
            return "cloud-meatball"  # Frozen falling precip (sleet/freezing rain)
        if "snow" in c or "flurries" in c or "blizzard" in c:
            return "snowflake"
        if "fog" in c or "mist" in c or "haze" in c:
            return "smog"
        if "rain" in c or "shower" in c or "drizzle" in c:
            return "cloud-rain"
        if "wind" in c and "cloudy" not in c:
            return "wind"
        if "partly" in c:
            return "cloud-sun" if is_daytime else "cloud-moon"
        if "sunny" in c or "clear" in c or "fair" in c:
            return "sun" if is_daytime else "moon"
        if "cloud" in c or "overcast" in c:
            return "cloud"
        return "cloud-sun" if is_daytime else "cloud-moon"

    def _compute_sunrise_sunset(self, date, lat, lon):
        """Calculate sunrise and sunset times using Astral library for accuracy.

        Returns UTC datetime objects for sunrise and sunset.
        """
        try:
            # Create location info (name doesn't matter for calculation)
            location = LocationInfo(latitude=lat, longitude=lon)

            # Get sun times for the date in UTC
            s = sun(location.observer, date=date, tzinfo=dt_timezone.utc)

            sunrise_dt = s["sunrise"]
            sunset_dt = s["sunset"]

            return sunrise_dt, sunset_dt

        except Exception as e:
            logger.warning(
                f"Astral sun calculation failed for {date} at lat={lat}, lon={lon}: {e}. Using fallback."
            )
            # Fallback: simple approximation (6 AM and 6 PM UTC)
            sunrise_dt = datetime(
                date.year, date.month, date.day, 6, 0, 0, tzinfo=dt_timezone.utc
            )
            sunset_dt = datetime(
                date.year, date.month, date.day, 18, 0, 0, tzinfo=dt_timezone.utc
            )
            return sunrise_dt, sunset_dt
