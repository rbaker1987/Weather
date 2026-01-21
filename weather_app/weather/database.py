"""Database models and repository pattern implementation."""

from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    selectinload,
)
from sqlalchemy.sql import delete, select

from ..core.config import get_config
from ..core.models import HourlyForecast, Location


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class LocationDB(Base):
    """Database model for locations."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zip_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    forecasts: Mapped[list["ForecastDB"]] = relationship(
        "ForecastDB", back_populates="location"
    )

    def to_domain(self) -> Location:
        """Convert database model to domain model."""
        return Location(
            name=self.name,
            latitude=self.latitude,
            longitude=self.longitude,
            zip_code=self.zip_code,
        )

    @classmethod
    def from_domain(cls, location: Location) -> "LocationDB":
        """Create database model from domain model."""
        return cls(
            name=location.name,
            latitude=location.latitude,
            longitude=location.longitude,
            zip_code=location.zip_code,
        )


class ForecastDB(Base):
    """Database model for weather forecasts."""

    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("locations.id"), nullable=False
    )
    forecast_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    temperature: Mapped[int] = mapped_column(Integer, nullable=False)
    apparent_temperature: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Wind data
    wind_speed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wind_direction: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    wind_gust: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Weather description
    short_forecast: Mapped[str] = mapped_column(String(200), nullable=False)
    detailed_forecast: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    valid_until: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    location: Mapped[LocationDB] = relationship(
        "LocationDB", back_populates="forecasts"
    )
    alerts: Mapped[list["AlertDB"]] = relationship("AlertDB", back_populates="forecast")


class AlertDB(Base):
    """Database model for weather alerts."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    forecast_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("forecasts.id"), nullable=True
    )
    location_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("locations.id"), nullable=False
    )

    event: Mapped[str] = mapped_column(String(100), nullable=False)
    headline: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    forecast: Mapped[Optional[ForecastDB]] = relationship(
        "ForecastDB", back_populates="alerts"
    )
    location: Mapped[LocationDB] = relationship("LocationDB")


class DatabaseManager:
    """Manages database connections and operations."""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or get_config().database.url

        # Create async engine
        if self.database_url.startswith("sqlite"):
            # Convert SQLite URL for async operation
            if not self.database_url.startswith("sqlite+aiosqlite"):
                self.database_url = self.database_url.replace(
                    "sqlite://", "sqlite+aiosqlite://"
                )

        self.engine = create_async_engine(
            self.database_url, echo=get_config().database.echo
        )

        self.async_session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def create_tables(self):
        """Create all database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_tables(self):
        """Drop all database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @asynccontextmanager
    async def get_session(self):
        """Get an async database session."""
        async with self.async_session_factory() as session:
            try:
                yield session
            finally:
                await session.close()


class ForecastRepository:
    """Repository for forecast data operations."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def save_location(self, location: Location) -> LocationDB:
        """Save or update a location."""
        async with self.db_manager.get_session() as session:
            # Check if location already exists
            stmt = select(LocationDB).where(LocationDB.name == location.name)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing location
                existing.latitude = location.latitude
                existing.longitude = location.longitude
                existing.zip_code = location.zip_code
                await session.commit()
                return existing
            # Create new location
            location_db = LocationDB.from_domain(location)
            session.add(location_db)
            await session.commit()
            await session.refresh(location_db)
            return location_db

    async def save_forecasts(self, forecasts: list[HourlyForecast]) -> list[ForecastDB]:
        """Save multiple forecasts."""
        if not forecasts:
            return []

        async with self.db_manager.get_session() as session:
            forecast_models = []

            for forecast in forecasts:
                # Get or create location
                location_stmt = select(LocationDB).where(
                    LocationDB.name == forecast.location.name
                )
                location_result = await session.execute(location_stmt)
                location_db = location_result.scalar_one_or_none()

                if not location_db:
                    location_db = LocationDB.from_domain(forecast.location)
                    session.add(location_db)
                    await session.flush()  # Get the ID

                # Create forecast
                forecast_db = ForecastDB(
                    location_id=location_db.id,
                    forecast_time=forecast.forecast_time,
                    temperature=forecast.temperature.value,
                    apparent_temperature=forecast.apparent_temperature,
                    wind_speed=forecast.wind.speed,
                    wind_direction=forecast.wind.direction,
                    wind_gust=forecast.wind.gust,
                    short_forecast=forecast.weather.short_forecast,
                    detailed_forecast=forecast.weather.detailed_forecast,
                    icon_url=forecast.weather.icon_url,
                    valid_until=datetime.utcnow().replace(
                        hour=23, minute=59, second=59
                    ),
                )

                session.add(forecast_db)
                forecast_models.append(forecast_db)

            await session.commit()
            return forecast_models

    async def get_forecasts_for_location(
        self,
        location_name: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[ForecastDB]:
        """Get forecasts for a location within a date range."""
        async with self.db_manager.get_session() as session:
            stmt = (
                select(ForecastDB)
                .join(LocationDB)
                .where(LocationDB.name == location_name)
                .options(
                    selectinload(ForecastDB.location), selectinload(ForecastDB.alerts)
                )
            )

            if start_date:
                stmt = stmt.where(ForecastDB.forecast_time >= start_date)
            if end_date:
                end_datetime = datetime.combine(end_date, datetime.max.time())
                stmt = stmt.where(ForecastDB.forecast_time <= end_datetime)

            stmt = stmt.order_by(ForecastDB.forecast_time)

            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def cleanup_old_forecasts(self, older_than: datetime) -> int:
        """Remove forecasts older than the specified datetime."""
        async with self.db_manager.get_session() as session:
            stmt = delete(ForecastDB).where(ForecastDB.valid_until < older_than)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount

    async def get_locations(self) -> list[LocationDB]:
        """Get all locations."""
        async with self.db_manager.get_session() as session:
            stmt = select(LocationDB).order_by(LocationDB.name)
            result = await session.execute(stmt)
            return list(result.scalars().all())


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    """Get the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_forecast_repository() -> ForecastRepository:
    """Get a forecast repository instance."""
    return ForecastRepository(get_database_manager())
