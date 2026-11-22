"""처리업체 아이디·비밀번호 로그인 (docs/specs/facility-password-login.md 6장)."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.passwords import hash_password, verify_password
from app.domains.auth.facility_accounts import ProvisionError, provision
from app.domains.companies.models import Company
from app.domains.transport.models import WorkflowFacilityAccount
from app.domains.treatment.repository import replace_snapshots
from app.domains.users.models import User
from app.main import create_app

FACILITY = "sarom-hwaseong-2"
OTHER_FACILITY = "veolia-doksan-hwaseong"
PASSWORD = "correct-horse-1"


async def _provision(db: AsyncSession, **kwargs):
    await replace_snapshots(db)
    params = {
        "login_id": "Sarom-Hwaseong",
        "password": PASSWORD,
        "facility_keys": [FACILITY],
        "contact_email": "manager@example.com",
    }
    return await provision(db, **(params | kwargs))


async def _login(client: AsyncClient, login_id: str, password: str):
    return await client.post(
        "/api/v1/auth/password-login", json={"login_id": login_id, "password": password}
    )


def test_password_hash_round_trip():
    stored = hash_password(PASSWORD)
    assert verify_password(PASSWORD, stored)
    assert not verify_password("wrong-password", stored)
    assert not verify_password(PASSWORD, None)
    assert not verify_password(PASSWORD, "garbage")


async def test_provisioned_account_logs_in_as_its_company(client: AsyncClient, db: AsyncSession):
    result = await _provision(db)
    assert result.created_user and result.created_company and not result.synthetic

    res = await _login(client, "  SAROM-hwaseong ", PASSWORD)

    assert res.status_code == 204
    assert "access_token" in res.cookies and "refresh_token" in res.cookies
    me = (await client.get("/api/v1/users/me")).json()
    company = await db.scalar(select(Company))
    assert me["company_id"] == str(company.id)
    assert me["provider"] == "password"
    binding = await db.get(WorkflowFacilityAccount, FACILITY)
    assert binding.company_id == company.id and not binding.synthetic
    assert company.site_name and company.site_address


async def test_wrong_password_and_unknown_id_both_401(client: AsyncClient, db: AsyncSession):
    await _provision(db)

    wrong = await _login(client, "sarom-hwaseong", "wrong-password")
    unknown = await _login(client, "nobody", PASSWORD)

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "AUTH_REQUIRED"


async def test_repeated_failures_lock_the_login_id_even_for_the_right_password(
    client: AsyncClient, db: AsyncSession
):
    from app.domains.auth import throttle

    await _provision(db)
    for _ in range(throttle.MAX_FAILURES_PER_LOGIN):
        assert (await _login(client, "sarom-hwaseong", "wrong-password")).status_code == 401

    locked = await _login(client, "SAROM-hwaseong", PASSWORD)

    assert locked.status_code == 429
    assert locked.json()["code"] == "TOO_MANY_ATTEMPTS"
    assert int(locked.headers["Retry-After"]) > 0
    assert "access_token" not in locked.cookies


async def test_success_clears_the_login_id_failures(client: AsyncClient, db: AsyncSession):
    from app.domains.auth import throttle

    await _provision(db)
    for _ in range(throttle.MAX_FAILURES_PER_LOGIN - 1):
        await _login(client, "sarom-hwaseong", "wrong-password")
    assert (await _login(client, "sarom-hwaseong", PASSWORD)).status_code == 204

    assert (await _login(client, "sarom-hwaseong", "wrong-password")).status_code == 401


async def test_spraying_many_ids_from_one_ip_is_blocked(client: AsyncClient, db: AsyncSession):
    from app.domains.auth import throttle

    for i in range(throttle.MAX_FAILURES_PER_IP):
        assert (await _login(client, f"guess-{i}", PASSWORD)).status_code == 401

    assert (await _login(client, "another-id", PASSWORD)).status_code == 429
    other_ip = await client.post(
        "/api/v1/auth/password-login",
        json={"login_id": "another-id", "password": PASSWORD},
        headers={"X-Azure-ClientIP": "203.0.113.9"},
    )
    assert other_ip.status_code == 401


def test_failures_expire_after_the_window():
    from app.domains.auth import throttle

    for _ in range(throttle.MAX_FAILURES_PER_LOGIN):
        throttle.record_failure("id", "ip", now=0.0)
    assert throttle.retry_after("id", "ip", now=1.0) == throttle.WINDOW_SECONDS - 1
    assert throttle.retry_after("id", "ip", now=float(throttle.WINDOW_SECONDS)) is None


async def test_user_without_password_hash_cannot_log_in(client: AsyncClient, db: AsyncSession):
    db.add(User(provider="password", provider_subject="nohash"))
    await db.commit()

    assert (await _login(client, "nohash", PASSWORD)).status_code == 401


async def test_withdrawn_account_is_403(client: AsyncClient, db: AsyncSession):
    await _provision(db)
    user = await db.scalar(select(User))
    user.withdrawn_at = datetime.now(UTC)
    await db.commit()

    res = await _login(client, "sarom-hwaseong", PASSWORD)

    assert res.status_code == 403
    assert "access_token" not in res.cookies


def test_prod_app_has_password_login_route():
    prod = Settings(
        app_env="prod",
        jwt_secret="p" * 32,
        session_secret="s" * 32,
        database_url="postgresql+asyncpg://u:p@localhost/db",
    )
    assert "/api/v1/auth/password-login" in create_app(prod).openapi()["paths"]


async def test_unknown_facility_key_creates_nothing(db: AsyncSession):
    with pytest.raises(ProvisionError):
        await _provision(db, facility_keys=["no-such-facility"])

    assert await db.scalar(select(func.count()).select_from(User)) == 0
    assert await db.scalar(select(func.count()).select_from(Company)) == 0


async def test_facility_bound_to_other_company_needs_force(db: AsyncSession):
    await _provision(db)

    with pytest.raises(ProvisionError):
        await _provision(db, login_id="second", contact_email="second@example.com")

    result = await _provision(db, login_id="second", contact_email="second@example.com", force=True)
    company = await db.scalar(
        select(Company)
        .join(User, Company.user_id == User.id)
        .where(User.provider_subject == "second")
    )
    assert result.created_company
    assert (await db.get(WorkflowFacilityAccount, FACILITY)).company_id == company.id


async def test_reprovision_updates_password_and_bindings(client: AsyncClient, db: AsyncSession):
    await _provision(db)
    company_before = await db.scalar(select(Company))

    result = await _provision(
        db,
        password="new-password-2",
        facility_keys=[FACILITY, OTHER_FACILITY],
        synthetic=True,
    )

    assert not result.created_user and not result.created_company and result.synthetic
    assert await db.scalar(select(func.count()).select_from(User)) == 1
    assert await db.scalar(select(func.count()).select_from(Company)) == 1
    other = await db.get(WorkflowFacilityAccount, OTHER_FACILITY)
    await db.refresh(other)
    assert other.company_id == company_before.id and other.synthetic
    assert (await _login(client, "sarom-hwaseong", PASSWORD)).status_code == 401
    assert (await _login(client, "sarom-hwaseong", "new-password-2")).status_code == 204


async def test_short_password_is_rejected(db: AsyncSession):
    with pytest.raises(ProvisionError):
        await _provision(db, password="short")


async def test_provisioned_facility_is_recipient_without_demo_flag(db: AsyncSession, monkeypatch):
    from app.domains.transport import recipient_accounts

    await _provision(db)
    prod = Settings(
        app_env="prod",
        jwt_secret="p" * 32,
        session_secret="s" * 32,
        database_url="postgresql+asyncpg://u:p@localhost/db",
    )
    assert not prod.synthetic_bindings_allowed
    monkeypatch.setattr(recipient_accounts, "get_settings", lambda: prod)
    review = {"next_step": {"options": [{"facilities": [{"facility_key": FACILITY}]}]}}

    result = await recipient_accounts.with_current_recipients(db, review)

    recipient = result["next_step"]["options"][0]["facilities"][0]["recipient"]
    company = await db.scalar(select(Company))
    assert recipient == {"id": str(company.id), "name": company.company_name, "synthetic": False}


async def test_provision_all_issues_one_account_per_facility(
    client: AsyncClient, db: AsyncSession, monkeypatch
):
    from app.core import passwords
    from app.domains.auth.facility_accounts import list_facilities, provision_all

    # 70여 곳을 두 번 발급하므로 해시 강도만 낮춤 (저장 형식에 n이 남아 검증은 그대로 됨)
    monkeypatch.setattr(passwords, "_N", 2**4)

    await _provision(db)  # sarom-hwaseong-2는 이미 다른 아이디의 기업에 연결됨
    total = len(await list_facilities(db))

    results, skipped = await provision_all(db, password=PASSWORD)

    assert list(skipped) == [FACILITY]
    assert len(results) == total - 1
    assert await db.scalar(select(func.count()).select_from(User)) == total
    login = await _login(client, OTHER_FACILITY, PASSWORD)
    assert login.status_code == 204
    me = (await client.get("/api/v1/users/me")).json()
    binding = await db.get(WorkflowFacilityAccount, OTHER_FACILITY)
    assert me["company_id"] == str(binding.company_id) and not binding.synthetic

    again, skipped_again = await provision_all(db, password="second-password")
    assert list(skipped_again) == [FACILITY]
    assert not any(r.created_user for r in again)
