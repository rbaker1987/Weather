# Weather app roadmap (2026-11-18)

Constraint that shapes everything: Render **free** web service, no permanent DB, no paid services.
Sleeping instance (cold starts), ephemeral disk, one worker. Every upgrade must be stateless-first.
Audience: the owner today; possibly public long-term (not yet). Avoid choices that block going public.

## Done

Merged in PR #102 (stateless redesign + model comparison):

- Celery/Redis removed; climate analysis computed on demand by `lat`/`lon` (`climate_data.py`,
  `/api/climate-indices/`); the `Location` table and every persisted forecast model, API, signal,
  importer and command dropped (migration 0023); `render.yaml` made accurate; dependencies pruned.
- `upstream.get_json` shared cache; parallel place and model fetches; per-model "unavailable"
  reasons; `/healthz/`.
- Model Agreement (`model_spread.py`, `/api/model-spread/`) and Recent Accuracy
  (`forecast_verification.py`, `/api/forecast-verification/`, temperature only, nearest NWS station).

## Status (2026-11-19)

Built and pushed as PRs (dependent PRs are drafts until their predecessors merge). Stacks: B1 > B2 > radar > B3; C2 > C3 > C4 > E1; C1, NOMADS removal
and the coordinates fix each stand alone.

| Item | Branch | Notes |
|---|---|---|
| B1 panel JSON endpoints | #103 `feat/place-panel-endpoints` | `/api/place/<panel>/` |
| B2 place page shell | #104 `feat/place-shell` | server-rendered fragments per panel, own retry |
| B3 shareable URLs | #106 `feat/shareable-urls` | models, days, climate date in URL; last place in localStorage |
| B4 NOMADS telemetry | dropped | NOMADS was already disabled; removed instead |
| C1 real normals | `feat/real-climate-normals` | 1991-2020 from Open-Meteo Archive |
| C2 sample-size warnings | #107 `feat/climate-sample-warnings` | warnings, multiple-testing summary, caveats |
| C3 analog years | #108 `feat/climate-analog-years` | scaled-distance ranking vs latest index values |
| C4 CSV export | #109 `feat/climate-csv-export` | client-side |
| D1+D2 radar | #105 `feat/radar-regional` | radar already existed; now US-coverage gated |
| E1+E2 seasonal outlook | #110 `feat/seasonal-outlook` | ENSO only (PDO file stale since Aug 2025) |
| NOMADS removal | `refactor/remove-nomads` | dead code, xarray and cfgrib dropped |
| Invalid coordinates page | `fix/place-invalid-coordinates` | 400 page instead of broken JS |

Not started: C5 composite plots, D3 alert polygons, and Track F (mypy, `views.py` split, test
consolidation, `pip-audit`, local TLS).

## Known findings

- `/api/climate-normals/` is mislabeled: it averages the 7-day NWS forecast, not climate normals (C1).
- Python `requests` cannot verify TLS on the owner's Windows machine (curl can), so live upstream
  calls cannot be exercised locally (F6).
- `npm run lint:js` shows about 550 CRLF-only errors locally; files are clean as LF.
- Open-Meteo's free tier is non-commercial and rate-limited: the main risk of going public.

## Decisions

- Radar is **US only** (NWS/MRMS), zoomed to the region around the place, hidden outside the US.
- Normals are **real 1991-2020 averages** computed from the Open-Meteo Archive, labeled
  "1991-2020 average at this location" (not NOAA station normals).
- Seasonal outlook stays, clearly labeled analog-based and low skill.
- NOMADS raw GRIB parsing: removed (it was already disabled in `ModelDetailView`).
- Optional PRs C5 and D3 are included.
- Rules for every PR: Conventional Commits, coverage >= 90% and diff coverage >= 80%, ruff, no
  persisted state, never label monthly indices as daily, no push/PR/auto-merge without approval.

## Plan (PRs by track)

Order: B1-B2 with C1-C2 interleaved, then C3, D1-D2, then B3/B4/C4/D3, then C5 and E, with F as filler.

### Track B: cold-start shell

| PR | Content | Depends on | Size |
|---|---|---|---|
| B1 | Split `place_service` into JSON endpoints: current conditions, forecast, alerts (keep parallel logic and shared cache) | - | M |
| B2 | Place page shell: server renders header + skeleton panels; JS panel loader fills each from B1; per-panel errors and retry. First paint must not wait on any upstream call | B1 | M |
| B3 | Shareable URLs: selected models, units, climate month/day in the query string; last place in `localStorage` | B2 | S |
| B4 | NOMADS telemetry: structured timing logs, hard timeout, graceful fallback | - | S |

### Track C: climate analysis

| PR | Content | Depends on | Size |
|---|---|---|---|
| C1 | Real 1991-2020 normals from the Open-Meteo Archive (see below) | - | S |
| C2 | Sample-size and confidence warnings in `climate_analysis.py` and the UI | - | S |
| C3 | Analog-year ranking: stats function, API field, ranked table | C2 | M |
| C4 | CSV export of results, with units and index frequency in headers | C2 | S |
| C5 | Composite plots per index phase (optional) | C3 | M |

Review each with the `climate-reviewer` agent.

**C1 detail.** One archive call for 1991-2020 daily high/low/precip (about 11k rows). For each calendar
day, average over a centered 7-day window across the 30 years. Feb 29 uses the Feb 28 to Mar 1 window,
averaged over years that have it. Skip missing values and require a minimum number of valid years.
Precipitation is the average daily total. Cache by coordinates rounded to 0.1 degrees for 7 days via
`upstream.get_json` (errors never cached). Keep `/api/climate-normals/?lat=&lon=` but return an explicit
`period: "1991-2020"` and `source`; 502 on upstream failure; per-IP rate limit. Update the consumers in
`models.html` and `model_detail.html` (they used to compare a forecast with a forecast average). Tests:
the pure averaging function (leap day, missing values, minimum years) and the API (success, upstream
failure, invalid coordinates, cache hit).

### Track D: radar and map (US only)

| PR | Content | Depends on | Size |
|---|---|---|---|
| D1 | Leaflet map panel on the place page, opens at regional zoom (about 7-8) around the place; panel loaded by the shell | B2 | S |
| D2 | NWS/MRMS radar overlay with time slider and animation, attribution; hide outside the US (NWS `/points` failure). Verify the WMS URL and time-dimension support first | D1 | M |
| D3 | NWS alert polygons on the map (optional) | D1, B1 | S |

### Track E: seasonal outlook

| PR | Content | Depends on | Size |
|---|---|---|---|
| E1 | Analog years chosen from ENSO/AO/NAO/PDO state, with the spread of outcomes across them (adds the PDO index file) | C3 | M |
| E2 | UI with required labeling: "analog-based, low skill", analog years listed, spread shown rather than a single number | E1 | S |

### Track F: code health (filler)

| PR | Content | Size |
|---|---|---|
| F1 | Get mypy green on the 3.14 target and keep it a gate | S-M |
| F2-F3 | Split `views.py` into `views/place.py`, `views/models.py`, `views/climate.py`; extract `ModelDetailView` data shaping into a tested service first. No behavior change | M each |
| F4 | Consolidate branch-coverage-named test files; delete tests of removed code | S |
| F5 | `pip-audit` in CI and weekly Dependabot | S |
| F6 | Fix local Python TLS (machine issue, not code) | S |

## Before going public

- Resolve the Open-Meteo terms question (commercial plan, or cache/self-host the data).
- Cold-start shell (B), an accessibility pass, a privacy note for "use my location", basic abuse limits
  on every API, and attribution for NWS, Open-Meteo and NOAA in the footer.
- Check radar tile terms.
