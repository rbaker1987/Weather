#!/usr/bin/env bash
set -euo pipefail

pip install .[django]
cd weather_app
python manage.py collectstatic --noinput
