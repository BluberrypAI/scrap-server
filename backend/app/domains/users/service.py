from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.auth import service as auth_service
from app.domains.companies import service as company_service
from app.domains.users import repository as user_repo
from app.domains.users.models import User


async def withdraw(db: AsyncSession, user: User) -> datetime:
    """Deactivate the user now and schedule permanent deletion. Returns the deletion time."""
    now = datetime.now(UTC)
    scheduled = now + timedelta(days=get_settings().withdrawal_grace_days)
    user.withdrawn_at = now
    user.deletion_scheduled_at = scheduled
    await auth_service.revoke_all_sessions(db, user.id)
    await db.commit()
    return scheduled


async def purge_withdrawn_users(db: AsyncSession, now: datetime | None = None) -> int:
    """Permanently delete users past their deletion time. Returns how many were deleted."""
    user_ids = await user_repo.get_users_due_for_deletion(db, now or datetime.now(UTC))
    if not user_ids:
        return 0
    # Explicit deletes instead of FK cascades so SQLite (no FK enforcement) behaves the same.
    await auth_service.delete_sessions_of_users(db, user_ids)
    await company_service.delete_companies_of_users(db, user_ids)
    await user_repo.delete_users(db, user_ids)
    await db.commit()
    return len(user_ids)
