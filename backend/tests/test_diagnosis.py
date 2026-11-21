"""문진 엔진 중계 (docs/specs/diagnosis-engine-integration.md 6장 완료 조건)."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domains.companies.models import Company
from app.domains.diagnosis.client import EngineClient, get_engine_client
from app.domains.users.models import User
from app.domains.users.service import purge_withdrawn_users
from app.main import app

TOKEN = "engine-test-token"
TURN = {"branch": "ASK_FACT", "message": "어떤 종류인가요?", "ui": {}, "assist": None}


class FakeEngine:
    """엔진 /internal/v1 대역. 받은 요청을 기록하고 정해 둔 응답을 돌려줌."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply: httpx.Response | Exception | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        if self.reply is not None:
            return self.reply
        path = request.url.path
        if request.method == "POST" and path == "/internal/v1/cases":
            return httpx.Response(
                201, json={"case": {"id": "C1", "status": "DIAGNOSING"}, "turn": TURN}
            )
        if path == "/internal/v1/cases":
            paging = {"currentPageNumber": 2, "pageSize": 5, "totalCount": 6, "totalPages": 2}
            return httpx.Response(200, json={"items": [{"id": "C1"}], "pagingInfo": paging})
        if request.method == "DELETE":
            return httpx.Response(200, json={"status": "DONE"})
        return httpx.Response(200, json=TURN)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def client(self, url: str = "http://engine.test") -> EngineClient:
        return EngineClient(url, TOKEN, 5, transport=httpx.MockTransport(self.handler))


def _error(status: int, code: str, details=None) -> httpx.Response:
    detail = {"code": code, "message": "엔진 메시지", "details": details or {}}
    return httpx.Response(status, json={"detail": detail})


@pytest.fixture
def fake_engine() -> FakeEngine:
    fake = FakeEngine()
    app.dependency_overrides[get_engine_client] = fake.client
    yield fake
    app.dependency_overrides.pop(get_engine_client, None)


async def _company_id(db: AsyncSession) -> str:
    return str(await db.scalar(select(Company.id)))


async def test_login_required(client: AsyncClient, fake_engine: FakeEngine):
    res = await client.post("/api/v1/diagnosis/cases", json={})
    assert res.status_code == 401
    assert res.json()["code"] == "AUTH_REQUIRED"
    assert fake_engine.requests == []


async def test_company_required(auth_client: AsyncClient, fake_engine: FakeEngine):
    res = await auth_client.post("/api/v1/diagnosis/cases", json={})
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"
    assert fake_engine.requests == []


async def test_create_case_sends_auth_and_strips_server_fields(
    company_client: AsyncClient, fake_engine: FakeEngine, db: AsyncSession
):
    body = {
        "memo": "PP 필름 자투리",
        "quantity": 1.5,
        "unit": "t",
        "confirmed_facts": {"emission_facility": True},
        "company_profile_version": "9",
    }
    res = await company_client.post("/api/v1/diagnosis/cases", json=body)
    assert res.status_code == 201
    assert res.json()["case"]["id"] == "C1"
    sent = fake_engine.last
    assert sent.url.path == "/internal/v1/cases"
    assert sent.headers["Authorization"] == f"Bearer {TOKEN}"
    assert sent.headers["X-Company-Id"] == await _company_id(db)
    assert json.loads(sent.content) == {"memo": "PP 필름 자투리", "quantity": 1.5, "unit": "t"}


async def test_create_case_sends_site_conditions_as_confirmed_facts(
    company_client: AsyncClient, fake_engine: FakeEngine
):
    """회원가입에서 받은 사업장 고정값만 confirmed_facts로 넘김 (모름은 보내지 않음)."""
    res = await company_client.patch(
        "/api/v1/companies/me",
        json={"profile_version": 1, "emission_facility": "no", "daily_avg_kg": 350},
    )
    assert res.status_code == 200
    res = await company_client.post("/api/v1/diagnosis/cases", json={"memo": "PP"})
    assert res.status_code == 201
    assert json.loads(fake_engine.last.content) == {
        "memo": "PP",
        "confirmed_facts": {"emission_facility": "no", "daily_avg_kg": 350},
        "company_profile_version": "2",
    }


async def test_list_cases_passes_query_and_paging(
    company_client: AsyncClient, fake_engine: FakeEngine
):
    res = await company_client.get(
        "/api/v1/diagnosis/cases", params={"status": "DIAGNOSING", "page": 2, "size": 5}
    )
    assert res.status_code == 200
    assert res.json()["pagingInfo"]["totalPages"] == 2
    assert dict(fake_engine.last.url.params) == {"status": "DIAGNOSING", "page": "2", "size": "5"}


async def test_message_is_forwarded_and_assist_passes_through(
    company_client: AsyncClient, fake_engine: FakeEngine
):
    turn = {**TURN, "assist": {"intent": "why", "text": "설명", "sources": []}}
    fake_engine.reply = httpx.Response(200, json=turn)
    body = {"quick_reply": {"key": "material", "kind": "value", "value": "pp"}}
    res = await company_client.post("/api/v1/diagnosis/cases/C1/messages", json=body)
    assert res.status_code == 200
    # 엔진이 새로 추가한 필드도 server가 버리지 않음
    assert res.json()["assist"]["intent"] == "why"
    assert fake_engine.last.url.path == "/internal/v1/cases/C1/diagnosis/messages"
    assert json.loads(fake_engine.last.content) == body


