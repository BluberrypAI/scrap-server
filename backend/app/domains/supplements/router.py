import math
import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.errors import ErrorCode, UnprocessableError
from app.core.storage import LocalFileStorage, get_storage
from app.db.session import DbSession
from app.domains.companies.schemas import PagingInfo
from app.domains.documents.models import VerificationStatus
from app.domains.documents.uploads import read_upload
from app.domains.reviews.dependencies import MyReview
from app.domains.supplements import service
from app.domains.supplements.models import Applicability, Supplement, SupplementType

router = APIRouter(prefix="/reviews/{review_id}/supplements", tags=["supplements"])


class SupplementCreated(BaseModel):
    supplement_id: uuid.UUID
    type: SupplementType
    applicability: Applicability
    mismatch_reason: str | None
    counted_in_judgment: bool = Field(description="물량이 맞고 검수된 자료만 true")


class SupplementItem(SupplementCreated):
    value: float | None
    applied_quantity_kg: float
    effective_date: date
    verification_status: VerificationStatus
    file_name: str | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        # SQLite는 시간대를 버림. 저장 값은 UTC임
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class SupplementPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[SupplementItem]
    paging_info: PagingInfo = Field(alias="pagingInfo")


def _created(s: Supplement) -> dict:
    return {
        "supplement_id": s.id,
        "type": s.type,
        "applicability": s.applicability,
        "mismatch_reason": s.mismatch_reason,
        "counted_in_judgment": service.counted_in_judgment(s),
    }


@router.post(
    "",
    response_model=SupplementCreated,
    status_code=status.HTTP_201_CREATED,
    summary="추가 자료 등록",
    description="multipart/form-data. "
    "적용 물량(applied_quantity_value, applied_quantity_unit=kg|t)은 필수. "
    "검토에서 확인된 물량과 다르면 mismatch이고 판정·재실행에 쓰지 않음.",
    responses={
        413: {"description": "FILE_TOO_LARGE"},
        415: {"description": "FILE_TYPE_UNSUPPORTED"},
        422: {"description": "MISSING_QUANTITY, VALIDATION_ERROR"},
    },
)
async def create_supplement(
    review: MyReview,
    db: DbSession,
    storage: Annotated[LocalFileStorage, Depends(get_storage)],
    type: SupplementType = Form(...),
    effective_date: date = Form(...),
    applied_quantity_value: float | None = Form(None, gt=0),
    applied_quantity_unit: str = Form("kg", pattern="^(kg|t)$"),
    verification_status: VerificationStatus = Form(VerificationStatus.UNVERIFIED),
    value: float | None = Form(None),
    file: UploadFile | None = File(None),
) -> SupplementCreated:
    if applied_quantity_value is None:
        raise UnprocessableError(ErrorCode.MISSING_QUANTITY, "자료가 적용되는 물량을 입력해야 함")
    upload = await read_upload(file) if file is not None else None
    supplement = await service.create(
        db,
        storage,
        review,
        type,
        applied_quantity_value * service.QUANTITY_UNITS[applied_quantity_unit],
        effective_date,
        verification_status,
        value,
        upload,
    )
    return SupplementCreated(**_created(supplement))


@router.get(
    "",
    response_model=SupplementPage,
    summary="추가 자료 목록",
    description="등록 순서. counted_in_judgment=false인 자료는 판정·재실행에 쓰지 않음.",
)
async def list_supplements(
    review: MyReview,
    db: DbSession,
    page_number: int = Query(1, alias="pageNumber", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
) -> SupplementPage:
    rows, total = await service.list_page(db, review.id, page_number, page_size)
    total_pages = math.ceil(total / page_size)
    return SupplementPage(
        items=[
            SupplementItem(
                **_created(s),
                value=s.value,
                applied_quantity_kg=s.applied_quantity_kg,
                effective_date=s.effective_date,
                verification_status=s.verification_status,
                file_name=s.file_name,
                created_at=s.created_at,
            )
            for s in rows
        ],
        paging_info=PagingInfo(
            current_page_number=page_number,
            page_size=page_size,
            element_count=total,
            total_page_count=total_pages,
            is_last_page=page_number >= total_pages,
            is_empty=not rows,
        ),
    )
