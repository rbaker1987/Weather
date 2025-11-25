# Ralph's Weather Django Application

A Django web application for weather forecasting using the National Weather Service API.

## Features

- **Web Interface**: Dashboard with browser geolocation and location management
- **Model Comparison**: Compare forecasts from 8 weather models (GFS, ICON, ECMWF, AIFS, GEM, HRRR, NAM, RGEM)
- **Temporary Locations**: View full forecasts for any map coordinates without saving
- **Custom Forecasts**: Edit daily and hourly forecasts with live preview and validation
- **Animated Radar**: Interactive weather radar maps with play/pause controls and time scrubbing
- **REST API**: Full CRUD operations for locations and forecasts
- **Real-time Data**: Current conditions, hourly/daily forecasts, and weather alerts from NWS
- **Merged Data**: Custom edits prioritized, NWS fills remaining forecast slots automatically
- **Timezone Support**: Accurate sunrise/sunset times with automatic timezone detection
- **Session Storage**: Locations stored per browser session (no user accounts)
- **Component-based UI**: Reusable Django template components
- **Responsive Design**: Bootstrap 5 with temperature-based color coding

## Quick Start

```bash
# Install dependencies
pip install -e ".[django]"

# Setup database and run migrations
cd weather_app
python manage.py migrate

# Start development server
python manage.py runserver
```

Visit <http://localhost:8000> to access the dashboard.

## Development

### Code Quality Tools

**Python (Ruff):**

```bash
pip install -e ".[dev]"
ruff check .              # Lint
ruff check --fix .        # Auto-fix
ruff format .             # Format
```

**JavaScript (ESLint + Prettier):**

```bash
npm install
npm run lint:js           # Lint
npm run lint:js:fix       # Auto-fix
npm run format            # Format
```

**Pre-commit Hooks (Optional):**

```bash
pip install pre-commit
pre-commit install
```

### VS Code Setup

Install recommended extensions (`.vscode/extensions.json`) for auto-formatting on save.

## Usage

### Web Interface

- **Home**: Browser location weather with automatic geolocation
- **Models**: Compare forecasts from multiple weather prediction models
  - **Global Models**: GFS (16-day), ICON (7-day), ECMWF (10-day), AIFS (10-day), GEM (10-day)
  - **Regional Models**: HRRR (2-day), NAM (3-day), RGEM (2-day)
  - Interactive temperature and precipitation charts
  - Model-specific forecast day limits
- **Locations**: Add locations by name/zip code, view detailed forecasts
- **Temporary Locations**: Click any map point to see full forecast data without saving
- **Forecasts**: 7-day forecasts with hourly breakdowns
- **Custom Forecasts**: Edit daily and hourly forecasts with live preview
- **Animated Radar**: Interactive weather radar with animation controls (play/pause, time slider)
- **Alerts**: Active weather alerts for your locations
- **Timezone Support**: Accurate sunrise/sunset times with proper timezone handling

**Note:** Locations are session-only and clear when browser closes.

### REST API Examples

```bash
# Create location
curl -X POST http://localhost:8000/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Austin, TX"}'

# Get forecasts
curl http://localhost:8000/api/locations/{id}/forecasts/

# Get hourly forecast with merged custom/NWS data
curl "http://localhost:8000/api/hourly_forecast/?lat=30.2672&lon=-97.7431&hours=24"

# Compare weather models
curl "http://localhost:8000/api/model-comparison/?latitude=30.2672&longitude=-97.7431&models=GFS,ICON,ECMWF&forecast_days=7"

# Create custom hourly forecast
curl -X POST http://localhost:8000/api/locations/{id}/hourly-forecasts/ \
  -H "Content-Type: application/json" \
  -d '{
    "forecast_time": "2025-11-24T14:00:00Z",
    "temperature": 75,
    "short_forecast": "Partly Cloudy",
    "wind_speed": 10,
    "precipitation_probability": 20
  }'
```

### Management Commands

```bash
# Update all forecasts
python manage.py update_forecasts

# Update specific locations
python manage.py update_forecasts --locations uuid1 uuid2
```

## Architecture

### Data Flow

1. User adds location (geolocation or manual entry)
2. Coordinates geocoded via Nominatim API (if needed)
3. Location ID stored in session
4. NWS API provides forecasts/alerts
5. Apparent temperature calculated (heat index/wind chill)
6. Data cached in SQLite, refreshed automatically

### Key Components

**Backend:**

- `weather/models.py` - Location, Forecast, Alert models
- `weather/views.py` - Django views and DRF API endpoints (including ModelDetailView, TempLocationView)
- `weather/services.py` - NWS API integration
- `weather/utils/` - Geocoding, apparent temperature, datetime utilities
- `weather/api/hourly_forecast_api.py` - Hourly forecast API with custom/NWS merge
- `weather/api/model_comparison_api.py` - Multi-model forecast comparison via Open-Meteo
- `weather/middleware.py` - Session location management

**Frontend:**

