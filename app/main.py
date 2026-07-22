import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import Base, async_session_factory, engine
from app.models.models import Account
from app.routers import admin, auth, health, identity, pgadmin_proxy, release, session


SECURITY_SCHEME_NAME = "bearerAuth"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: create tables and seed admin
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        await _seed_admin(db)

    yield

    # Shutdown
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AshenAPI",
        description="Ashen Studio API — Minecraft launcher session management, identity linking, release distribution, and migration orchestration",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── OpenAPI security scheme (Swagger Authorize button) ──
    _orig_openapi = app.openapi

    def _custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = _orig_openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {})[SECURITY_SCHEME_NAME] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter your JWT access token. Get one via POST /api/auth/login.",
        }
        schema.setdefault("security", []).append({SECURITY_SCHEME_NAME: []})
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi

    # ── CORS ───────────────────────────────────────────────
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(identity.router)
    app.include_router(session.router)
    app.include_router(release.router)
    app.include_router(admin.router)
    app.include_router(pgadmin_proxy.router)

    return app


async def _seed_admin(db: AsyncSession) -> None:
    if not settings.admin_email or not settings.admin_password:
        return

    result = await db.execute(select(Account).where(Account.username == settings.admin_email))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return

    admin = Account(
        id=UUID(int=secrets.randbits(128)),
        username=settings.admin_email,
        password_hash=bcrypt.hashpw(settings.admin_password.encode(), bcrypt.gensalt()).decode(),
        is_admin=True,
    )
    db.add(admin)
    await db.commit()


app = create_app()
