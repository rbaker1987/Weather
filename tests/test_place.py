"""Tests for stateless place lookup: service, place page and geocode search."""

from unittest.mock import Mock, patch

import pytest
import requests
from django.urls import reverse

from weather import place_service

POINTS = {
    "properties": {
        "gridId": "OUN",
        "gridX": 10,
        "gridY": 20,
        "forecast": "https://nws.test/forecast",
        "observationStations": "https://nws.test/stations",
    }
}
STATIONS = {"features": [{"properties": {"stationIdentifier": "KOUN"}}]}
OBSERVATION = {
    "properties": {
        "temperature": {"value": 20},
        "relativeHumidity": {"value": 55.4},
        "windSpeed": {"value": 16},
        "windGust": {"value": 32},
        "windDirection": {"value": 90},
        "heatIndex": {"value": 22},
        "textDescription": "Sunny",
        "timestamp": "2026-11-18T12:00:00Z",
    }
}
FORECAST = {
    "properties": {
        "periods": [
            {
                "startTime": "2026-11-18T06:00:00-06:00",
                "endTime": "2026-11-18T18:00:00-06:00",
                "isDaytime": True,
                "temperature": 70,
                "temperatureUnit": "F",
                "windSpeed": "10 to 20 mph",
                "windDirection": "S",
                "shortForecast": "Sunny",
                "detailedForecast": "Sunny.",
                "probabilityOfPrecipitation": {"value": 10},
            },
            {
                "startTime": "2026-11-18T18:00:00-06:00",
                "endTime": "2026-11-19T06:00:00-06:00",
                "isDaytime": False,
                "temperature": 50,
                "windSpeed": "5 mph",
                "windDirection": "N",
                "shortForecast": "Clear",
                "detailedForecast": "Clear.",
            },
            {
                "startTime": "2026-11-19T02:00:00-06:00",
                "endTime": "2026-11-19T06:00:00-06:00",
                "isDaytime": False,
                "temperature": 48,
                "windSpeed": "",
                "shortForecast": "Clear",
            },
        ]
    }
}
ALERTS = {
    "features": [
        {
            "properties": {
                "event": "Wind Advisory",
                "headline": "Windy",
                "severity": "Moderate",
                "onset": "2026-11-18T12:00:00Z",
                "expires": "2026-11-19T00:00:00Z",
            }
        },
        {"properties": {}},
    ]
}


def _json_response(payload):
    response = Mock()
    response.json.return_value = payload
    return response


def _nws_get(url, **_kwargs):
    routes = {
        "/points/": POINTS,
        "/stations/KOUN/": OBSERVATION,
        "nws.test/stations": STATIONS,
        "nws.test/forecast": FORECAST,
        "/alerts/active": ALERTS,
    }
    for fragment, payload in routes.items():
        if fragment in url:
            return _json_response(payload)
    raise AssertionError(f"unexpected URL {url}")


def test_validate_coordinates():
    assert place_service.validate_coordinates("35.5", "-97.5") == (35.5, -97.5)
    for bad in [("x", "1"), (None, "1"), ("91", "0"), ("0", "181")]:
        with pytest.raises(ValueError):
            place_service.validate_coordinates(*bad)


@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (35.2, -97.4, True),  # Norman, OK
        (47.6, -122.3, True),  # Seattle
        (25.8, -80.2, True),  # Miami
        (20.0, -60.0, True),  # the corner of the grid
        (61.2, -149.9, False),  # Anchorage is outside the CONUS grid
        (21.3, -157.8, False),  # Honolulu
        (51.5, -0.1, False),  # London
        (19.9, -97.4, False),  # just south of the grid
    ],
)
def test_in_radar_coverage(lat, lon, expected):
    assert place_service.in_radar_coverage(lat, lon) is expected


def test_parse_wind_speed():
    assert place_service.parse_wind_speed("10 to 20 mph") == 15
    assert place_service.parse_wind_speed("5 mph") == 5
    assert place_service.parse_wind_speed("") == 0
    assert place_service.parse_wind_speed(None) == 0


def test_alerts_context_lists_active_alerts():
    with patch("requests.get", side_effect=_nws_get):
        context = place_service.panel_context("alerts", 35.2, -97.4)

    alerts = context["active_alerts"]
    assert [a.event for a in alerts] == ["Wind Advisory", "Unknown"]
    assert alerts[0].severity == "moderate"


def test_current_context_builds_a_place_without_database():
    with patch("requests.get", side_effect=_nws_get):
        place = place_service.panel_context("current", 35.2, -97.4)["location"]

    assert place.nws_office == "OUN"
    assert place.current_temp == 68
    assert place.current_apparent_temp == 71
    assert place.current_humidity == 55
    assert place.current_wind_speed == 9
    assert place.current_wind_gust == 19
    assert place.current_wind_direction == "E"
    assert place.current_conditions == "Sunny"


