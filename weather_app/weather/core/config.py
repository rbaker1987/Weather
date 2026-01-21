"""Application configuration management using Pydantic Settings."""

from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class DatabaseConfig(BaseSettings):
    """Database configuration."""

    url: str = Field(default="sqlite:///weather_data.db", description="Database URL")
    echo: bool = Field(default=False, description="Echo SQL queries")

    class Config:
        env_prefix = "DB_"


class APIConfig(BaseSettings):
    """External API configuration."""

    nws_base_url: str = Field(
        default="https://api.weather.gov", description="NWS API base URL"
    )
    request_timeout: int = Field(default=30, description="Request timeout in seconds")
    rate_limit_delay: float = Field(
        default=1.0, description="Delay between requests in seconds"
    )
    user_agent: str = Field(
        default="weather-app/0.2.0", description="User agent for API requests"
    )

    class Config:
        env_prefix = "API_"


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Logging level")
    format: str = Field(
        default="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        description="Log format string",
    )
    file: Optional[str] = Field(
        default=None, description="Log file path (stdout if None)"
    )
    rotation: str = Field(default="10 MB", description="Log file rotation size")
    retention: str = Field(default="30 days", description="Log file retention period")

    class Config:
        env_prefix = "LOG_"


class UIConfig(BaseSettings):
    """User interface configuration."""

    theme: str = Field(default="Default", description="UI theme name")
    window_size: tuple[int, int] = Field(
        default=(1024, 768), description="Default window size"
    )
    default_locations: List[str] = Field(
        default=["Austin, TX", "Dallas, TX", "Houston, TX", "Tyler, TX"],
        description="Default locations for forecasts",
    )

    class Config:
        env_prefix = "UI_"


class AppConfig(BaseSettings):
    """Main application configuration."""

    debug: bool = Field(default=False, description="Enable debug mode")
    data_dir: Path = Field(default=Path("./data"), description="Data directory path")
    cache_dir: Path = Field(default=Path("./cache"), description="Cache directory path")

    # Sub-configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    class Config:
        env_prefix = "WEATHER_"
        env_nested_delimiter = "__"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.data_dir.mkdir(exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)


# Global configuration instance
config = AppConfig()


def load_config(config_file: Optional[Path] = None) -> AppConfig:
    """Load configuration from environment variables and optional config file."""
    if config_file and config_file.exists():
        # Could implement YAML/TOML loading here
        pass
    return AppConfig()


def get_config() -> AppConfig:
    """Get the current application configuration."""
    return config
