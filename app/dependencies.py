from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import Account

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Account:
    """Extract and validate the JWT bearer token. Returns the Account."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.jwt_key,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        account_id = payload.get("sub")
        if account_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(select(Account).where(Account.id == UUID(account_id)))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found")
    return account


async def get_optional_account(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Account | None:
    """Try to extract the JWT bearer token, but return None if not present or invalid."""
    if credentials is None:
        return None
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_key,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        account_id = payload.get("sub")
        if account_id is None:
            return None
        result = await db.execute(select(Account).where(Account.id == UUID(account_id)))
        return result.scalar_one_or_none()
    except JWTError:
        return None


async def require_admin(account: Account = Depends(get_current_account)) -> Account:
    """Require the Admin role on top of authentication."""
    if not account.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return account


async def verify_server_key(
    x_ashen_server_key: str | None = Header(default=None, alias="X-Ashen-Server-Key"),
) -> str:
    """Validate the X-Ashen-Server-Key header. Returns the key on success."""
    if not x_ashen_server_key or x_ashen_server_key != settings.server_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid X-Ashen-Server-Key required",
        )
    return x_ashen_server_key


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Simple DB session dependency with auto-rollback on error."""
    async for session in get_db():
        yield session


def is_valid_server_key(x_ashen_server_key: str | None) -> bool:
    """Check if the provided server key is valid (no exception variant)."""
    return bool(x_ashen_server_key and x_ashen_server_key == settings.server_key)
