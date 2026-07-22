from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Account, Identity, MigrationLog, MigrationRetryRequest


class AdminService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Account management ─────────────────────────────────

    async def list_accounts(self, page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
        page_size = max(1, min(page_size, 100))
        total_q = select(func.count(Account.id))
        total_result = await self.db.execute(total_q)
        total_count = total_result.scalar() or 0

        result = await self.db.execute(
            select(Account).order_by(Account.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        accounts = result.scalars().all()

        items = []
        for acc in accounts:
            cnt_result = await self.db.execute(
                select(func.count(Identity.id)).where(Identity.account_id == acc.id)
            )
            identity_count = cnt_result.scalar() or 0
            items.append({
                "id": acc.id,
                "username": acc.username,
                "created_at": acc.created_at,
                "identity_count": identity_count,
            })

        return items, total_count

    async def delete_account(self, account_id: UUID) -> bool:
        result = await self.db.execute(select(Account).where(Account.id == account_id))
        account = result.scalar_one_or_none()
        if account is None:
            return False
        await self.db.delete(account)
        await self.db.flush()
        return True

    # ── Migration logs ─────────────────────────────────────

    async def list_migration_logs(self, page: int = 1, page_size: int = 20) -> tuple[list[MigrationLog], int]:
        page_size = max(1, min(page_size, 100))
        total_q = select(func.count(MigrationLog.id))
        total_result = await self.db.execute(total_q)
        total_count = total_result.scalar() or 0

        result = await self.db.execute(
            select(MigrationLog)
            .options(selectinload(MigrationLog.account))
            .order_by(MigrationLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total_count

    async def get_migration_log_by_id(self, log_id: UUID) -> MigrationLog | None:
        result = await self.db.execute(
            select(MigrationLog)
            .options(selectinload(MigrationLog.account))
            .where(MigrationLog.id == log_id)
        )
        return result.scalar_one_or_none()

    async def get_migration_log_counts(self) -> dict[str, int]:
        result = await self.db.execute(
            select(MigrationLog.status, func.count(MigrationLog.id))
            .group_by(MigrationLog.status)
        )
        counts = {"Pending": 0, "Failed": 0, "Completed": 0}
        for status, count in result.all():
            counts[status] = count
        return counts

    async def complete_migration(self, log_id: UUID, success: bool, error_message: str | None = None) -> bool:
        result = await self.db.execute(select(MigrationLog).where(MigrationLog.id == log_id))
        log = result.scalar_one_or_none()
        if log is None:
            return False
        log.status = "Completed" if success else "Failed"
        log.completed_at = datetime.now(timezone.utc)
        log.error_message = error_message
        await self.db.flush()
        return True

    # ── Migration Retry Requests ───────────────────────────

    async def create_retry_request(
        self,
        retry_type: str,
        migration_log_id: UUID | None = None,
        old_uuid: str | None = None,
        new_uuid: str | None = None,
        minecraft_username: str | None = None,
        requested_by: str | None = None,
    ) -> MigrationRetryRequest:
        request = MigrationRetryRequest(
            id=uuid4(),
            migration_log_id=migration_log_id,
            retry_type=retry_type,
            old_uuid=old_uuid,
            new_uuid=new_uuid,
            minecraft_username=minecraft_username,
            requested_by=requested_by,
            status="Pending",
        )
        self.db.add(request)
        await self.db.flush()
        return request

    async def list_retry_requests(self, page: int = 1, page_size: int = 20) -> tuple[list[MigrationRetryRequest], int]:
        page_size = max(1, min(page_size, 100))
        total_q = select(func.count(MigrationRetryRequest.id))
        total_result = await self.db.execute(total_q)
        total_count = total_result.scalar() or 0

        result = await self.db.execute(
            select(MigrationRetryRequest).order_by(MigrationRetryRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total_count

    async def claim_next_pending_retry_request(self) -> MigrationRetryRequest | None:
        stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=15)
        result = await self.db.execute(
            select(MigrationRetryRequest)
            .where(
                (MigrationRetryRequest.status == "Pending") |
                ((MigrationRetryRequest.status == "InProgress") & (MigrationRetryRequest.created_at < stale_threshold))
            )
            .order_by(MigrationRetryRequest.created_at)
            .limit(1)
        )
        request = result.scalar_one_or_none()
        if request is None:
            return None
        request.status = "InProgress"
        await self.db.flush()
        return request

    async def update_retry_request(self, request_id: UUID, status: str, result_message: str | None = None) -> bool:
        result = await self.db.execute(select(MigrationRetryRequest).where(MigrationRetryRequest.id == request_id))
        request = result.scalar_one_or_none()
        if request is None:
            return False
        request.status = status
        request.result_message = result_message
        if status in ("Completed", "Failed"):
            request.completed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True
