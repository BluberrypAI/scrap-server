import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.domains.auth import service as auth_service
from app.domains.companies import service as company_service
from app.domains.companies.models import Company
from app.domains.diagnosis.client import EngineClient, get_engine_client
from app.domains.users import repository as user_repo
from app.domains.users.models import User

logger = logging.getLogger(__name__)


async def withdraw(db: AsyncSession, user: User) -> datetime:
    """Deactivate the user now and schedule permanent deletion. Returns the deletion time."""
    now = datetime.now(UTC)
    scheduled = now + timedelta(days=get_settings().withdrawal_grace_days)
    user.withdrawn_at = now
    user.deletion_scheduled_at = scheduled
    await auth_service.revoke_all_sessions(db, user.id)
    await db.commit()
    return scheduled


async def purge_withdrawn_users(
    db: AsyncSession, now: datetime | None = None, engine: EngineClient | None = None
) -> int:
    """Permanently delete users past their deletion time. Returns how many were deleted."""
    user_ids = await user_repo.get_users_due_for_deletion(db, now or datetime.now(UTC))
    if not user_ids:
        return 0
    user_ids = await _delete_engine_data(db, user_ids, engine or get_engine_client())
    if not user_ids:
        return 0
    # Explicit deletes instead of FK cascades so SQLite (no FK enforcement) behaves the same.
    await auth_service.delete_sessions_of_users(db, user_ids)
    await company_service.delete_companies_of_users(db, user_ids)
    await user_repo.delete_users(db, user_ids)
    await db.commit()
    return len(user_ids)


async def _delete_engine_data(
    db: AsyncSession, user_ids: list[uuid.UUID], engine: EngineClient
) -> list[uuid.UUID]:
    """문진 엔진의 기업 데이터를 먼저 지움.

    실패한 사용자는 이번에 지우지 않고 다음 purge에서 다시 시도함.
    """
    if not engine.configured:
        logger.warning("DIAGNOSIS_ENGINE_URL is not set; skipping engine data deletion")
        return user_ids
    rows = await db.execute(
        select(Company.user_id, Company.id).where(Company.user_id.in_(user_ids))
    )
    failed: set[uuid.UUID] = set()
    for user_id, company_id in rows.all():
        try:
            await engine.delete_company_data(str(company_id))
        except AppError:
            logger.error("Engine data deletion failed for company %s; retry next purge", company_id)
            failed.add(user_id)
    return [uid for uid in user_ids if uid not in failed]
