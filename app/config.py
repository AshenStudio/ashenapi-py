from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


def build_database_url(
    user: str = "ashenapi",
    password: str = "AshenDBP@ssw0rd!",
    host: str = "localhost",
    port: int = 5432,
    database: str = "ashenapi",
    driver: str = "postgresql+asyncpg",
) -> str:
    """Build a database URL with the password properly URL-encoded."""
    encoded_password = quote(password, safe="")
    return f"{driver}://{user}:{encoded_password}@{host}:{port}/{database}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────
    # If DATABASE_URL is explicitly set, use it as-is (overrides individual parts).
    database_url: str | None = None

    # Individual DB connection parts (used when DATABASE_URL is not set).
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "ashenapi"
    db_password: str = "AshenDBP@ssw0rd!"
    db_name: str = "ashenapi"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return build_database_url(
            user=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    # ── JWT ─────────────────────────────────────────────────
    jwt_key: str = "change-this-jwt-key-must-be-at-least-32-bytes!"
    jwt_issuer: str = "AshenAPI"
    jwt_audience: str = "AshenLauncher"
    jwt_expires_in_minutes: int = 60

    # ── Security ────────────────────────────────────────────
    refresh_token_key: str = "change-this-refresh-token-key-must-be-32-bytes!"

    # ── Server ──────────────────────────────────────────────
    server_key: str = "change-this-server-key-must-be-32-bytes!"

    # ── Admin seed ──────────────────────────────────────────
    admin_email: str = "admin"
    admin_password: str = "AdminP@ssw0rd!"

    # ── CORS ────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5209,http://localhost:3000"

    # ── Storage ─────────────────────────────────────────────
    storage_path: str = "storage"

    # ── Base URL (for download links) ───────────────────────
    base_url: str = "http://localhost:8000"


settings = Settings()
