import bcrypt
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import Account, RefreshToken

# Username: 3-32 chars, letters/digits/underscores
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
# Password: min 8, at least one upper, one lower, one digit
_PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Public API ─────────────────────────────────────────

    async def register(self, username: str, password: str) -> Account:
        if not _USERNAME_RE.match(username):
            raise ValueError("Username must be 3-32 characters (letters, digits, underscores).")
        if not _PASSWORD_RE.match(password):
            raise ValueError("Password must be at least 8 characters and contain uppercase, lowercase, and digit.")

        result = await self.db.execute(select(Account).where(Account.username == username))
        if result.scalar_one_or_none() is not None:
            raise ValueError("Username is already taken.")

        account = Account(
            id=uuid4(),
            username=username,
            password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        )
        self.db.add(account)
        await self.db.flush()
        return account

    async def login(self, username: str, password: str) -> tuple[dict, Account] | None:
        result = await self.db.execute(select(Account).where(Account.username == username))
        account = result.scalar_one_or_none()
        if account is None or not bcrypt.checkpw(password.encode(), account.password_hash.encode()):
            return None

        tokens = await self._generate_token_pair(account)
        return tokens, account

    async def refresh(self, refresh_token: str) -> dict | None:
        token_hash = self._hash_token(refresh_token)
        result = await self.db.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .where(RefreshToken.revoked_at.is_(None))
        )
        stored = result.scalar_one_or_none()
        if stored is None or stored.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None

        # Revoke old token
        stored.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()

        result = await self.db.execute(select(Account).where(Account.id == stored.account_id))
        account = result.scalar_one_or_none()
        if account is None:
            return None

        return await self._generate_token_pair(account)

    async def logout(self, refresh_token: str) -> None:
        token_hash = self._hash_token(refresh_token)
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        stored = result.scalar_one_or_none()
        if stored is not None:
            stored.revoked_at = datetime.now(timezone.utc)
            await self.db.flush()

    async def change_password(self, account_id: UUID, current_password: str, new_password: str) -> bool:
        result = await self.db.execute(select(Account).where(Account.id == account_id))
        account = result.scalar_one_or_none()
        if account is None or not bcrypt.checkpw(current_password.encode(), account.password_hash.encode()):
            return False
        if not _PASSWORD_RE.match(new_password):
            raise ValueError("Password must be at least 8 characters and contain uppercase, lowercase, and digit.")
        account.password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        account.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def reset_password(self, account_id: UUID, new_password: str | None = None) -> str:
        result = await self.db.execute(select(Account).where(Account.id == account_id))
        account = result.scalar_one_or_none()
        if account is None:
            raise ValueError("Account not found.")
        password = new_password or self._generate_random_password()
        account.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        account.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return password

    # ── Private helpers ────────────────────────────────────

    async def _generate_token_pair(self, account: Account) -> dict:
        access_token = self._generate_access_token(account)
        refresh_token = self._generate_refresh_token()

        rt = RefreshToken(
            id=uuid4(),
            token_hash=self._hash_token(refresh_token),
            account_id=account.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        self.db.add(rt)
        await self.db.flush()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": settings.jwt_expires_in_minutes * 60,
        }

    def _generate_access_token(self, account: Account) -> str:
        now = datetime.now(timezone.utc)
        claims = {
            "sub": str(account.id),
            "username": account.username,
            "role": "Admin" if account.is_admin else "User",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "exp": now + timedelta(minutes=settings.jwt_expires_in_minutes),
            "iat": now,
        }
        return jwt.encode(claims, settings.jwt_key, algorithm="HS256")

    @staticmethod
    def _generate_refresh_token() -> str:
        return secrets.token_urlsafe(64)

    def _hash_token(self, token: str) -> str:
        """HMAC-SHA256 keyed by RefreshTokenKey."""
        key = settings.refresh_token_key.encode("utf-8")
        digest = hmac.new(key, token.encode("utf-8"), hashlib.sha256).digest()
        return digest.hex()

    @staticmethod
    def _generate_random_password() -> str:
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*"
        return "".join(secrets.choice(chars) for _ in range(16))
