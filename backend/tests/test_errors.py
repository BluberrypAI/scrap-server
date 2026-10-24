"""Completion criteria from docs/specs/error-response.md."""

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.test_companies import COMPANIES, COMPANY, ME


def assert_error(res, status: int, code: str) -> dict:
    assert res.status_code == status
    body = res.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == code
    assert body["message"]
    return body


async def test_missing_token_returns_auth_required(client: AsyncClient):
    res = await client.get("/api/v1/users/me")

    body = assert_error(res, 401, "AUTH_REQUIRED")
    assert body["details"] is None
    assert res.headers["www-authenticate"] == "Bearer"


async def test_validation_error_lists_fields(auth_client: AsyncClient):
    payload = {**COMPANY, "contact": {"name": ""}}

    res = await auth_client.post(COMPANIES, json=payload)

    body = assert_error(res, 422, "VALIDATION_ERROR")
    assert [d["field"] for d in body["details"]] == ["body.contact.name"]


async def test_query_validation_error_field(auth_client: AsyncClient):
    await auth_client.post(COMPANIES, json=COMPANY)

    res = await auth_client.get(f"{ME}/history", params={"pageSize": 0})

    body = assert_error(res, 422, "VALIDATION_ERROR")
    assert body["details"][0]["field"] == "query.pageSize"


async def test_unknown_route_returns_not_found(client: AsyncClient):
    res = await client.get("/api/v1/nope")
    assert_error(res, 404, "NOT_FOUND")


async def test_wrong_method_returns_method_not_allowed(client: AsyncClient):
    res = await client.delete("/api/v1/users/me")
    assert_error(res, 405, "METHOD_NOT_ALLOWED")


async def test_missing_company_returns_not_found(auth_client: AsyncClient):
    res = await auth_client.get(ME)
    assert_error(res, 404, "NOT_FOUND")


async def test_conflict_codes(auth_client: AsyncClient):
    await auth_client.post(COMPANIES, json=COMPANY)

    again = await auth_client.post(COMPANIES, json=COMPANY)
    stale = await auth_client.patch(ME, json={"profile_version": 9, "industry": "A"})

    assert_error(again, 409, "COMPANY_ALREADY_EXISTS")
    assert_error(stale, 409, "VERSION_CONFLICT")


async def test_unsupported_provider_code(client: AsyncClient):
    res = await client.get("/api/v1/auth/kakao/login")
    assert_error(res, 404, "UNSUPPORTED_PROVIDER")


async def test_unhandled_error_hides_details():
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/boom")

    assert_error(res, 500, "INTERNAL_ERROR")
    assert "secret" not in res.text