async def test_apply_values_fills_reviewer(
    company_client: AsyncClient, fake_engine: FakeEngine, user: User
):
    body = {
        "values": [
            {
                "value_id": "V1",
                "document_version": 1,
                "reviewer": "가짜",
                "reviewed_at": "2000-01-01",
            }
        ]
    }
    before = datetime.now(UTC)
    res = await company_client.post(
        "/api/v1/diagnosis/cases/C1/documents/D1/values/apply", json=body
    )
    assert res.status_code == 200
    sent = json.loads(fake_engine.last.content)["values"][0]
    assert sent["reviewer"] == str(user.id)
    assert datetime.fromisoformat(sent["reviewed_at"]) >= before
    assert sent["value_id"] == "V1"


async def test_upload_forwards_multipart(company_client: AsyncClient, fake_engine: FakeEngine):
    fake_engine.reply = httpx.Response(
        201, json={"document": {"id": "D1"}, "turn": TURN, "values": []}
    )
    res = await company_client.post(
        "/api/v1/diagnosis/cases/C1/documents",
        files={"file": ("report.txt", b"oil 2%", "text/plain")},
        data={"facts": '{"oil_content_pct": 2}'},
    )
    assert res.status_code == 201
    sent = fake_engine.last
    assert sent.headers["content-type"].startswith("multipart/form-data")
    assert b"oil 2%" in sent.content
    assert b'{"oil_content_pct": 2}' in sent.content
    assert b'filename="report.txt"' in sent.content


async def test_kb_changed_is_passed_through(company_client: AsyncClient, fake_engine: FakeEngine):
    fake_engine.reply = _error(409, "KB_CHANGED", {"session_kb_version": "a"})
    res = await company_client.post("/api/v1/diagnosis/cases/C1/messages", json={"text": "네"})
    assert res.status_code == 409
    assert res.json()["code"] == "KB_CHANGED"
    assert res.json()["details"] is None


async def test_value_problems_become_details(company_client: AsyncClient, fake_engine: FakeEngine):
    problems = {"problems": [{"key": "ph", "value": "약 2", "reason": "숫자가 아님"}]}
    fake_engine.reply = _error(422, "VALIDATION_ERROR", problems)
    res = await company_client.post(
        "/api/v1/diagnosis/cases/C1/documents/D1/values/apply",
        json={"values": [{"fact_key": "ph", "value": "약 2", "document_version": 1}]},
    )
    assert res.status_code == 422
    assert res.json()["details"] == [{"field": "ph", "message": "숫자가 아님"}]


@pytest.mark.parametrize(
    "reply",
    [
        _error(401, "AUTH_REQUIRED"),
        _error(500, "INTERNAL_ERROR"),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_engine_failures_are_503(company_client: AsyncClient, fake_engine: FakeEngine, reply):
    fake_engine.reply = reply
    res = await company_client.get("/api/v1/diagnosis/cases/C1")
    assert res.status_code == 503
    assert res.json()["code"] == "ENGINE_UNAVAILABLE"


async def test_engine_url_not_set_is_503(company_client: AsyncClient, fake_engine: FakeEngine):
    app.dependency_overrides[get_engine_client] = lambda: fake_engine.client(url="")
    res = await company_client.get("/api/v1/diagnosis/catalog/facts")
    assert res.status_code == 503
    assert fake_engine.requests == []


async def test_unknown_engine_code_uses_http_status(
    company_client: AsyncClient, fake_engine: FakeEngine
):
    fake_engine.reply = _error(404, "SOMETHING_NEW")
    res = await company_client.get("/api/v1/diagnosis/cases/C1/trace")
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


async def test_bad_case_id_is_rejected(company_client: AsyncClient, fake_engine: FakeEngine):
    res = await company_client.get("/api/v1/diagnosis/cases/a.b")
    assert res.status_code == 422
    assert fake_engine.requests == []


async def _withdrawn(db: AsyncSession, user: User) -> None:
    user.withdrawn_at = datetime.now(UTC) - timedelta(days=40)
    user.deletion_scheduled_at = datetime.now(UTC) - timedelta(days=10)
    await db.commit()


async def test_purge_deletes_engine_data(company_client: AsyncClient, db: AsyncSession, user: User):
    company_id = await _company_id(db)
    await _withdrawn(db, user)
    fake = FakeEngine()
    assert await purge_withdrawn_users(db, engine=fake.client()) == 1
    assert fake.last.method == "DELETE"
    assert fake.last.url.path == f"/internal/v1/companies/{company_id}/data"
    assert "X-Company-Id" not in fake.last.headers


async def test_purge_keeps_user_when_engine_fails(
    company_client: AsyncClient, db: AsyncSession, user: User
):
    await _withdrawn(db, user)
    fake = FakeEngine()
    fake.reply = _error(500, "DELETION_FAILED")
    assert await purge_withdrawn_users(db, engine=fake.client()) == 0
    assert await db.scalar(select(Company.id)) is not None


def test_prod_requires_engine_token():
    with pytest.raises(ValueError, match="ENGINE_SERVICE_TOKEN"):
        Settings(
            app_env="prod",
            jwt_secret="x" * 40,
            session_secret="y" * 40,
            database_url="postgresql+asyncpg://u:p@h/db",
            diagnosis_engine_url="http://engine:8030",
        )
