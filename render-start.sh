#!/usr/bin/env bash
set -euo pipefail

cd weather_app
gunicorn config.wsgi:application
