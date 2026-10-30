"""docs/specs/review-documents.md 완료 조건."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.storage import get_storage
from app.domains.documents.models import Document, DocumentValue, VerificationStatus
from app.domains.users.models import User
from app.domains.users.service import purge_withdrawn_users

PDF = b"%PDF-1.4 test report"


@pytest.fixture
async def review_id(company_client: AsyncClient) -> str:
    res = await company_client.post("/api/v1/reviews", json={"free_text": "PP 파쇄품 처리"})
    return res.json()["review_id"]


async def upload(client: AsyncClient, review_id: str, name="성적서.pdf", data=PDF, **form):
    return await client.post(
        f"/api/v1/reviews/{review_id}/documents",
        files={"file": (name, data, "application/octet-stream")},
        data=form,
    )


async def add_value(db: AsyncSession, document_id: str, **fields) -> str:
    """값 추출(OCR)이 연결되기 전이라 테스트에서 직접 넣음."""
    item = DocumentValue(
        document_id=uuid.UUID(document_id),
        name=fields.pop("name", "함수율"),
        value=fields.pop("value", 12.5),
        unit=fields.pop("unit", "%"),
        source_location="p.1 표1",
        **fields,
    )
    db.add(item)
    await db.commit()
    return str(item.id)


def stored_path(key: str) -> Path:
    return Path(get_settings().upload_dir) / key


# --- 업로드·목록 ---


async def test_upload_returns_201_and_saves_file(
    company_client: AsyncClient, review_id: str, db: AsyncSession
):
    res = await upload(company_client, review_id, doc_type="test_report")

    assert res.status_code == 201
    body = res.json()
    assert body["format"] == "pdf"
    assert body["doc_type"] == "test_report"
    assert body["status"] == "uploaded"
    document = await db.get(Document, uuid.UUID(body["document_id"]))
    assert stored_path(document.storage_key).read_bytes() == PDF


async def test_upload_rejects_unsupported_type(company_client: AsyncClient, review_id: str):
    res = await upload(company_client, review_id, name="malware.exe")

    assert res.status_code == 415
    assert res.json()["code"] == "FILE_TYPE_UNSUPPORTED"


async def test_upload_rejects_too_large_file(
    company_client: AsyncClient, review_id: str, monkeypatch
):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)

    res = await upload(company_client, review_id, data=b"0" * (1024 * 1024 + 1))

    assert res.status_code == 413
    assert res.json()["code"] == "FILE_TOO_LARGE"


async def test_list_documents_in_upload_order(company_client: AsyncClient, review_id: str):
    await upload(company_client, review_id, name="a.pdf")
    await upload(company_client, review_id, name="b.JPEG")

    res = await company_client.get(f"/api/v1/reviews/{review_id}/documents")

    body = res.json()
    assert [(d["file_name"], d["format"]) for d in body["items"]] == [
        ("a.pdf", "pdf"),
        ("b.JPEG", "jpg"),
    ]
    assert body["items"][0]["doc_type"] == "other"
    assert body["pagingInfo"]["elementCount"] == 2


# --- 측정값 ---


async def test_list_values(company_client: AsyncClient, review_id: str, db: AsyncSession):
    document_id = (await upload(company_client, review_id)).json()["document_id"]
    await add_value(db, document_id, basis="건조 기준")

    res = await company_client.get(f"/api/v1/documents/{document_id}/values")

    item = res.json()["items"][0]
    assert item["name"] == "함수율"
    assert item["unit"] == "%"
    assert item["source_location"] == "p.1 표1"
    assert item["basis"] == "건조 기준"
    assert item["verification_status"] == "unverified"


async def test_verify_value(company_client: AsyncClient, review_id: str, db: AsyncSession):
    document_id = (await upload(company_client, review_id)).json()["document_id"]
    value_id = await add_value(db, document_id)

    res = await company_client.patch(
        f"/api/v1/documents/{document_id}/values/{value_id}",
        json={"verification_status": "verified"},
    )

    assert res.status_code == 200
    assert res.json()["verification_status"] == "verified"


async def test_editing_value_resets_verification(
    company_client: AsyncClient, review_id: str, db: AsyncSession
):
    document_id = (await upload(company_client, review_id)).json()["document_id"]
    value_id = await add_value(db, document_id, verification_status=VerificationStatus.VERIFIED)

    res = await company_client.patch(
        f"/api/v1/documents/{document_id}/values/{value_id}",
        json={"value": 13.0, "verification_status": "verified"},
    )

    assert res.json()["value"] == 13.0
    assert res.json()["verification_status"] == "unverified"


async def test_value_without_unit_returns_422(
    company_client: AsyncClient, review_id: str, db: AsyncSession
):
    document_id = (await upload(company_client, review_id)).json()["document_id"]
    value_id = await add_value(db, document_id, value=None, unit=None)

    res = await company_client.patch(
        f"/api/v1/documents/{document_id}/values/{value_id}", json={"value": 3.2}
    )

    assert res.status_code == 422
    assert res.json()["code"] == "UNIT_REQUIRED"


async def test_empty_value_update_returns_422(
    company_client: AsyncClient, review_id: str, db: AsyncSession
):
    document_id = (await upload(company_client, review_id)).json()["document_id"]
    value_id = await add_value(db, document_id)

    res = await company_client.patch(f"/api/v1/documents/{document_id}/values/{value_id}", json={})

    assert res.status_code == 422


# --- 교체 ---


async def test_replace_resets_values_and_swaps_file(
    company_client: AsyncClient, review_id: str, db: AsyncSession
):
    document_id = (await upload(company_client, review_id)).json()["document_id"]
    await add_value(db, document_id, verification_status=VerificationStatus.VERIFIED)
    old_key = (await db.get(Document, uuid.UUID(document_id))).storage_key

    res = await company_client.post(
        f"/api/v1/documents/{document_id}/replace",
        files={"file": ("새 성적서.xlsx", b"PK new", "application/octet-stream")},
    )

    assert res.status_code == 200
    assert res.json()["file_version"] == 2
    assert res.json()["values_reset"] is True
    values = (await company_client.get(f"/api/v1/documents/{document_id}/values")).json()
    assert {v["verification_status"] for v in values["items"]} == {"unverified"}
    db.expire_all()
    document = await db.get(Document, uuid.UUID(document_id))
    assert document.format == "xlsx"
    assert stored_path(document.storage_key).read_bytes() == b"PK new"
    assert not stored_path(old_key).exists()


async def test_replace_rejects_unsupported_type(company_client: AsyncClient, review_id: str):
    document_id = (await upload(company_client, review_id)).json()["document_id"]

    res = await company_client.post(
        f"/api/v1/documents/{document_id}/replace",
        files={"file": ("a.docx", b"x", "application/octet-stream")},
    )

    assert res.status_code == 415


# --- 접근 격리·삭제 ---


async def test_other_company_cannot_access_documents(
    company_client: AsyncClient, other_client: AsyncClient, review_id: str, db: AsyncSession
):
    document_id = (await upload(company_client, review_id)).json()["document_id"]
    value_id = await add_value(db, document_id)

    assert (await upload(other_client, review_id)).status_code == 404
    assert (await other_client.get(f"/api/v1/reviews/{review_id}/documents")).status_code == 404
    assert (await other_client.get(f"/api/v1/documents/{document_id}/values")).status_code == 404
    patch = await other_client.patch(
        f"/api/v1/documents/{document_id}/values/{value_id}",
        json={"verification_status": "verified"},
    )
    assert patch.status_code == 404


async def test_purge_deletes_documents_and_files(
    company_client: AsyncClient, review_id: str, db: AsyncSession, user: User
):
    document_id = (await upload(company_client, review_id)).json()["document_id"]
    await add_value(db, document_id)
    key = (await db.get(Document, uuid.UUID(document_id))).storage_key
    user.withdrawn_at = datetime.now(UTC) - timedelta(days=31)
    user.deletion_scheduled_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()

    await purge_withdrawn_users(db)

    assert await db.scalar(select(func.count()).select_from(Document)) == 0
    assert await db.scalar(select(func.count()).select_from(DocumentValue)) == 0
    assert not (Path(get_storage().root) / key).exists()
