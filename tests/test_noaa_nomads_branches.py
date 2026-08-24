"""Tests for NOMADS decoding and fetch edge branches."""

from unittest.mock import patch

import pytest
import requests

from weather import noaa_nomads


class Value:
    def __init__(self, value):
        self.values = self
        self._value = value

    def tolist(self):
        return self._value


class Variable:
    def __init__(self, short_name, values, dims=()):
        self.attrs = {"GRIB_shortName": short_name}
        self.dims = dims
        self.coords = {}
        self.values = Value(values)

    def sel(self, **kwargs):
        return Value(self.values)


class Dataset:
    data_vars = {}
    dims = {}
    coords = {"latitude": [30], "longitude": [-97]}

    def __contains__(self, key):
        return key in {"time", "t2m", "u10", "v10", "tp", "sd"}

    def __getitem__(self, key):
        if key == "time":
            return Value(["time"])
        return self.data_vars[key]

    def sel(self, **kwargs):
        return self


def test_decode_point_extracts_direct_fallback_variables():
    dataset = Dataset()
    dataset.data_vars = {
        "t2m": Variable("other", [70]),
        "u10": Variable("other", [3]),
        "v10": Variable("other", [4]),
        "tp": Variable("other", [1.5]),
        "sd": Variable("other", [2]),
    }

    with (
        patch.object(noaa_nomads, "_ensure_cfgrib"),
        patch("xarray.open_dataset", return_value=dataset),
    ):
        result = noaa_nomads._decode_point("forecast.grib2", 30, -97)

    assert result["time"] == ["time"]
    assert result["temperature_2m"] == [70]
    assert result["u10"] == [3]
    assert result["v10"] == [4]
    assert result["precipitation"] == [1.5]
    assert result["snowfall"] == [2]


def test_fetch_gfs_nomads_merges_points_and_calculates_wind_speed():
    point = {"time": ["t1"], "u10": [3], "v10": [4], "temperature_2m": [70]}

    with (
        patch.object(noaa_nomads, "_ensure_cfgrib"),
        patch.object(noaa_nomads, "_download_grib", return_value="file.grib2"),
        patch.object(noaa_nomads, "_decode_point", return_value=point),
    ):
        result = noaa_nomads.fetch_gfs_nomads(
            30, -97, forecast_hours=[0, 1], timeout=60
        )

    assert result["model_source"] == "NOAA-NOMADS"
    assert result["hourly"]["time"] == ["t1", "t1"]
    assert result["hourly"]["wind_speed_10m"] == [5.0, 5.0]


def test_fetch_gfs_nomads_continues_after_http_errors():
    point = {"time": ["t1"], "u10": [1], "v10": [0]}
    http_error = requests.exceptions.HTTPError("404 not found")

    with (
        patch.object(noaa_nomads, "_ensure_cfgrib"),
        patch.object(
            noaa_nomads,
            "_download_grib",
            side_effect=[http_error, "file.grib2"],
        ),
        patch.object(noaa_nomads, "_decode_point", return_value=point),
    ):
        result = noaa_nomads.fetch_gfs_nomads(30, -97, forecast_hours=[0, 1])

    assert result is not None
    assert result["hourly"]["time"] == ["t1"]


def test_fetch_gfs_nomads_returns_none_when_all_hours_fail():
    with (
        patch.object(noaa_nomads, "_ensure_cfgrib"),
        patch.object(
            noaa_nomads,
            "_download_grib",
            side_effect=RuntimeError("decode failed"),
        ),
    ):
        assert noaa_nomads.fetch_gfs_nomads(30, -97, forecast_hours=[0]) is None


def test_fetch_gfs_nomads_stops_when_timeout_is_exceeded():
    with (
        patch.object(noaa_nomads, "_ensure_cfgrib"),
        patch("time.time", side_effect=[0, 100]),
        patch.object(noaa_nomads, "_download_grib") as download,
    ):
        assert noaa_nomads.fetch_gfs_nomads(30, -97, forecast_hours=[0], timeout=1) is None

    download.assert_not_called()


def test_ensure_cfgrib_wraps_missing_dependencies():
    with (
        patch.dict("sys.modules", {"cfgrib": None, "xarray": None}),
        pytest.raises(noaa_nomads.GribDecoderUnavailableError),
    ):
        noaa_nomads._ensure_cfgrib()
