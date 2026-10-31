import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domains.companies.schemas import PagingInfo


class Reason(BaseModel):
    code: str
    label: str


class FacilityRef(BaseModel):
    facility_id: str | None
    name: str | None


class RouteStep(BaseModel):
    step_no: int
    stage_id: str
    transition: str | None
    facility: FacilityRef | None
    condition_status: str = Field(description="unmet, needs_verification, conditions_met")
    condition_reason: str | None


class FacilitySummary(FacilityRef):
    status_label: str


class RiskCounts(BaseModel):
    high: int
    medium: int


class CandidateItem(BaseModel):
    candidate_id: str
    judgment: str = Field(
        description="suitable, needs_check, unsuitable, verification_failed, excluded"
    )
    judgment_reasons: list[Reason]
    process_route: list[RouteStep]
    facility: FacilitySummary | None = Field(description="첫 번째로 시설이 연결된 단계")
    tentative_rank: int | None = Field(description="Pareto 비교 전이라 null")
    exclusion_reason: str | None
    cost_status: str = Field(description="제출 근거가 없으면 missing")
    carbon_status: str
    risk_counts: RiskCounts
    stale_company_profile: bool = Field(description="실행 뒤 기업 정보가 바뀌었는지")


class CandidatePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[CandidateItem]
    paging_info: PagingInfo = Field(alias="pagingInfo")


class Risk(BaseModel):
    risk_id: str
    step_no: int | None
    target_id: str
    target_type: str = Field(description="stage 또는 handoff")
    label: str | None
    reason: str | None
    severity: str = Field(description="high: 공개 조건과 어긋남, medium: 확인되지 않음")
    engine_status: str | None
    next_action: str | None
    source_ids: list[str]


class Judgment(BaseModel):
    status: str
    reasons: list[Reason]


class StageCheck(BaseModel):
    step_no: int
    stage_id: str
    result: str


class LegalEvidence(BaseModel):
    target_id: str
    target_type: str
    topic: str = Field(description="classification, process, facility, handover")
    search_status: str = Field(description="retrieved, no_hits, unavailable, budget_exhausted")
    query: str | None
    results: list[dict[str, Any]] = Field(
        description="원문·조문·출처·시행일. applicability는 항상 not_audited (적용성 미검토)"
    )


class NotComputed(BaseModel):
    status: str
    total: float | None
    missing: list[str]


class CriticResult(BaseModel):
    status: str
    issues: list[Any]


class Unconfirmed(BaseModel):
    kind: str
    ref_id: str
    label: str | None


class CandidateDetail(BaseModel):
    candidate_id: str
    judgment: Judgment
    process_route: list[RouteStep]
    handoffs: list[dict[str, Any]]
    facility: FacilitySummary | None
    tentative_rank: int | None
    exclusion_reason: str | None
    checks: list[StageCheck]
    risks: list[Risk]
    risk_counts: RiskCounts
    legal_evidence: list[LegalEvidence]
    cost: NotComputed
    carbon: NotComputed
    critic: CriticResult
    unconfirmed: list[Unconfirmed]
    evidence_grade: str | None = Field(description="실행에 고정한 근거 등급 (A, B, C)")
    stale_company_profile: bool


class ReviewQueueItem(BaseModel):
    candidate_id: str
    reason: str
    required_checks: list[str]
    assignee_role: str | None


class ReviewQueue(BaseModel):
    router_state: str | None
    items: list[ReviewQueueItem]


class TaskItem(BaseModel):
    task_id: str
    candidate_id: str
    risk_id: str | None
    item: str | None
    required_material: str | None
    assignee_role: str | None
    status: str = Field(description="open 또는 done")


class TaskPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[TaskItem]
    paging_info: PagingInfo = Field(alias="pagingInfo")


class Change(BaseModel):
    candidate_id: str
    field: str = Field(description="presence, judgment, high_risks, blockers")
    base_value: Any
    target_value: Any


class Comparison(BaseModel):
    base_run_id: uuid.UUID
    target_run_id: uuid.UUID
    graph_changed: bool = Field(description="두 실행의 지식그래프 버전이 다른지")
    changes: list[Change]
