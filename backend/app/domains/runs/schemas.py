import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.companies.schemas import PagingInfo
from app.domains.runs.models import RunErrorCode, RunStatus


def _utc(value: datetime | None) -> datetime | None:
    # SQLite는 시간대를 버림. 저장 값은 UTC임
    if value is None or value.tzinfo:
        return value
    return value.replace(tzinfo=UTC)


class RunCreate(BaseModel):
    intake_version: int = Field(ge=1, description="화면이 불러온 입력 버전. 현재 버전과 다르면 409")
    document_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=50,
        description="근거로 쓸 문서. 이 문서들의 검수된 측정값만 고정함",
    )

    @field_validator("document_ids")
    @classmethod
    def _unique(cls, ids: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(ids) != len(set(ids)):
            raise ValueError("같은 문서를 두 번 보낼 수 없음")
        return ids


class RunCreated(BaseModel):
    run_id: uuid.UUID
    status: RunStatus
    pinned_versions: dict[str, Any]


class RunStage(BaseModel):
    stage: str
    status: str = Field(description="pending, running, done, skipped, limit_reached, failed")
    reason: str | None


class RunErrorInfo(BaseModel):
    code: RunErrorCode
    message: str | None


class RunListItem(BaseModel):
    run_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    rerun_from_stage: str | None
    status: RunStatus
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_utc(cls, value: datetime) -> datetime | None:
        return _utc(value)


class RunRead(RunListItem):
    stages: list[RunStage]
    router_state: str | None = Field(description="엔진 판정 (PASS, REVISE, REVIEW). 완료 전 null")
    pinned_versions: dict[str, Any]
    error: RunErrorInfo | None
    coverage: dict[str, Any] | None = Field(description="엔진 조회 범위. 완료 전 null")
    limitations: list[str] = Field(description="엔진이 밝힌 결과의 한계")
    next_actions: list[str]
    started_at: datetime | None
    finished_at: datetime | None

    @field_validator("started_at", "finished_at")
    @classmethod
    def _times_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value)


class RunPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[RunListItem]
    paging_info: PagingInfo = Field(alias="pagingInfo")
