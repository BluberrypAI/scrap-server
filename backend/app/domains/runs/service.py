import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.models import (
    Document,
    DocumentType,
    DocumentValue,
    VerificationStatus,
)
from app.domains.reviews import intake as intake_rules
from app.domains.reviews.models import Review, ReviewStatus
from app.domains.runs import stages
from app.domains.runs.engine_client import LOT_FIELDS
from app.domains.runs.models import IN_PROGRESS, Run, RunErrorCode, RunStatus


class IntakeIncompleteError(Exception):
    pass


class IntakeVersionConflictError(Exception):
    pass


class RunInProgressError(Exception):
    pass


class InvalidDocumentsError(Exception):
    pass


def evidence_grade(intake: dict[str, Any], verified_from_test_report: bool) -> str:
    """근거 등급 (FR-1.6). A: 검수된 시험성적서 측정값, B: 사용자가 확인한 측정값, C: 추정 기반."""
    if verified_from_test_report:
        return "A"
    measured = intake_rules.confirmed_values(intake)
    if any(f in measured for f in intake_rules.MEASURED_FIELDS):
        return "B"
    return "C"


async def _verified_values(
    db: AsyncSession, review_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
) -> list[tuple[uuid.UUID, DocumentType]]:
    """지정한 문서의 검수된 측정값 (id, 문서 유형). 다른 검토 문서면 InvalidDocumentsError."""
    if not document_ids:
        return []
    owned = set(
        await db.scalars(
            select(Document.id).where(
                Document.id.in_(document_ids), Document.review_id == review_id
            )
        )
    )
    if owned != set(document_ids):
        raise InvalidDocumentsError
    rows = await db.execute(
        select(DocumentValue.id, Document.doc_type)
        .join(Document, Document.id == DocumentValue.document_id)
        .where(
            DocumentValue.document_id.in_(document_ids),
            DocumentValue.verification_status == VerificationStatus.VERIFIED,
        )
        .order_by(DocumentValue.id)
    )
    return [(row[0], row[1]) for row in rows]


async def create_run(
    db: AsyncSession,
    review: Review,
    intake_version: int,
    document_ids: Sequence[uuid.UUID],
    parent: Run | None = None,
    rerun_from_stage: str | None = None,
    supplement_ids: Sequence[uuid.UUID] = (),
) -> Run:
    """실행 레코드를 queued로 만들고 입력·버전을 고정함. 엔진 호출은 워커가 함."""
    if intake_version != review.intake_version:
        raise IntakeVersionConflictError
    if review.status != ReviewStatus.INTAKE_READY:
        raise IntakeIncompleteError
    running = await db.scalar(
        select(Run.id).where(Run.review_id == review.id, Run.status.in_(IN_PROGRESS)).limit(1)
    )
    if running is not None:
        raise RunInProgressError

    verified = await _verified_values(db, review.id, document_ids)
    from_test_report = any(doc_type == DocumentType.TEST_REPORT for _, doc_type in verified)
    lot = {
        field: value
        for field, value in intake_rules.confirmed_values(review.intake).items()
        if field in LOT_FIELDS
    }
    run = Run(
        review_id=review.id,
        parent_run_id=parent.id if parent else None,
        rerun_from_stage=rerun_from_stage,
        status=RunStatus.QUEUED,
        stages=stages.initial_stages(),
        pinned_versions={
            "intake_version": review.intake_version,
            "company_profile_version": review.company_profile_version,
            "evidence_grade": evidence_grade(review.intake, from_test_report),
            "document_ids": [str(d) for d in document_ids],
            "verified_value_ids": [str(value_id) for value_id, _ in verified],
            # 재실행에 반영한 추가 자료 (엔진 lot에는 들어가지 않고 추적용으로만 고정)
            "supplement_ids": [str(s) for s in supplement_ids],
            # 아래는 엔진 응답을 받은 뒤 채움
            "engine_contract_version": None,
            "engine_run_id": None,
            "request_sha256": None,
            "graph_trace": None,
        },
        lot=lot,
        created_at=datetime.now(UTC),
    )
    db.add(run)
    await db.commit()
    return run


async def get_run(db: AsyncSession, review_id: uuid.UUID, run_id: uuid.UUID) -> Run | None:
    return await db.scalar(select(Run).where(Run.id == run_id, Run.review_id == review_id))


async def list_runs(
    db: AsyncSession, review_id: uuid.UUID, page_number: int, page_size: int
) -> tuple[list[Run], int]:
    where = Run.review_id == review_id
    total = await db.scalar(select(func.count()).select_from(Run).where(where))
    rows = await db.scalars(
        select(Run)
        .where(where)
        .order_by(Run.created_at.desc(), Run.id)
        .offset((page_number - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), total or 0


async def latest_run_ids(
    db: AsyncSession, review_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """검토별 가장 최근 실행 id."""
    if not review_ids:
        return {}
    rows = await db.execute(
        select(Run.review_id, Run.id)
        .where(Run.review_id.in_(review_ids))
        .order_by(Run.review_id, Run.created_at.desc())
    )
    latest: dict[uuid.UUID, uuid.UUID] = {}
    for review_id, run_id in rows:
        latest.setdefault(review_id, run_id)
    return latest


async def recover_interrupted(db: AsyncSession) -> int:
    """서버 시작 시 끝나지 못한 실행을 실패로 바꿈 (프로세스 안 워커라 재개할 수 없음)."""
    result = await db.execute(
        update(Run)
        .where(Run.status.in_(IN_PROGRESS))
        .values(
            status=RunStatus.FAILED,
            error_code=RunErrorCode.WORKER_INTERRUPTED,
            error_message="서버가 다시 시작되어 실행이 중단됨. 다시 실행해야 함",
            finished_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return result.rowcount or 0


def run_ids_of_reviews(review_ids: Select[tuple[uuid.UUID]]) -> Select[tuple[uuid.UUID]]:
    return select(Run.id).where(Run.review_id.in_(review_ids))


async def delete_runs_of_reviews(db: AsyncSession, review_ids: Select[tuple[uuid.UUID]]) -> None:
    """탈퇴 사용자 삭제 시 실행을 지움. 커밋은 호출한 쪽에서 함."""
    # 재실행이 원래 실행을 가리키므로 연결을 먼저 끊음
    await db.execute(
        update(Run)
        .where(Run.review_id.in_(review_ids))
        .values(parent_run_id=None)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(Run)
        .where(Run.review_id.in_(review_ids))
        .execution_options(synchronize_session=False)
    )
