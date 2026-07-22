from datetime import datetime, timedelta

from pydantic import BaseModel


class DatabaseHealth(BaseModel):
    can_connect: bool
    error: str | None = None


class MigrationHealth(BaseModel):
    state: str
    pending_count: int = 0
    pending_migrations: list[str] | None = None


class HealthResponse(BaseModel):
    status: str
    startup_time: datetime
    uptime: float  # seconds
    database: DatabaseHealth
    migration: MigrationHealth
