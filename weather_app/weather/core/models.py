"""Core weather data models using Pydantic for validation and serialization."""

from datetime import date as date_type
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field, validator


class TemperatureUnit(str, Enum):
    """Temperature unit enumeration."""

    FAHRENHEIT = "F"
    CELSIUS = "C"


class WindDirection(str, Enum):
    """Cardinal wind directions."""

    N = "N"
    NE = "NE"
    E = "E"
    SE = "SE"
    S = "S"
    SW = "SW"
    W = "W"
    NW = "NW"


class Location(BaseModel):
    """Geographic location model."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., description="Location name (e.g., 'Lindale, TX')")
    latitude: Optional[float] = Field(
        None, ge=-90, le=90, description="Latitude in decimal degrees"
    )
    longitude: Optional[float] = Field(
        None, ge=-180, le=180, description="Longitude in decimal degrees"
    )
    zip_code: Optional[str] = Field(
        None, pattern=r"^\d{5}(-\d{4})?$", description="US ZIP code"
    )

    @validator("name")
    def validate_name(cls, v):  # noqa: N805
        if not v or v.isspace():
            raise ValueError("Location name cannot be empty")
        return v.title()


class WindCondition(BaseModel):
    """Wind condition data."""

    speed: int = Field(..., ge=0, description="Wind speed in mph")
    direction: Optional[Union[WindDirection, str]] = Field(
        None, description="Wind direction"
    )
    gust: Optional[int] = Field(None, ge=0, description="Wind gust speed in mph")


class Temperature(BaseModel):
    """Temperature data with automatic apparent temperature calculation."""

    value: int = Field(..., description="Temperature value")
    unit: TemperatureUnit = Field(
        default=TemperatureUnit.FAHRENHEIT, description="Temperature unit"
    )

    def apparent_temperature(self, wind_speed: int) -> int:
        """Calculate apparent temperature (wind chill/heat index)."""
        if self.unit != TemperatureUnit.FAHRENHEIT:
            raise ValueError("Apparent temperature calculation requires Fahrenheit")

        # Simple wind chill calculation
        if self.value > 50 or wind_speed < 5:
            return self.value
        return int(
            35.74
            + (0.6215 * self.value)
            - 35.75 * (wind_speed**0.16)
            + 0.4275 * self.value * (wind_speed**0.16)
        )


class WeatherCondition(BaseModel):
    """Weather condition description."""

    short_forecast: str = Field(..., description="Brief weather description")
    detailed_forecast: Optional[str] = Field(
        None, description="Detailed weather description"
    )
    icon_url: Optional[str] = Field(None, description="Weather icon URL")


class WeatherAlert(BaseModel):
    """Weather alert/warning information."""

    event: str = Field(..., description="Alert event type")
    headline: Optional[str] = Field(None, description="Alert headline")
    description: Optional[str] = Field(None, description="Alert description")
    start_time: datetime = Field(..., description="Alert start time")
    end_time: Optional[datetime] = Field(None, description="Alert end time")
    severity: Optional[str] = Field(None, description="Alert severity level")


class HourlyForecast(BaseModel):
    """Single hour weather forecast."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    location: Location
    forecast_time: datetime = Field(..., description="Time this forecast is for")
    temperature: Temperature
    wind: WindCondition
    weather: WeatherCondition
    alerts: list[WeatherAlert] = Field(default_factory=list)
    precipitation_probability: Optional[int] = Field(
        None, ge=0, le=100, description="Chance of precipitation (%)"
    )

    @property
    def wind_condition(self) -> WindCondition:
        """Alias used by Django service layer."""
        return self.wind

    @property
    def period_start(self) -> datetime:
        return self.forecast_time

    @property
    def period_end(self) -> datetime:
        return self.forecast_time + timedelta(hours=1)

    @property
    def date(self) -> date_type:
        return self.forecast_time.date()

    @property
    def short_forecast(self) -> str:
        return self.weather.short_forecast

    @property
    def detailed_forecast(self) -> Optional[str]:
        return self.weather.detailed_forecast

    @property
    def apparent_temperature(self) -> int:
        """Get apparent temperature for this forecast."""
        return self.temperature.apparent_temperature(self.wind.speed)

    @property
    def time_12h(self) -> str:
        """Get 12-hour formatted time string."""
        hour = self.forecast_time.hour
        if hour == 0:
            return "12AM"
        if hour < 10:
            return f"0{hour}AM"
        if hour < 12:
            return f"{hour}AM"
        if hour == 12:
            return "12PM"
        if hour < 22:
            return f"0{hour - 12}PM"
        return f"{hour - 12}PM"


class DailyForecast(BaseModel):
    """Daily weather forecast containing multiple hourly forecasts."""

    date: date_type = Field(..., description="Forecast date")
    location: Location
    hourly_forecasts: list[HourlyForecast] = Field(default_factory=list)

    @property
    def high_temperature(self) -> Optional[int]:
        """Get the highest temperature for the day."""
        if not self.hourly_forecasts:
            return None
        return max(f.temperature.value for f in self.hourly_forecasts)

    @property
    def low_temperature(self) -> Optional[int]:
        """Get the lowest temperature for the day."""
        if not self.hourly_forecasts:
            return None
        return min(f.temperature.value for f in self.hourly_forecasts)

    @property
    def primary_weather(self) -> Optional[str]:
        """Get the most common weather condition for the day."""
        if not self.hourly_forecasts:
            return None
        # Simple approach: return the weather condition from noon or closest to it
        noon_forecasts = [
            f for f in self.hourly_forecasts if 10 <= f.forecast_time.hour <= 14
        ]
        if noon_forecasts:
            return noon_forecasts[0].weather.short_forecast
        return self.hourly_forecasts[0].weather.short_forecast


class WeatherReport(BaseModel):
    """Complete weather report for one or more locations."""

    locations: list[Location]
    daily_forecasts: list[DailyForecast] = Field(default_factory=list)
    alerts: list[WeatherAlert] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)

    def get_forecasts_for_location(self, location_name: str) -> list[DailyForecast]:
        """Get all daily forecasts for a specific location."""
        return [
            df
            for df in self.daily_forecasts
            if df.location.name.lower() == location_name.lower()
        ]

    def get_alerts_for_location(self, location_name: str) -> list[WeatherAlert]:
        """Get all alerts for a specific location."""
        # This would need to be implemented based on how alerts are associated with locations
        return self.alerts


# Legacy data conversion utilities
def dict_to_hourly_forecast(data: dict, location: Location) -> HourlyForecast:
    """Convert legacy dictionary format to modern HourlyForecast model."""
    return HourlyForecast(
        location=location,
        forecast_time=datetime.strptime(
            f"{data['date']} {data['time']}", "%Y-%m-%d %I%p"
        ),
        temperature=Temperature(value=data["temperature"]),
        wind=WindCondition(speed=data["wind"]),
        weather=WeatherCondition(short_forecast=data["weather"]),
        alerts=[
            WeatherAlert(
                event=alert,
                start_time=datetime.now(),  # This would need proper parsing
                headline=alert,
            )
            for alert in data.get("alerts", "").split(", ")
            if alert
        ],
    )
