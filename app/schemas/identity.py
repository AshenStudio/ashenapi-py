from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LinkMicrosoftRequest(BaseModel):
    minecraft_access_token: str
    minecraft_uuid: str
    minecraft_username: str


class LinkOfflineRequest(BaseModel):
    username: str


class IdentityDto(BaseModel):
    id: UUID
    type: str
    minecraft_uuid: str
    minecraft_username: str
    created_at: datetime


class IdentityListResponse(BaseModel):
    identities: list[IdentityDto]


class LinkMicrosoftResponse(BaseModel):
    identity: IdentityDto
    previous_offline_uuid: str | None = None
