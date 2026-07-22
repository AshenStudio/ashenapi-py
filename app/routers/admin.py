import uuid

from fastapi import APIRouter, Depends, HTTPException, Header, Query, UploadFile, File, Form, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_db_session,
    get_optional_account,
    is_valid_server_key,
    require_admin,
    verify_server_key,
)
from app.models.models import Account, MigrationLog
from app.schemas.admin import (
    AdminAccountDto,
    AdminAccountListDto,
    AdminReleaseDto,
    CompleteMigrationRequest,
    CreateRetryRequestDto,
    MigrationCountsDto,
    MigrationLogDto,
    MigrationLogListDto,
    ResetPasswordRequest,
    ResetPasswordResponse,
    RetryRequestDto,
    RetryRequestListDto,
    UpdateRetryRequestDto,
)
from app.schemas.release import ReleaseDto, ReleaseListDto
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService
from app.services.release_service import ReleaseService

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ── Accounts ──────────────────────────────────────────────

@router.get("/accounts", response_model=AdminAccountListDto)
async def get_accounts(
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    service = AdminService(db)
    accounts, total = await service.list_accounts(page, page_size)
    dtos = [AdminAccountDto(**a) for a in accounts]
    return AdminAccountListDto(accounts=dtos, total_count=total, page=page, page_size=page_size)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: str,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        uid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid account ID.")
    service = AdminService(db)
    success = await service.delete_account(uid)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")


@router.post("/accounts/{account_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    account_id: str,
    body: ResetPasswordRequest,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        uid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid account ID.")
    service = AuthService(db)
    try:
        password = await service.reset_password(uid, body.new_password)
        return ResetPasswordResponse(temporary_password=password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ── Launcher Releases ─────────────────────────────────────

@router.get("/releases/launcher", response_model=ReleaseListDto)
async def get_launcher_releases(
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = ReleaseService(db)
    releases = await service.get_all("Launcher")
    dtos = [ReleaseDto(version=r.version, download_url="", sha256=r.sha256, release_notes=r.release_notes, published_at=r.published_at) for r in releases]
    return ReleaseListDto(releases=dtos)


@router.post("/releases/launcher", response_model=AdminReleaseDto, status_code=status.HTTP_201_CREATED)
async def publish_launcher_release(
    file: UploadFile = File(...),
    version: str = Form(...),
    release_notes: str = Form(...),
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = ReleaseService(db)
    content = await file.read()
    try:
        release = await service.publish("Launcher", version, content, release_notes)
        return AdminReleaseDto(version=release.version, sha256=release.sha256, release_notes=release.release_notes, published_at=release.published_at, is_latest=release.is_latest)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/releases/launcher/{version}")
async def get_launcher_release(
    version: str,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = ReleaseService(db)
    release = await service.get("Launcher", version)
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")
    return AdminReleaseDto(version=release.version, sha256=release.sha256, release_notes=release.release_notes, published_at=release.published_at, is_latest=release.is_latest)


@router.delete("/releases/launcher/{version}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_launcher_release(
    version: str,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = ReleaseService(db)
    success = await service.delete("Launcher", version)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")


# ── Modpack Releases ──────────────────────────────────────

@router.get("/releases/modpack", response_model=ReleaseListDto)
async def get_modpack_releases(
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = ReleaseService(db)
    releases = await service.get_all("Modpack")
    dtos = [ReleaseDto(version=r.version, download_url="", sha256=r.sha256, release_notes=r.release_notes, published_at=r.published_at) for r in releases]
    return ReleaseListDto(releases=dtos)


@router.post("/releases/modpack", response_model=AdminReleaseDto, status_code=status.HTTP_201_CREATED)
async def publish_modpack_release(
    file: UploadFile = File(...),
    version: str = Form(...),
    release_notes: str = Form(...),
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = ReleaseService(db)
    content = await file.read()
    try:
        release = await service.publish("Modpack", version, content, release_notes)
        return AdminReleaseDto(version=release.version, sha256=release.sha256, release_notes=release.release_notes, published_at=release.published_at, is_latest=release.is_latest)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/releases/modpack/{version}")
async def get_modpack_release(
    version: str,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = ReleaseService(db)
    release = await service.get("Modpack", version)
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")
    return AdminReleaseDto(version=release.version, sha256=release.sha256, release_notes=release.release_notes, published_at=release.published_at, is_latest=release.is_latest)


@router.delete("/releases/modpack/{version}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_modpack_release(
    version: str,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = ReleaseService(db)
    success = await service.delete("Modpack", version)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")


# ── Migration Logs ────────────────────────────────────────

@router.get("/migrations/counts", response_model=MigrationCountsDto)
async def get_migration_counts(
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = AdminService(db)
    counts = await service.get_migration_log_counts()
    return MigrationCountsDto(**counts)


@router.get("/migrations")
async def get_migration_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    x_ashen_server_key: str | None = Header(default=None, alias="X-Ashen-Server-Key"),
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db_session),
):
    # Dual-mode auth: JWT admin OR server key
    is_admin = account is not None and account.is_admin
    has_server_key = is_valid_server_key(x_ashen_server_key)
    if not is_admin and not has_server_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin JWT or valid X-Ashen-Server-Key required.")

    service = AdminService(db)
    logs, total = await service.list_migration_logs(page, page_size)

    # Populate account usernames via eager loading
    dtos = []
    for log in logs:
        username = ""
        if log.account:
            username = log.account.username
        dtos.append(
            MigrationLogDto(
                id=log.id,
                account_id=log.account_id,
                account_username=username,
                old_offline_uuid=log.old_offline_uuid,
                new_premium_uuid=log.new_premium_uuid,
                minecraft_username=log.minecraft_username,
                status=log.status,
                created_at=log.created_at,
                completed_at=log.completed_at,
                error_message=log.error_message,
            )
        )
    return MigrationLogListDto(logs=dtos, total_count=total, page=page, page_size=page_size)


@router.get("/migrations/{log_id}")
async def get_migration_log(
    log_id: str,
    x_ashen_server_key: str | None = Header(default=None, alias="X-Ashen-Server-Key"),
    account: Account | None = Depends(get_optional_account),
    db: AsyncSession = Depends(get_db_session),
):
    # Dual-mode auth: JWT admin OR server key
    is_admin = account is not None and account.is_admin
    has_server_key = is_valid_server_key(x_ashen_server_key)
    if not is_admin and not has_server_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin JWT or valid X-Ashen-Server-Key required.")

    try:
        uid = uuid.UUID(log_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid log ID.")

    service = AdminService(db)
    log = await service.get_migration_log_by_id(uid)
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Migration log not found.")
    return MigrationLogDto(
        id=log.id,
        account_id=log.account_id,
        account_username=log.account.username if log.account else "",
        old_offline_uuid=log.old_offline_uuid,
        new_premium_uuid=log.new_premium_uuid,
        minecraft_username=log.minecraft_username,
        status=log.status,
        created_at=log.created_at,
        completed_at=log.completed_at,
        error_message=log.error_message,
    )


@router.patch("/migrations/{log_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_migration(
    log_id: str,
    body: CompleteMigrationRequest,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        uid = uuid.UUID(log_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid log ID.")
    service = AdminService(db)
    success = await service.complete_migration(uid, body.success, body.error_message)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Migration log not found.")


# ── Migration Retry Requests ──────────────────────────────

@router.post("/migrations/retry-requests", response_model=RetryRequestDto, status_code=status.HTTP_201_CREATED)
async def create_retry_request(
    body: CreateRetryRequestDto,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = AdminService(db)
    request = await service.create_retry_request(
        retry_type=body.retry_type,
        migration_log_id=body.migration_log_id,
        old_uuid=body.old_uuid,
        new_uuid=body.new_uuid,
        minecraft_username=body.minecraft_username,
        requested_by=admin.username,
    )
    return RetryRequestDto(
        id=request.id,
        migration_log_id=request.migration_log_id,
        retry_type=request.retry_type,
        old_uuid=request.old_uuid,
        new_uuid=request.new_uuid,
        minecraft_username=request.minecraft_username,
        requested_by=request.requested_by,
        status=request.status,
        result_message=request.result_message,
        created_at=request.created_at,
        completed_at=request.completed_at,
    )


@router.get("/migrations/retry-requests")
async def get_retry_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    service = AdminService(db)
    requests, total = await service.list_retry_requests(page, page_size)
    dtos = [
        RetryRequestDto(
            id=r.id,
            migration_log_id=r.migration_log_id,
            retry_type=r.retry_type,
            old_uuid=r.old_uuid,
            new_uuid=r.new_uuid,
            minecraft_username=r.minecraft_username,
            requested_by=r.requested_by,
            status=r.status,
            result_message=r.result_message,
            created_at=r.created_at,
            completed_at=r.completed_at,
        )
        for r in requests
    ]
    return RetryRequestListDto(requests=dtos, total_count=total, page=page, page_size=page_size)


@router.get("/migrations/retry-requests/pending")
async def get_pending_retry_request(
    x_ashen_server_key: str = Depends(verify_server_key),
    db: AsyncSession = Depends(get_db_session),
):
    service = AdminService(db)
    request = await service.claim_next_pending_retry_request()
    if request is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return RetryRequestDto(
        id=request.id,
        migration_log_id=request.migration_log_id,
        retry_type=request.retry_type,
        old_uuid=request.old_uuid,
        new_uuid=request.new_uuid,
        minecraft_username=request.minecraft_username,
        requested_by=request.requested_by,
        status=request.status,
        result_message=request.result_message,
        created_at=request.created_at,
        completed_at=request.completed_at,
    )


@router.get("/migrations/retry-requests/{request_id}")
async def get_retry_request(
    request_id: str,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid request ID.")
    service = AdminService(db)
    requests, _ = await service.list_retry_requests(1, 10000)
    for r in requests:
        if r.id == rid:
            return RetryRequestDto(
                id=r.id,
                migration_log_id=r.migration_log_id,
                retry_type=r.retry_type,
                old_uuid=r.old_uuid,
                new_uuid=r.new_uuid,
                minecraft_username=r.minecraft_username,
                requested_by=r.requested_by,
                status=r.status,
                result_message=r.result_message,
                created_at=r.created_at,
                completed_at=r.completed_at,
            )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retry request not found.")


@router.patch("/migrations/retry-requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_retry_request(
    request_id: str,
    body: UpdateRetryRequestDto,
    x_ashen_server_key: str = Depends(verify_server_key),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid request ID.")
    service = AdminService(db)
    success = await service.update_retry_request(rid, body.status, body.result_message)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retry request not found.")
