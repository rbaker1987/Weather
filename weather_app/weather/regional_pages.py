"""Regional report pages (East Texas, NM Mountains) shown inside the app.

The reports are written once a morning into ``data/today.json`` in the separate
``ralphs-weather-pages`` repository. Rather than copying that file into this repo (which would
need a redeploy for every update), the app reads it on demand and keeps it in the process-local
cache for a few minutes. Nothing is stored. If the file cannot be fetched or has an unexpected
shape the page says the report is unavailable instead of failing.

This module only shapes data for the templates; the markup lives in
``templates/weather/regional/`` and the styling in ``static/weather/css/regional.css``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from .upstream import get_json

logger = logging.getLogger("weather")

DATA_URL = "https://raw.githubusercontent.com/rbaker1987/ralphs-weather-pages/main/data/today.json"
CACHE_SECONDS = 10 * 60
FETCH_TIMEOUT = 10
ICONS = {"sun", "moon", "pcloud", "cloud", "rain", "storm", "snow", "fog", "wind"}
DATE_FORMAT = "%A, %b %d, %Y"
# A report older than this many days gets a "may be out of date" note.
STALE_AFTER_DAYS = 1


class ReportUnavailableError(Exception):
    """The report data could not be fetched or did not have the expected shape."""


def fetch_regional_data() -> dict[str, Any]:
    """Return the full ``today.json`` payload (cached; raises on failure)."""
    try:
        data = get_json(DATA_URL, timeout=FETCH_TIMEOUT, ttl=CACHE_SECONDS)
    except Exception as exc:
        raise ReportUnavailableError(f"could not fetch report data: {exc}") from exc
    if not isinstance(data, dict):
        raise ReportUnavailableError("report data was not a JSON object")
    return data


def band(temperature: Any) -> str:
    """Temperature color-band class (matches the main app's palette) for a value in F."""
    try:
        value = int(round(float(temperature)))
    except (TypeError, ValueError):
        return ""
    if value <= -1:
        return "tb--10"
    if 30 <= value <= 32:
        return "tb-frz"
    return f"tb-{min(110, (value // 10) * 10)}"


def icon_name(name: Any) -> str:
    return name if name in ICONS else "pcloud"


def issued_age_days(date_label: str, today: date | None = None) -> int | None:
    """Whole days between the report's date and today, or None if it cannot be parsed."""
    try:
        reported = datetime.strptime(date_label, DATE_FORMAT).date()
    except (TypeError, ValueError):
        return None
    return ((today or date.today()) - reported).days


def _temps(day: dict[str, Any]) -> dict[str, Any]:
    if "hi" in day or "lo" in day:
        return {"mode": "hilo", "hi": day.get("hi"), "lo": day.get("lo")}
    kind = day.get("temp_kind", "")
    return {
        "mode": "text",
        "kind": kind if kind in ("h", "l") else "",
        "text": day.get("temp_text", ""),
    }


def _days(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "day": item["day"],
            "icon": icon_name(item.get("icon")),
            "flag": bool(item.get("flag")),
            "temps": _temps(item),
            "text": item["text"],
        }
        for item in items
    ]


def _table(
    columns: list[tuple[str, str]], rows: list[tuple[bool, list[dict[str, Any]]]]
) -> dict[str, Any]:
    """Table data: ``columns`` are (label, css class); each row is (is_key, cells)."""
    return {
        "columns": [{"label": label, "cls": cls} for label, cls in columns],
        "rows": [{"key": key, "cells": cells} for key, cells in rows],
    }


def _name_cell(name: Any, sub: Any = "") -> dict[str, Any]:
    return {"kind": "name", "text": name, "sub": sub}


def _num_cell(text: Any, cls: str = "") -> dict[str, Any]:
    return {"kind": "num", "text": text, "cls": cls}


