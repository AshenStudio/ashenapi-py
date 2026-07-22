from datetime import datetime

from pydantic import BaseModel


class ReleaseDto(BaseModel):
    version: str
    download_url: str
    sha256: str
    release_notes: str
    published_at: datetime


class ReleaseListDto(BaseModel):
    releases: list[ReleaseDto]


class AdminReleaseDto(BaseModel):
    version: str
    sha256: str
    release_notes: str
    published_at: datetime
    is_latest: bool
