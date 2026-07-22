import uuid

from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_account, get_db_session, verify_server_key
from app.models.models import Account, Identity
from app.schemas.identity import IdentityDto
from app.schemas.session import (
    CreateSessionRequest,
    SessionDto,
    SessionValidationDto,
)
from app.services.session_service import SessionService

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    current_account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db_session),
):
    service = SessionService(db)

    # Auto-resolve identity if not provided
    identity_id = body.identity_id
    if identity_id is None:
        result = await db.execute(
            select(Identity).where(Identity.account_id == current_account.id).order_by(Identity.created_at).limit(1)
        )
        identity = result.scalar_one_or_none()
        if identity is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Minecraft identity linked to this account. Complete the Minecraft auth step first.",
            )
        identity_id = identity.id

    try:
        session = await service.create(current_account.id, identity_id, body.previous_offline_uuid)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return SessionDto(
        token=session.token_hash,
        expires_at=session.expires_at,
        identity=IdentityDto(
            id=session.identity.id,
            type=session.identity.type,
            minecraft_uuid=session.identity.minecraft_uuid,
            minecraft_username=session.identity.minecraft_username,
            created_at=session.identity.created_at,
        ),
    )


@router.get("/{token}")
async def validate_session(
    token: str,
    x_ashen_server_key: str = Depends(verify_server_key),
    db: AsyncSession = Depends(get_db_session),
):
    service = SessionService(db)
    session = await service.validate(token)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found or expired.")

    identity = session.identity

    # Conflict check for premium identities
    if identity.type != "Offline":
        from sqlalchemy import select as sel
        result = await db.execute(
            sel(Identity).where(
                Identity.type == "Offline",
                Identity.minecraft_username == identity.minecraft_username,
                Identity.account_id != session.account_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Minecraft username '{identity.minecraft_username}' is already linked to another Ashen account as an offline identity.",
            )

    return SessionValidationDto(
        valid=True,
        account_id=session.account_id,
        identity=IdentityDto(
            id=identity.id,
            type=identity.type,
            minecraft_uuid=identity.minecraft_uuid,
            minecraft_username=identity.minecraft_username,
            created_at=identity.created_at,
        ),
        expires_at=session.expires_at,
        previous_offline_uuid=session.previous_offline_uuid,
    )


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    token: str,
    current_account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db_session),
):
    service = SessionService(db)
    await service.revoke(token)
