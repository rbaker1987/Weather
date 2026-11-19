"""Tests for the East Texas and NM Mountains reports served inside the app."""

import copy
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from weather import regional_pages as rp

FIXTURE = json.loads(
    (Path(__file__).parent / "data" / "regional_today.json").read_text(encoding="utf-8")
)


def _fresh():
    """The fixture with its date set to today so no staleness note appears."""
    data = copy.deepcopy(FIXTURE)
    label = date.today().strftime(rp.DATE_FORMAT)
    data["east_texas"]["date_label"] = label
    data["nm"]["date_label"] = label
    return data


@pytest.mark.parametrize(
    ("temperature", "expected"),
    [
        (-5, "tb--10"),
        (0, "tb-0"),
        (31, "tb-frz"),
        (30, "tb-frz"),
        (32, "tb-frz"),
        (33, "tb-30"),
        (73, "tb-70"),
        (99.6, "tb-100"),
        (140, "tb-110"),
        ("bad", ""),
        (None, ""),
    ],
)
def test_band(temperature, expected):
    assert rp.band(temperature) == expected


def test_icon_name_falls_back_for_unknown_icons():
    assert rp.icon_name("storm") == "storm"
    assert rp.icon_name("tornado") == "pcloud"
    assert rp.icon_name(None) == "pcloud"


def test_issued_age_days():
    today = date(2026, 11, 19)
    assert rp.issued_age_days("Thursday, Nov 19, 2026", today) == 0
    assert rp.issued_age_days("Tuesday, Nov 17, 2026", today) == 2
    assert rp.issued_age_days("sometime", today) is None
    assert rp.issued_age_days(None, today) is None


def test_east_texas_context_from_the_real_report():
    context = rp.east_texas_context(FIXTURE["east_texas"])

    assert context["theme"] == "et"
    assert [r["style"] for r in context["readings"]] == ["hi", "lo"]
    assert context["readings"][0]["value"] == "73°"
    assert len(context["slots"]) == 6
    assert context["slots"][2]["band"] == "tb-70"
    assert context["days"][0]["temps"] == {"mode": "hilo", "hi": 74, "lo": 55}
    assert context["facts"] and len(context["facts"]) <= 4
    assert sum(len(row) for row in context["panel_rows"]) == 2
    assert context["links"][0]["url"].startswith("https://www.weather.gov/shv")


def test_nm_context_builds_the_town_table_and_extra_panels():
    context = rp.nm_context(FIXTURE["nm"])

    assert context["theme"] == "nm"
    table = context["town_table"]
    assert [c["label"] for c in table["columns"]][:2] == ["Town", "Today high"]
    meter = next(c for c in table["rows"][0]["cells"] if c["kind"] == "meter")
    assert 0 <= meter["pop"] <= 100
    kickers = [p["kicker"] for row in context["panel_rows"] for p in row]
    assert kickers[:3] == [
        "Snowpack",
        "Ski areas",
        FIXTURE["nm"]["tables"][0]["kicker"],
    ]
    assert context["readings"][0]["label"] == ["Angel Fire low", "this morning"]


def test_day_temperatures_support_text_and_partial_values():
    days = rp._days(
        [
            {"day": "Mon", "hi": 60, "text": "x"},
            {"day": "Tue", "temp_text": "Cold", "temp_kind": "l", "text": "y"},
            {"day": "Wed", "temp_text": "Mild", "temp_kind": "other", "text": "z"},
            {"day": "Thu", "lo": 10, "icon": "moon", "text": "w", "flag": True},
        ]
    )

    assert days[0]["temps"] == {"mode": "hilo", "hi": 60, "lo": None}
    assert days[1]["temps"] == {"mode": "text", "kind": "l", "text": "Cold"}
    assert days[2]["temps"]["kind"] == ""
    assert days[3]["flag"] is True and days[3]["icon"] == "moon"
    assert days[0]["icon"] == "pcloud"


def test_generic_tables_accept_plain_and_named_first_cells():
    data = copy.deepcopy(FIXTURE["nm"])
    data["snowpack"], data["ski"] = [], []
    data["tables"] = [
        {
            "kicker": "Fire",
            "title": "Fire danger",
            "cols": ["Area", "Level"],
            "rows": [
                ["Taos", "Low"],
                [{"name": "Red River", "sub": "8,750 ft"}, "High"],
            ],
            "key_rows": [1],
            "note": "Check closures.",
        }
    ]

    rows = rp.nm_context(data)["panel_rows"]

    fire = rows[0][0]
    assert fire["paras"] == ["Check closures."]
    assert fire["table"]["rows"][0]["cells"][0] == {"kind": "text", "text": "Taos"}
    assert fire["table"]["rows"][1]["key"] is True
    assert fire["table"]["rows"][1]["cells"][0]["sub"] == "8,750 ft"


