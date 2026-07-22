from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://ashenapi:AshenDBP@ssw0rd!@localhost:5432/ashenapi"

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
