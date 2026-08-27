"""Targeted coverage tests for Django bootstrap modules."""

import builtins
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


def test_config_init_handles_missing_celery_dependency():
    config_init = APP_ROOT / "config" / "__init__.py"
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "config.celery":
            raise ImportError("simulated missing celery")
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=guarded_import):
        namespace = runpy.run_path(str(config_init), run_name="__main__")

    assert namespace["celery_app"] is None
    assert namespace["__all__"] == ()
