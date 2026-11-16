"""Completion criteria from docs/specs/account-withdrawal.md."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_token
from app.domains.auth.cookies import ACCESS_COOKIE, REFRESH_COOKIE
from app.domains.auth.models import RefreshToken
from app.domains.auth.service import login_or_register, start_session
from app.domains.companies import service as company_service
from app.domains.companies.models import Company, CompanyProfileHistory
from app.domains.companies.schemas import CompanyCreate, CompanyUpdate
from app.domains.users.models import User
from app.domains.users.service import purge_withdrawn_users

WITHDRAW = "/api/v1/users/me/withdraw"
COMPANY = CompanyCreate(
    company_name="한빛플라스틱",
    contact_email="manager@example.com",
    industry="플라스틱 제품 제조",
    site_name="안산 공장",
    site_address="경기도 안산시",
    site_facilities=["혼합시설"],
    main_products=["플라스틱 용기"],
    main_waste_types=[{"category": "PP"}],
)


async def count(db: AsyncSession, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_withdraw_returns_deletion_date_30_days_later(auth_client: AsyncClient):
    before = datetime.now(UTC)

    res = await auth_client.post(WITHDRAW, json={"confirm": True})

    assert res.status_code == 200
    scheduled = datetime.fromisoformat(res.json()["deletion_scheduled_at"])
    assert before + timedelta(days=30) <= scheduled <= datetime.now(UTC) + timedelta(days=30)


async def test_withdraw_requires_confirm_true(auth_client: AsyncClient):
    assert (await auth_client.post(WITHDRAW)).status_code == 422
    assert (await auth_client.post(WITHDRAW, json={"confirm": False})).status_code == 422

    assert (await auth_client.get("/api/v1/users/me")).status_code == 200


async def test_withdraw_clears_auth_cookies(auth_client: AsyncClient):
    res = await auth_client.post(WITHDRAW, json={"confirm": True})

    cleared = [c for c in res.headers.get_list("set-cookie") if "max-age=0" in c.lower()]
    assert any(c.startswith(f"{ACCESS_COOKIE}=") for c in cleared)
    assert any(c.startswith(f"{REFRESH_COOKIE}=") for c in cleared)


async def test_withdraw_revokes_refresh_tokens(
    auth_client: AsyncClient, db: AsyncSession, user: User
):
    refresh_token = await start_session(db, user.id)

    await auth_client.post(WITHDRAW, json={"confirm": True})

    auth_client.cookies.clear()
    auth_client.cookies.set(REFRESH_COOKIE, refresh_token)
    assert (await auth_client.post("/api/v1/auth/refresh")).status_code == 401


async def test_access_token_is_rejected_after_withdrawal(client: AsyncClient, user: User):
    headers = {"Authorization": f"Bearer {create_token(user.id, 'access')}"}

    await client.post(WITHDRAW, json={"confirm": True}, headers=headers)

    assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 401


async def _make_user(db: AsyncSession, subject: str, deletion_in: timedelta | None) -> User:
    user = await login_or_register(db, "google", {"sub": subject, "email": f"{subject}@x.com"})
    company = await company_service.create_company(db, user.id, COMPANY)
    await company_service.update_company(
        db, company, CompanyUpdate(profile_version=1, industry="변경된 업종")
    )
    await start_session(db, user.id)
    if deletion_in is not None:
        now = datetime.now(UTC)
        user.withdrawn_at = now
        user.deletion_scheduled_at = now + deletion_in
        await db.commit()
    return user


async def test_purge_deletes_only_users_past_deletion_time(db: AsyncSession):
    await _make_user(db, "due", deletion_in=timedelta(days=-1))
    pending = await _make_user(db, "pending", deletion_in=timedelta(days=10))
    active = await _make_user(db, "active", deletion_in=None)

    purged = await purge_withdrawn_users(db)

    assert purged == 1
    remaining = set(await db.scalars(select(User.id)))
    assert remaining == {pending.id, active.id}
    assert await count(db, RefreshToken) == 2
    assert await count(db, Company) == 2
    assert await count(db, CompanyProfileHistory) == 2


async def test_login_after_purge_creates_new_user(db: AsyncSession):
    old = await _make_user(db, "due", deletion_in=timedelta(days=-1))
    await purge_withdrawn_users(db)

    new = await login_or_register(db, "google", {"sub": "due"})

    assert new.id != old.id
    assert not new.is_withdrawn