def test_panels_are_paired_with_a_single_leftover():
    panels = [{"kicker": str(n), "title": "t"} for n in range(3)]

    rows = rp._panels(panels)

    assert [len(row) for row in rows] == [2, 1]


def test_fetch_reads_the_pages_repo_data_with_caching():
    with patch.object(rp, "get_json", return_value={"east_texas": {}}) as get:
        assert rp.fetch_regional_data() == {"east_texas": {}}

    assert get.call_args.args == (rp.DATA_URL,)
    assert get.call_args.kwargs["ttl"] == rp.CACHE_SECONDS
    assert "ralphs-weather-pages" in rp.DATA_URL


def test_fetch_failures_become_report_unavailable():
    with (
        patch.object(rp, "get_json", side_effect=OSError("down")),
        pytest.raises(rp.ReportUnavailableError, match="could not fetch"),
    ):
        rp.fetch_regional_data()
    with (
        patch.object(rp, "get_json", return_value=[1, 2]),
        pytest.raises(rp.ReportUnavailableError, match="not a JSON object"),
    ):
        rp.fetch_regional_data()


def test_build_report_rejects_an_unexpected_shape():
    broken = copy.deepcopy(FIXTURE)
    del broken["east_texas"]["headline"]

    with (
        patch.object(rp, "fetch_regional_data", return_value=broken),
        pytest.raises(rp.ReportUnavailableError, match="unexpected shape"),
    ):
        rp.build_report("east-texas")


@pytest.mark.parametrize(
    ("url", "heading"),
    [
        ("/east-texas/", "East Texas Weather"),
        ("/nm-mountains/", "Northern Mountains Report"),
    ],
)
class TestRegionalPages:
    def test_renders_the_report_inside_the_app_layout(self, client, url, heading):
        with patch.object(rp, "fetch_regional_data", return_value=_fresh()):
            response = client.get(url)

        html = response.content.decode()
        assert response.status_code == 200
        assert f"<h1>{heading}</h1>" in html
        assert "regional.css" in html
        assert "navbar" in html  # the app's own navigation, not a separate page chrome
        assert 'href="/east-texas/"' in html and 'href="/nm-mountains/"' in html
        assert "may be out of date" not in html
        assert 'class="regional page' in html

    def test_old_reports_get_a_staleness_note(self, client, url, heading):
        data = _fresh()
        old = "Monday, Jan 05, 2026"
        data["east_texas"]["date_label"] = data["nm"]["date_label"] = old
        with patch.object(rp, "fetch_regional_data", return_value=data):
            response = client.get(url)

        assert "days old and may be out of date" in response.content.decode()

    def test_unavailable_report_is_a_503_with_a_way_forward(self, client, url, heading):
        with patch.object(
            rp, "fetch_regional_data", side_effect=rp.ReportUnavailableError("down")
        ):
            response = client.get(url)

        html = response.content.decode()
        assert response.status_code == 503
        assert "not available right now" in html
        assert 'href="/"' in html


def test_east_texas_page_shows_hourly_week_and_facts(client):
    with patch.object(rp, "fetch_regional_data", return_value=_fresh()):
        html = client.get("/east-texas/").content.decode()

    assert 'class="strip"' in html and "slot tb-70" in html
    assert 'class="days"' in html and 'class="facts"' in html
    assert '<use href="#fog"/>' in html
    assert "Official alerts: NWS Shreveport" in html


def test_nm_page_shows_towns_snowpack_and_ski_areas(client):
    with patch.object(rp, "fetch_regional_data", return_value=_fresh()):
        html = client.get("/nm-mountains/").content.decode()

    assert 'class="meter"' in html
    assert "Snow on the ground (SNOTEL)" in html
    assert "Ski areas" in html
    assert 'class="el"' in html


def test_report_text_is_escaped(client):
    data = _fresh()
    data["east_texas"]["headline"] = "<script>alert(1)</script> & more"
    with patch.object(rp, "fetch_regional_data", return_value=data):
        html = client.get("/east-texas/").content.decode()

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in html


def test_a_report_with_an_unexpected_shape_is_reported_unavailable(client):
    data = _fresh()
    del data["nm"]["towns"]
    with patch.object(rp, "fetch_regional_data", return_value=data):
        response = client.get("/nm-mountains/")

    assert response.status_code == 503


def test_home_page_links_to_both_reports(client):
    html = client.get("/").content.decode()

    assert 'href="/east-texas/"' in html
    assert 'href="/nm-mountains/"' in html
