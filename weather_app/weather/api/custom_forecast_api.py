from datetime import datetime, time, timedelta

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import CustomDailyForecast, Location


class CustomForecastAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        location_id = request.GET.get("location_id")
        if not location_id:
            return Response(
                {"error": "location_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        location = Location.objects.filter(id=location_id, owner=request.user).first()
        if not location:
            return Response(
                {"error": "Location not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        custom_qs = CustomDailyForecast.objects.filter(
            owner=request.user, location=location
        ).order_by("forecast_date", "-is_daytime")

        days = _build_days_payload(custom_qs)
        return Response({"location_id": str(location.id), "days": days})

    def post(self, request):
        # Get location_id from query params or request body
        location_id = request.GET.get("location_id") or request.data.get("location_id")
        days = request.data.get("days", [])

        if not location_id:
            return Response(
                {"error": "location_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        location = Location.objects.filter(id=location_id, owner=request.user).first()
        if not location:
            return Response(
                {"error": "Location not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not isinstance(days, list):
            return Response(
                {"error": "days must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not days:
            CustomDailyForecast.objects.filter(
                owner=request.user, location=location
            ).delete()
            return Response({"status": "cleared"})

        updated = 0
        for day in days:
            date_value = _parse_date(day.get("date"))
            if not date_value:
                continue

            updated += _upsert_period(
                request.user,
                location,
                date_value,
                False,
                day.get("morning_temp"),
                day.get("morning_weather"),
            )
            updated += _upsert_period(
                request.user,
                location,
                date_value,
                True,
                day.get("afternoon_temp"),
                day.get("afternoon_weather"),
            )

        return Response({"status": "saved", "count": updated})

    def delete(self, request):
        location_id = request.GET.get("location_id")
        if not location_id:
            return Response(
                {"error": "location_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        location = Location.objects.filter(id=location_id, owner=request.user).first()
        if not location:
            return Response(
                {"error": "Location not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        deleted, _ = CustomDailyForecast.objects.filter(
            owner=request.user, location=location
        ).delete()
        return Response({"status": "cleared", "count": deleted})


def _build_days_payload(queryset):
    days_by_date = {}
    for forecast in queryset:
        date_key = forecast.forecast_date.isoformat()
        day = days_by_date.setdefault(
            date_key,
            {
                "date": date_key,
                "morning_temp": None,
                "morning_weather": "",
                "afternoon_temp": None,
                "afternoon_weather": "",
            },
        )
        if forecast.is_daytime:
            day["afternoon_temp"] = forecast.temperature
            day["afternoon_weather"] = forecast.short_forecast
        else:
            day["morning_temp"] = forecast.temperature
            day["morning_weather"] = forecast.short_forecast

    return [days_by_date[key] for key in sorted(days_by_date.keys())]


def _parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).date()
    except ValueError:
        return None


def _parse_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _upsert_period(owner, location, forecast_date, is_daytime, temp, weather):
    temperature = _parse_int(temp)
    short_forecast = (weather or "").strip()

    if temperature is None and not short_forecast:
        deleted, _ = CustomDailyForecast.objects.filter(
            owner=owner,
            location=location,
            forecast_date=forecast_date,
            is_daytime=is_daytime,
        ).delete()
        return deleted

    start_time = time(15, 0) if is_daytime else time(6, 0)

    period_start = timezone.make_aware(datetime.combine(forecast_date, start_time))
    period_end = period_start + timedelta(hours=12)

    CustomDailyForecast.objects.update_or_create(
        owner=owner,
        location=location,
        forecast_date=forecast_date,
        is_daytime=is_daytime,
        defaults={
            "period_start": period_start,
            "period_end": period_end,
            "temperature": temperature or 0,
            "temperature_unit": "F",
            "apparent_temperature": temperature,
            "short_forecast": short_forecast or "Custom forecast",
            "detailed_forecast": short_forecast,
            "wind_speed": 0,
            "wind_direction": "",
            "wind_gust": None,
            "precipitation_probability": None,
        },
    )
    return 1
