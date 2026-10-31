"""리스크 단계 결정과 증빙 (docs/specs/review-risks-supplements.md 3장)."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.models import Document, DocumentValue, VerificationStatus
from app.domains.results import transform
from app.domains.risks.models import Decision, ProceedOption, RiskEvidence, RiskStepDecision
from app.domains.runs.models import Run
from app.domains.supplements.models import Supplement


class StepNotFoundError(Exception):
    pass


class StepOutOfOrderError(Exception):
    pass


class RiskOptionRequiredError(Exception):
    pass


@dataclass
class RunRiskState:
    """한 실행의 결정·증빙. decisions는 (후보, 단계) → 마지막 결정."""

    decisions: dict[tuple[str, int], RiskStepDecision] = field(default_factory=dict)
    resolved: set[str] = field(default_factory=set)

    def risk_status(self, candidate_id: str, risk: dict[str, Any]) -> str:
        # 해소는 증빙이 연결됐을 때만. 확인(confirm) 결정만으로는 해소되지 않음
        if risk["risk_id"] in self.resolved:
            return "resolved"
        decided = self.decisions.get((candidate_id, risk["step_no"]))
        if decided is not None and decided.decision == Decision.CONFIRM:
            return "confirmed"
        return "open"

    def steps(self, candidate: dict[str, Any]) -> dict[str, Any]:
        candidate_id = candidate["plan"]["plan_id"]
        steps, current = [], None
        for step in transform.process_route(candidate):
            decided = self.decisions.get((candidate_id, step["step_no"]))
            if current is None and (
                decided is None or decided.decision == Decision.REQUEST_EVIDENCE
            ):
                current = step["step_no"]
            steps.append(
                {
                    "step_no": step["step_no"],
                    "decision": decided.decision if decided else None,
                    "proceed_option": decided.proceed_option if decided else None,
                    "decided_at": decided.created_at if decided else None,
                }
            )
        return {"current_step": current, "steps": steps}


async def load_state(db: AsyncSession, run_id: uuid.UUID) -> RunRiskState:
    state = RunRiskState()
    decisions = await db.scalars(
        select(RiskStepDecision)
        .where(RiskStepDecision.run_id == run_id)
        .order_by(RiskStepDecision.created_at, RiskStepDecision.id)
    )
    for d in decisions:
        state.decisions[(d.candidate_id, d.step_no)] = d
    state.resolved = set(
        await db.scalars(select(RiskEvidence.risk_id).where(RiskEvidence.run_id == run_id))
    )
    return state


async def decide(
    db: AsyncSession,
    run: Run,
    candidate: dict[str, Any],
    step_no: int,
    decision: Decision,
    proceed_option: ProceedOption | None,
) -> tuple[RiskStepDecision, int | None]:
    """현재 단계에 결정을 남기고 (기록, 다음 현재 단계)를 돌려줌."""
    candidate_id = candidate["plan"]["plan_id"]
    state = await load_state(db, run.id)
    route = transform.process_route(candidate)
    if not 1 <= step_no <= len(route):
        raise StepNotFoundError
    if state.steps(candidate)["current_step"] != step_no:
        raise StepOutOfOrderError

    severe_open = [
        r
        for r in transform.risks(candidate)
        if r["step_no"] == step_no
        and r["severity"] == "high"
        and state.risk_status(candidate_id, r) != "resolved"
    ]
    if severe_open and decision == Decision.CONFIRM and proceed_option is None:
        raise RiskOptionRequiredError

    record = RiskStepDecision(
        run_id=run.id,
        candidate_id=candidate_id,
        step_no=step_no,
        decision=decision,
        proceed_option=proceed_option,
        created_at=datetime.now(UTC),
    )
    db.add(record)
    await db.commit()
    state.decisions[(candidate_id, step_no)] = record
    return record, state.steps(candidate)["current_step"]


async def document_has_verified_values(
    db: AsyncSession, review_id: uuid.UUID, document_id: uuid.UUID
) -> bool | None:
    """이 검토의 문서가 아니면 None, 검수된 측정값이 있으면 True."""
    owned = await db.scalar(
        select(Document.id).where(Document.id == document_id, Document.review_id == review_id)
    )
    if owned is None:
        return None
    verified = await db.scalar(
        select(DocumentValue.id)
        .where(
            DocumentValue.document_id == document_id,
            DocumentValue.verification_status == VerificationStatus.VERIFIED,
        )
        .limit(1)
    )
    return verified is not None


async def link_evidence(
    db: AsyncSession,
    run: Run,
    candidate_id: str,
    risk_id: str,
    supplement: Supplement | None,
    document_id: uuid.UUID | None,
) -> None:
    db.add(
        RiskEvidence(
            run_id=run.id,
            candidate_id=candidate_id,
            risk_id=risk_id,
            supplement_id=supplement.id if supplement else None,
            document_id=document_id,
        )
    )
    await db.commit()


async def delete_of_runs(db: AsyncSession, run_ids: Select[tuple[uuid.UUID]]) -> None:
    """탈퇴 사용자 삭제 시 결정·증빙 기록을 지움. 커밋은 호출한 쪽에서 함."""
    for model in (RiskEvidence, RiskStepDecision):
        await db.execute(
            delete(model)
            .where(model.run_id.in_(run_ids))
            .execution_options(synchronize_session=False)
        )
