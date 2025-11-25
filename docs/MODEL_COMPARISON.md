# Model Comparison Feature

## Overview

The model comparison feature allows users to compare forecasts from multiple weather prediction models (GFS, ICON, ECMWF, AIFS, GEM, HRRR, NAM, RGEM) for any location.

## Components

### 1. Model Comparison API (`weather/api/model_comparison_api.py`)

**Endpoint**: `/api/model-comparison/`

**Purpose**: Fetches forecast data from Open-Meteo API for multiple weather models.

**Parameters**:
- `latitude` (required): Latitude coordinate (-90 to 90)
- `longitude` (required): Longitude coordinate (-180 to 180)
- `models` (required): Comma-separated list of model names (e.g., "GFS,ICON,ECMWF")
- `forecast_days` (optional): Number of days to forecast (default: 7, max: 16)

**Response Format**:
```json
{
  "status": "success",
  "models": [
    {
      "name": "GFS",
      "data": {
        "hourly": {
          "time": ["2025-11-25T00:00", ...],
          "temperature_2m": [70.5, ...],
          "precipitation": [0.0, ...]
        }
      }
    }
  ]
}
```

**Error Handling**:
- Returns 400 for missing/invalid parameters
- Returns 500 for API failures
- Includes error messages in response

### 2. Models Comparison Page (`templates/weather/models.html`)

**URL**: `/models/`

**Features**:
- Model selection checkboxes (up to 8 models)
- Location selector with map picker
- Interactive temperature and precipitation charts
- Forecast days dropdown (2-16 days)
- Real-time chart updates on selection changes

**JavaScript Functions**:
- `getSelectedModels()`: Returns set of checked model names
- `onModelSelectionChange()`: Handles model checkbox changes
- `loadModelData()`: Fetches and displays model comparison data
- `goToModelDetail(modelName)`: Navigates to individual model detail page

### 3. Model Detail Page (`templates/weather/model_detail.html`)

**URL**: `/models/<model_name>/`

**Features**:
- Detailed view for single weather model
- Model selector dropdown
- Location selector with map picker
- Forecast days dropdown with model-specific limits
- Temperature and precipitation charts
- Statistical summary (min/max/avg)

**Model Configuration**:
```python
MODEL_CONFIGS = {
    'GFS': {'max_days': 16},
    'ICON': {'max_days': 7},
    'ECMWF': {'max_days': 10},
    'AIFS': {'max_days': 10},
    'GEM': {'max_days': 10},
    'HRRR': {'max_days': 2},
    'NAM': {'max_days': 3},
    'RGEM': {'max_days': 2},
}
```

**Dynamic Forecast Days Logic**:
- Defaults to model's `max_days` when not specified
- Clamps user-provided days to model limits
- Auto-expands when switching to longer-range model
- Auto-clamps when switching to shorter-range model
- Dynamically rebuilds dropdown options

### 4. Location Selector Component (`templates/weather/components/location_selector.html`)

**Purpose**: Reusable component for location selection and map picker button.

**Usage**:
```django
{% include 'weather/components/location_selector.html' with location_col_class='col-md-8' map_btn_col_class='col-md-4' %}
```

**Features**:
- Dropdown of saved locations
- Current location indicator (⭐)
- Map picker button integration
- Customizable column classes for responsive layout

### 5. Location Picker Map Component (`templates/weather/components/location_picker_map.html`)

**Purpose**: Interactive map modal for coordinate selection.

**Features**:
- Leaflet-based map with OpenStreetMap tiles
- Click to select coordinates
- Rounds coordinates to 4 decimal places
- Fetches elevation from Open-Meteo API
- Defaults to current location if available
- Context-aware navigation (models vs location pages)

**JavaScript Functions**:
- `initLocationPickerMap()`: Initializes map and centers on current/selected location
- Coordinate validation and rounding
- Elevation fetching

### 6. Temporary Location View (`views.py: TempLocationView`)

**URL**: `/temp-location/`

**Purpose**: Display full forecast data for coordinates without saving location.

**Features**:
- Fetches NWS grid point data
- Retrieves observation station data for current conditions
- Gets 7-day forecast periods
- Fetches active weather alerts
- Creates pseudo-location object for template compatibility
- Uses same `location_detail.html` template as saved locations

**Data Sources**:
1. NWS Points API: Grid data
2. NWS Observation Stations API: Station list
3. NWS Observations API: Current conditions
4. NWS Forecast API: Daily periods
5. NWS Alerts API: Active alerts

## Model Information

### Global Models (Long-range forecasts)

**GFS (NOAA)**: 16 days
- Global coverage
- Updated 4x daily
- 13km resolution

**ICON (DWD)**: 7 days
- European focus
- High accuracy
- 13km global resolution

**ECMWF (IFS)**: 10 days
- Industry standard
- High accuracy
- 25km resolution

**AIFS (ECMWF)**: 10 days
- AI-based forecast
- Experimental
- 25km resolution

**GEM (ECCC)**: 10 days
- Canadian model
- North America focus
- 15km resolution

### Regional Models (Short-range, high-resolution forecasts)

**HRRR (NOAA)**: 2 days
- US only
- 3km resolution
- Updated hourly
- Excellent for severe weather

**NAM (NOAA)**: 3 days
- North America
- 12km resolution
- Updated 4x daily

**RGEM (ECCC)**: 2 days
- Regional Canadian model
- 10km resolution
- North America focus

## UI Enhancements

### Header Navigation
- **Home** (formerly "Dashboard"): Home icon
- **Models**: Chart icon (formerly cloud icon)
- **Locations**: Map marker icon
- **Alerts**: Exclamation triangle icon

### Breadcrumbs
- Updated to show "Home" instead of "Dashboard"
- Temporary locations show "Temporary Location" in breadcrumb

### Back Buttons
- "Back to Home" for temporary locations
- "Back to Locations" for saved locations

### Conditional UI Elements
Temporary locations hide:
- Edit location button
- Update forecast button
- Edit location modal
- Display customized "No Data" messages

## Integration Points

### Session Management
- Saved location IDs stored in `session['location_ids']`
- Used for filtering user-specific data
- Temporary locations not added to session

### API Caching
- Model comparison API includes cache-control headers
- Prevents stale data display
- Forces fresh requests for model data

### Error Handling
- Graceful degradation when NWS API unavailable
- User-friendly error messages
- Console logging for debugging

## Future Enhancements

Potential improvements:
- Persist temporary locations in session for quick re-access
- Add "Save as Location" button on temporary location page
- Visual indicators showing forecast days beyond model max
- Unified error handling for all API failures
- Loading states during data fetch operations
- Model ensemble averages
- Confidence intervals
- Historical accuracy tracking
