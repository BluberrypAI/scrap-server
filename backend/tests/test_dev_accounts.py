"""로컬 시험용 업체 계정 연결 스크립트."""

import uuid

import pytest
from sqlalchemy import select

from app.domains.companies.models import Company
from app.domains.transport import dev_accounts
from app.domains.transport.models import WorkflowFacilityAccount
from app.domains.users.models import User


@pytest.mark.asyncio
async def test_bind_links_company_and_skips_missing(db, monkeypatch):
    user = User(provider="dev", provider_subject="pp-sort", email="pp-sort@example.com", name="B")
    db.add(user)
    await db.flush()
    company = Company(
        user_id=user.id,
        company_name="B 선별",
        contact_email="pp-sort@example.com",
        industry="재활용",
        site_name="본사",
        site_address="경기도 화성시",
        site_facilities=[],
        main_products=[],
        main_waste_types=[],
    )
    db.add(company)
    await db.commit()

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(dev_accounts, "SessionLocal", Session)
    missing = await dev_accounts.bind(
        {"pp-sort@example.com": ["sarom-hwaseong-2"], "nobody@example.com": ["bgf-yesan"]}
    )

    assert missing == 1
    rows = list(await db.scalars(select(WorkflowFacilityAccount)))
    assert [(r.facility_key, r.company_id, r.synthetic) for r in rows] == [
        ("sarom-hwaseong-2", company.id, True)
    ]
    assert isinstance(rows[0].company_id, uuid.UUID)
