"""Deployment security configuration tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANAGE_PY = PROJECT_ROOT / "weather_app" / "manage.py"


@pytest.mark.django_db
def test_deploy_check_passes_with_production_environment():
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_DEBUG": "False",
            "DJANGO_SECRET_KEY": "deployment-secret-key-that-is-long-enough-to-be-secure",
            "DJANGO_ALLOWED_HOSTS": "weather.example.com",
        }
    )
    environment.pop("PYTEST_CURRENT_TEST", None)

    result = subprocess.run(
        [sys.executable, str(MANAGE_PY), "check", "--deploy"],
        cwd=MANAGE_PY.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
