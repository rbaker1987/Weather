"""Targeted coverage tests for Django bootstrap modules."""

import runpy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "weather_app"


def test_manage_py_executes_django_entrypoint():
    manage_py = APP_ROOT / "manage.py"

    with patch("django.core.management.execute_from_command_line") as execute:
        runpy.run_path(str(manage_py), run_name="__main__")

    execute.assert_called_once()
    assert execute.call_args[0][0]


def test_config_asgi_module_sets_application():
    asgi_path = APP_ROOT / "config" / "asgi.py"

    with patch("django.core.asgi.get_asgi_application", return_value="asgi-app"):
        namespace = runpy.run_path(str(asgi_path), run_name="__main__")

    assert namespace["application"] == "asgi-app"


def test_config_wsgi_module_sets_application():
    wsgi_path = APP_ROOT / "config" / "wsgi.py"

    with patch("django.core.wsgi.get_wsgi_application", return_value="wsgi-app"):
        namespace = runpy.run_path(str(wsgi_path), run_name="__main__")

    assert namespace["application"] == "wsgi-app"