def test_forecast_context_groups_periods_by_day():
    with patch("requests.get", side_effect=_nws_get):
        context = place_service.panel_context("forecast", 35.2, -97.4)

    days = context["daily_forecasts"]
    assert len(days) == 1  # the 2 AM night period folds into the previous day
    assert days[0]["day"].wind_speed == 15
    assert days[0]["day"].precipitation_probability == 10
    assert days[0]["night"].short_forecast == "Clear"
    assert context["location"].last_forecast_update is not None


def test_forecast_context_without_forecast_url_is_empty():
    with patch("requests.get", return_value=_json_response({"properties": {}})):
        context = place_service.panel_context("forecast", 30.0, -97.0)

    assert context["daily_forecasts"] == []


def test_current_context_handles_missing_station_data():
    points = _json_response({"properties": {"observationStations": "https://x/s"}})
    no_stations = _json_response({"features": []})
    no_id = _json_response({"features": [{"properties": {}}]})

    for stations in (no_stations, no_id):
        with patch("requests.get", side_effect=[points, stations]):
            place = place_service.panel_context("current", 30.0, -97.0)["location"]
        assert place.current_temp is None


def test_panel_context_lets_upstream_failures_surface():
    with (
        patch("requests.get", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError),
    ):
        place_service.panel_context("alerts", 30.0, -97.0)


def test_is_unsupported_place_only_matches_nws_404():
    def error(status):
        response = requests.Response()
        response.status_code = status
        return requests.HTTPError(response=response)

    assert place_service.is_unsupported_place(error(404)) is True
    assert place_service.is_unsupported_place(error(500)) is False
    assert place_service.is_unsupported_place(requests.HTTPError()) is False
    assert place_service.is_unsupported_place(OSError("down")) is False


def test_timezone_lookup_falls_back_when_unavailable():
    place_service._timezone_finder = None
    with patch.object(place_service, "TimezoneFinder", side_effect=RuntimeError):
        assert place_service._timezone_for(30.0, -97.0) is not None

    place_service._timezone_finder = None
    with patch.object(place_service, "TimezoneFinder") as finder:
        finder.return_value.timezone_at.return_value = None
        assert place_service._timezone_for(0.0, 0.0) is not None
    place_service._timezone_finder = None


@pytest.mark.django_db
class TestPlaceView:
    def test_place_page_is_a_shell_that_makes_no_upstream_calls(self, client):
        with patch("requests.get", side_effect=AssertionError("no upstream")) as get:
            response = client.get(
                reverse("weather:place", kwargs={"coords": "35.2226,-97.4395"}),
                {"name": "Norman, OK"},
            )

        assert response.status_code == 200
        assert get.call_count == 0
        assert response.context["location"].display_name == "Norman, OK"
        assert response.context["latitude"] == pytest.approx(35.2226)
        assert response.context["is_temp_location"] is True
        html = response.content.decode()
        for panel in ("alerts", "current", "forecast"):
            assert f"/weather/35.222600,-97.439500/panel/{panel}/" in html

    def test_model_comparison_section_is_still_on_the_page(self, client):
        html = client.get("/weather/35.2226,-97.4395/").content.decode()

        assert 'id="modelComparisonContainer"' in html
        assert "Weather Model Comparison" in html

    def test_radar_is_shown_inside_the_covered_area(self, client):
        response = client.get("/weather/35.2226,-97.4395/")

        assert response.context["radar_supported"] is True
        html = response.content.decode()
        assert 'id="radarMap"' in html
        assert "contiguous United States only" not in html

    def test_radar_is_replaced_by_a_note_outside_the_covered_area(self, client):
        response = client.get("/weather/51.5,-0.1/")

        assert response.context["radar_supported"] is False
        html = response.content.decode()
        assert 'id="radarMap"' not in html
        assert "contiguous United States only" in html

    def test_place_page_rejects_out_of_range_coordinates(self, client):
        response = client.get("/weather/95.0,-97.0/")

        assert response.status_code == 200
        assert "valid" in response.context["error"]
        assert "/panel/" not in response.content.decode()

    def test_non_coordinate_path_is_not_matched(self, client):
        assert client.get("/weather/abc/").status_code == 404


