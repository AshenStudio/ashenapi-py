from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AdminReleaseDto(BaseModel):
    version: str
    sha256: str
    release_notes: str
    published_at: datetime
    is_latest: bool


class ResetPasswordRequest(BaseModel):
    new_password: str | None = None


class ResetPasswordResponse(BaseModel):
    temporary_password: str


class AdminAccountDto(BaseModel):
    id: UUID
    username: str
    created_at: datetime
    identity_count: int


class AdminAccountListDto(BaseModel):
    accounts: list[AdminAccountDto]
    total_count: int
    page: int
    page_size: int


class MigrationLogDto(BaseModel):
    id: UUID
    account_id: UUID
    account_username: str
    old_offline_uuid: str
    new_premium_uuid: str
    minecraft_username: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None


class MigrationLogListDto(BaseModel):
    logs: list[MigrationLogDto]
    total_count: int
    page: int
    page_size: int


class CompleteMigrationRequest(BaseModel):
    success: bool
    error_message: str | None = None


class MigrationCountsDto(BaseModel):
    pending: int
    failed: int
    completed: int


class CreateRetryRequestDto(BaseModel):
    retry_type: str
    migration_log_id: UUID | None = None
    old_uuid: str | None = None
    new_uuid: str | None = None
    minecraft_username: str | None = None


class RetryRequestDto(BaseModel):
    id: UUID
    migration_log_id: UUID | None = None
    retry_type: str
    old_uuid: str | None = None
    new_uuid: str | None = None
    minecraft_username: str | None = None
    requested_by: str | None = None
    status: str
    result_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class RetryRequestListDto(BaseModel):
    requests: list[RetryRequestDto]
    total_count: int
    page: int
    page_size: int


class UpdateRetryRequestDto(BaseModel):
    status: str
    result_message: str | None = None


class DbQueryRequest(BaseModel):
    query: str
    params: dict | None = None


class DbQueryResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    affected_rows: int
    execution_time_ms: float
