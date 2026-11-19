"""Django REST Framework views for weather API."""

import logging
import os
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views import View
from django.views.generic import TemplateView

from .place_service import (
    PANELS,
    build_place,
    is_unsupported_place,
    panel_context,
    validate_coordinates,
)
from .regional_pages import ReportUnavailableError, build_report

logger = logging.getLogger("weather")


# =============================================================================
# Django Web Interface Views
# =============================================================================


class HomeView(TemplateView):
    """Home page: use my location or enter a location (nothing is stored)."""

    template_name = "weather/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Weather"
        return context


class RegionalReportView(TemplateView):
    """A regional report (East Texas, NM Mountains) written elsewhere each morning.

    The text is read on demand from the ralphs-weather-pages data file (see
    ``regional_pages``); if it cannot be loaded the page says so with a 503.
    """

    template_name = "weather/regional/report.html"
    slug = ""
    page_title = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context["report"] = build_report(self.slug)
        except ReportUnavailableError as exc:
            logger.warning("Regional report %s unavailable: %s", self.slug, exc)
            context["report"] = None
        context["page_title"] = self.page_title
        context["theme"] = "et" if self.slug == "east-texas" else "nm"
        return context

    def render_to_response(self, context, **response_kwargs):
        if context["report"] is None:
            response_kwargs["status"] = 503
        return super().render_to_response(context, **response_kwargs)


class ModelsView(TemplateView):
    """View for comparing weather models (place chosen by URL or map picker)."""

    template_name = "weather/models.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Weather Models"
        return context


def _place_context(context, lat, lon, name=None):
    """Fill ``context`` for location_detail.html from coordinates in the request.

    No database rows are created and no upstream call is made here: the place is a
    stand-in object built from the URL, and each panel loads its own data afterwards
    (see ``PlacePanelView``).
    """
    try:
        latitude, longitude = validate_coordinates(lat, lon)
    except ValueError:
        context["error"] = "Latitude and longitude are required and must be valid"
        context["page_title"] = "Weather"
        return context

    place = build_place(latitude, longitude, name)
    context["location"] = place
    context["latitude"] = latitude
    context["longitude"] = longitude
    context["panel_coords"] = f"{latitude:.6f},{longitude:.6f}"
    context["page_title"] = f"Weather - {place.display_name}"
    context["is_temp_location"] = True
    return context


class TempLocationView(TemplateView):
    """Forecast for map-selected coordinates (?latitude=&longitude=)."""

    template_name = "weather/location_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return _place_context(
            context,
            self.request.GET.get("latitude"),
            self.request.GET.get("longitude"),
            self.request.GET.get("name"),
        )


class PlaceView(TemplateView):
    """Forecast for a place carried in the URL: /weather/<lat>,<lon>/?name=."""

    template_name = "weather/location_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lat, _, lon = kwargs["coords"].partition(",")
        return _place_context(context, lat, lon, self.request.GET.get("name"))


class PlacePanelView(View):
    """One panel of the place page (alerts, current conditions or forecast) as HTML.

    The place page loads each panel separately so its first paint never waits on an
    upstream call, and one failing upstream only affects its own panel.
    """

    def get(self, request, coords, panel):
        if panel not in PANELS:
            raise Http404("Unknown panel")
        lat, _, lon = coords.partition(",")
        try:
            latitude, longitude = validate_coordinates(lat, lon)
        except ValueError:
            return HttpResponse("Invalid coordinates", status=400)

        try:
            context = panel_context(panel, latitude, longitude)
        except Exception as exc:
            logger.warning("Place panel %s failed: %s", panel, exc)
            unsupported = is_unsupported_place(exc)
            message = (
                "The National Weather Service does not cover this location."
                if unsupported
                else "This section is unavailable right now."
            )
            response = render(
                request,
                "weather/panels/error.html",
                {"message": message, "retryable": not unsupported},
                status=404 if unsupported else 502,
            )
        else:
            response = render(request, f"weather/panels/{panel}.html", context)
        response["X-Place-Panel"] = (
            "1"  # lets the page tell fragments from proxy error pages
        )
        return response


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
                frzr_slr = min(1.0, 2.0 / max(area_ratio_warm_to_cold, 0.5))
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
        # Ensemble selection
        ensemble = request.GET.get("ens", "det").lower()
        valid_ens = {"det", "control", "mean"} | {f"p{i:02d}" for i in range(1, 31)}
        if ensemble not in valid_ens:
            ensemble = "det"

        data = None
        error = None
        run_time = None
        model_source = "Open-Meteo"
        cycle = None
        forecast_hours = None
        if lat and lon:
            from datetime import datetime

            import requests

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

            # GFS comes from Open-Meteo, which has the richer fields
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
            error = "Latitude/longitude not provided. Choose a place on the map."

        import json

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
                "locations": [],
                "locations_json": "[]",
                "available_models": list(self.MODEL_CONFIGS.keys()),
                "page_title": f"{model_name} Model Details",
            }
        )
        fetch_elapsed = time.time() - fetch_start
        logger.info(f"ModelDetailView completed in {fetch_elapsed:.2f}s")
        return context
