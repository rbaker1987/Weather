"""Place search: turn text (city, ZIP, or "lat,lon") into place URLs."""

import logging
import re
from urllib.parse import quote

import requests
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from weather.place_service import validate_coordinates

logger = logging.getLogger("weather")

GEOCODER_URL = "https://geocoding-api.open-meteo.com/v1/search"
GEOCODER_TIMEOUT = 8
MAX_RESULTS = 5
_COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$")


class GeocodeThrottle(AnonRateThrottle):
    rate = "60/minute"


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

        match = _COORDINATES.match(query)
        if match:
            try:
                latitude, longitude = validate_coordinates(*match.groups())
            except ValueError:
                return Response({"error": "Coordinates out of range"}, status=400)
            label = f"{latitude:.4f}, {longitude:.4f}"
            return Response({"results": [_result(latitude, longitude, label)]})

        try:
            response = requests.get(
                GEOCODER_URL,
                params={
                    "name": query,
                    "count": MAX_RESULTS,
                    "language": "en",
                    "format": "json",
                },
                timeout=GEOCODER_TIMEOUT,
            )
            response.raise_for_status()
            items = response.json().get("results") or []
        except Exception as exc:
            logger.warning("Geocoding failed for %r: %s", query, exc)
            return Response({"error": "Place search is unavailable"}, status=502)

        results = [
            _result(item["latitude"], item["longitude"], _label(item))
            for item in items
            if "latitude" in item and "longitude" in item
        ]
        return Response({"results": results})
