import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.companies.schemas import PagingInfo
from app.domains.documents.models import DocumentStatus, DocumentType, VerificationStatus


class DocumentUploaded(BaseModel):
    document_id: uuid.UUID
    format: str
    doc_type: DocumentType
    status: DocumentStatus


class DocumentRead(DocumentUploaded):
    file_name: str
    file_version: int
    uploaded_at: datetime

    @field_validator("uploaded_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        # SQLite는 시간대를 버림. 저장 값은 UTC임
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class DocumentPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[DocumentRead]
    paging_info: PagingInfo = Field(alias="pagingInfo")


class DocumentReplaced(BaseModel):
    document_id: uuid.UUID
    file_version: int
    status: DocumentStatus
    values_reset: bool = Field(description="기존 측정값의 검수 상태를 모두 해제했는지")


class ValueRead(BaseModel):
    value_id: uuid.UUID
    name: str
    value: float | None
    unit: str | None
    source_location: str | None
    basis: str | None
    verification_status: VerificationStatus


class ValuePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[ValueRead]
    paging_info: PagingInfo = Field(alias="pagingInfo")


class ValueUpdate(BaseModel):
    """보낸 필드만 바꿈. 값이나 단위를 고치면 검수 상태는 unverified로 돌아감."""

    model_config = ConfigDict(extra="forbid")

    verification_status: VerificationStatus | None = None
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str | None = Field(default=None, min_length=1, max_length=40)

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data:
            raise ValueError("바꿀 필드를 하나 이상 보내야 함")
        return data


class ValueUpdated(BaseModel):
    value_id: uuid.UUID
    value: float | None
    unit: str | None
    verification_status: VerificationStatus
