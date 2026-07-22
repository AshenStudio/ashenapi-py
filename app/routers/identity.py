from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_account, get_db_session
from app.models.models import Account
from app.schemas.identity import (
    IdentityDto,
    IdentityListResponse,
    LinkMicrosoftRequest,
    LinkMicrosoftResponse,
    LinkOfflineRequest,
)
from app.services.identity_service import IdentityService

router = APIRouter(prefix="/api/identities", tags=["Identities"])


@router.get("", response_model=IdentityListResponse)
async def get_identities(
    current_account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db_session),
):
    service = IdentityService(db)
    identities = await service.get_identities(current_account.id)
    dtos = [
        IdentityDto(
            id=i.id,
            type=i.type,
            minecraft_uuid=i.minecraft_uuid,
            minecraft_username=i.minecraft_username,
            created_at=i.created_at,
        )
        for i in identities
    ]
    return IdentityListResponse(identities=dtos)


@router.post("/microsoft", response_model=LinkMicrosoftResponse)
async def link_microsoft(
    body: LinkMicrosoftRequest,
    current_account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db_session),
):
    service = IdentityService(db)
    identity, prev_offline = await service.link_microsoft(
        current_account.id,
        body.minecraft_uuid,
        body.minecraft_username,
    )
    return LinkMicrosoftResponse(
        identity=IdentityDto(
            id=identity.id,
            type=identity.type,
            minecraft_uuid=identity.minecraft_uuid,
            minecraft_username=identity.minecraft_username,
            created_at=identity.created_at,
        ),
        previous_offline_uuid=prev_offline,
    )


@router.post("/offline", status_code=status.HTTP_201_CREATED)
async def link_offline(
    body: LinkOfflineRequest,
    current_account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db_session),
):
    service = IdentityService(db)
    try:
        identity = await service.link_offline(current_account.id, body.username)
        return IdentityDto(
            id=identity.id,
            type=identity.type,
            minecraft_uuid=identity.minecraft_uuid,
            minecraft_username=identity.minecraft_username,
            created_at=identity.created_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.delete("/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_identity(
    identity_id: str,
    current_account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_db_session),
):
    import uuid
    try:
        uid = uuid.UUID(identity_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid identity ID.")
    service = IdentityService(db)
    success = await service.delete(current_account.id, uid)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity not found.")
