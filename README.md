# Ralph's Weather Django Application

A Django web application for weather forecasting with REST API and web interface.

## Features

- **Web Interface**: Weather dashboard with location management
- **REST API**: Full CRUD operations for locations and forecasts
- **Admin Panel**: Django admin for data management
- **Background Tasks**: Automatic forecast updates (optional)
- **Geographic Support**: Location coordinates and mapping
- **Session-based Storage**: All locations stored in session only (non-persistent across sessions)

## Quick Start

```bash
# Install dependencies
pip install -e ".[django]"

# Setup database
cd weather_app
python manage.py migrate

# Run the application
python manage.py runserver
```

**Access Points:**
- Web Dashboard: http://localhost:8000
- Admin Panel: http://localhost:8000/admin
- API Documentation: http://localhost:8000/api

## Data Persistence

**Important:** This application uses SQLite for local development. Data persistence behavior:

- **Database File**: `weather_app/db.sqlite3` (excluded from git)
- **Location Storage**: All locations stored in session only (cleared when session expires or browser closes)
- **Forecast Data**: Cached in SQLite for performance, refreshed automatically from NWS API
- **If Database Deleted**: Forecast cache will be lost, but will be re-fetched from NWS API on next request
- **No User Accounts**: Authentication system not implemented - all users are anonymous

**Recommendations:**
- For production deployment, migrate to PostgreSQL or MySQL for better performance
- Consider implementing user authentication if persistent location storage is needed

## Usage

### Web Interface

- Visit the dashboard to view your browser's current location weather
- Add saved locations by name or zip code
- View detailed forecasts and current conditions
- Check weather alerts for your locations

**Note:** All locations are stored in your browser session only. When you close your browser or the session expires, your saved locations will be cleared.

### REST API
```bash
# Create location
curl -X POST http://localhost:8000/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Austin, TX"}'

# Get forecasts
curl "http://localhost:8000/api/locations/{id}/forecasts/"
```

### Management Commands
```bash
# Update all forecasts
python manage.py update_forecasts

# Update specific locations
python manage.py update_forecasts --locations uuid1 uuid2
```

## Optional: Background Tasks

For automatic forecast updates:
```bash
# Install Redis and start
redis-server

# Start Celery worker (separate terminal)
cd weather_app
celery -A config worker --loglevel=info

# Start Celery beat scheduler (separate terminal)
celery -A config beat --loglevel=info
```

## Configuration

Optional environment variables:
```bash
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=False
DATABASE_URL=postgresql://user:pass@localhost/weather  # Optional
REDIS_URL=redis://localhost:6379/0  # For caching/Celery
```

## Project Structure

```text
Weather/
├── weather_app/             # Django project
│   ├── config/              # Settings and configuration
│   │   ├── settings.py      # Django settings
│   │   ├── urls.py          # URL routing
│   │   └── wsgi.py          # WSGI entry point
│   ├── weather/             # Main weather app
│   │   ├── models.py        # Database models (Location, Forecast, Alert)
│   │   ├── views.py         # API ViewSets and web views
│   │   ├── middleware.py    # Session location storage middleware
│   │   ├── services.py      # Business logic and NWS API integration
│   │   ├── serializers.py   # DRF serializers
│   │   ├── admin.py         # Django admin interface
│   │   ├── api/             # External API clients (NWS)
│   │   ├── utils/           # Helper functions (datetime, geocoding, logging)
│   │   └── management/      # Custom management commands
│   │       └── commands/
│   │           └── update_forecasts.py
│   ├── templates/           # HTML templates
│   │   └── weather/
│   │       ├── dashboard.html      # Main dashboard with browser location
│   │       ├── location_list.html  # Saved locations management
│   │       ├── location_detail.html # Individual location details
│   │       ├── forecast_list.html  # Forecast overview
│   │       └── alert_list.html     # Weather alerts
│   ├── static/              # CSS/JS assets
│   │   └── weather/
│   │       ├── css/style.css
│   │       └── js/weather.js
│   ├── db.sqlite3           # SQLite database (excluded from git)
│   └── manage.py            # Django management script
├── tests/                   # Unit tests
│   ├── test_models.py
│   └── test_datetime_utils.py
├── pyproject.toml           # Python packaging and dependencies
├── README.md                # This file
└── .gitignore               # Git ignore patterns (includes db.sqlite3)
```

## Architecture

**Session Management:**
- All users: `SessionLocationMiddleware` initializes `request.session['location_ids']` list
- No user authentication system implemented
- All location storage is session-based and temporary

**Data Flow:**
1. User adds location (browser geolocation or manual entry)
2. Location geocoded via Nominatim API (if coordinates missing)
3. Location ID saved to session storage
4. Views filter locations by session IDs
5. NWS API fetches forecasts/alerts for displayed locations
6. Current conditions updated every 30 minutes

**Key Features:**
- Browser geolocation integration on all pages
- Real-time weather from NWS API
- Automatic forecast updates
- Session-only storage (no persistence across sessions)
