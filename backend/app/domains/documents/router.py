import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode, NotFoundError, UnprocessableError
from app.core.storage import LocalFileStorage, get_storage
from app.db.session import DbSession
from app.domains.companies.schemas import PagingInfo
from app.domains.documents import service
from app.domains.documents.models import Document, DocumentType, DocumentValue
from app.domains.documents.schemas import (
    DocumentPage,
    DocumentRead,
    DocumentReplaced,
    DocumentUploaded,
    ValuePage,
    ValueRead,
    ValueUpdate,
    ValueUpdated,
)
from app.domains.reviews.dependencies import MyCompany, MyReview

router = APIRouter(tags=["documents"])

Storage = Annotated[LocalFileStorage, Depends(get_storage)]

_FILE_ERRORS = {
    413: {"description": "파일 크기 초과 (FILE_TOO_LARGE)"},
    415: {"description": "허용되지 않은 형식 (FILE_TYPE_UNSUPPORTED)"},
}


def _paging(page_number: int, page_size: int, total: int, empty: bool) -> PagingInfo:
    total_pages = math.ceil(total / page_size)
    return PagingInfo(
        current_page_number=page_number,
        page_size=page_size,
        element_count=total,
        total_page_count=total_pages,
        is_last_page=page_number >= total_pages,
        is_empty=empty,
    )


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    """형식과 크기를 검사하고 (파일 이름, 내용)을 돌려줌."""
    file_name = file.filename or ""
    try:
        service.file_format(file_name)
    except service.FileTypeUnsupportedError:
        raise AppError(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            ErrorCode.FILE_TYPE_UNSUPPORTED,
            f"지원 형식: {', '.join(sorted(set(service.ALLOWED_FORMATS.values())))}",
        ) from None
    limit = get_settings().max_upload_mb * 1024 * 1024
    # 한도보다 1바이트 더 읽어 초과 여부만 확인함 (큰 파일을 전부 메모리에 올리지 않음)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            ErrorCode.FILE_TOO_LARGE,
            f"파일은 {get_settings().max_upload_mb}MB 이하여야 함",
        )
    return file_name, data


def _document_read(document: Document) -> DocumentRead:
    return DocumentRead(
        document_id=document.id,
        format=document.format,
        doc_type=document.doc_type,
        status=document.status,
        file_name=document.file_name,
        file_version=document.file_version,
        uploaded_at=document.created_at,
    )


def _value_read(item: DocumentValue) -> ValueRead:
    return ValueRead(
        value_id=item.id,
        name=item.name,
        value=item.value,
        unit=item.unit,
        source_location=item.source_location,
        basis=item.basis,
        verification_status=item.verification_status,
    )


async def _my_document(document_id: uuid.UUID, company: MyCompany, db: DbSession) -> Document:
    document = await service.get_document(db, company.id, document_id)
    if document is None:
        raise NotFoundError("문서를 찾을 수 없음")
    return document


MyDocument = Annotated[Document, Depends(_my_document)]


@router.post(
    "/reviews/{review_id}/documents",
    response_model=DocumentUploaded,
    status_code=status.HTTP_201_CREATED,
    summary="문서 업로드",
    description="multipart/form-data. doc_type=test_report이면 시험성적서. "
    "값 추출(OCR)은 아직 연결되지 않아 status는 uploaded에 머묾.",
    responses=_FILE_ERRORS,
)
async def upload_document(
    review: MyReview,
    db: DbSession,
    storage: Storage,
    file: UploadFile = File(...),
    doc_type: DocumentType = Form(DocumentType.OTHER),
) -> DocumentUploaded:
    file_name, data = await _read_upload(file)
    document = await service.upload(db, storage, review, file_name, data, doc_type)
    return DocumentUploaded(
        document_id=document.id,
        format=document.format,
        doc_type=document.doc_type,
        status=document.status,
    )


@router.get(
    "/reviews/{review_id}/documents",
    response_model=DocumentPage,
    summary="문서 목록",
    description="업로드한 순서. status로 값 추출 진행 상태를 확인함.",
)
async def list_documents(
    review: MyReview,
    db: DbSession,
    page_number: int = Query(1, alias="pageNumber", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
) -> DocumentPage:
    rows, total = await service.list_documents(db, review.id, page_number, page_size)
    return DocumentPage(
        items=[_document_read(d) for d in rows],
        paging_info=_paging(page_number, page_size, total, not rows),
    )


@router.get(
    "/documents/{document_id}/values",
    response_model=ValuePage,
    summary="측정값 후보 목록",
    description="문서에서 추출한 측정값 후보. 원문 위치, 단위, 측정 기준, 검수 상태를 포함함.",
)
async def list_values(
    document: MyDocument,
    db: DbSession,
    page_number: int = Query(1, alias="pageNumber", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
) -> ValuePage:
    rows, total = await service.list_values(db, document.id, page_number, page_size)
    return ValuePage(
        items=[_value_read(v) for v in rows],
        paging_info=_paging(page_number, page_size, total, not rows),
    )


@router.patch(
    "/documents/{document_id}/values/{value_id}",
    response_model=ValueUpdated,
    summary="측정값 검수·수정",
    description="verification_status로 검수함. value나 unit을 고치면 검수 상태는 unverified로 "
    "돌아감. 값이 있는데 단위가 없으면 422 UNIT_REQUIRED.",
)
async def update_value(
    value_id: uuid.UUID, data: ValueUpdate, document: MyDocument, db: DbSession
) -> ValueUpdated:
    item = await service.get_value(db, document.id, value_id)
    if item is None:
        raise NotFoundError("측정값을 찾을 수 없음")
    try:
        await service.update_value(db, item, data)
    except service.UnitRequiredError:
        raise UnprocessableError(ErrorCode.UNIT_REQUIRED, "값에는 단위가 있어야 함") from None
    return ValueUpdated(
        value_id=item.id,
        value=item.value,
        unit=item.unit,
        verification_status=item.verification_status,
    )


@router.post(
    "/documents/{document_id}/replace",
    response_model=DocumentReplaced,
    summary="문서 교체",
    description="파일을 바꾸고 기존 측정값의 검수 상태를 모두 해제함.",
    responses=_FILE_ERRORS,
)
async def replace_document(
    document: MyDocument, db: DbSession, storage: Storage, file: UploadFile = File(...)
) -> DocumentReplaced:
    file_name, data = await _read_upload(file)
    await service.replace(db, storage, document, file_name, data)
    return DocumentReplaced(
        document_id=document.id,
        file_version=document.file_version,
        status=document.status,
        values_reset=True,
    )
