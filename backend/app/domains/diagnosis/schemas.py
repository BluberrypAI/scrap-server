"""브라우저 → server 문진 요청 본문.

엔진 규약의 요청 본문에서 server가 정하는 값은 받지 않음:
- confirmed_facts, company_profile_version: 엔진이 "server가 확인한 값"으로 믿는 필드
- reviewer, reviewed_at: 현재 사용자와 server 시각으로 채움
모르는 필드는 무시함. 값의 세부 검사는 엔진이 함 (오류는 422 VALIDATION_ERROR).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CaseCreateIn(_Body):
    memo: str | None = Field(default=None, max_length=2000, examples=["PP 필름 자투리"])
    quantity: float | None = Field(default=None, ge=0, examples=[1.5])
    unit: str | None = Field(default=None, max_length=20, examples=["t"])
    period: str | None = Field(default=None, max_length=50, examples=["월"])


class QuickReplyIn(_Body):
    key: str = Field(examples=["material"])
    kind: Literal["value", "unknown", "none_all", "expand", "retract"] = "value"
    value: Any = None


class MessageIn(_Body):
    """자유 진술(text) 또는 선택지 버튼(quick_reply) 중 하나."""

    text: str | None = Field(default=None, max_length=4000, examples=["무기성 오니예요"])
    quick_reply: QuickReplyIn | None = None


class ApplyValueIn(_Body):
    """검수한 서류 값 하나. value_id(후보 행) 또는 fact_key 중 하나는 있어야 함."""

    value_id: str | None = None
    fact_key: str | None = None
    value: Any = None
    unit: str | None = Field(default=None, max_length=30)
    document_version: int = Field(ge=1)
    reject: bool = False


class ApplyIn(_Body):
    values: list[ApplyValueIn] = Field(min_length=1, max_length=200)


class RevokeIn(_Body):
    reason: str | None = Field(default=None, max_length=1000)
    document_version: int | None = Field(default=None, ge=1)


class ConfirmIn(_Body):
    expected_code: str | None = Field(default=None, examples=["51-03-01"])


class ReopenIn(_Body):
    reason: str | None = Field(default=None, max_length=1000)


class TreatmentSelectionIn(BaseModel):
    """Only a missing physical form is supplied by the browser."""

    model_config = ConfigDict(extra="forbid")
    input_form: str | None = Field(default=None, max_length=80)
    solid_confirmed: bool = Field(default=False, strict=True)


class TreatmentContextRead(BaseModel):
    status: Literal["needs_input", "review_required", "unsupported", "ready"]
    message: str
    case_id: str
    handoff: dict[str, Any] | None = None
    available_forms: list[dict[str, str]] = Field(default_factory=list)
    requires_solid_confirmation: bool = False
    origin: dict[str, float] | None = None
    origin_label: str | None = None
    warnings: list[str] = Field(default_factory=list)
    route_input: dict[str, Any] | None = None
    next_step: dict[str, Any] | None = None
    reviews: dict[str, Any] | None = None
