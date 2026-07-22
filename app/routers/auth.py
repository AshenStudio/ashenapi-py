from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_account, get_db_session
from app.models.models import Account
from app.schemas.auth import (
    AccountDto,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db_session)):
    service = AuthService(db)
    try:
        account = await service.register(body.username, body.password)
        return AccountDto(id=account.id, username=account.username, created_at=account.created_at)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db_session)):
    service = AuthService(db)
    result = await service.login(body.username, body.password)
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")

    tokens, account = result
    return LoginResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        account=AccountDto(id=account.id, username=account.username, created_at=account.created_at),
    )


@router.post("/refresh")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db_session)):
    service = AuthService(db)
    tokens = await service.refresh(body.refresh_token)
    if tokens is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token.")
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, db: AsyncSession = Depends(get_db_session)):
    service = AuthService(db)
    await service.logout(body.refresh_token)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db_session),
):
    service = AuthService(db)
    try:
        success = await service.change_password(current_account.id, body.current_password, body.new_password)
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
