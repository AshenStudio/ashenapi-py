import hashlib
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Identity, MigrationLog

# Shared HTTP client reused across requests (prevents connection pool leaks).
# This mirrors the original .NET pattern of registering HttpClient as a singleton.
_http_client = httpx.AsyncClient(timeout=5.0)


class IdentityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_identities(self, account_id: UUID) -> list[Identity]:
        result = await self.db.execute(
            select(Identity)
            .where(Identity.account_id == account_id)
            .order_by(Identity.created_at)
        )
        return list(result.scalars().all())

    async def link_microsoft(
        self,
        account_id: UUID,
        minecraft_uuid: str,
        minecraft_username: str,
    ) -> tuple[Identity, str | None]:
        # Check for existing premium identity
        result = await self.db.execute(
            select(Identity).where(
                Identity.account_id == account_id,
                Identity.type == "Premium",
                Identity.minecraft_uuid == minecraft_uuid,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing, None

        # Detect offline→premium upgrade
        previous_offline_uuid: str | None = None
        result = await self.db.execute(
            select(Identity).where(
                Identity.account_id == account_id,
                Identity.type == "Offline",
                Identity.minecraft_username == minecraft_username,
            )
        )
        offline = result.scalar_one_or_none()
        if offline is not None:
            previous_offline_uuid = offline.minecraft_uuid
            await self.db.delete(offline)
            await self.db.flush()

        identity = Identity(
            id=uuid4(),
            account_id=account_id,
            type="Premium",
            minecraft_uuid=minecraft_uuid,
            minecraft_username=minecraft_username,
        )
        self.db.add(identity)

        if previous_offline_uuid is not None:
            log = MigrationLog(
                id=uuid4(),
                account_id=account_id,
                old_offline_uuid=previous_offline_uuid,
                new_premium_uuid=minecraft_uuid,
                minecraft_username=minecraft_username,
                status="Pending",
            )
            self.db.add(log)

        await self.db.flush()
        return identity, previous_offline_uuid

    async def link_offline(self, account_id: UUID, username: str) -> Identity:
        # Cross-account uniqueness
        result = await self.db.execute(
            select(Identity).where(
                Identity.type == "Offline",
                Identity.minecraft_username == username,
                Identity.account_id != account_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError(
                f"Offline username '{username}' is already linked to another Ashen account."
            )

        # Check Mojang API if username is premium
        is_premium = await self._is_premium_username(username)
        if is_premium:
            raise ValueError(
                f"'{username}' is a premium Minecraft account. Offline users cannot use premium account names."
            )

        # Check existing offline identity for this account
        result = await self.db.execute(
            select(Identity).where(
                Identity.account_id == account_id,
                Identity.type == "Offline",
                Identity.minecraft_username == username,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

        offline_uuid = self._generate_offline_uuid(username)
        identity = Identity(
            id=uuid4(),
            account_id=account_id,
            type="Offline",
            minecraft_uuid=offline_uuid,
            minecraft_username=username,
        )
        self.db.add(identity)
        await self.db.flush()
        return identity

    async def delete(self, account_id: UUID, identity_id: UUID) -> bool:
        result = await self.db.execute(
            select(Identity).where(
                Identity.id == identity_id,
                Identity.account_id == account_id,
            )
        )
        identity = result.scalar_one_or_none()
        if identity is None:
            return False
        await self.db.delete(identity)
        await self.db.flush()
        return True

    async def _is_premium_username(self, username: str) -> bool:
        try:
            response = await _http_client.get(
                f"https://api.mojang.com/users/profiles/minecraft/{username}"
            )
            if response.status_code == 200:
                data = response.json()
                return bool(data.get("id"))
            return False
        except (httpx.RequestError, httpx.TimeoutException):
            return False

    @staticmethod
    def _generate_offline_uuid(username: str) -> str:
        hash_bytes = hashlib.md5(f"OfflinePlayer:{username}".encode("utf-8")).digest()
        b = bytearray(hash_bytes)
        b[6] = (b[6] & 0x0F) | 0x30
        b[8] = (b[8] & 0x3F) | 0x80
        return str(UUID(bytes=bytes(b)))
