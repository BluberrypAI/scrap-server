import uuid
from datetime import UTC, datetime
from pathlib import PurePath

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import LocalFileStorage
from app.domains.documents.models import (
    Document,
    DocumentStatus,
    DocumentType,
    DocumentValue,
    VerificationStatus,
)
from app.domains.documents.schemas import ValueUpdate
from app.domains.reviews.models import Review

# 확장자 → 저장 형식. 형식 판단은 확장자로만 함 (클라이언트가 보낸 Content-Type은 믿지 않음)
ALLOWED_FORMATS = {
    "pdf": "pdf",
    "png": "png",
    "jpg": "jpg",
    "jpeg": "jpg",
    "xlsx": "xlsx",
    "csv": "csv",
}


class FileTypeUnsupportedError(Exception):
    pass


class UnitRequiredError(Exception):
    pass


def file_format(file_name: str) -> str:
    """허용된 형식이면 정규화한 확장자, 아니면 FileTypeUnsupportedError."""
    ext = PurePath(file_name).suffix.lower().lstrip(".")
    if ext not in ALLOWED_FORMATS:
        raise FileTypeUnsupportedError
    return ALLOWED_FORMATS[ext]


def _storage_key(review: Review, document_id: uuid.UUID, version: int, fmt: str) -> str:
    return f"{review.company_id}/{review.id}/{document_id}/v{version}.{fmt}"


async def upload(
    db: AsyncSession,
    storage: LocalFileStorage,
    review: Review,
    file_name: str,
    data: bytes,
    doc_type: DocumentType,
) -> Document:
    fmt = file_format(file_name)
    document_id = uuid.uuid4()
    key = _storage_key(review, document_id, 1, fmt)
    storage.save(key, data)
    document = Document(
        id=document_id,
        review_id=review.id,
        file_name=PurePath(file_name).name[:255],
        format=fmt,
        size_bytes=len(data),
        doc_type=doc_type,
        # 값 추출(OCR)이 아직 연결되지 않아 uploaded에 머묾 (INT-008)
        status=DocumentStatus.UPLOADED,
        storage_key=key,
        file_version=1,
        created_at=datetime.now(UTC),
    )
    db.add(document)
    await db.commit()
    return document


async def list_documents(
    db: AsyncSession, review_id: uuid.UUID, page_number: int, page_size: int
) -> tuple[list[Document], int]:
    where = Document.review_id == review_id
    total = await db.scalar(select(func.count()).select_from(Document).where(where))
    rows = await db.scalars(
        select(Document)
        .where(where)
        .order_by(Document.created_at, Document.id)
        .offset((page_number - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), total or 0


async def get_document(
    db: AsyncSession, company_id: uuid.UUID, document_id: uuid.UUID
) -> Document | None:
    """다른 기업의 문서는 없는 것으로 취급함."""
    return await db.scalar(
        select(Document)
        .join(Review, Review.id == Document.review_id)
        .where(Document.id == document_id, Review.company_id == company_id)
    )


async def list_values(
    db: AsyncSession, document_id: uuid.UUID, page_number: int, page_size: int
) -> tuple[list[DocumentValue], int]:
    where = DocumentValue.document_id == document_id
    total = await db.scalar(select(func.count()).select_from(DocumentValue).where(where))
    rows = await db.scalars(
        select(DocumentValue)
        .where(where)
        .order_by(DocumentValue.created_at, DocumentValue.id)
        .offset((page_number - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), total or 0


async def get_value(
    db: AsyncSession, document_id: uuid.UUID, value_id: uuid.UUID
) -> DocumentValue | None:
    return await db.scalar(
        select(DocumentValue).where(
            DocumentValue.id == value_id, DocumentValue.document_id == document_id
        )
    )


async def update_value(db: AsyncSession, item: DocumentValue, data: ValueUpdate) -> None:
    sent = data.model_fields_set
    edited = False
    if "value" in sent and data.value != item.value:
        item.value, edited = data.value, True
    if "unit" in sent and data.unit != item.unit:
        item.unit, edited = data.unit, True

    if item.value is not None and item.unit is None:
        # 단위 없는 수치는 근거로 쓸 수 없음
        raise UnitRequiredError

    if edited:
        # 값을 고치면 이전 검수는 무효임. 같은 요청에서 verified를 보내도 다시 검수해야 함
        item.verification_status = VerificationStatus.UNVERIFIED
    elif data.verification_status is not None:
        item.verification_status = data.verification_status
    await db.commit()


async def replace(
    db: AsyncSession, storage: LocalFileStorage, document: Document, file_name: str, data: bytes
) -> None:
    """파일을 바꾸고 기존 측정값의 검수 상태를 모두 해제함."""
    fmt = file_format(file_name)
    review = await db.get(Review, document.review_id)
    old_key = document.storage_key
    document.file_version += 1
    document.storage_key = _storage_key(review, document.id, document.file_version, fmt)
    storage.save(document.storage_key, data)
    document.file_name = PurePath(file_name).name[:255]
    document.format = fmt
    document.size_bytes = len(data)
    document.status = DocumentStatus.UPLOADED
    await db.execute(
        update(DocumentValue)
        .where(DocumentValue.document_id == document.id)
        .values(verification_status=VerificationStatus.UNVERIFIED)
    )
    await db.commit()
    storage.delete(old_key)


async def delete_documents_of_reviews(
    db: AsyncSession, storage: LocalFileStorage, review_ids: Select[tuple[uuid.UUID]]
) -> None:
    """탈퇴 사용자 삭제 시 문서·측정값·파일을 지움. 커밋은 호출한 쪽에서 함."""
    documents = list(await db.scalars(select(Document).where(Document.review_id.in_(review_ids))))
    document_ids = [d.id for d in documents]
    if not document_ids:
        return
    await db.execute(
        delete(DocumentValue)
        .where(DocumentValue.document_id.in_(document_ids))
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(Document)
        .where(Document.id.in_(document_ids))
        .execution_options(synchronize_session=False)
    )
    for document in documents:
        storage.delete(document.storage_key)
