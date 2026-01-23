"""API endpoint for fetching weather model comparison data."""

import logging

import requests
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("weather")


class ModelComparisonAPIView(APIView):
    """API view to fetch weather model data from Open-Meteo."""

    permission_classes = []  # Public endpoint

    # Model configurations with their endpoints and parameters
    MODEL_CONFIGS = {
        "GFS": {
            "url": "https://api.open-meteo.com/v1/gfs",
            "max_days": 16,
        },
        "ICON": {
            "url": "https://api.open-meteo.com/v1/dwd-icon",
            "max_days": 7,
        },
        "ECMWF": {
            "url": "https://api.open-meteo.com/v1/ecmwf",
            "max_days": 10,
        },
        "AIFS": {
            "url": "https://api.open-meteo.com/v1/forecast",
            "max_days": 10,
            "models": "ecmwf_aifs025",
        },
        "GEM": {
            "url": "https://api.open-meteo.com/v1/gem",
            "max_days": 10,
        },
        "HRRR": {
            "url": "https://api.open-meteo.com/v1/forecast",
            "max_days": 2,
            "models": "ncep_hrrr_conus",
        },
        "NAM": {
            "url": "https://api.open-meteo.com/v1/forecast",
            "max_days": 3,
            "models": "ncep_nam_conus",
        },
        "RGEM": {
            "url": "https://api.open-meteo.com/v1/gem",
            "max_days": 2,
            "models": "cmc_gem_rdps",
        },
        "NBM": {
            "url": "https://api.open-meteo.com/v1/gfs",
            "max_days": 11,
            "models": "ncep_nbm_conus",
        },
    }

    def fetch_model_data(
        self,
        model_name: str,
        lat: float,
        lon: float,
        forecast_days: int,
    ) -> dict:
        """Fetch data for a single model."""
        config = self.MODEL_CONFIGS.get(model_name)
        if not config:
            return {"name": model_name, "data": None, "error": "Unknown model"}

        # Skip if location outside declared bounding box (region-limited model)
        bb = config.get("bounding_box")
        if bb and not (
            bb["min_lat"] <= lat <= bb["max_lat"]
            and bb["min_lon"] <= lon <= bb["max_lon"]
        ):
            return {
                "name": model_name,
                "data": None,
                "error": None,
                "skipped": "Outside domain",
            }

        # Build URL parameters
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,temperature_925hPa,temperature_850hPa,precipitation",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "mm",
            "timezone": "auto",
            "forecast_days": min(forecast_days, config["max_days"]),
        }

        # Add models parameter if specified
        if "models" in config:
            params["models"] = config["models"]

        # Add cache-busting headers to ensure latest data
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        }

        try:
            response = requests.get(
                config["url"], params=params, headers=headers, timeout=10.0
            )
            response.raise_for_status()
            data = response.json()

            # Check for API errors
            if "error" in data:
                logger.warning(
                    f"API error for {model_name}: {data.get('reason', 'Unknown')}"
                )
                return {"name": model_name, "data": None, "error": data.get("reason")}

            return {"name": model_name, "data": data, "error": None, "skipped": None}

        except requests.Timeout:
            logger.error(f"Timeout fetching {model_name} data")
            return {
                "name": model_name,
                "data": None,
                "error": "Timeout",
                "skipped": None,
            }
        except requests.HTTPError as e:
            logger.error(f"HTTP error fetching {model_name}: {e}")
            return {
                "name": model_name,
                "data": None,
                "error": f"HTTP {e.response.status_code}",
                "skipped": None,
            }
        except Exception as e:
            logger.error(f"Error fetching {model_name} data: {e}")
            return {"name": model_name, "data": None, "error": str(e), "skipped": None}

    def fetch_all_models(
        self, models: list[str], lat: float, lon: float, forecast_days: int
    ) -> list[dict]:
        """Fetch data for specified models."""
        results = []
        for model_name in models:
            result = self.fetch_model_data(model_name, lat, lon, forecast_days)
            results.append(result)
        return results

    def get(self, request):
        """Handle GET request for model comparison data."""
        # Get query parameters
        lat = request.query_params.get("latitude")
        lon = request.query_params.get("longitude")
        models_param = request.query_params.get("models", "")
        forecast_days = request.query_params.get("forecast_days", "7")

        # Validate parameters
        if not lat or not lon:
            return Response(
                {
                    "status": "error",
                    "error": "latitude and longitude parameters are required",
                },
                status=400,
            )

        if not models_param:
            return Response(
                {"status": "error", "error": "models parameter is required"}, status=400
            )

        try:
            lat = float(lat)
            lon = float(lon)
            forecast_days = int(forecast_days)
            models = [m.strip().upper() for m in models_param.split(",") if m.strip()]
        except (ValueError, TypeError):
            return Response(
                {
                    "status": "error",
                    "error": "Invalid latitude, longitude, or forecast_days",
                },
                status=400,
            )

        # Validate ranges
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return Response(
                {"status": "error", "error": "Invalid latitude or longitude range"},
                status=400,
            )

        if not (1 <= forecast_days <= 16):
            return Response(
                {"status": "error", "error": "forecast_days must be between 1 and 16"},
                status=400,
            )

        # Fetch all model data
        try:
            results = self.fetch_all_models(models, lat, lon, forecast_days)

            # Apply precipitation classification to each model using simple temperature logic
            for result in results:
                if result.get("data") and result.get("data", {}).get("hourly"):
                    hourly = result["data"]["hourly"]
                    temps = hourly.get("temperature_2m", [])
                    precips = hourly.get("precipitation", [])

                    if temps and precips:
                        precip_types = []
                        slrs = []

                        # Simple temperature-based classification for each hour
                        for i in range(len(precips)):
                            temp_f = temps[i] if i < len(temps) else None

                            # Classify based on temperature
                            if temp_f is not None:
                                if temp_f < 28:  # -2.2°C
                                    ptype = "snow"
                                    slr = 15.0
                                elif temp_f < 32:  # 0°C
                                    ptype = "sleet"
                                    slr = 2.0
                                elif temp_f < 37:  # 2.8°C
                                    ptype = "freezing_rain"
                                    slr = 0.3
                                else:
                                    ptype = "rain"
                                    slr = 1.0
                            else:
                                ptype = "rain"
                                slr = 1.0

                            precip_types.append(ptype)
                            slrs.append(slr)

                        # Add to hourly data
                        result["data"]["hourly"]["precip_type"] = precip_types
                        result["data"]["hourly"]["snow_liquid_ratio"] = slrs

            return Response({"status": "success", "models": results})
        except Exception as e:
            logger.error(f"Error fetching model data: {e}")
            import traceback

            traceback.print_exc()
            return Response(
                {"status": "error", "error": "Failed to fetch model data"}, status=500
            )
