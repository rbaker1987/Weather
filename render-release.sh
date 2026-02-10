#!/usr/bin/env bash
set -euo pipefail

cd weather_app
python manage.py migrate
