"""기업 간 인계 API 오류는 공통 형식({code, message})으로 이유를 그대로 돌려줌."""

import uuid

import pytest


@pytest.mark.asyncio
async def test_missing_lot_returns_reason(company_client):
    res = await company_client.get(f"/api/v1/workflow/lots/{uuid.uuid4()}")
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"
    assert res.json()["message"] == "해당 처리 건을 찾을 수 없습니다."


@pytest.mark.asyncio
async def test_bad_photo_returns_reason(company_client):
    res = await company_client.post(
        f"/api/v1/workflow/lots/{uuid.uuid4()}/photos",
        files={"file": ("x.jpg", b"not an image", "image/jpeg")},
    )
    assert res.status_code == 422
    assert res.json()["code"] == "VALIDATION_ERROR"
    assert res.json()["message"] == "사진 파일을 읽을 수 없습니다."
