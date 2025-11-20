# Ralph's Weather Django Application

A Django web application for weather forecasting using the National Weather Service API.

## Features

- **Web Interface**: Dashboard with browser geolocation and location management
- **REST API**: Full CRUD operations for locations and forecasts
- **Real-time Data**: Current conditions, hourly/daily forecasts, and weather alerts from NWS
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

- **Dashboard**: Browser location weather with automatic geolocation
- **Locations**: Add locations by name/zip code, view detailed forecasts
- **Forecasts**: 7-day forecasts with hourly breakdowns
- **Alerts**: Active weather alerts for your locations

**Note:** Locations are session-only and clear when browser closes.

### REST API Examples

```bash
# Create location
curl -X POST http://localhost:8000/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Austin, TX"}'

# Get forecasts
curl http://localhost:8000/api/locations/{id}/forecasts/
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
- `weather/views.py` - Django views and DRF API endpoints
- `weather/services.py` - NWS API integration
- `weather/utils/` - Geocoding, apparent temperature calculations
- `weather/middleware.py` - Session location management

**Frontend:**

- `templates/weather/components/` - Reusable template fragments
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

### Apparent Temperature

- Centralized calculation in `weather/utils/apparent_temperature.py`
- Heat Index (≥80°F) and Wind Chill (≤50°F, wind ≥3mph)
- Only displayed when difference ≥3°F
- New field: `Location.current_wind_gust` (requires migration)

### Component-Based Templates

- `forecast_period_card.html` - Day/night forecast display
- `section_header.html` - Standardized card headers
- Eliminated ~200 lines of duplicate markup

## Contributing

Run tests before committing:

```bash
pytest tests/
ruff check .
npm run lint:js
```

