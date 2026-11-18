"""운영(prod)에서 시연용(synthetic) 업체 연결을 켜고 끄는 설정."""

import uuid

import pytest

from app.core.config import Settings, get_settings
from app.domains.transport import dev_accounts
from app.domains.transport.models import WorkflowFacilityAccount
from tests.test_pp_company_workflow import setup_flow as _setup_flow

setup_flow = _setup_flow
PROD = {"app_env": "prod", "jwt_secret": "x" * 32, "session_secret": "y" * 32}
PG = "postgresql+asyncpg://u:p@localhost/db"


def test_synthetic_bindings_allowed_only_in_local_test_or_when_enabled():
    assert Settings(app_env="local").synthetic_bindings_allowed
    assert Settings(app_env="test").synthetic_bindings_allowed
    assert not Settings(**PROD, database_url=PG).synthetic_bindings_allowed
    assert Settings(**PROD, database_url=PG, demo_facility_bindings=True).synthetic_bindings_allowed


@pytest.mark.parametrize("enabled", [False, True])
async def test_prod_offer_to_synthetic_binding_follows_flag(setup_flow, db, monkeypatch, enabled):
    req, create, actors, _ = setup_flow
    db.add(
        WorkflowFacilityAccount(
            facility_key="jungang-gongju",
            company_id=uuid.UUID(actors["B"][1]),
            synthetic=True,
            verification_reference="synthetic demo test only",
        )
    )
    await db.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "demo_facility_bindings", enabled)

    lot = await create()
    lot = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    f = next(
        f
        for o in lot["review"]["next_step"]["options"]
        for f in o["facilities"]
        if f["facility_key"] == "jungang-gongju"
    )
    assert (f["recipient"] is not None) is enabled
    if enabled:
        assert f["recipient"]["synthetic"] is True
    r = await req(
        "A",
        f"/lots/{lot['id']}/offers",
        {"revision": lot["revision"], "capability_key": f["capability_key"]},
    )
    assert (r.status_code == 200) is enabled, r.text


def test_dev_accounts_cli_requires_explicit_targets_in_prod(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "demo_facility_bindings", False)
    monkeypatch.setattr("sys.argv", ["dev_accounts"])
    with pytest.raises(SystemExit) as exc:
        dev_accounts.main()
    assert "DEMO_FACILITY_BINDINGS" in str(exc.value.code)

    monkeypatch.setattr(settings, "demo_facility_bindings", True)
    with pytest.raises(SystemExit) as exc:
        dev_accounts.main()
    assert exc.value.code == 2  # 기본 example.com 계정으로는 운영에서 실행 안 함