@pytest.mark.django_db
class TestGeocodeAPI:
    def _get(self, client, **params):
        return client.get(reverse("weather:geocode"), params)

    def test_requires_query(self, client):
        assert self._get(client).status_code == 400
        assert self._get(client, q="  ").status_code == 400

    def test_accepts_raw_coordinates(self, client):
        response = self._get(client, q="35.2226, -97.4395")

        assert response.status_code == 200
        [result] = response.json()["results"]
        assert result["url"].startswith("/weather/35.2226,-97.4395/?name=")

    def test_accepts_space_separated_coordinates(self, client):
        response = self._get(client, q="  35.2   -97.4 ")

        assert response.json()["results"][0]["latitude"] == 35.2

    def test_rejects_out_of_range_coordinates(self, client):
        assert self._get(client, q="95, 10").status_code == 400

    def test_rejects_overlong_queries(self, client):
        assert self._get(client, q="9 " + "1 " * 300).status_code == 400
        assert self._get(client, q="a" * 201).status_code == 400

    def test_geocodes_place_names(self, client):
        payload = {
            "results": [
                {
                    "name": "Austin",
                    "admin1": "Texas",
                    "country_code": "US",
                    "latitude": 30.2672,
                    "longitude": -97.7431,
                },
                {"name": "No coordinates"},
            ]
        }
        with patch("requests.get", return_value=_json_response(payload)) as mock_get:
            response = self._get(client, q="Austin")

        assert mock_get.call_args.kwargs["params"]["name"] == "Austin"
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["label"] == "Austin, Texas, US"
        assert results[0]["url"].startswith("/weather/30.2672,-97.7431/?name=Austin")

    def test_handles_no_results(self, client):
        with patch("requests.get", return_value=_json_response({})):
            assert self._get(client, q="zzzz").json() == {"results": []}

    def test_handles_geocoder_failure(self, client):
        with patch("requests.get", side_effect=RuntimeError("down")):
            response = self._get(client, q="Austin")

        assert response.status_code == 502


class TestPlacePanelView:
    def _get(self, client, panel, coords="35.2226,-97.4395"):
        return client.get(
            reverse("weather:place-fragment", kwargs={"coords": coords, "panel": panel})
        )

    @pytest.mark.parametrize(
        ("panel", "expected"),
        [
            ("alerts", "Wind Advisory"),
            ("current", "Sunny"),
            ("forecast", "NWS Daily"),
        ],
    )
    def test_each_panel_renders_its_fragment(self, client, panel, expected):
        with patch("requests.get", side_effect=_nws_get):
            response = self._get(client, panel)

        assert response.status_code == 200
        assert expected in response.content.decode()
        assert "<html" not in response.content.decode()  # a fragment, not a page

    def test_alerts_panel_shows_all_clear_when_there_are_none(self, client):
        def get(url, **kwargs):
            if "/alerts/" in url:
                return _json_response({"features": []})
            return _nws_get(url, **kwargs)

        with patch("requests.get", side_effect=get):
            response = self._get(client, "alerts")

        assert "No Active Alerts" in response.content.decode()

    def test_current_panel_without_observation_shows_a_note(self, client):
        with patch(
            "requests.get", return_value=_json_response({"properties": {"gridId": "X"}})
        ):
            response = self._get(client, "current")

        assert response.status_code == 200
        assert "No current observation" in response.content.decode()

    def test_forecast_panel_without_periods_shows_a_note(self, client):
        with patch(
            "requests.get", return_value=_json_response({"properties": {"gridId": "X"}})
        ):
            response = self._get(client, "forecast")

        assert "No Forecast Data Available" in response.content.decode()

    def test_upstream_failure_renders_a_retryable_error(self, client):
        with patch("requests.get", side_effect=OSError("down")):
            response = self._get(client, "alerts")

        assert response.status_code == 502
        html = response.content.decode()
        assert "unavailable right now" in html
        assert "data-retry" in html

    def test_place_outside_nws_coverage_is_not_retryable(self, client):
        error = requests.Response()
        error.status_code = 404
        with patch("requests.get", side_effect=requests.HTTPError(response=error)):
            response = self._get(client, "forecast")

        assert response.status_code == 404
        html = response.content.decode()
        assert "does not cover" in html
        assert "data-retry" not in html

    def test_one_failing_panel_does_not_affect_another(self, client):
        def get(url, **kwargs):
            if "/alerts/" in url:
                raise OSError("alerts down")
            return _nws_get(url, **kwargs)

        with patch("requests.get", side_effect=get):
            assert self._get(client, "alerts").status_code == 502
            assert self._get(client, "forecast").status_code == 200

    def test_unknown_panel_is_404(self, client):
        assert self._get(client, "radar").status_code == 404

    def test_out_of_range_coordinates_are_rejected(self, client):
        assert self._get(client, "alerts", coords="95.0,-97.0").status_code == 400

    def test_fragments_and_their_errors_carry_the_marker_header(self, client):
        # The failure goes first: successful upstream responses are cached.
        with patch("requests.get", side_effect=OSError("down")):
            failed = self._get(client, "alerts")
        with patch("requests.get", side_effect=_nws_get):
            ok = self._get(client, "alerts")

        assert ok["X-Place-Panel"] == "1"
        assert failed.status_code == 502
        assert failed["X-Place-Panel"] == "1"
