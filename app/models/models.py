import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Account(Base):
    __tablename__ = "Accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    identities = relationship("Identity", back_populates="account", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="account", cascade="all, delete-orphan")
    launcher_sessions = relationship("LauncherSession", back_populates="account", cascade="all, delete-orphan")
    migration_logs = relationship("MigrationLog", back_populates="account", cascade="all, delete-orphan")


class Identity(Base):
    __tablename__ = "Identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("Accounts.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # "Premium" or "Offline"
    minecraft_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    minecraft_username: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    account = relationship("Account", back_populates="identities")
    launcher_sessions = relationship("LauncherSession", back_populates="identity", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "RefreshTokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("Accounts.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    account = relationship("Account", back_populates="refresh_tokens")


class LauncherSession(Base):
    __tablename__ = "LauncherSessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("Accounts.id", ondelete="CASCADE"), nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("Identities.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    previous_offline_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)

    account = relationship("Account", back_populates="launcher_sessions")
    identity = relationship("Identity", back_populates="launcher_sessions")


class Release(Base):
    __tablename__ = "Releases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # "Launcher" or "Modpack"
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)


class MigrationLog(Base):
    __tablename__ = "MigrationLogs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("Accounts.id", ondelete="CASCADE"), nullable=False)
    old_offline_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    new_premium_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    minecraft_username: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="Pending", nullable=False)  # Pending, Completed, Failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    account = relationship("Account", back_populates="migration_logs")


class MigrationRetryRequest(Base):
    __tablename__ = "MigrationRetryRequests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    migration_log_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    retry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    old_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    new_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    minecraft_username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="Pending", nullable=False)
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
