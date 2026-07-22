import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.models import Identity, LauncherSession


class SessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        account_id: UUID,
        identity_id: UUID,
        previous_offline_uuid: str | None = None,
    ) -> LauncherSession:
        result = await self.db.execute(
            select(Identity)
            .where(Identity.id == identity_id, Identity.account_id == account_id)
        )
        identity = result.scalar_one_or_none()
        if identity is None:
            raise ValueError("Identity not found for this account.")

        token = secrets.token_urlsafe(64)
        token_hash = self._hash_token(token)

        session = LauncherSession(
            id=uuid4(),
            token_hash=token_hash,
            account_id=account_id,
            identity_id=identity_id,
            previous_offline_uuid=previous_offline_uuid,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self.db.add(session)
        await self.db.flush()

        # Return with the plain token in token_hash
        session.token_hash = token
        session.identity = identity
        return session

    async def validate(self, token: str) -> LauncherSession | None:
        token_hash = self._hash_token(token)
        result = await self.db.execute(
            select(LauncherSession)
            .options(
                selectinload(LauncherSession.identity),
                selectinload(LauncherSession.account),
            )
            .where(LauncherSession.token_hash == token_hash)
        )
        session = result.scalar_one_or_none()
        if session is None or session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None
        return session

    async def revoke(self, token: str) -> None:
        token_hash = self._hash_token(token)
        result = await self.db.execute(
            select(LauncherSession).where(LauncherSession.token_hash == token_hash)
        )
        session = result.scalar_one_or_none()
        if session is not None:
            await self.db.delete(session)
            await self.db.flush()

    def _hash_token(self, token: str) -> str:
        """HMAC-SHA256 keyed by RefreshTokenKey — matches the original .NET hash recipe."""
        key = settings.refresh_token_key.encode("utf-8")
        digest = hmac.new(key, token.encode("utf-8"), hashlib.sha256).digest()
        return digest.hex()
