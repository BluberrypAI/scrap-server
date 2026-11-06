"""docs/specs/dev-mock-engine.md 완료 조건.

가짜 엔진 모드로 AI 서버 없이 전체 흐름을 지나고, 가짜 응답이 엔진 계약과 맞는지 확인함.
"""

import json
from pathlib import Path

import jsonschema
import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.domains.reviews import intake as intake_rules
from app.domains.runs.engine_client import LOT_FIELDS
from app.domains.runs.mock_engine import MOCK_NOTICE, research_result
from app.main import create_app

CONTRACT = json.loads(
    (Path(__file__).parent / "contracts" / "candidate-research-v1.json").read_text("utf-8")
)
PROD = {
    "app_env": "prod",
    "jwt_secret": "x" * 32,
    "session_secret": "y" * 32,
    "database_url": "postgresql+asyncpg://u:p@db/resource",
}


def run_url(review_id: str, run_id: str) -> str:
    return f"/api/v1/reviews/{review_id}/runs/{run_id}"


@pytest.fixture
def mock_mode(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "ai_engine_mode", "mock")


async def start_run(client: AsyncClient, review_id: str) -> str:
    res = await client.post(f"/api/v1/reviews/{review_id}/runs", json={"intake_version": 1})
    assert res.status_code == 202, res.text
    return res.json()["run_id"]


# --- 계약 ---


def test_contract_snapshot_matches_supported_version():
    assert CONTRACT["source"]["contract_version"] == "candidate-research-v1"
    version = CONTRACT["response"]["properties"]["contract_version"]
    assert version["const"] == "candidate-research-v1"


def test_mock_response_follows_engine_contract():
    jsonschema.validate(research_result(), CONTRACT["response"])


def test_lot_fields_exist_in_engine_contract():
    lot_schema = CONTRACT["request"]["$defs"]["AssessedPlansRequest"]

    assert set(LOT_FIELDS) <= set(lot_schema["properties"])


def test_lot_sent_to_engine_follows_contract():
    lot = {
        "material": "PP",
        "input_form": "scrap",
        "quantity_kg": 3000.0,
        "moisture_pct": 8.0,
        "designated_waste": False,
    }

    jsonschema.validate({"lot": lot}, CONTRACT["request"])


def test_server_only_intake_field_is_not_sent_to_engine():
    server_only = set(intake_rules.FIELD_ORDER) - set(LOT_FIELDS)

    assert server_only == {"has_test_report"}


# --- 안전장치 ---


def test_default_mode_is_real_engine():
    assert Settings.model_fields["ai_engine_mode"].default == "http"


def test_mock_mode_is_rejected_in_prod():
    with pytest.raises(ValidationError, match="AI_ENGINE_MODE=mock"):
        Settings(_env_file=None, ai_engine_mode="mock", **PROD)


def test_dev_values_route_is_absent_in_prod():
    app = create_app(Settings(_env_file=None, **PROD))

    paths = app.openapi()["paths"]
    assert "/api/v1/documents/{document_id}/values" in paths
    assert "/api/v1/documents/{document_id}/dev-values" not in paths


# --- 샘플 측정값 ---


async def test_dev_values_can_be_verified(company_client: AsyncClient, ready_review: str):
    upload = await company_client.post(
        f"/api/v1/reviews/{ready_review}/documents",
        files={"file": ("report.pdf", b"%PDF", "application/pdf")},
        data={"doc_type": "test_report"},
    )
    document_id = upload.json()["document_id"]

    res = await company_client.post(f"/api/v1/documents/{document_id}/dev-values")

    assert res.status_code == 201
    values = res.json()
    assert [v["verification_status"] for v in values] == ["unverified", "unverified"]
    patched = await company_client.patch(
        f"/api/v1/documents/{document_id}/values/{values[0]['value_id']}",
        json={"verification_status": "verified"},
    )
    assert patched.json()["verification_status"] == "verified"


async def test_other_company_cannot_add_dev_values(
    company_client: AsyncClient, other_client: AsyncClient, ready_review: str
):
    upload = await company_client.post(
        f"/api/v1/reviews/{ready_review}/documents",
        files={"file": ("report.pdf", b"%PDF", "application/pdf")},
    )

    res = await other_client.post(f"/api/v1/documents/{upload.json()['document_id']}/dev-values")

    assert res.status_code == 404


# --- 전체 흐름 ---


@pytest.mark.usefixtures("mock_mode", "run_queue")
async def test_full_flow_without_ai_server(company_client: AsyncClient, ready_review: str):
    run_id = await start_run(company_client, ready_review)
    url = run_url(ready_review, run_id)

    run = (await company_client.get(url)).json()
    assert run["status"] == "completed"
    assert run["limitations"][0] == MOCK_NOTICE

    candidates = (await company_client.get(f"{url}/candidates")).json()["items"]
    assert {c["judgment"] for c in candidates} == {"needs_check", "unsuitable"}
    queue = (await company_client.get(f"{url}/review-queue")).json()
    assert [i["candidate_id"] for i in queue["items"]] == ["plan-a"]

    blocked = await company_client.post(
        f"{url}/candidates/plan-b/risk-steps/1/decision", json={"decision": "confirm"}
    )
    assert blocked.json()["code"] == "RISK_OPTION_REQUIRED"

    supplement = await company_client.post(
        f"/api/v1/reviews/{ready_review}/supplements",
        data={
            "type": "inspection_result",
            "effective_date": "2026-10-01",
            "applied_quantity_value": "3000",
            "verification_status": "verified",
        },
    )
    supplement_id = supplement.json()["supplement_id"]
    linked = await company_client.post(
        f"{url}/risks/plan-b-r1/evidence", json={"supplement_id": supplement_id}
    )
    assert linked.json()["status"] == "resolved"
    decided = await company_client.post(
        f"{url}/candidates/plan-b/risk-steps/1/decision", json={"decision": "confirm"}
    )
    assert decided.json()["next_step"] == 2

    rerun = await company_client.post(f"{url}/rerun", json={"supplement_ids": [supplement_id]})
    assert rerun.status_code == 202
    compared = await company_client.get(
        f"/api/v1/reviews/{ready_review}/compare",
        params={"base_run_id": run_id, "target_run_id": rerun.json()["new_run_id"]},
    )
    assert compared.json()["changes"] == []


@pytest.mark.usefixtures("mock_mode", "run_queue")
async def test_mock_result_is_same_for_different_input(company_client: AsyncClient):
    """고정 샘플이라 입력이 달라도 후보가 같음. 판정 품질은 mock으로 검증할 수 없음."""
    ids = []
    for material in ("PP", "PE"):
        review = await company_client.post(
            "/api/v1/reviews",
            json={"free_text": material, "overrides": {"material": material, "quantity_kg": 1}},
        )
        review_id = review.json()["review_id"]
        run_id = await start_run(company_client, review_id)
        res = await company_client.get(f"{run_url(review_id, run_id)}/candidates")
        ids.append([c["candidate_id"] for c in res.json()["items"]])

    assert ids[0] == ids[1]
