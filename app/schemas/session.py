from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.identity import IdentityDto


class CreateSessionRequest(BaseModel):
    identity_id: UUID | None = None
    previous_offline_uuid: str | None = None


class SessionDto(BaseModel):
    token: str
    expires_at: datetime
    identity: IdentityDto


class SessionValidationDto(BaseModel):
    valid: bool
    account_id: UUID
    identity: IdentityDto
    expires_at: datetime
    previous_offline_uuid: str | None = None
