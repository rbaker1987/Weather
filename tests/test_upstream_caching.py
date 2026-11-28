"""Caching and concurrency of upstream fetches."""

import threading
from unittest.mock import Mock, patch

from rest_framework.test import APIClient
from test_place import _nws_get

from weather import place_service
from weather.api.model_comparison_api import ModelComparisonAPIView


def _open_meteo_response():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"hourly": {"time": [], "temperature_2m": []}}
    return response


def test_model_fetches_run_concurrently_and_keep_order():
    """The three upstream calls overlap: each waits until all three are in flight at once.

    A barrier proves the overlap without depending on wall-clock time, so it cannot be flaky on a
    slow or busy machine. If the calls ran one after another the barrier would time out and the
    affected models would come back with an error.
    """
    threads = set()
    barrier = threading.Barrier(3, timeout=10)

    def overlapping_get(*_args, **_kwargs):
        threads.add(threading.get_ident())
        barrier.wait()
        return _open_meteo_response()

    with patch("requests.get", side_effect=overlapping_get):
        results = ModelComparisonAPIView().fetch_all_models(
            ["GFS", "ICON", "ECMWF"], 35.0, -97.0, 3
        )

    assert [r["name"] for r in results] == ["GFS", "ICON", "ECMWF"]
    assert all(r["error"] is None for r in results)
    assert len(threads) == 3


def test_fetch_all_models_with_no_models_returns_empty_list():
    assert ModelComparisonAPIView().fetch_all_models([], 35.0, -97.0, 3) == []


def test_model_results_are_cached_between_requests():
    with patch("requests.get", return_value=_open_meteo_response()) as get:
        view = ModelComparisonAPIView()
        view.fetch_all_models(["GFS", "ICON"], 35.0, -97.0, 3)
        view.fetch_all_models(["GFS", "ICON"], 35.0, -97.0, 3)
        view.fetch_all_models(["GFS"], 35.0, -97.0, 5)  # different days: new call

    assert get.call_count == 3


def test_open_meteo_error_payloads_are_not_cached():
    error = Mock()
    error.raise_for_status.return_value = None
    error.json.return_value = {"error": True, "reason": "bad"}
    with patch("requests.get", return_value=error) as get:
        view = ModelComparisonAPIView()
        first = view.fetch_all_models(["GFS"], 35.0, -97.0, 3)
        view.fetch_all_models(["GFS"], 35.0, -97.0, 3)

    assert first[0]["error"] == "bad"
    assert get.call_count == 2


def test_place_panels_are_cached_between_requests():
    calls = []

    def counting_get(url, **kwargs):
        calls.append(url)
        return _nws_get(url, **kwargs)

    with patch("requests.get", side_effect=counting_get):
        first = {
            panel: place_service.panel_context(panel, 35.2, -97.4)
            for panel in place_service.PANELS
        }
        made = len(calls)
        second = {
            panel: place_service.panel_context(panel, 35.2, -97.4)
            for panel in place_service.PANELS
        }

    assert made > 0
    assert len(calls) == made  # the second round was served entirely from cache
    assert len(first["forecast"]["daily_forecasts"]) == 1
    assert len(second["forecast"]["daily_forecasts"]) == 1
    assert (
        second["current"]["location"].current_temp
        == first["current"]["location"].current_temp
    )


def test_shared_grid_lookup_is_fetched_once_across_panels():
    calls = []

    def counting_get(url, **kwargs):
        calls.append(url)
        return _nws_get(url, **kwargs)

    with patch("requests.get", side_effect=counting_get):
        for panel in place_service.PANELS:
            place_service.panel_context(panel, 35.2, -97.4)

    assert sum("/points/" in url for url in calls) == 1


def test_geocode_results_are_cached(monkeypatch):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "results": [{"latitude": 30.2, "longitude": -97.7, "name": "Austin"}]
    }
    with patch("requests.get", return_value=response) as get:
        client = APIClient()
        first = client.get("/api/geocode/", {"q": "Austin"})
        second = client.get("/api/geocode/", {"q": "Austin"})

    assert first.status_code == second.status_code == 200
    assert first.data == second.data
    assert get.call_count == 1
