from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session
from app.schemas.health import DatabaseHealth, HealthResponse, MigrationHealth

router = APIRouter(tags=["Health"])

_startup_time = datetime.now(timezone.utc)


@router.get("/api/health", response_model=HealthResponse)
async def get_health(db: AsyncSession = Depends(get_db_session)):
    now = datetime.now(timezone.utc)
    uptime = now - _startup_time
    if uptime.total_seconds() < 0:
        uptime = 0

    # Database connectivity
    db_healthy = False
    db_error: str | None = None
    try:
        await db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception as e:
        db_error = str(e)

    db_health = DatabaseHealth(can_connect=db_healthy, error=db_error)

    # Migration status - simplified check
    migration_health = MigrationHealth(state="Unknown")
    try:
        result = await db.execute(
            text("SELECT COUNT(*) FROM \"__EFMigrationsHistory\"")
        )
        migration_count = result.scalar() or 0
        migration_health = MigrationHealth(
            state="Up to date" if migration_count > 0 else "No migrations",
            pending_count=0,
            pending_migrations=None,
        )
    except Exception as e:
        migration_health = MigrationHealth(
            state="Unknown",
            pending_count=0,
            pending_migrations=[f"Could not check migrations: {e}"],
        )

    overall_status = "Healthy" if (db_healthy and migration_health.pending_count == 0) else "Degraded"

    return HealthResponse(
        status=overall_status,
        startup_time=_startup_time,
        uptime=uptime.total_seconds(),
        database=db_health,
        migration=migration_health,
    )
