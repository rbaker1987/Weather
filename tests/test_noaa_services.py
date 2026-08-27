"""Deterministic tests for NOAA service and NOMADS helper behavior."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from weather import noaa_nomads, noaa_service


def response(payload):
    result = Mock()
    result.json.return_value = payload
    result.status_code = 200
    result.content = b"grib data"
    return result


def test_fetch_noaa_forecast_converts_supported_model_response():
    points = response(
        {"properties": {"gridX": 10, "gridY": 20, "cwa": "OUN", "elevation": {"value": 300}}}
    )
    forecast = response(
        {
            "properties": {
                "generatedAt": "2026-01-01T00:00:00+00:00",
                "periods": [
                    {
                        "startTime": "2026-01-01T00:00:00Z",
                        "temperature": 40,
                        "relativeHumidity": {"value": 80},
                        "windSpeed": "10 mph",
                    },
                    {
                        "startTime": "2026-01-01T12:00:00Z",
                        "temperature": 50,
                        "relativeHumidity": 70,
                        "windSpeed": "calm",
                    },
                ],
            }
        }
    )

    with patch.object(noaa_service.requests, "get", side_effect=[points, forecast]):
        result = noaa_service.fetch_noaa_forecast(35.0, -97.0, "GFS")

    assert result["model_source"] == "NOAA"
    assert result["grid_point"] == {"office": "OUN", "x": 10, "y": 20}
    assert result["hourly"]["temperature_2m"] == [40, 50]
    assert result["hourly"]["relativehumidity_2m"] == [80, 70]
    assert result["hourly"]["wind_speed_10m"] == [10, None]


@pytest.mark.parametrize("model", ["GFS", "NAM", "HRRR", "NDFD"])
def test_fetch_noaa_forecast_accepts_supported_models(model):
    points = response({"properties": {"gridX": 1, "gridY": 2, "cwa": "XXX"}})
    forecast = response({"properties": {"periods": [{"temperature": 1}]}})

    with patch.object(noaa_service.requests, "get", side_effect=[points, forecast]):
        result = noaa_service.fetch_noaa_forecast(1, 2, model)

    assert result["model_source"] == "NOAA"


def test_fetch_noaa_forecast_rejects_unsupported_model():
    with patch.object(noaa_service.requests, "get") as get:
        result = noaa_service.fetch_noaa_forecast(1, 2, "ICON")

    assert result is None
    get.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [{}, {"properties": {}}, {"properties": {"gridX": 1, "gridY": 2}}],
)
def test_fetch_noaa_forecast_returns_none_for_incomplete_grid_data(payload):
    with patch.object(noaa_service.requests, "get", return_value=response(payload)):
        assert noaa_service.fetch_noaa_forecast(1, 2, "GFS") is None


def test_fetch_noaa_forecast_returns_none_for_request_error():
    with patch.object(
        noaa_service.requests,
        "get",
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        assert noaa_service.fetch_noaa_forecast(1, 2, "GFS") is None


def test_fetch_noaa_forecast_returns_none_without_periods():
    points = response({"properties": {"gridX": 1, "gridY": 2, "cwa": "XXX"}})
    forecast = response({"properties": {"periods": []}})

    with patch.object(noaa_service.requests, "get", side_effect=[points, forecast]):
        assert noaa_service.fetch_noaa_forecast(1, 2, "GFS") is None


def test_nomads_bbox_clamps_coordinates():
    assert noaa_nomads._bbox(89.5, 179.5, 1) == {
        "leftlon": 178.5,
        "rightlon": 180.0,
        "toplat": 90.0,
        "bottomlat": 88.5,
    }


@pytest.mark.parametrize(
    "ensemble, expected",
    [("det", "filter_gfs_0p25.pl"), ("control", "c00"), ("mean", "mean"), ("p01", "p01")],
)
def test_nomads_filter_url_supports_ensemble_modes(ensemble, expected):
    url = noaa_nomads._gfs_filter_url(
        12, 3, noaa_nomads._bbox(40, -75), ensemble, "20260101"
    )

    assert expected in url
    assert "f003" in url
    assert "leftlon=-76.000" in url


def test_nomads_download_grib_writes_response():
    mocked = response({})
    with patch.object(noaa_nomads.requests, "get", return_value=mocked):
        path = noaa_nomads._download_grib("https://example.test/file")

    downloaded = Path(path)
    assert downloaded.read_bytes() == b"grib data"
    downloaded.unlink()


def test_fetch_gfs_nomads_returns_none_without_decoder():
    with patch.object(
        noaa_nomads,
        "_ensure_cfgrib",
        side_effect=noaa_nomads.GribDecoderUnavailableError("missing"),
    ):
        assert noaa_nomads.fetch_gfs_nomads(40, -75, forecast_hours=[]) is None


def test_fetch_gfs_nomads_returns_none_when_no_time_data():
    point = {"time": [], "u10": [3], "v10": [4]}
    with (
        patch.object(noaa_nomads, "_ensure_cfgrib"),
        patch.object(noaa_nomads, "_download_grib", return_value="file.grib2"),
        patch.object(noaa_nomads, "_decode_point", return_value=point),
    ):
        assert noaa_nomads.fetch_gfs_nomads(40, -75, forecast_hours=[0]) is None


def test_latest_cycle_is_12z():
    assert noaa_nomads._latest_cycle(datetime.now(timezone.utc)) == 12
