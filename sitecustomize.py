"""Site customization to ensure Django settings package is importable during pytest-django early initialization.

Adds `weather_app` directory to `sys.path` so `config.settings` can be imported before `conftest.py` runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent
_WEATHER_APP = _PROJECT_ROOT / "weather_app"

if _WEATHER_APP.exists():
    path_str = str(_WEATHER_APP)
    if path_str not in sys.path:
        # Prepend to prioritize local project modules
        sys.path.insert(0, path_str)
