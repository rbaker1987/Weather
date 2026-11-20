# CLAUDE.md

Django weather app: NWS forecasts plus raw model data (GFS, ICON, ECMWF, AIFS, GEM, HRRR, NAM, RGEM) side by side, and a historical climate/teleconnection analysis. Favor exposing raw, comparable model detail over a single blended number.

## Direction: stateless, free hosting

Production is a Render **free** web service with **no permanent database** (free Postgres expires every 30 days, and we do not pay for hosting). Design accordingly:

- There are no app models: the `weather` app has none (migration 0023 dropped them all). SQLite exists only for Django admin/auth/sessions and is rebuilt by `migrate` on every start (`render-release.sh`). Do not add models that must persist.
- User accounts are removed (signup/login/profile, `Location.owner`); only Django admin keeps `django.contrib.auth`. Session locations (`request.session["location_ids"]`) and the location/forecast/alert list pages are removed; the home page offers "use my location" or "enter a location", with the place carried in the URL, not the session or DB.
- Celery/Redis are removed; data is fetched on demand and the cache is process-local memory.
- The custom forecast builder is removed.
- Places are carried in the URL: `/weather/<lat>,<lon>/?name=` (`PlaceView`, `place_service.py`, no DB rows); `/api/geocode/?q=` powers the search box. Climate analysis (`/api/climate-analysis/?lat=&lon=&month=&day=`) and normals (`/api/climate-normals/?lat=&lon=`) also take coordinates. The `Location` table and every forecast/alert model, serializer, viewset, signal, Celery task and importer are gone.
- Remaining planned work lives in `docs/ROADMAP.md` (shared fetch cache, parallel upstream calls, model spread view, `views.py` split).

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
# Full pre-PR check (commit first): whole-repo ruff/eslint/prettier, file hygiene, commit messages, tests + 90% coverage
bash scripts/lint_all.sh
# Django checks CI runs
cd weather_app && python manage.py check --deploy && python manage.py makemigrations --check --dry-run
# Dev server (VS Code task "Django Runserver"), port 8000
cd weather_app && python manage.py runserver 8000
```

`make test` runs `manage.py test`, which is not what CI uses; prefer pytest. mypy (`mypy weather_app/weather --ignore-missing-imports`) is in CI lint but was failing locally on numpy stubs under Python 3.10; the project now targets Python 3.14 (CI, mypy, `.python-version` for Render).

## CI gates (all must be green before merge)

- Overall coverage **>= 90%** (`--cov=weather --cov-fail-under=90`) and **>= 80% diff coverage** (`diff-cover`).
- Lint (ruff, ESLint, Prettier) and pre-commit run on the **whole repo** for every PR and every push to master (auto-fixing hooks can exit 1 on the first run, rerun once), plus CodeQL and the PR description check. Run `bash scripts/lint_all.sh` before opening a PR; it covers everything except detect-secrets and django-upgrade, which only CI runs (they hang on the maintainer's Windows machine). If detect-secrets fails, commit the `.secrets.baseline` diff shown in the CI log.
- **commitlint**: Conventional Commits, body lines <= 200 chars, applied to every commit in the PR.

## Git workflow

- Never commit or push to `master`. Branch from an up-to-date `master`, make small validated milestone commits (focused Conventional Commit each), open a PR, merge (squash).
- Do not push or open a PR unless asked. Never commit unrelated work or generated files (`weather_app.egg-info`, `out.txt`, `coverage.xml`).
- After opening a PR, watch CI and fix failures. The PR template checklist is in `.github/pull_request_template.md`.
- After a PR merges: checkout `master`, `git pull origin master`, delete the local branch (squash merges need `git branch -D` after confirming the PR state), `git fetch --prune`, confirm a clean status.

## Layout

- `weather_app/weather/`: `views.py` (home, models, place and model-detail pages; `ModelDetailView` is ~1.3k lines), `place_service.py`, `regional_pages.py` (East Texas / NM Mountains reports, read on demand from the ralphs-weather-pages repo's `data/today.json`), `climate_data.py`, `climate_analysis.py`.
- `weather_app/weather/api/`: DRF views (climate analysis/indices/normals, geocode, hourly forecast, model comparison, summarize).
- `weather_app/weather/core/`: config only. `weather_app/config/`: settings, urls, wsgi.
- `tests/` at repo root (pytest-django, `config.settings`). Templates in `weather_app/templates/weather/`.
- Settings fall back to SQLite when `DATABASE_URL` is unset; `DJANGO_SECRET_KEY` and allowed hosts are enforced in production.

## Climate analysis

- UI: `location_detail.html`; API: `api/climate_analysis_api.py`; stats in `climate_analysis.py`; on-demand NOAA/Open-Meteo fetch and parsing in `climate_data.py` (no DB; cached in process memory); `/api/climate-indices/` gives the latest index values.
- Weather source: Open-Meteo Archive (daily, F/mph/in, per-location timezone). Indices: NAO/AO/PNA from CPC CDAS daily files; EPO/WPO from PSL core files standardized per calendar month (1991-2020); ENSO (internal key `oni`) is monthly. Never label monthly indices as daily.
- The user selects month/day and clicks Run (no request on page load). Completed years only; centered 7-day average; events are warm/cool/dry/wet at the top/bottom 10%.
- Everything is fetched on request (one Open-Meteo archive call for the full history, indices in parallel) and cached in memory; a failed index is reported in `unavailable_indices` instead of failing the request. The endpoint is rate-limited per IP.

## Deploy (Render)

- Service `Weather` (`srv-d65khre3jp1c73athqbg`), `master`, build `render-build.sh`, start `render-release.sh && render-start.sh` (migrate, then gunicorn). Dashboard-managed; `render.yaml` is stale (describes services and a database that do not exist).
- Auto-deploy fires on merge to `master` once all GitHub checks pass (`checksPass`). Master Lint runs on the whole repo, so a failure there silently blocks deploys. Build uses the Python in `.python-version`.

## Editing gotchas

- Many source files use CRLF line endings. When rewriting files with scripts, read bytes, preserve `\r\n`, and re-check with `git diff --stat` that the diff is not whole-file.
- Re-run `ruff check` after removals: unused imports are the usual fallout.