def _panels(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Panels arranged in rows of up to two."""
    prepared = [
        {
            "kicker": item["kicker"],
            "title": item["title"],
            "paras": item.get("paras", []),
            "table": item.get("table"),
        }
        for item in items
    ]
    return [prepared[i : i + 2] for i in range(0, len(prepared), 2)]


def _chips(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"text": c["text"], "kind": c.get("kind", "")} for c in items[:3]]


def east_texas_context(data: dict[str, Any]) -> dict[str, Any]:
    """Template context for the East Texas report."""
    return {
        "theme": "et",
        "page_title": "East Texas Weather",
        "brand": "Ralph's Weather",
        "area": "Tyler · Smith County area",
        "date_label": data["date_label"],
        "issued": data["issued"],
        "chips": _chips(data["chips"]),
        "readings": [
            {
                "style": "hi",
                "value": f"{data['hi']}°",
                "label": [data.get("hi_label", "High today")],
            },
            {
                "style": "lo",
                "value": f"{data['lo']}°",
                "label": [data.get("lo_label", "Low tonight")],
            },
        ],
        "headline": data["headline"],
        "summary": data["summary"],
        "hourly_title": data.get("hourly_title", "Today"),
        "rain_note": data["rain_note"],
        "slots": [
            {
                "time": slot["time"],
                "icon": icon_name(slot.get("icon")),
                "temp": slot["temp"],
                "band": band(slot["temp"]),
                "sky": slot["sky"],
                "wind": slot["wind"],
            }
            for slot in data["hourly"][:6]
        ],
        "week_note": "High / low",
        "days": _days(data["days"]),
        "facts": [
            {"k": fact["k"], "v": fact["v"], "p": fact["p"]}
            for fact in data["facts"][:4]
        ],
        "panel_rows": _panels(data["panels"]),
        "links": [
            {
                "text": "Official alerts: NWS Shreveport",
                "url": "https://www.weather.gov/shv/",
            },
            {
                "text": "Ralph's Weather on Facebook",
                "url": "https://www.facebook.com/RalphsWeather/",
            },
        ],
        "sources": data["sources"],
        "age_days": issued_age_days(data["date_label"]),
    }


def _nm_town_table(data: dict[str, Any]) -> dict[str, Any]:
    labels = data["town_cols"]
    rows = []
    for town in data["towns"]:
        pop = int(town["pop"])
        rows.append(
            (
                bool(town.get("key")),
                [
                    _name_cell(town["name"], town["elev"]),
                    {
                        "kind": "hl",
                        "tone": "h",
                        "text": f"{town['d1_hi']}°",
                        "cls": "hide-sm",
                    },
                    {"kind": "hl", "tone": "l", "text": f"{town['n1_lo']}°", "cls": ""},
                    {"kind": "meter", "pop": max(0, min(100, pop)), "text": f"{pop}%"},
                    {
                        "kind": "hl",
                        "tone": "h",
                        "text": f"{town['d2_hi']}°",
                        "cls": "hide-sm",
                    },
                    {"kind": "hl", "tone": "l", "text": f"{town['n2_lo']}°", "cls": ""},
                ],
            )
        )
    return _table(
        [
            ("Town", ""),
            (labels[0], "hide-sm"),
            (labels[1], ""),
            ("Precip", ""),
            (labels[2], "hide-sm"),
            (labels[3], ""),
        ],
        rows,
    )


def _nm_extra_panels(data: dict[str, Any]) -> list[dict[str, Any]]:
    extra: list[dict[str, Any]] = []
    if data.get("snowpack"):
        table = _table(
            [("Station", ""), ("Depth", ""), ("Water", "")],
            [
                (
                    False,
                    [
                        _name_cell(s["station"], s["elev"]),
                        _num_cell(s["depth"]),
                        _num_cell(s["swe"]),
                    ],
                )
                for s in data["snowpack"]
            ],
        )
        extra.append(
            {
                "kicker": "Snowpack",
                "title": "Snow on the ground (SNOTEL)",
                "paras": [data["snow_note"]] if data.get("snow_note") else [],
                "table": table,
            }
        )
    if data.get("ski"):
        table = _table(
            [("Resort", ""), (data.get("ski_col", "Opens"), "")],
            [
                (
                    bool(s.get("key")),
                    [_name_cell(s["name"]), _num_cell(s["status"])],
                )
                for s in data["ski"]
            ],
        )
        extra.append(
            {
                "kicker": "Ski areas",
                "title": data.get("ski_title", "Opening days"),
                "paras": [data["ski_note"]] if data.get("ski_note") else [],
                "table": table,
            }
        )
    # Generic tables (e.g. summer "Peak weather", "Fire", "Trail conditions"):
    # {"kicker", "title", "cols": [...], "rows": [[cell, ...], ...], "key_rows": [i, ...], "note"}
    for spec in data.get("tables", []):
        rows = []
        for number, row in enumerate(spec["rows"]):
            cells = []
            for column, value in enumerate(row):
                if column == 0 and isinstance(value, dict):
                    cells.append(_name_cell(value["name"], value.get("sub", "")))
                elif column == 0:
                    cells.append({"kind": "text", "text": value})
                else:
                    cells.append(_num_cell(value))
            rows.append((number in spec.get("key_rows", []), cells))
        extra.append(
            {
                "kicker": spec["kicker"],
                "title": spec["title"],
                "paras": [spec["note"]] if spec.get("note") else [],
                "table": _table([(h, "") for h in spec["cols"]], rows),
            }
        )
    return extra


def nm_context(data: dict[str, Any]) -> dict[str, Any]:
    """Template context for the northern New Mexico mountains report."""
    return {
        "theme": "nm",
        "page_title": "Northern Mountains Report",
        "brand": "New Mexico Mountains Weather & Info",
        "area": "Sangre de Cristo & Tusas Mountains",
        "date_label": data["date_label"],
        "issued": data["issued"],
        "chips": _chips(data["chips"]),
        "readings": [
            {
                "style": reading["style"],
                "value": reading["value"],
                "label": reading["label"].split("|"),
            }
            for reading in data["hero"]
        ],
        "headline": data["headline"],
        "summary": data["summary"],
        "town_title": data.get("town_title", "Mountain towns"),
        "town_source": "NWS Albuquerque",
        "town_table": _nm_town_table(data),
        "week_note": "Northern mountains",
        "days": _days(data["days"]),
        "panel_rows": _panels(_nm_extra_panels(data) + data["panels"]),
        "links": [
            {
                "text": "Official alerts: NWS Albuquerque",
                "url": "https://www.weather.gov/abq/",
            },
            {"text": "Road conditions: NMRoads", "url": "https://www.nmroads.com"},
            {
                "text": "NM Mountains Weather on Facebook",
                "url": "https://www.facebook.com/jicaritapeak/",
            },
        ],
        "sources": data["sources"],
        "age_days": issued_age_days(data["date_label"]),
    }


REPORTS = {
    "east-texas": ("east_texas", east_texas_context),
    "nm-mountains": ("nm", nm_context),
}


def build_report(slug: str) -> dict[str, Any]:
    """Fetch and shape one report; raises ``ReportUnavailableError`` for any problem."""
    key, shape = REPORTS[slug]
    data = fetch_regional_data()
    try:
        return shape(data[key])
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        logger.warning("Regional report %s has an unexpected shape: %r", slug, exc)
        raise ReportUnavailableError(f"report {slug} has an unexpected shape") from exc
