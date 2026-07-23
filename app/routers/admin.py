import time
import uuid
import re

from fastapi import APIRouter, Depends, HTTPException, Header, Query, UploadFile, File, Form, Response, status
from sqlalchemy import text
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
    ColumnInfo,
    CompleteMigrationRequest,
    CreateRetryRequestDto,
    DbExecuteRequest,
    DbExecuteResponse,
    DbQueryRequest,
    DbQueryResponse,
    MigrationCountsDto,
    MigrationLogDto,
    MigrationLogListDto,
    ResetPasswordRequest,
    ResetPasswordResponse,
    RetryRequestDto,
    RetryRequestListDto,
    TableInfo,
    TableInfoList,
    TableSchema,
    UpdateRetryRequestDto,
)
from app.schemas.release import ReleaseDto, ReleaseListDto
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService
from app.services.release_service import ReleaseService

router = APIRouter(prefix="/api/admin", tags=["Admin"])

# ── DB Query Editor ───────────────────────────────────────

READONLY_RE = re.compile(
    r"^\s*(SELECT|EXPLAIN|WITH|SHOW|DESCRIBE|VALUES)\b",
    re.IGNORECASE,
)


@router.post("/db/query", response_model=DbQueryResponse)
async def execute_db_query(
    body: DbQueryRequest,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Execute a SQL query against the database.

    Only read-only queries (SELECT, EXPLAIN, WITH, SHOW, DESCRIBE, VALUES)
    are allowed. Returns column names and rows.
    """
    if not READONLY_RE.match(body.query.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only read-only queries are allowed (SELECT, EXPLAIN, WITH, SHOW, DESCRIBE, VALUES).",
        )

    start = time.perf_counter()
    try:
        result = await db.execute(text(body.query), body.params or {})
        elapsed = time.perf_counter() - start

        if result.returns_rows:
            rows = result.fetchmany(500)  # Limit to 500 rows
            columns = list(result.keys())
            return DbQueryResponse(
                columns=columns,
                rows=[[str(cell) if cell is not None else None for cell in row] for row in rows],
                row_count=len(rows),
                affected_rows=0,
                execution_time_ms=round(elapsed * 1000, 2),
            )
        else:
            return DbQueryResponse(
                columns=[],
                rows=[],
                row_count=0,
                affected_rows=result.rowcount or 0,
                execution_time_ms=round(elapsed * 1000, 2),
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Query error: {str(e)}",
        )


# ── DB Write / Table Browser ──────────────────────────────


@router.post("/db/execute", response_model=DbExecuteResponse)
async def execute_db_write(
    body: DbExecuteRequest,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Execute write queries (INSERT, UPDATE, DELETE, ALTER, etc.).

    Requires admin privileges. Returns affected row count and execution time.
    """
    start = time.perf_counter()
    try:
        result = await db.execute(text(body.query), body.params or {})
        await db.commit()
        elapsed = time.perf_counter() - start
        affected = result.rowcount or 0
        return DbExecuteResponse(
            success=True,
            affected_rows=affected,
            execution_time_ms=round(elapsed * 1000, 2),
            message=f"Query executed successfully. {affected} rows affected.",
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Query error: {str(e)}",
        )


@router.get("/db/tables", response_model=TableInfoList)
async def list_tables(
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """List all tables in the database with estimated row counts."""
    query = text("""
        SELECT
            t.table_name,
            t.table_schema,
            (SELECT reltuples::bigint FROM pg_class WHERE oid = (quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass) AS row_count
        FROM information_schema.tables t
        WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY t.table_schema, t.table_name
    """)
    try:
        result = await db.execute(query)
        rows = result.fetchall()
        tables = [
            TableInfo(table_name=row[0], table_schema=row[1], row_count=row[2])
            for row in rows
        ]
        return TableInfoList(tables=tables)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list tables: {str(e)}",
        )


@router.get("/db/tables/{table_name}/schema", response_model=TableSchema)
async def get_table_schema(
    table_name: str,
    schema: str = Query("public", alias="schema"),
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Get the schema (columns, types, constraints) for a table."""
    try:
        # Get column info
        col_query = text("""
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable::boolean,
                c.column_default,
                c.character_maximum_length,
                CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary_key
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                    ON tc.constraint_name = ku.constraint_name
                    AND tc.table_schema = ku.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema = :schema
                    AND tc.table_name = :table
            ) pk ON c.column_name = pk.column_name
            WHERE c.table_schema = :schema
                AND c.table_name = :table
            ORDER BY c.ordinal_position
        """)
        result = await db.execute(col_query, {"schema": schema, "table": table_name})
        columns = []
        primary_key = None
        for row in result.fetchall():
            col = ColumnInfo(
                column_name=row[0],
                data_type=row[1],
                is_nullable=row[2],
                column_default=row[3],
                character_maximum_length=row[4],
                is_primary_key=row[5],
            )
            if row[5]:
                primary_key = row[0]
            columns.append(col)

        # Get row count
        safe_schema = schema.replace('"', '""')
        safe_table = table_name.replace('"', '""')
        count_query = text(f'SELECT COUNT(*) FROM "{safe_schema}"."{safe_table}"')
        count_result = await db.execute(count_query)
        row_count = count_result.scalar()

        return TableSchema(
            table_name=table_name,
            table_schema=schema,
            columns=columns,
            primary_key=primary_key,
            row_count=row_count,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get schema: {str(e)}",
        )


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
