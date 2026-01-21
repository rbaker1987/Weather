"""NOAA NOMADS GRIB fetcher for deterministic and ensemble GFS.

This module downloads small GRIB subsets from NOMADS filter endpoints
and decodes them via xarray/cfgrib. It targets upper-air temps, RH,
low-level winds, and precip. Intended as a first slice for GFS/GEFS.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# Supported ensemble modes - fetch up to 240 hours (10 days) to match typical NOMADS availability
# Requesting all 385 hours results in many 404s and unnecessary HTTP requests
DEFAULT_FORECAST_HOURS = list(range(241))  # 0, 1, 2, 3, ..., 240


class GribDecoderUnavailableError(Exception):
    """Raised when cfgrib/xarray or eccodes is missing."""


def _ensure_cfgrib():
    try:
        import cfgrib  # noqa: F401
        import xarray as xr  # noqa: F401
    except Exception as exc:  # pragma: no cover - import guard
        raise GribDecoderUnavailableError(
            "cfgrib/xarray (and eccodes) are required for NOAA GRIB decoding"
        ) from exc


def _latest_cycle(now: datetime) -> int:
    """Return a reliable GFS cycle hour.

    For maximum reliability, always return 12Z, which:
    - Is published around 15:30-16:00 UTC every day
    - Has time to fully populate on NOMADS (file completion can take 1-2 hours)
    - Is available from every day in the past (no "latest" edge case)

    This is conservative but ensures data is always available.
    """
    # Always return 12Z as a reliable, safe cycle
    return 12


def _bbox(lat: float, lon: float, delta: float = 1.0) -> dict[str, float]:
    return {
        "leftlon": max(-180.0, lon - delta),
        "rightlon": min(180.0, lon + delta),
        "toplat": min(90.0, lat + delta),
        "bottomlat": max(-90.0, lat - delta),
    }


def _gfs_filter_url(
    cycle: int, fhr: int, bbox: dict[str, float], ensemble: str, cycle_date: str
) -> str:
    """Build NOMADS filter URL for GFS or GEFS (control/mean/member).

    Args:
        cycle: cycle hour (0, 6, 12, 18)
        fhr: forecast hour (0, 1, 2, ...)
        bbox: bounding box dict
        ensemble: "det", "control", "mean", or "p01"-"p30"
        cycle_date: date string in YYYYMMDD format
    """
    base = "https://nomads.ncep.noaa.gov/cgi-bin"
    if ensemble == "det":
        # Deterministic GFS 0.25°
        file = f"gfs.t{cycle:02d}z.pgrb2.0p25.f{fhr:03d}"
        script = "filter_gfs_0p25.pl"
    elif ensemble in {"control", "mean"}:
        # GEFS mean/control 0.25° atmospheric fields
        member_tag = "c00" if ensemble == "control" else "mean"
        file = f"gefs.t{cycle:02d}z.pgrb2a.0p25.f{fhr:03d}.{member_tag}"
        script = "filter_gefs_atmos_0p25.pl"
    else:
        # Individual member p01..p30
        file = f"gefs.t{cycle:02d}z.pgrb2a.0p25.f{fhr:03d}.p{int(ensemble[1:]):02d}"
        script = "filter_gefs_atmos_0p25.pl"

    params = {
        "file": file,
        # Levels
        "lev_2_m_above_ground": "on",
        "lev_10_m_above_ground": "on",
        "lev_925_mb": "on",
        "lev_850_mb": "on",
        "lev_700_mb": "on",
        "lev_500_mb": "on",
        # Variables
        "var_TMP": "on",
        "var_RH": "on",
        "var_UGRD": "on",
        "var_VGRD": "on",
        "var_GUST": "on",  # Wind gusts
        "var_APCP": "on",  # Accumulated precipitation
        "var_SNOD": "on",  # Snow depth
        # Subset box
        **{k: f"{v:.3f}" for k, v in bbox.items()},
        "dir": f"/gfs.{cycle_date}/{cycle:02d}z",
    }
    # Build query string
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base}/{script}?{query}"


def _download_grib(url: str) -> str:
    timeout = int(os.getenv("NOMADS_TIMEOUT", "45"))
    resp = requests.get(url, timeout=timeout)
    logger.debug(f"NOMADS filter request: {url[:100]}... -> {resp.status_code}")
    resp.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=".grib2")
    os.close(fd)
    with Path(path).open("wb") as f:
        f.write(resp.content)
    return path


def _decode_point(
    grib_path: str, lat: float, lon: float
) -> dict[str, list[float | None]]:
    _ensure_cfgrib()
    import xarray as xr

    ds = xr.open_dataset(grib_path, engine="cfgrib")

    # Debug: log available variables and dimensions
    logger.debug(f"GRIB variables: {list(ds.data_vars)}")
    logger.debug(f"GRIB dimensions: {dict(ds.dims)}")
    logger.debug(f"GRIB coordinates: {list(ds.coords)}")

    # cfgrib uses latitude/longitude names
    point = ds.sel(latitude=lat, longitude=lon, method="nearest")

    def _has_coord(var, coord_names: list[str]) -> str | None:
        for name in coord_names:
            if name in var.dims or name in var.coords:
                return name
        return None

    def _extract_at_height(shortnames: list[str], height: float) -> list[float | None]:
        """Extract variable at given heightAboveGround in meters, by shortName list."""
        # Scan all variables to find matching shortName and height coord
        for _, var in ds.data_vars.items():
            short = var.attrs.get("GRIB_shortName")
            if short and short in shortnames:
                height_dim = _has_coord(var, ["heightAboveGround", "height"])
                if height_dim:
                    try:
                        hsel = var.sel({height_dim: height}, method="nearest")
                        v = hsel.sel(
                            latitude=lat, longitude=lon, method="nearest"
                        ).values
                        return (
                            v.tolist()
                            if hasattr(v, "tolist")
                            else [float(v)]
                            if isinstance(v, (int, float))
                            else []
                        )
                    except Exception:
                        continue
        # Fallback: try direct variable names like t2m/u10/v10/gust
        for candidate in ["t2m", "u10", "v10", "r2m", "gust"]:
            if candidate in point:
                v = point[candidate].values
                return (
                    v.tolist()
                    if hasattr(v, "tolist")
                    else [float(v)]
                    if isinstance(v, (int, float))
                    else []
                )
        return []

    def _extract_at_level(shortnames: list[str], level_hpa: int) -> list[float | None]:
        """Extract variable at isobaric level (hPa) from any matching var."""
        for _, var in ds.data_vars.items():
            short = var.attrs.get("GRIB_shortName")
            if short and short in shortnames:
                lvl_dim = _has_coord(
                    var, ["isobaricInhPa", "isobaricInPa", "pressure", "level"]
                )
                if lvl_dim:
                    try:
                        lsel = var.sel({lvl_dim: level_hpa}, method="nearest")
                        v = lsel.sel(
                            latitude=lat, longitude=lon, method="nearest"
                        ).values
                        return (
                            v.tolist()
                            if hasattr(v, "tolist")
                            else [float(v)]
                            if isinstance(v, (int, float))
                            else []
                        )
                    except Exception:
                        continue
        return []

    def _extract_any(shortnames: list[str], names: list[str]) -> list[float | None]:
        """Extract any var by shortName or by direct name at the point (no level)."""
        for _, var in ds.data_vars.items():
            short = var.attrs.get("GRIB_shortName")
            if short and short in shortnames:
                try:
                    v = var.sel(latitude=lat, longitude=lon, method="nearest").values
                    return (
                        v.tolist()
                        if hasattr(v, "tolist")
                        else [float(v)]
                        if isinstance(v, (int, float))
                        else []
                    )
                except Exception:
                    continue
        for nm in names:
            if nm in point:
                v = point[nm].values
                return (
                    v.tolist()
                    if hasattr(v, "tolist")
                    else [float(v)]
                    if isinstance(v, (int, float))
                    else []
                )
        return []

    time_vals = point["time"].values.tolist() if "time" in point else []

    # Scalars at heightAboveGround
    t2m = _extract_at_height(["t"], 2)
    r2m = _extract_at_height(["r"], 2)
    u10 = _extract_at_height(["u"], 10)
    v10 = _extract_at_height(["v"], 10)
    gust10 = _extract_at_height(["gust"], 10)

    # Pressure levels
    t925 = _extract_at_level(["t"], 925)
    t850 = _extract_at_level(["t"], 850)
    t700 = _extract_at_level(["t"], 700)
    t500 = _extract_at_level(["t"], 500)
    r925 = _extract_at_level(["r"], 925)
    r850 = _extract_at_level(["r"], 850)
    r700 = _extract_at_level(["r"], 700)
    r500 = _extract_at_level(["r"], 500)

    # Precip and snow depth (accumulated)
    precip = _extract_any(["tp", "apcp"], ["tp", "apcp"])
    snowd = _extract_any(["sd"], ["sd"])  # snow depth

    return {
        "time": time_vals,
        "temperature_2m": t2m,
        "temperature_925hPa": t925,
        "temperature_850hPa": t850,
        "temperature_700hPa": t700,
        "temperature_500hPa": t500,
        "relativehumidity_2m": r2m,
        "relativehumidity_925hPa": r925,
        "relativehumidity_850hPa": r850,
        "relativehumidity_700hPa": r700,
        "relativehumidity_500hPa": r500,
        "wind_speed_10m": u10,  # Will compute magnitude from u/v
        "wind_gusts_10m": gust10,
        "u10": u10,
        "v10": v10,
        "precipitation": precip,
        "snowfall": snowd,
    }


def fetch_gfs_nomads(
    latitude: float,
    longitude: float,
    ensemble: str = "det",
    forecast_hours: list[int] = DEFAULT_FORECAST_HOURS,
    timeout: int = 60,
) -> dict | None:
    """Fetch deterministic or ensemble GFS/GEFS via NOMADS filter + cfgrib.

    Args:
        latitude: target latitude
        longitude: target longitude
        ensemble: "det" (deterministic), "control", "mean", or member like "p01"
        forecast_hours: list of forecast hours to pull
        timeout: overall timeout in seconds for the entire fetch operation
    """
    try:
        _ensure_cfgrib()
    except GribDecoderUnavailableError as exc:
        logger.error(str(exc))
        return None

    import time
    from datetime import timedelta as td

    start_time = time.time()
    now = datetime.now(timezone.utc)
    cycle = _latest_cycle(now)

    # Always use yesterday's cycle for maximum reliability and data availability.
    # Yesterday's 12Z cycle is published around 15:30 UTC and has 5+ hours to populate files.
    safe_hours_back = 24  # Go back 1 full day to yesterday
    cycle_time = now - td(hours=safe_hours_back)
    cycle_date = cycle_time.strftime("%Y%m%d")

    bbox = _bbox(latitude, longitude, delta=1.0)

    merged = {"time": []}
    successful_hours = 0
    failed_hours = 0

    logger.info(
        f"Using NOMADS cycle: {cycle_date}/{cycle:02d}z (computed {safe_hours_back}h ago from now)"
    )

    for fhr in forecast_hours:
        # Check if we've exceeded timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            logger.warning(
                f"NOMADS fetch timed out after {elapsed:.1f}s (timeout={timeout}s) at f{fhr:03d}; fetched {successful_hours} hours so far"
            )
            break

        url = _gfs_filter_url(cycle, fhr, bbox, ensemble, cycle_date)
        try:
            logger.debug(f"Fetching f{fhr:03d}...")
            grib_path = _download_grib(url)
            logger.debug(f"Downloaded GRIB to {grib_path}, decoding...")
            point = _decode_point(grib_path, latitude, longitude)
            logger.debug(
                f"Decoded f{fhr:03d}: time={len(point.get('time',[]))}, t2m={len(point.get('temperature_2m',[]))}"
            )
            for k, v in point.items():
                if k not in merged:
                    merged[k] = []
                if isinstance(v, list):
                    merged[k].extend(v)
            successful_hours += 1
        except requests.exceptions.HTTPError as exc:
            if "404" in str(exc):
                logger.debug(f"f{fhr:03d} not yet available on NOMADS (404)")
            else:
                logger.warning(f"HTTP error fetching f{fhr:03d}: {exc}")
            failed_hours += 1
            continue
        except Exception as exc:
            logger.warning(f"Failed to fetch/parse f{fhr:03d} {ensemble}: {exc}")
            failed_hours += 1
            continue

    if not merged.get("time"):
        logger.error(
            f"No time data extracted from GRIB files (successful: {successful_hours}, failed: {failed_hours})"
        )
        return None

    # Debug: log what we got
    logger.info(
        f"NOMADS success for {ensemble} - fetched {successful_hours} hours ({failed_hours} 404s/errors): time={len(merged.get('time', []))} pts, temp_2m={len(merged.get('temperature_2m', []))}, precip={len(merged.get('precipitation', []))}"
    )

    # Compute wind speed magnitude from u/v components if available
    import math

    u10 = merged.get("u10", [])
    v10 = merged.get("v10", [])
    if u10 and v10 and len(u10) == len(v10):
        merged["wind_speed_10m"] = [
            math.sqrt(u**2 + v**2) if (u is not None and v is not None) else None
            for u, v in zip(u10, v10)
        ]

    return {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": merged,
        "model_source": "NOAA-NOMADS",
        "cycle": f"{cycle:02d}Z",
        "forecast_hours": forecast_hours,
    }
