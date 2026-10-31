import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from app.domains.companies.schemas import PagingInfo
from app.domains.reviews.models import ReviewStatus

# 자연어 상황 입력 최대 길이. 넘으면 422 TEXT_TOO_LONG
MAX_FREE_TEXT = 5000


class IntakeValues(BaseModel):
    """입력 객체 항목. 길이·범위 제한은 AI 엔진 lot 스키마(AssessedPlansRequest)와 같게 둠."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    material: str | None = Field(default=None, min_length=1, max_length=160, examples=["PP"])
    input_form: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, min_length=1, max_length=80)
    contamination: str | None = Field(default=None, min_length=1, max_length=500)
    quantity_kg: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    generation_process: str | None = Field(default=None, min_length=1, max_length=200)
    region: str | None = Field(default=None, min_length=1, max_length=200)
    current_treatment: str | None = Field(default=None, min_length=1, max_length=200)
    moisture_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    contamination_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    designated_waste: StrictBool | None = None
    # 엔진에는 보내지 않음. 질문 흐름(FR-1.4)과 근거 등급(FR-1.6)에만 씀
    has_test_report: StrictBool | None = None


IntakeField = Literal[
    "material",
    "input_form",
    "color",
    "contamination",
    "quantity_kg",
    "generation_process",
    "region",
    "current_treatment",
    "moisture_pct",
    "contamination_pct",
    "designated_waste",
    "has_test_report",
]

# 항목별로 받을 수 있는 단위. 첫 번째가 저장 단위이고 나머지는 환산함
_UNITS: dict[str, dict[str, float]] = {
    "quantity_kg": {"kg": 1, "t": 1000},
    "moisture_pct": {"%": 1},
    "contamination_pct": {"%": 1},
}


class IntakeAnswer(BaseModel):
    field: IntakeField
    value: Any = Field(description="모르면 null. null도 답변으로 기록함")
    unit: str | None = Field(default=None, examples=["kg"])

    @model_validator(mode="after")
    def _convert_and_check(self) -> "IntakeAnswer":
        units = _UNITS.get(self.field)
        if self.unit is not None:
            if units is None or self.unit not in units:
                allowed = ", ".join(units) if units else "없음"
                raise ValueError(f"{self.field}의 단위는 {allowed} 중 하나여야 함")
            if isinstance(self.value, int | float) and not isinstance(self.value, bool):
                self.value = self.value * units[self.unit]
        try:
            checked = IntakeValues.model_validate({self.field: self.value})
        except ValidationError as exc:
            raise ValueError(f"{self.field}: {exc.errors()[0]['msg']}") from None
        self.value = getattr(checked, self.field)
        return self


class IntakeUpdate(BaseModel):
    answers: list[IntakeAnswer] = Field(min_length=1)

    @field_validator("answers")
    @classmethod
    def _unique_fields(cls, answers: list[IntakeAnswer]) -> list[IntakeAnswer]:
        fields = [a.field for a in answers]
        if len(fields) != len(set(fields)):
            raise ValueError("같은 항목에 답변을 두 번 보낼 수 없음")
        return answers


class IntakeItem(BaseModel):
    field: str
    value: Any
    source: Literal["user", "company_profile"]


class IntakeGroups(BaseModel):
    confirmed: list[IntakeItem]
    unconfirmed: list[IntakeItem]


class IntakeQuestion(BaseModel):
    field: str
    reason: str
    required: bool = Field(description="true면 답하기 전까지 실행할 수 없음")


class IntakeRead(BaseModel):
    status: ReviewStatus
    intake_version: int
    intake: IntakeGroups
    questions: list[IntakeQuestion]


class IntakeUpdateResult(BaseModel):
    status: ReviewStatus
    intake_version: int


class ReviewCreate(BaseModel):
    # 빈 값·길이 초과는 전용 코드(EMPTY_INPUT, TEXT_TOO_LONG)로 돌려주려고 service에서 검사함
    free_text: str = Field(description=f"자연어 상황 입력. 1~{MAX_FREE_TEXT}자")
    title: str | None = Field(default=None, max_length=200, description="없으면 free_text 앞 30자")
    overrides: IntakeValues = Field(
        default_factory=IntakeValues,
        description="사용자가 직접 입력한 구조화 항목. 보낸 항목은 확인된 값이 됨",
    )


class ReviewCreated(BaseModel):
    review_id: uuid.UUID
    status: ReviewStatus
    company_profile_version: int


class ReviewListItem(BaseModel):
    review_id: uuid.UUID
    title: str
    status: ReviewStatus
    created_at: datetime
    latest_run_id: uuid.UUID | None = None

    @field_validator("created_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        # SQLite는 시간대를 버림. 저장 값은 UTC임
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class ReviewRead(ReviewListItem):
    free_text: str
    company_profile_version: int
    intake_version: int


class ReviewPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[ReviewListItem]
    paging_info: PagingInfo = Field(alias="pagingInfo")
