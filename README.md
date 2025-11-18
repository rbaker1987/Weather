# Weather Django Application

A Django web application for weather forecasting with REST API and web interface.

## Features

- **Web Interface**: Weather dashboard with location management
- **REST API**: Full CRUD operations for locations and forecasts 
- **Admin Panel**: Django admin for data management
- **Background Tasks**: Automatic forecast updates (optional)
- **Geographic Support**: Location coordinates and mapping

## Quick Start

```bash
# Install dependencies
pip install -e ".[django]"

# Setup database
cd weather_app
python manage.py migrate
python manage.py createsuperuser

# Run the application
python manage.py runserver
```

**Access Points:**
- Web Dashboard: http://localhost:8000
- Admin Panel: http://localhost:8000/admin
- API Documentation: http://localhost:8000/api

## Usage

### Web Interface
1. Visit the dashboard to add locations
2. View current forecasts and weather data
3. Use admin panel for detailed data management

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

```
Weather/
├── weather_app/             # Django project
│   ├── config/              # Settings and configuration
│   ├── weather/             # Main weather app
│   │   ├── models.py        # Database models
│   │   ├── views.py         # API and web views
│   │   ├── services.py      # Business logic
│   │   ├── admin.py         # Admin interface
│   │   ├── api/             # External API clients
│   │   ├── utils/           # Helper functions
│   │   └── management/      # Custom commands
│   ├── templates/           # HTML templates
│   └── static/              # CSS/JS assets
└── pyproject.toml           # Python packaging
```