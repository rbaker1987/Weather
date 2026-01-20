"""NOAA NOMADS GRIB fetcher for deterministic and ensemble GFS.

This module downloads small GRIB subsets from NOMADS filter endpoints
and decodes them via xarray/cfgrib. It targets upper-air temps, RH,
low-level winds, and precip. Intended as a first slice for GFS/GEFS.
"""

from __future__ import annotations

import tempfile
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Supported ensemble modes
DEFAULT_FORECAST_HOURS = [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48]


class GribDecoderUnavailable(Exception):
    """Raised when cfgrib/xarray or eccodes is missing."""


def _ensure_cfgrib():
    try:
        import xarray as xr  # noqa: F401
        import cfgrib  # noqa: F401
    except Exception as exc:  # pragma: no cover - import guard
        raise GribDecoderUnavailable(
            "cfgrib/xarray (and eccodes) are required for NOAA GRIB decoding"
        ) from exc


def _latest_cycle(now: datetime) -> int:
    """Return the latest GFS cycle hour (0,6,12,18) not after now."""
    hour = now.hour
    for cyc in (18, 12, 6, 0):
        if hour >= cyc:
            return cyc
    return 18  # fallback


def _bbox(lat: float, lon: float, delta: float = 1.0) -> Dict[str, float]:
    return {
        "leftlon": max(-180.0, lon - delta),
        "rightlon": min(180.0, lon + delta),
        "toplat": min(90.0, lat + delta),
        "bottomlat": max(-90.0, lat - delta),
    }


def _gfs_filter_url(cycle: int, fhr: int, bbox: Dict[str, float], ensemble: str) -> str:
    """Build NOMADS filter URL for GFS or GEFS (control/mean/member)."""
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
        "var_APCP": "on",
        "var_SNOD": "on",
        # Subset box
        **{k: f"{v:.3f}" for k, v in bbox.items()},
        "dir": f"/gfs.{datetime.now(timezone.utc).strftime('%Y%m%d')}/{cycle:02d}z",
    }
    # Build query string
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base}/{script}?{query}"


def _download_grib(url: str) -> str:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".grib2")
    tmp.write(resp.content)
    tmp.flush()
    tmp.close()
    return tmp.name


def _decode_point(grib_path: str, lat: float, lon: float) -> Dict[str, List[Optional[float]]]:
    _ensure_cfgrib()
    import xarray as xr

    ds = xr.open_dataset(grib_path, engine="cfgrib")
    # cfgrib uses latitude/longitude names
    point = ds.sel(latitude=lat, longitude=lon, method="nearest")

    def _get(var_name):
        if var_name in point:
            vals = point[var_name].values
            # If it has time dimension, flatten to list
            return vals.tolist() if hasattr(vals, "tolist") else [float(vals)]
        return []

    # Extract variables
    return {
        "time": point["time"].values.tolist() if "time" in point else [],
        "temperature_2m": _get("t2m"),
        "temperature_925hPa": _get("t"),  # will filter by level later
        "relativehumidity_2m": _get("r2m") if "r2m" in point else [],
        "relativehumidity_925hPa": _get("r"),
        "u10": _get("u10"),
        "v10": _get("v10"),
        "u": _get("u"),
        "v": _get("v"),
        "precipitation": _get("tp") if "tp" in point else _get("prate"),
        "snow_depth": _get("sd") if "sd" in point else _get("snod"),
    }


def fetch_gfs_nomads(
    latitude: float,
    longitude: float,
    ensemble: str = "det",
    forecast_hours: List[int] = DEFAULT_FORECAST_HOURS,
) -> Optional[dict]:
    """Fetch deterministic or ensemble GFS/GEFS via NOMADS filter + cfgrib.

    Args:
        latitude: target latitude
        longitude: target longitude
        ensemble: "det" (deterministic), "control", "mean", or member like "p01"
        forecast_hours: list of forecast hours to pull
    """
    try:
        _ensure_cfgrib()
    except GribDecoderUnavailable as exc:
        logger.error(str(exc))
        return None

    now = datetime.now(timezone.utc)
    cycle = _latest_cycle(now)
    bbox = _bbox(latitude, longitude, delta=1.0)

    merged = {"time": []}

    for fhr in forecast_hours:
        url = _gfs_filter_url(cycle, fhr, bbox, ensemble)
        try:
            grib_path = _download_grib(url)
            point = _decode_point(grib_path, latitude, longitude)
            for k, v in point.items():
                if k not in merged:
                    merged[k] = []
                if isinstance(v, list):
                    merged[k].extend(v)
        except Exception as exc:
            logger.warning(f"Failed to fetch/parse f{fhr:03d} {ensemble}: {exc}")
            continue

    if not merged.get("time"):
        return None

    return {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": merged,
        "model_source": "NOAA-NOMADS",
        "cycle": f"{cycle:02d}Z",
        "forecast_hours": forecast_hours,
    }
