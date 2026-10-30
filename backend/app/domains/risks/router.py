import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.errors import ConflictError, ErrorCode, NotFoundError, UnprocessableError
from app.db.session import DbSession
from app.domains.results import transform
from app.domains.reviews.dependencies import MyReview
from app.domains.risks import service
from app.domains.risks.models import Decision, ProceedOption
from app.domains.runs.dependencies import MyRun, find_candidate, result_of
from app.domains.supplements import service as supplement_service

router = APIRouter(prefix="/reviews/{review_id}/runs/{run_id}", tags=["risks"])


class DecisionCreate(BaseModel):
    decision: Decision = Field(description="confirm(확인), request_evidence(자료 요청), hold(보류)")
    proceed_option: ProceedOption | None = Field(
        default=None,
        description="심각(high) 리스크가 해소되지 않은 단계를 confirm할 때 필수",
    )


class DecisionResult(BaseModel):
    decision: Decision
    proceed_option: ProceedOption | None
    decided_at: datetime
    next_step: int | None = Field(description="다음에 결정할 단계. 모두 끝났으면 null")

    @field_validator("decided_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class EvidenceCreate(BaseModel):
    supplement_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "EvidenceCreate":
        if (self.supplement_id is None) == (self.document_id is None):
            raise ValueError("supplement_id와 document_id 중 하나만 보내야 함")
        return self


class EvidenceResult(BaseModel):
    risk_id: str
    status: str = Field(description="증빙이 연결되면 resolved")


@router.post(
    "/candidates/{candidate_id}/risk-steps/{step_no}/decision",
    response_model=DecisionResult,
    summary="리스크 단계 결정",
    description="현재 단계에만 결정할 수 있음. confirm·hold는 다음 단계로 넘어가고, "
    "request_evidence는 같은 단계에 머묾. confirm만으로 리스크가 해소되지는 않음.",
    responses={
        409: {"description": "STEP_OUT_OF_ORDER, RISK_OPTION_REQUIRED, RESULT_NOT_READY"},
    },
)
async def decide_step(
    candidate_id: str, step_no: int, data: DecisionCreate, run: MyRun, db: DbSession
) -> DecisionResult:
    candidate = find_candidate(result_of(run), candidate_id)
    try:
        record, next_step = await service.decide(
            db, run, candidate, step_no, data.decision, data.proceed_option
        )
    except service.StepNotFoundError:
        raise NotFoundError("단계를 찾을 수 없음") from None
    except service.StepOutOfOrderError:
        raise ConflictError(
            ErrorCode.STEP_OUT_OF_ORDER, "현재 단계가 아님. 앞 단계부터 순서대로 결정해야 함"
        ) from None
    except service.RiskOptionRequiredError:
        raise ConflictError(
            ErrorCode.RISK_OPTION_REQUIRED,
            "해소되지 않은 심각 리스크가 있음. proceed_option(hold_and_proceed, exclude)이 필요함",
        ) from None
    return DecisionResult(
        decision=record.decision,
        proceed_option=record.proceed_option,
        decided_at=record.created_at,
        next_step=next_step,
    )


@router.post(
    "/risks/{risk_id}/evidence",
    response_model=EvidenceResult,
    summary="리스크에 증빙 연결",
    description="물량이 맞고 검수된 추가 자료(counted_in_judgment=true)나 검수된 측정값이 있는 "
    "문서만 연결할 수 있고, 연결되면 리스크는 resolved가 됨.",
    responses={422: {"description": "EVIDENCE_NOT_APPLICABLE"}},
)
async def link_evidence(
    risk_id: str, data: EvidenceCreate, run: MyRun, review: MyReview, db: DbSession
) -> EvidenceResult:
    result = result_of(run)
    owner = next(
        (
            c["plan"]["plan_id"]
            for c in result.get("candidates", [])
            if any(r["risk_id"] == risk_id for r in transform.risks(c))
        ),
        None,
    )
    if owner is None:
        raise NotFoundError("리스크를 찾을 수 없음")

    supplement = None
    if data.supplement_id is not None:
        supplement = await supplement_service.get(db, review.id, data.supplement_id)
        if supplement is None:
            raise NotFoundError("추가 자료를 찾을 수 없음")
        applicable = supplement_service.counted_in_judgment(supplement)
    else:
        verified = await service.document_has_verified_values(db, review.id, data.document_id)
        if verified is None:
            raise NotFoundError("문서를 찾을 수 없음")
        applicable = verified
    if not applicable:
        raise UnprocessableError(
            ErrorCode.EVIDENCE_NOT_APPLICABLE,
            "물량이 맞지 않거나 검수되지 않은 자료는 증빙으로 쓸 수 없음",
        )

    await service.link_evidence(db, run, owner, risk_id, supplement, data.document_id)
    return EvidenceResult(risk_id=risk_id, status="resolved")
