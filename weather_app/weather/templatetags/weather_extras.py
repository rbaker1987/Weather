"""Backwards-compat shim for older templates.

This module mirrors `ui_tags` to prevent import errors if any template or
third-party snippet still references `{% load weather_extras %}`. Prefer
`{% load ui_tags %}` going forward.
"""

from .ui_tags import *  # noqa: F401,F403
