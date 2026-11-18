"""Tests for stateless place lookup: service, place page and geocode search."""

from unittest.mock import Mock, patch

import pytest
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


def test_parse_wind_speed():
    assert place_service.parse_wind_speed("10 to 20 mph") == 15
    assert place_service.parse_wind_speed("5 mph") == 5
    assert place_service.parse_wind_speed("") == 0
    assert place_service.parse_wind_speed(None) == 0


@pytest.mark.django_db
def test_fetch_place_weather_builds_place_without_database():
    with patch("requests.get", side_effect=_nws_get):
        data = place_service.fetch_place_weather(35.2, -97.4, "Norman, OK")

    place = data["place"]
    assert place.display_name == "Norman, OK"
    assert place.nws_office == "OUN"
    assert place.current_temp == 68
    assert place.current_apparent_temp == 71
    assert place.current_humidity == 55
    assert place.current_wind_speed == 9
    assert place.current_wind_gust == 19
    assert place.current_wind_direction == "E"
    assert place.current_conditions == "Sunny"
    assert place.last_forecast_update is not None

    days = data["daily_forecasts"]
    assert len(days) == 1  # the 2 AM night period folds into the previous day
    assert days[0]["day"].wind_speed == 15
    assert days[0]["day"].precipitation_probability == 10
    assert days[0]["night"].short_forecast == "Clear"
    assert [a.event for a in data["alerts"]] == ["Wind Advisory", "Unknown"]
    assert data["alerts"][0].severity == "moderate"


def test_fetch_place_weather_survives_upstream_failures():
    def failing_get(url, **_kwargs):
        if "/points/" in url:
            return _json_response(
                {"properties": {"forecast": "https://nws.test/forecast"}}
            )
        raise RuntimeError("down")

    with patch("requests.get", side_effect=failing_get):
        data = place_service.fetch_place_weather(30.0, -97.0)

    assert data["place"].display_name == "30.00, -97.00"
    assert data["place"].current_temp is None
    assert data["daily_forecasts"] == []
    assert data["alerts"] == []


def test_fetch_place_weather_handles_missing_station_data():
    points = _json_response({"properties": {"observationStations": "https://x/s"}})
    no_stations = _json_response({"features": []})
    no_id = _json_response({"features": [{"properties": {}}]})
    no_alerts = _json_response({"features": []})

    for stations in (no_stations, no_id):
        with patch("requests.get", side_effect=[points, stations, no_alerts]):
            data = place_service.fetch_place_weather(30.0, -97.0)
        assert data["place"].current_temp is None
        assert data["daily_forecasts"] == []

    with patch("requests.get", side_effect=RuntimeError("down")):
        assert place_service.fetch_place_weather(30.0, -97.0)["alerts"] == []


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
    def test_place_page_renders_from_url_without_saving(self, client):
        with patch("requests.get", side_effect=_nws_get):
            response = client.get(
                reverse("weather:place", kwargs={"coords": "35.2226,-97.4395"}),
                {"name": "Norman, OK"},
            )

        assert response.status_code == 200
        assert response.context["location"].display_name == "Norman, OK"
        assert response.context["latitude"] == pytest.approx(35.2226)
        assert response.context["is_temp_location"] is True
        assert len(response.context["daily_forecasts"]) == 1

    def test_place_page_rejects_out_of_range_coordinates(self, client):
        response = client.get("/weather/95.0,-97.0/")

        assert response.status_code == 200
        assert "valid" in response.context["error"]

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