- `templates/weather/components/` - Reusable template fragments (location_selector.html, location_picker_map.html, radar_map.html, etc.)
- `static/weather/js/weather.js` - Dynamic UI interactions
- `static/weather/css/style.css` - Temperature-based styling

**Template Filters (`weather/templatetags/ui_tags.py`):**

- `condition_icon` - Maps forecast text to Font Awesome icons
- `temp_bg_class` - Returns temperature-based background class
- `should_show_feels_like` - Shows feels-like when ≥3°F difference

### Session Storage

- All location IDs stored in `request.session['location_ids']`
- No authentication system
- Locations cleared on session expiry/browser close
- Views automatically filter by session IDs

### Database

- **Development**: SQLite (`db.sqlite3`, excluded from git)
- **Production**: PostgreSQL/MySQL recommended
- **Persistence**: Forecast cache only; locations are session-based

## Optional: Background Tasks

Enable automatic forecast updates with Celery:

```bash
# Install and start Redis
redis-server

# Start Celery worker (terminal 1)
cd weather_app
celery -A config worker --loglevel=info

# Start Celery beat scheduler (terminal 2)
celery -A config beat --loglevel=info
```

## Configuration

Environment variables (optional):

```bash
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=False
DATABASE_URL=postgresql://user:pass@localhost/weather
REDIS_URL=redis://localhost:6379/0
```

## Project Structure

```text
weather_app/
├── config/                  # Django settings
├── weather/                 # Main app
│   ├── api/                 # NWS API client
│   ├── utils/               # Helpers (geocoding, apparent temp)
│   ├── templatetags/        # Custom filters
│   ├── management/commands/ # CLI commands
│   └── migrations/          # Database migrations
├── templates/weather/       # HTML templates
│   └── components/          # Reusable fragments
└── static/weather/          # CSS/JS assets
tests/                       # Unit tests
```

## Recent Enhancements

### Multi-Model Weather Comparison (NEW)

- Compare forecasts from 8 weather prediction models on interactive charts
- Global models: GFS (NOAA), ICON (DWD), ECMWF, AIFS, GEM (ECCC)
- Regional high-resolution models: HRRR, NAM, RGEM
- Model-specific forecast day limits (2-16 days) with dynamic UI
- Powered by Open-Meteo API for unified model access
- Individual model detail pages with statistics and data export

### Temporary Location Support (NEW)

- Click anywhere on map to view full forecast without saving location
- Fetches real-time data from NWS API (grid points, observations, forecasts, alerts)
- Same rich UI as saved locations (current conditions, daily forecasts, alerts)
- Perfect for travel planning or checking weather at arbitrary coordinates

### Location Picker Map (NEW)

- Interactive Leaflet map modal for precise coordinate selection
- Defaults to current location with elevation display
- Coordinate rounding to 4 decimal places (~11m precision)
- Context-aware navigation (integrates with models and location pages)

### UI Refinements (NEW)

- Renamed "Dashboard" to "Home" throughout interface
- Changed Models icon from cloud to chart for clearer data visualization context
- Reorganized location detail header for more compact layout
- Removed decorative icons from model names for cleaner presentation
- Extracted reusable location selector component to eliminate code duplication
- Dynamic forecast days dropdown adapts to selected model capabilities

### Animated Radar Maps

- Interactive weather radar using Leaflet.js and NOAA/NWS WMS layers
- Animation controls: play/pause button and time slider
- 11 frames covering last 2 hours at 10-minute intervals
- Reusable `radar_map.html` component with configurable parameters
- Base map switching: Street view or satellite imagery
- Base reflectivity data with color-coded legend (NOAA/NWS MRMS)
- Automatic radar initialization on dashboard and location detail pages

### Custom Forecast Editing

- Edit daily and hourly forecasts through modal interfaces
- Live preview with icon and temperature-based background updates
- Merged display: custom edits take priority, NWS fills remaining slots
- Time-aligned matching with 60-minute tolerance window
- Bulk save operations with validation
- "Update Forecast" button clears custom edits and refreshes from NWS

### Timezone Support

- Accurate sunrise/sunset calculations using Astral library
- TimezoneFinder for automatic timezone detection by coordinates
- Per-date sun event tracking for multi-day forecasts
- Proper UTC handling with `datetime_utils` module
- Day/night icon selection based on local solar position

### Apparent Temperature

- Centralized calculation in `weather/utils/apparent_temperature.py`
- Heat Index (≥80°F) and Wind Chill (≤50°F, wind ≥3mph)
- Only displayed when difference ≥3°F
- New field: `Location.current_wind_gust` (requires migration)

### Component-Based Templates

- `location_selector.html` - Reusable location dropdown with map picker button
- `location_picker_map.html` - Interactive coordinate selection modal
- `radar_map.html` - Animated weather radar with Leaflet.js integration
- `forecast_period_card.html` - Day/night forecast display
- `section_header.html` - Standardized card headers
- Eliminated ~300 lines of duplicate markup across templates

## Contributing

Run tests before committing:

```bash
pytest tests/
ruff check .
npm run lint:js
```

