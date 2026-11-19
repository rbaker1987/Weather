"""Place search: turn text (city, ZIP, or "lat,lon") into place URLs."""

import logging
import re
from urllib.parse import quote

from django.urls import reverse
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from weather.place_service import validate_coordinates
from weather.upstream import get_json

logger = logging.getLogger("weather")

GEOCODER_URL = "https://geocoding-api.open-meteo.com/v1/search"
GEOCODER_TIMEOUT = 8
GEOCODER_CACHE_SECONDS = 24 * 60 * 60
MAX_RESULTS = 5
MAX_QUERY_LENGTH = 200
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class GeocodeThrottle(AnonRateThrottle):
    rate = "60/minute"


def _parse_coordinates(query):
    """Return the two numbers in "lat, lon" / "lat lon" text, or None."""
    parts = [part for part in re.split(r"[,\s]+", query) if part]
    if len(parts) == 2 and all(_NUMBER.fullmatch(part) for part in parts):
        return parts
    return None


def place_url(latitude, longitude, name=None):
    """Build the stateless place URL for coordinates and an optional label."""
    path = reverse(
        "weather:place", kwargs={"coords": f"{latitude:.4f},{longitude:.4f}"}
    )
    return f"{path}?name={quote(name)}" if name else path


def _result(latitude, longitude, label):
    return {
        "label": label,
        "latitude": latitude,
        "longitude": longitude,
        "url": place_url(latitude, longitude, label),
    }


def _label(item):
    parts = [item.get("name"), item.get("admin1"), item.get("country_code")]
    return ", ".join(part for part in parts if part)


class GeocodeAPIView(APIView):
    """GET /api/geocode/?q=Austin, TX  ->  {"results": [{label, url, ...}]}"""

    permission_classes = []
    throttle_classes = [GeocodeThrottle]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if not query:
            return Response({"error": "q parameter is required"}, status=400)
        if len(query) > MAX_QUERY_LENGTH:
            return Response({"error": "q parameter is too long"}, status=400)

        coordinates = _parse_coordinates(query)
        if coordinates:
            try:
                latitude, longitude = validate_coordinates(*coordinates)
            except ValueError:
                return Response({"error": "Coordinates out of range"}, status=400)
            label = f"{latitude:.4f}, {longitude:.4f}"
            return Response({"results": [_result(latitude, longitude, label)]})

        try:
            items = (
                get_json(
                    GEOCODER_URL,
                    params={
                        "name": query,
                        "count": MAX_RESULTS,
                        "language": "en",
                        "format": "json",
                    },
                    timeout=GEOCODER_TIMEOUT,
                    ttl=GEOCODER_CACHE_SECONDS,
                ).get("results")
                or []
            )
        except Exception as exc:
            logger.warning("Geocoding failed for %r: %s", query, exc)
            return Response({"error": "Place search is unavailable"}, status=502)

        results = [
            _result(item["latitude"], item["longitude"], _label(item))
            for item in items
            if "latitude" in item and "longitude" in item
        ]
        return Response({"results": results})
