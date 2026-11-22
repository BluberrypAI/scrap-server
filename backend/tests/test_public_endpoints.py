"""로그인 없이 열려 있으면 안 되는 경로와, 밖에서 부르는 헬스체크 확인."""

import pytest
from httpx import AsyncClient

PROTECTED = [
    ("POST", "/api/treatment/next-step", {"waste_code": "51-03-01"}),
    ("POST", "/api/treatment/facility-candidates", {"waste_code": "51-03-01"}),
    ("POST", "/api/treatment/intake-review", {}),
    ("POST", "/api/treatment/intake-reviews", {}),
    ("POST", "/api/treatment/facility-web-search", {}),
    ("GET", "/api/classification/profiles", None),
    ("POST", "/api/classification/sessions", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), PROTECTED)
async def test_treatment_and_classification_require_login(
    client: AsyncClient, method: str, path: str, body: dict | None
):
    response = await client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
async def test_health_is_public(client: AsyncClient, path: str):
    response = await client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
