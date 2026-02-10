#!/usr/bin/env bash
set -euo pipefail

cd weather_app
celery -A config worker --loglevel=info
