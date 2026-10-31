"""값 추출(OCR)이 없는 동안 측정값 검수를 시험하는 로컬 전용 API.

app.main이 APP_ENV가 local 또는 test일 때만 등록함. prod에는 경로가 없음.
"""

import uuid

from fastapi import APIRouter, status

from app.core.errors import NotFoundError
from app.db.session import DbSession
from app.domains.documents import service
from app.domains.documents.models import DocumentValue, VerificationStatus
from app.domains.documents.schemas import ValueRead
from app.domains.reviews.dependencies import MyCompany

router = APIRouter(prefix="/documents", tags=["documents"])

_SAMPLES = (
    {"name": "함수율", "value": 12.5, "unit": "%", "basis": "습윤 기준"},
    {"name": "납", "value": 3.2, "unit": "mg/kg", "basis": "용출 시험"},
)


@router.post(
    "/{document_id}/dev-values",
    response_model=list[ValueRead],
    status_code=status.HTTP_201_CREATED,
    summary="샘플 측정값 넣기 (로컬 전용)",
    description="문서에 미검수 샘플 측정값 2개를 넣음. 실제 추출 결과가 아님.",
)
async def add_dev_values(
    document_id: uuid.UUID, company: MyCompany, db: DbSession
) -> list[ValueRead]:
    document = await service.get_document(db, company.id, document_id)
    if document is None:
        raise NotFoundError("문서를 찾을 수 없음")
    items = [
        DocumentValue(
            document_id=document.id,
            source_location="샘플",
            verification_status=VerificationStatus.UNVERIFIED,
            **sample,
        )
        for sample in _SAMPLES
    ]
    db.add_all(items)
    await db.commit()
    return [
        ValueRead(
            value_id=item.id,
            name=item.name,
            value=item.value,
            unit=item.unit,
            source_location=item.source_location,
            basis=item.basis,
            verification_status=item.verification_status,
        )
        for item in items
    ]
