# CLAUDE.md

Django weather app: NWS forecasts plus raw model data (GFS, ICON, ECMWF, AIFS, GEM, HRRR, NAM, RGEM) side by side, and a historical climate/teleconnection analysis. Favor exposing raw, comparable model detail over a single blended number.

## Direction: stateless, free hosting

Production is a Render **free** web service with **no permanent database** (free Postgres expires every 30 days, and we do not pay for hosting). Design accordingly:

- The database is a disposable cache. SQLite is rebuilt by `migrate` on every start (`render-release.sh`); data is lost on deploy and restart. Do not add models that must persist.
- User accounts are removed (signup/login/profile, `Location.owner`); only Django admin keeps `django.contrib.auth`. Session locations (`request.session["location_ids"]`) and the location/forecast/alert list pages are removed; the home page offers "use my location" or "enter a location", with the place carried in the URL, not the session or DB.
- Celery/Redis are being dropped; data is fetched on demand. `CELERY_ENABLED` is false in production already.
- The custom forecast builder is removed.
- Places are carried in the URL: `/weather/<lat>,<lon>/?name=` (`PlaceView`, `place_service.py`, no DB rows); `/api/geocode/?q=` powers the search box. The `Location` table is being removed entirely (decision: no cache rows); until then `/locations/<uuid>/` and the read-only `/api/locations/<uuid>/` serve existing rows, and climate analysis takes a `location_id` without a session check.
- Work is split into small PRs (accounts removal, place-from-URL, remove session locations and list pages, Celery/Redis removal and on-demand climate data, drop the Location table, deploy config cleanup).

## Commands

Windows: use the repo venv `.venv\Scripts\python.exe` (Git Bash path `.venv/Scripts/python.exe`), never the system Python. `manage.py` lives in `weather_app/`, not the repo root.

```bash
# Tests (what CI runs; run from repo root)
PYTHONPATH=weather_app DJANGO_SETTINGS_MODULE=config.settings .venv/Scripts/python.exe -m pytest tests/ -q
# Single test
... -m pytest tests/test_view_user.py::test_name -q
# Lint / format
.venv/Scripts/ruff.exe check .        # also run `ruff format .` (repo-wide clean; CI checks it)
npm run lint:js                       # JS in weather_app/static/weather/js
# Django checks CI runs
cd weather_app && python manage.py check --deploy && python manage.py makemigrations --check --dry-run
# Dev server (VS Code task "Django Runserver"), port 8000
cd weather_app && python manage.py runserver 8000
```

`make test` runs `manage.py test`, which is not what CI uses; prefer pytest. mypy (`mypy weather_app/weather --ignore-missing-imports`) is in CI lint but was failing locally on numpy stubs under Python 3.10; the project now targets Python 3.14 (CI, mypy, `.python-version` for Render).

## CI gates (all must be green before merge)

- Overall coverage **>= 90%** (`--cov=weather --cov-fail-under=90`) and **>= 80% diff coverage** (`diff-cover`).
- Ruff, pre-commit (run on the base..HEAD diff for PRs; auto-fixing hooks can exit 1 on the first run, rerun once), CodeQL, PR description check.
- **commitlint**: Conventional Commits, body lines <= 200 chars, applied to every commit in the PR.

## Git workflow

- Never commit or push to `master`. Branch from an up-to-date `master`, make small validated milestone commits (focused Conventional Commit each), open a PR, merge (squash).
- Do not push or open a PR unless asked. Never commit unrelated work or generated files (`weather_app.egg-info`, `out.txt`, `coverage.xml`).
- After opening a PR, watch CI and fix failures. The PR template checklist is in `.github/pull_request_template.md`.
- After a PR merges: checkout `master`, `git pull origin master`, delete the local branch (squash merges need `git branch -D` after confirming the PR state), `git fetch --prune`, confirm a clean status.

## Layout

- `weather_app/weather/`: models, `views.py` (large, ~2.7k lines), `services.py`, `tasks.py` (Celery), `noaa_service.py`, `noaa_nomads.py`, `climate_analysis.py`.
- `weather_app/weather/api/`: DRF views (climate analysis and normals, hourly forecast, model comparison, NWS client, summarize).
- `weather_app/weather/core/`: non-Django core logic. `weather_app/config/`: settings, urls, celery, wsgi.
- `weather_app/weather/management/commands/`: importers (`import_climate_data` has `--indices-only`), `update_forecasts`.
- `tests/` at repo root (pytest-django, `config.settings`). Templates in `weather_app/templates/weather/`.
- Settings fall back to SQLite when `DATABASE_URL` is unset; `DJANGO_SECRET_KEY` and allowed hosts are enforced in production.

## Climate analysis

- UI: `location_detail.html`; API: `api/climate_analysis_api.py`; stats in `climate_analysis.py`; importer in `import_climate_data.py`.
- Weather source: Open-Meteo Archive (daily, F/mph/in, per-location timezone). Indices: NAO/AO/PNA from CPC CDAS daily files; EPO/WPO from PSL core files standardized per calendar month (1991-2020); ENSO (internal key `oni`) is monthly. Never label monthly indices as daily.
- The user selects month/day and clicks Run (no request on page load). Completed years only; centered 7-day average; events are warm/cool/dry/wet at the top/bottom 10%.
- Missing indices load synchronously when Celery is off. The endpoint is rate-limited per IP and rejects inactive locations.

## Deploy (Render)

- Service `Weather` (`srv-d65khre3jp1c73athqbg`), `master`, build `render-build.sh`, start `render-release.sh && render-start.sh` (migrate, then gunicorn). Dashboard-managed; `render.yaml` is stale (describes services and a database that do not exist).
- Auto-deploy fires on merge to `master` once all GitHub checks pass (`checksPass`). Master Lint runs on the whole repo, so a failure there silently blocks deploys. Build uses the Python in `.python-version`.

## Editing gotchas

- Many source files use CRLF line endings. When rewriting files with scripts, read bytes, preserve `\r\n`, and re-check with `git diff --stat` that the diff is not whole-file.
- Re-run `ruff check` after removals: unused imports are the usual fallout.
